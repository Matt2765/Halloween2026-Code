"""MOSFET fan-out and validation using the real RSM functions without serial."""
import ast
from pathlib import Path
import queue
import re
import threading
import unittest
import uuid


class MosfetTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/"control/remote_sensor_monitor.py"
        tree=ast.parse(path.read_text(encoding="utf-8-sig"))
        names={"tx_to_id","mosfet","get_mosfet_state","_store_device","_valid_id","_uint32","_newer","command_failure"}
        tree.body=[node for node in tree.body if getattr(node,"name",None) in names]
        self.devices={key:dict(kind="mosfet",session=7,vals=dict(available_pins=[13,14],on_pins=[]))
                      for key in ("MOSFET1","MOSFET2")}
        self.scope=dict(uuid=uuid,queue=queue,re=re,_disabled=False,_commands={},
            _txq=queue.Queue(),_tx_lock=threading.Lock(),MAX_COMMANDS=128,MAX_DEVICES=64,
            _now_ms=lambda:100,get=lambda key:dict(connected=True,host="host") if key=="_connection" else self.devices.get(key),
            device_status=lambda key:dict(available=True,state="valid",age_ms=0))
        exec(compile(tree,str(path),"exec"),self.scope)

    def test_fan_out_keeps_logical_addressing_and_boot_fence(self):
        ids=self.scope['mosfet'](['MOSFET1','MOSFET2'],13,True)
        self.assertEqual(set(ids),{'MOSFET1','MOSFET2'})
        for sid,cid in ids.items():
            request=self.scope['_txq'].get_nowait()
            self.assertEqual((request['id'],request['op'],request['pin'],request['value'],request['target_session']),
                             (sid,'mosfet',13,1,7))
            self.assertEqual(request['duration_ms'],0)
            self.assertEqual(self.scope['_commands'][cid]['pin'],13)

    def test_string_target_off_and_duplicate_ids(self):
        self.scope['mosfet']('MOSFET1',13,False)
        self.assertEqual(self.scope['_txq'].get_nowait()['value'],0)
        self.scope['mosfet'](['MOSFET1','MOSFET1'],14,True)
        self.assertEqual(self.scope['_txq'].qsize(),1)

    def test_bad_arguments_reject_before_sending_anything(self):
        for ids,pin,on in [([],13,True),(['MOSFET1','bad id'],13,True),(['MOSFET1'],True,True),
                          (['MOSFET1'],40,True),(['MOSFET1'],13,1),(['MOSFET1'],13,'on')]:
            with self.subTest(ids=ids,pin=pin,on=on),self.assertRaises(ValueError):
                self.scope['mosfet'](ids,pin,on)
        self.assertTrue(self.scope['_txq'].empty())

    def test_wrong_kind_and_disabled_pin_do_not_enter_radio_queue(self):
        self.devices['MOSFET1']['kind']='servo'
        cid=self.scope['mosfet'](['MOSFET1'],13,True)['MOSFET1']
        self.assertEqual(self.scope['_commands'][cid]['reason'],'not_a_mosfet')
        cid=self.scope['mosfet'](['MOSFET2'],15,True)['MOSFET2']
        self.assertEqual(self.scope['_commands'][cid]['reason'],'pin_not_configured')
        self.assertTrue(self.scope['_txq'].empty())

    def test_disabled_mode_never_queues_commands(self):
        self.scope['_disabled']=True
        self.assertIn('MOSFET1',self.scope['mosfet'](['MOSFET1'],13,True))
        self.assertTrue(self.scope['_txq'].empty())

    def test_telemetry_rejects_outputs_not_in_configured_pins(self):
        vals=dict(available_pins=[13,14],on_pins=[13],ready=True)
        record=dict(id='MOSFET1',kind='mosfet',vals=vals,session=1,seq=1,mac='00:11:22:33:44:55')
        shared={};self.assertTrue(self.scope['_store_device'](shared,record,100))
        for changed in (dict(on_pins=[15]),dict(available_pins=[13,13]),dict(on_pins=[True]),dict(available_pins=[])):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                self.scope['_store_device']({},dict(record,vals=dict(vals,**changed)),100)

    def test_success_on_other_pin_does_not_hide_pin_failure(self):
        self.scope['_commands']={
            'failed':dict(id='MOSFET1',op='mosfet',pin=13,status='rejected',created_ms=1,t_host_ms=1),
            'ok':dict(id='MOSFET1',op='mosfet',pin=14,status='accepted',created_ms=2,t_host_ms=2)}
        self.assertEqual(self.scope['command_failure']()['pin'],13)
        self.scope['_commands']['ok']['pin']=13
        self.assertIsNone(self.scope['command_failure']())


if __name__=='__main__': unittest.main()
