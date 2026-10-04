"""Offscreen smoke tests exercise real Qt widgets and the application workflows."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from hauntsim.app import MainWindow
from hauntsim.model import Project, example, new_object
from hauntsim.editor import ObjectItem
from hauntsim.forms import Form
from hauntsim.persistence import save,load
from hauntsim.engine import Engine
from hauntsim.analytics import summarize


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        # Existing UI tests must never contact the real share or upload user queues.
        sync_patch=patch('hauntsim.cloud_ui.CloudController.sync',return_value=False)
        sync_patch.start()
        self.addCleanup(sync_patch.stop)
        self.window=MainWindow()
        self.window.show()
        self.app.processEvents()

    def test_cloud_save_download_and_menu(self):
        from hauntsim.cloud import CloudStore
        w=self.window
        with tempfile.TemporaryDirectory() as folder:
            w.cloud.store=CloudStore(Path(folder)/'cache.sqlite')
            w.project.name='Cloud test'
            w.dirty=True
            with patch('hauntsim.cloud_ui.QInputDialog.getText',return_value=('My haunt',True)):
                self.assertTrue(w.save())
            self.assertFalse(w.dirty)
            key=w.cloud.active
            self.assertTrue(w.cloud.store.get(key)['pending'])
            w.project.name='Edited offline'
            self.assertTrue(w.save())
            self.assertEqual(w.cloud.active,key)
            self.assertEqual(len(w.cloud.store.rows()),1)
            target=Path(folder)/'download.hauntsim'
            with patch('hauntsim.cloud_ui.QFileDialog.getSaveFileName',return_value=(str(target),'')):
                w.cloud.download()
            self.assertEqual(load(target).name,'Edited offline')
            self.assertEqual(w.cloud.active,key)
            cloud=next(a.menu() for a in w.menuBar().actions() if a.text()=='&Cloud')
            self.assertTrue(any(a.text()=='Cloud projects...' for a in cloud.actions()))
            w.set_project(Project())
            self.assertIsNone(w.cloud.active)

    def test_duration_presets_custom_cancel_scenarios_and_reload(self):
        w=self.window
        p=example()
        p.settings.update(duration=123,stop='time')
        w.set_project(p)
        self.assertEqual(w.preset.currentIndex(),4)
        w.preset.setCurrentIndex(1)
        self.assertEqual(w.effective().settings['duration'],600)
        self.assertTrue(w.init_engine())
        self.assertEqual(w.engine.project.settings['duration'],600)
        self.assertFalse(w.preset.isEnabled())
        w.reset()
        with patch('hauntsim.app.edit_values',return_value=None):
            w.preset.setCurrentIndex(4)
        self.assertEqual(w.preset.currentIndex(),1)
        self.assertEqual(w.effective().settings['duration'],600)
        def custom(parent,title,values):
            self.assertEqual(values['duration'],123)
            values.update(duration=321,stop='groups',limit=7)
            return values
        with patch('hauntsim.app.edit_values',side_effect=custom):
            w.preset.setCurrentIndex(4)
        self.assertEqual(w.effective().settings['duration'],321)
        self.assertEqual(w.effective().settings['stop'],'groups')
        w.preset.setCurrentIndex(2)
        self.assertEqual(w.effective().settings['duration'],1800)
        self.assertEqual(w.effective().settings['stop'],'time')
        with patch('hauntsim.app.edit_values',side_effect=lambda parent,title,values:values):
            w.preset.setCurrentIndex(4)
        self.assertEqual(w.effective().settings['duration'],321)
        self.assertEqual(w.effective().settings['stop'],'groups')
        w.project.scenarios['Short']={'settings':{'duration':600,'stop':'time','duration_preset':'preset'}}
        w.switch_scenario('Short')
        self.assertEqual(w.preset.currentIndex(),1)
        w.switch_scenario('Base')
        self.assertEqual(w.preset.currentIndex(),4)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'project.hauntsim'
            save(w.project,path)
            w.set_project(load(path))
        self.assertEqual(w.preset.currentIndex(),4)
        self.assertEqual(w.project.settings['custom_duration'],321)

    def test_settings_change_and_undo_refresh_duration(self):
        w=self.window
        w.set_project(example())
        def changed(parent,title,values):
            values['duration']=71
            return values
        with patch('hauntsim.app.edit_values',side_effect=changed):
            w.project_settings()
        self.assertEqual(w.preset.currentIndex(),4)
        w.preset.setCurrentIndex(3)
        self.assertEqual(w.project.settings['duration'],7200)
        w.undo()
        self.assertEqual(w.project.settings['duration'],71)
        self.assertEqual(w.preset.currentIndex(),4)

    def test_advisor_rejects_stale_configuration(self):
        w=self.window
        w.set_project(example())
        source=('Base',w.effective().data())
        room=next(o for o in w.project.objects if o['kind']=='room')
        advice={'overrides':{room['id']:{'duration':{'min':15,'typical':15,'max':15}}}}
        room['duration']['typical']=21
        with patch.object(w,'notice') as notice:
            w.apply_advice(advice,source)
        notice.assert_called_once()
        self.assertEqual(w.project.scenarios,{})

    def test_visual_time_run_continues_to_horizon_when_idle(self):
        w=self.window
        p=example()
        p.settings.update(duration=300,exterior_groups=1)
        w.set_project(p)
        w.run_visual()
        while w.engine.queue:
            w.engine.step()
            if w.engine.stopped:
                break
        self.assertLess(w.engine.now,300)
        w.last_tick=time.monotonic()-.1
        w.tick()
        self.assertTrue(w.timer.isActive())
        w.engine.advance(300)
        w.tick()
        self.assertFalse(w.timer.isActive())
        self.assertEqual(w.last_result['metrics']['duration'],300)

    def test_stopped_visual_run_cannot_resume_or_duplicate_history(self):
        w=self.window
        w.set_project(example())
        self.assertTrue(w.init_engine())
        w.engine.advance(100)
        w.stop()
        count=len(w.project.results)
        w.stop()
        self.assertEqual(len(w.project.results),count)
        with patch.object(w,'notice'):
            self.assertFalse(w.init_engine())
        w.reset()
        self.assertTrue(w.init_engine())

    def tearDown(self):
        self.window.dirty=False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_end_to_end(self):
        w=self.window
        w.set_project(example())
        self.assertTrue(w.preflight())
        w.view.fit()
        w.init_engine()
        w.engine.advance(90)
        w.render_status()
        w.stop()
        self.assertGreater(w.last_result['metrics']['groups_admitted'],0)
        w.overlay()
        w.reset()
        room=next(o for o in w.project.objects if o['kind']=='room')
        w.inspect(room['id'])
        self.app.processEvents()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'project.hauntsim'
            save(w.project,path)
            w.set_project(load(path),str(path))
            self.assertEqual(len(w.project.objects),11)
        self.assertFalse(w.grab().isNull())

    def test_edit_undo_redo_copy_and_scenario(self):
        w=self.window
        w.add_object(new_object('room',100,100))
        self.assertEqual(len(w.project.objects),1)
        w.undo()
        self.assertEqual(len(w.project.objects),0)
        w.redo()
        self.assertEqual(len(w.project.objects),1)
        w.clipboard=[w.project.objects[0]]
        w.paste()
        self.assertEqual(len(w.project.objects),2)
        self.assertNotEqual(w.project.objects[0]['id'],w.project.objects[1]['id'])
        w.project.scenarios['Test']={}
        w.switch_scenario('Test')
        self.assertFalse(w.view.editable)

    def test_background_and_calibration_roundtrip(self):
        w=self.window
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'floor.png'
            image=QImage(400,300,QImage.Format_RGB32)
            image.fill(QColor('#dddddd'))
            image.save(str(path))
            with patch('hauntsim.app.QFileDialog.getOpenFileName',return_value=(str(path),'')):
                w.import_background()
            w.calibrate(25.,'feet')
            project_path=Path(d)/'project.hauntsim'
            save(w.project,project_path)
            restored=load(project_path)
            self.assertEqual(restored.background,path.read_bytes())
            self.assertEqual(restored.settings['pixels_per_unit'],25.)

    def test_background_worker_returns_results(self):
        w=self.window
        w.set_project(example())
        w.project.settings['duration']=120
        w.fast()
        deadline=time.monotonic()+10
        while w.worker and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertIsNone(w.worker)
        self.assertIsNotNone(w.last_result)
        self.assertEqual(w.last_result['metrics']['duration'],120)

    def test_sensor_edit_updates_graphical_location(self):
        w=self.window
        w.set_project(example())
        sensor=next(o for o in w.project.objects if o['kind']=='sensor').copy()
        sensor['fraction']=.25
        w.change_objects([sensor])
        sensor=w.project.by_id()[sensor['id']]
        path=w.project.by_id()[sensor['path']]
        expected=path['points'][0][0]+.25*(path['points'][1][0]-path['points'][0][0])
        self.assertAlmostEqual(sensor['x'],expected)

    def test_new_and_moved_door_associate_with_nearest_path(self):
        w=self.window
        first=new_object('path',points=[[20,50],[220,50]])
        second=new_object('path',points=[[20,250],[220,250]])
        w.set_project(Project(objects=[first,second]))
        w.view.set_tool('door')
        QTest.mouseClick(w.view.viewport(),Qt.LeftButton,Qt.NoModifier,
                         w.view.mapFromScene(QPointF(100,60)))
        self.app.processEvents()
        door=next(o for o in w.project.objects if o['kind']=='door')
        self.assertEqual(door['path'],first['id'])
        moved=door.copy()
        moved.update(x=100,y=240)
        w.change_objects([moved])
        self.assertEqual(w.project.by_id()[door['id']]['path'],second['id'])

    def test_handles_preview_geometry_without_translating_object(self):
        for kind in ('path','door','room'):
            with self.subTest(kind=kind):
                w=self.window
                obj=new_object(kind,200,200)
                if kind=='path':
                    obj['points']=[[100,100],[200,200],[300,100]]
                w.set_project(Project(objects=[obj]))
                self.app.processEvents()
                item=next(i for i in w.view.scene().items() if isinstance(i,ObjectItem))
                item.setSelected(True)
                self.app.processEvents()
                handle=w.view.handles[1 if kind=='path' else 0]
                original_position=item.pos()
                start=w.view.mapFromScene(handle.pos())
                end=w.view.mapFromScene(handle.pos()+QPointF(35,25))
                QTest.mousePress(w.view.viewport(),Qt.LeftButton,Qt.NoModifier,start)
                QTest.mouseMove(w.view.viewport(),end,10)
                self.app.processEvents()
                # Check the visible state while the button is still held, not just the commit.
                self.assertEqual(item.pos(),original_position)
                self.assertNotEqual(item.obj,obj)
                self.assertEqual(w.project.objects[0],obj)
                if kind=='path':
                    self.assertEqual(item.obj['points'][0],obj['points'][0])
                    self.assertEqual(item.obj['points'][2],obj['points'][2])
                    self.assertNotEqual(item.obj['points'][1],obj['points'][1])
                else:
                    self.assertEqual((item.obj['x'],item.obj['y']),(obj['x'],obj['y']))
                QTest.mouseRelease(w.view.viewport(),Qt.LeftButton,Qt.NoModifier,end)
                self.app.processEvents()
                self.assertNotEqual(w.project.objects[0],obj)
                self.assertEqual(len(w.undo_history),1)
                w.undo()
                self.assertEqual(w.project.objects[0],obj)

    def test_path_vertex_can_be_deleted_without_deleting_path(self):
        w=self.window
        path=new_object('path',points=[[10,10],[80,30],[140,10]])
        w.set_project(Project(objects=[path]))
        item=next(i for i in w.view.scene().items() if isinstance(i,ObjectItem))
        item.setSelected(True)
        self.app.processEvents()
        middle=w.view.handles[1]
        self.assertTrue(middle.delete_vertex())
        self.assertEqual(len(w.project.objects),1)
        self.assertEqual(w.project.objects[0]['points'],[[10,10],[140,10]])
        item=next(i for i in w.view.scene().items() if isinstance(i,ObjectItem))
        item.setSelected(True)
        self.app.processEvents()
        self.assertFalse(w.view.handles[0].delete_vertex())
        self.assertEqual(len(w.project.objects[0]['points']),2)

    def test_clicks_follow_shapes_and_reach_routes_inside_rooms(self):
        w=self.window
        room=new_object('room',200,200)
        room.update(width=400,height=400)
        path=new_object('path',points=[[100,100],[300,100],[300,300]])
        door=new_object('door',100,250)
        door['width']=90
        sensor=new_object('sensor',150,150)
        w.set_project(Project(objects=[room,path,door,sensor]))
        self.app.processEvents()
        for point,expected in [((200,200),room),  # Empty interior of the path's bounding box.
                               ((180,150),room),  # Outside the sensor marker.
                               ((130,280),room),  # Inside door bounds, away from its leaf.
                               ((300,200),path),  # Route within a filled room.
                               ((135,250),door),
                               ((150,150),sensor)]:
            with self.subTest(point=point):
                QTest.mouseClick(w.view.viewport(),Qt.LeftButton,Qt.NoModifier,
                                 w.view.mapFromScene(QPointF(*point)))
                self.app.processEvents()
                self.assertEqual(w.view.selected_ids(),[expected['id']])

    def test_properties_apply_live_preserve_focus_and_group_undo(self):
        w=self.window
        obj=new_object('door',200,200)
        w.set_project(Project(objects=[obj]))
        item=next(i for i in w.view.scene().items() if isinstance(i,ObjectItem))
        item.setSelected(True)
        form=w.inspector.widget().findChild(Form)
        width=form.widgets['width'][1]
        width.setValue(70)
        width.setValue(95)
        self.assertEqual(w.project.objects[0]['width'],95)
        self.assertIs(w.inspector.widget().findChild(Form),form)
        item=next(i for i in w.view.scene().items() if isinstance(i,ObjectItem))
        self.assertEqual(item.obj['width'],95)
        self.assertEqual(len(w.undo_history),1)
        name=form.widgets['name'][1]
        name.setFocus()
        name.selectAll()
        QTest.keyClicks(name,'Front door')
        self.assertEqual(w.project.objects[0]['name'],'Front door')
        self.assertTrue(name.hasFocus())
        self.assertEqual(len(w.undo_history),2)
        w.undo()
        self.assertEqual(w.project.objects[0]['name'],obj['name'])
        self.assertEqual(w.project.objects[0]['width'],95)
        w.undo()
        self.assertEqual(w.project.objects[0]['width'],obj['width'])

    def test_event_log_search_shortcut_and_auto_scroll(self):
        w=self.window
        w.set_project(example())
        w.engine=Engine(w.project)
        w.engine.log=[dict(time=i,event='test_event',source='',group=i,detail='line') for i in range(200)]
        w.log_dock.show()
        w.log_autoscroll.setChecked(True)
        w.refresh_log()
        scrollbar=w.log_text.verticalScrollBar()
        self.assertEqual(scrollbar.value(),scrollbar.maximum())
        w.log_autoscroll.setChecked(False)
        scrollbar.setValue(scrollbar.maximum()//2)
        previous=scrollbar.value()
        w.engine.log.append(dict(time=201,event='test_event',source='',group=201,detail='new'))
        w.refresh_log()
        self.assertEqual(scrollbar.value(),previous)
        w.log_filter.setEditText('group:201')
        QTest.keyClick(w,Qt.Key_F,Qt.ControlModifier)
        self.app.processEvents()
        self.assertTrue(w.log_dock.isVisible())
        self.assertTrue(w.log_filter.lineEdit().hasFocus())
        self.assertEqual(w.log_filter.lineEdit().selectedText(),'group:201')


if __name__=='__main__':
    unittest.main()
