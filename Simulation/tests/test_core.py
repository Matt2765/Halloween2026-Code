import copy
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
from hauntsim.model import Project, example, timing, sample, travel, length, interpolate, new_object, uid, door_path_fraction
from hauntsim.persistence import save, load
from hauntsim.validation import validate
from hauntsim.engine import Engine, Group
from hauntsim.analytics import summarize, export_csv
from hauntsim.analysis_jobs import advise, repeated


def fixture():
    p=example()
    p.settings.update(duration=300,exterior_groups=8)
    for o in p.objects:
        if o['kind']=='door':
            o['style']='passage'
    return p


class PersistenceTests(unittest.TestCase):
    def test_roundtrip_with_asset_scenarios_and_history(self):
        p=fixture()
        p.background=b'embedded-test-image'
        p.scenarios={'Variant':{'settings':{'seed':13}}}
        p.results=[{'test':i} for i in range(30)]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'portable.hauntsim'
            save(p,path)
            q=load(path)
            self.assertEqual(q.background,p.background)
            self.assertEqual(q.data(),p.data())
            self.assertEqual(len(q.results),20)

    def test_version_rejection(self):
        for version in (None,0,2):
            data=Project().data()
            data['version']=version
            with self.assertRaises(ValueError):
                Project.from_data(data)

    def test_legacy_path_door_reference_migrates_to_door(self):
        p=fixture()
        path=next(o for o in p.objects if o['kind']=='path')
        door=next(o for o in p.objects if o['kind']=='door')
        door.pop('path',None)
        path['door']=door['id']
        restored=Project.from_data(p.data())
        self.assertEqual(restored.by_id()[door['id']]['path'],path['id'])
        self.assertNotIn('door',restored.by_id()[path['id']])

    def test_atomic_save_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.hauntsim'
            save(fixture(),path)
            original=path.read_bytes()
            with patch('hauntsim.persistence.os.replace',side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    save(Project(),path)
            self.assertEqual(original,path.read_bytes())
            self.assertEqual(len(list(Path(d).iterdir())),1)


class ModelTests(unittest.TestCase):
    def test_triangular_room_sampling(self):
        rng=random.Random(12)
        values=[sample(timing(20,10,30),rng) for _ in range(1000)]
        self.assertTrue(all(10<=v<=30 for v in values))
        self.assertAlmostEqual(sum(values)/len(values),20,delta=.5)
        self.assertEqual(sample(timing(8),rng),8)

    def test_group_sizes(self):
        p=fixture()
        p.settings['group_size']=timing(5,2,8)
        e=Engine(p).run()
        self.assertTrue(all(2<=g.guests<=8 for g in e.groups.values()))
        self.assertGreater(len(set(g.guests for g in e.groups.values())),1)

    def test_path_geometry_and_travel(self):
        points=[[0,0],[3,4],[3,9]]
        self.assertEqual(length(points),10)
        self.assertEqual(interpolate(points,.5),(3,4))
        p=Project()
        p.settings['pixels_per_unit']=2
        path=new_object('path',points=points)
        path['seconds']=0
        self.assertEqual(travel(path,p,2),2.5)
        path['seconds']=7
        self.assertEqual(travel(path,p,2),7)

    def test_door_threshold_uses_leaf_intersection(self):
        path=new_object('path',points=[[0,0],[100,0]])
        door=new_object('door',25,-20)
        door.update(width=40,angle=90)
        self.assertAlmostEqual(door_path_fraction(path,door),.25)

    def test_scenario_isolation(self):
        p=fixture()
        room=next(o for o in p.objects if o['kind']=='room')
        p.scenarios={'Quick':{'objects':{room['id']:{'duration':timing(12)}},'settings':{'seed':77}}}
        variant=p.scenario('Quick')
        self.assertEqual(variant.by_id()[room['id']]['duration']['typical'],12)
        self.assertEqual(room['duration']['typical'],20)
        self.assertEqual(variant.settings['seed'],77)


class EngineTests(unittest.TestCase):
    def test_group_stops_at_midpath_door_then_finishes_remaining_travel(self):
        p=fixture()
        p.settings.update(duration=30,exterior_groups=1)
        path=next(o for o in p.objects if o.get('source')==next(n['id'] for n in p.objects if n['kind']=='entrance'))
        room=p.by_id()[path['target']]
        door=next(o for o in p.objects if o['kind']=='door')
        door.update(path=path['id'],x=(path['points'][0][0]+path['points'][-1][0])/2,
                    y=path['points'][0][1]-20,width=40,angle=90,automatic=False,style='swing')
        e=Engine(p)
        e.step()  # simulation start and admission
        e.step()  # reach the door halfway through the five-second path
        g=e.groups[1]
        self.assertEqual(g.state,'blocked')
        self.assertAlmostEqual(e.now,2.5)
        self.assertAlmostEqual(e.position(g)[0],door['x'])
        self.assertFalse(e.occupants[room['id']])
        self.assertFalse(any(row['event']=='room_entered' for row in e.log))
        e.door(door['id'],True)
        while e.queue and not any(row['event']=='room_entered' for row in e.log):
            e.step()
        entered=next(row for row in e.log if row['event']=='room_entered')
        self.assertAlmostEqual(entered['time'],7.0)  # 5s walking + 2s opening

    def test_multiple_doors_block_at_distinct_positions_on_one_path(self):
        p=fixture()
        p.settings.update(duration=30,exterior_groups=1)
        path=next(o for o in p.objects if o.get('source')==next(n['id'] for n in p.objects if n['kind']=='entrance'))
        y=path['points'][0][1]
        x0,x1=path['points'][0][0],path['points'][-1][0]
        doors=[o for o in p.objects if o['kind']=='door']
        doors[0].update(path=path['id'],x=x0+(x1-x0)*.25,y=y-20,width=40,angle=90,automatic=True,style='swing')
        second=copy.deepcopy(doors[0])
        second.update(id=uid(),name='Second door',x=x0+(x1-x0)*.75)
        p.objects.append(second)
        e=Engine(p).run()
        failures=[row for row in e.log if row['event']=='flow_failure']
        self.assertEqual([row['detail'] for row in failures],[doors[0]['id'],second['id']])
        entered=next(row for row in e.log if row['event']=='room_entered')
        self.assertAlmostEqual(entered['time'],9.0)  # 5s route + two 2s door openings

    def test_condition_is_checked_only_when_event_occurs(self):
        p=fixture()
        rooms=[o for o in p.objects if o['kind']=='room']
        door=next(o for o in p.objects if o['kind']=='door')
        door.update(style='swing',automatic=False)
        p.rules.append(dict(id=uid(),name='Conditional door',enabled=True,
            event='room_completed',source=rooms[0]['id'],condition='room_available',
            condition_target=rooms[1]['id'],action='open_door',target=door['id'],delay=0))
        e=Engine(p)
        e.occupants[rooms[1]['id']].add(999)
        e.emit('room_completed',rooms[0]['id'],1)
        self.assertFalse(any(row[2]=='action' and row[3][0]=='open_door' for row in e.queue))
        e.occupants[rooms[1]['id']].clear()
        self.assertFalse(any(row[2]=='action' and row[3][0]=='open_door' for row in e.queue))
        e.emit('room_completed',rooms[0]['id'],1)
        self.assertTrue(any(row[2]=='action' and row[3][0]=='open_door' for row in e.queue))

    def test_sensor_event_waits_until_room_becomes_available_then_opens_door_once(self):
        p=fixture()
        room=[o for o in p.objects if o['kind']=='room'][1]
        sensor=next(o for o in p.objects if o['kind']=='sensor')
        door=next(o for o in p.objects if o['kind']=='door')
        door.update(style='swing',automatic=False)
        rule=dict(id=uid(),name='Wait for downstream room',enabled=True,
            event='sensor_crossed',source=sensor['id'],condition='room_available',
            condition_target=room['id'],wait_for_condition=True,
            action='open_door',target=door['id'],delay=0)
        p.rules.append(rule)
        e=Engine(p)
        e.occupants[room['id']].add(999)
        e.emit('sensor_crossed',sensor['id'],1)
        e.emit('sensor_crossed',sensor['id'],2)
        self.assertEqual(list(e.pending_rules),[rule['id']])
        self.assertFalse(any(row[2]=='action' and row[3][0]=='open_door' for row in e.queue))
        e.occupants[room['id']].clear()
        e.reevaluate_pending_rules()
        actions=[row for row in e.queue if row[2]=='action' and row[3][0]=='open_door']
        self.assertEqual(len(actions),1)
        self.assertFalse(e.pending_rules)
        while e.queue and e.doors[door['id']]['state']=='closed':
            e.step()
        self.assertEqual(e.doors[door['id']]['state'],'opening')
        events=[row['event'] for row in e.log]
        self.assertIn('rule_waiting',events)
        self.assertIn('rule_wait_coalesced',events)
        self.assertIn('rule_condition_met',events)

    def test_additional_condition_types(self):
        p=fixture()
        room=next(o for o in p.objects if o['kind']=='room')
        path=next(o for o in p.objects if o['kind']=='path')
        door=next(o for o in p.objects if o['kind']=='door')
        e=Engine(p)
        def check(kind,target):
            return e.condition_met(dict(condition=kind,condition_target=target))
        self.assertTrue(check('room_empty',room['id']))
        self.assertFalse(check('room_occupied',room['id']))
        e.occupants[room['id']].add(1)
        self.assertFalse(check('room_empty',room['id']))
        self.assertTrue(check('room_occupied',room['id']))
        self.assertTrue(check('path_clear',path['id']))
        e.paths[path['id']].add(1)
        self.assertFalse(check('path_clear',path['id']))
        self.assertTrue(check('door_closed',door['id']))
        self.assertFalse(check('door_open',door['id']))
        self.assertTrue(check('enabled',door['id']))
        door_in_engine=e.objects[door['id']]
        door_in_engine['enabled']=False
        self.assertTrue(check('disabled',door['id']))

    def test_seeded_repeatability(self):
        p=fixture()
        p.settings['speed']=timing(3,1,5)
        for o in p.objects:
            if o['kind']=='room':
                o['duration']=timing(20,10,35)
        a,b=Engine(p).run(),Engine(p).run()
        self.assertEqual(a.log,b.log)
        self.assertEqual(summarize(a)['metrics'],summarize(b)['metrics'])

    def test_event_ordering_and_admission(self):
        e=Engine(fixture()).run()
        times=[r['time'] for r in e.log]
        self.assertEqual(times,sorted(times))
        sensor=[r for r in e.log if r['event']=='sensor_crossed']
        arrivals=[g.admitted for g in e.groups.values()]
        self.assertEqual(arrivals[0],0)
        self.assertEqual(arrivals[1],sensor[0]['time'])
        self.assertEqual(sum(e.sensor_counts.values()),8)

    def test_door_transitions(self):
        p=example()
        p.settings.update(duration=100,exterior_groups=1)
        e=Engine(p).run()
        states=[r['event'] for r in e.log if r['event'].startswith('door_')]
        self.assertEqual(states,['door_opening','door_opened','door_closing','door_closed'])
        self.assertEqual(sum(e.door_cycles.values()),1)

    def test_room_capacity_and_interior_failure(self):
        p=fixture()
        rooms=[o for o in p.objects if o['kind']=='room']
        rooms[1]['duration']=timing(80)
        e=Engine(p)
        while e.queue and e.queue[0][0]<=300:
            e.step()
            self.assertTrue(all(len(e.occupants[o['id']])<=o['capacity'] for o in rooms))
        result=summarize(e)
        self.assertGreater(result['metrics']['interior_failures'],0)
        self.assertGreater(result['metrics']['room_overstays'],0)
        self.assertTrue(any(v['cause']==rooms[1]['id'] for v in result['failures']))

    def test_ongoing_block_included(self):
        p=fixture()
        room=[o for o in p.objects if o['kind']=='room'][1]
        room['duration']=timing(1000)
        e=Engine(p).run()
        result=summarize(e)
        self.assertTrue(any(v.get('ongoing') for v in result['failures']))
        self.assertGreater(result['metrics']['longest_blockage'],100)

    def test_entrance_pending_release_and_coalescing(self):
        p=fixture()
        p.settings['initial_release']=False
        e=Engine(p)
        e.step()
        e.release()
        e.release()
        e.release()
        self.assertEqual(len(e.groups),1)
        self.assertEqual(e.coalesced_signals,1)
        e.advance(5)
        self.assertEqual(len(e.groups),2)
        self.assertEqual(e.latencies[1]['latency'],5)

    def test_sensor_disabled_and_cooldown(self):
        p=fixture()
        sensor=next(o for o in p.objects if o['kind']=='sensor')
        sensor['cooldown']=1000
        e=Engine(p).run()
        self.assertEqual(e.sensor_counts[sensor['id']],1)
        self.assertEqual(len(e.groups),2)
        sensor['enabled']=False
        e=Engine(p).run()
        self.assertEqual(len(e.groups),1)

    def test_throughput_exact(self):
        e=Engine(fixture()).run()
        r=summarize(e)
        done=sum(g.completed is not None for g in e.groups.values())
        self.assertEqual(r['metrics']['groups_per_hour'],done*12)
        self.assertEqual(r['metrics']['guests_per_hour'],done*48)
        self.assertEqual(sum(v['groups'] for v in r['windows']['5']),done)

    def test_stop_at_group_target(self):
        p=fixture()
        p.settings.update(stop='groups',limit=3)
        e=Engine(p).run()
        self.assertEqual(sum(g.completed is not None for g in e.groups.values()),3)

    def test_different_frame_steps_same_engine_result(self):
        p=fixture()
        fast=Engine(p).run()
        visual=Engine(p)
        for t in range(1,301):
            visual.advance(t)
        self.assertEqual(fast.log,visual.log)
        self.assertEqual(summarize(fast)['metrics'],summarize(visual)['metrics'])

    def test_csv_export(self):
        r=summarize(Engine(fixture()).run())
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'results.csv'
            export_csv(r,path)
            self.assertIn('groups_per_hour',path.read_text(encoding='utf-8-sig'))

    def test_cancellation(self):
        e=Engine(fixture()).run(lambda:True)
        self.assertEqual(e.reason,'Cancelled')
        self.assertEqual(len(e.groups),0)

    def test_crossing_path_spacing_conflict(self):
        p=fixture()
        paths=[o for o in p.objects if o['kind']=='path']
        paths[0].update(points=[[0,0],[100,0]],seconds=10,spacing=5)
        paths[1].update(points=[[50,-50],[50,50]],seconds=10,spacing=5)
        e=Engine(p)
        a=Group(1,4,3,0,paths[0]['source'])
        b=Group(2,4,3,0,paths[1]['source'])
        e.groups={1:a,2:b}
        e.enter_path(a,e.objects[paths[0]['id']])
        e.enter_path(b,e.objects[paths[1]['id']])
        self.assertEqual(len(e.spacing),1)
        self.assertAlmostEqual(e.spacing[0]['time'],5)
        self.assertAlmostEqual(e.spacing[0]['distance'],0)


class AnalysisTests(unittest.TestCase):
    def test_advisor_constraints_and_no_mutation(self):
        p=fixture()
        p.settings['duration']=120
        before=p.data()
        result=advise(p)
        self.assertGreater(result['tested'],0)
        for oid,override in result['overrides'].items():
            room=p.by_id()[oid]
            self.assertTrue(all(room['acceptable_min']<=v<=room['acceptable_max'] for v in override['duration'].values()))
        self.assertEqual(p.data(),before)

    def test_repeated_runs(self):
        p=fixture()
        result=repeated(p,3)
        self.assertEqual(result['runs'],3)
        self.assertEqual(result['p05_groups_per_hour'],result['p95_groups_per_hour'])
        self.assertTrue(0<=result['failure_probability']<=1)


class ValidationTests(unittest.TestCase):
    def test_example_valid(self):
        self.assertEqual(validate(fixture())[0],[])

    def test_missing_entrance_exit_and_rules(self):
        errors,_=validate(Project())
        self.assertGreaterEqual(len(errors),3)

    def test_disconnected_room(self):
        p=fixture()
        p.objects.append(new_object('room'))
        self.assertTrue(any('unreachable' in e for e in validate(p)[0]))

    def test_invalid_timing_and_missing_scale(self):
        p=fixture()
        next(o for o in p.objects if o['kind']=='room')['duration']=timing(20,30,10)
        next(o for o in p.objects if o['kind']=='path')['seconds']=0
        errors=validate(p)[0]
        self.assertTrue(any('minimum' in e for e in errors))
        self.assertTrue(any('calibrate' in e for e in errors))

    def test_deleted_reference_and_duplicate(self):
        p=fixture()
        p.rules[0]['source']='deleted'
        p.objects.append(copy.deepcopy(p.objects[0]))
        errors=validate(p)[0]
        self.assertTrue(any('deleted' in e for e in errors))
        self.assertTrue(any('Duplicate' in e for e in errors))

    def test_signal_cycle(self):
        p=fixture()
        for source,target in [('a','b'),('b','a')]:
            p.rules.append(dict(id=uid(),name=source,enabled=True,event='custom_signal',source=source,
                condition='always',condition_target='',action='signal',target=target,delay=0))
        self.assertTrue(any('Cyclic' in e for e in validate(p)[0]))

    def test_condition_type_and_target_validation(self):
        p=fixture()
        room=next(o for o in p.objects if o['kind']=='room')
        rule=p.rules[0]
        rule.update(condition='door_open',condition_target=room['id'])
        self.assertTrue(any('requires a door' in e for e in validate(p)[0]))
        rule.update(condition='made_up_condition')
        self.assertTrue(any('unknown condition' in e for e in validate(p)[0]))


if __name__=='__main__':
    unittest.main()
