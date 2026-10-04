"""Desktop application shell. All model mutations pass through undoable snapshots."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QAction, QKeySequence, QImage
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QDockWidget,QScrollArea,QPushButton,QLabel,QComboBox,QListWidget,QToolBar,
    QTabWidget,QFileDialog,QMessageBox,QInputDialog,QPlainTextEdit,QProgressBar)
from .model import Project, example, uid, interpolate, nearest_fraction
from .persistence import save, load
from .validation import validate
from .engine import Engine
from .analytics import summarize, compact, export_csv
from .analysis_jobs import repeated, advise
from .editor import LayoutView
from .forms import Form, edit_values
from .reports import Reports, table
from .workers import Worker
from .cloud_ui import CloudController


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings=QSettings('HauntSim','Layout Studio')
        self.project=Project()
        self.filename=''
        self.dirty=False
        self.undo_history=[]
        self.redo_history=[]
        self.clipboard=[]
        self.active='Base'
        self.engine=None
        self.worker=None
        self.last_result=None
        self.current_id=''
        self.property_edit_key=None
        self.updating_properties=False
        self.timer=QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.resize(1440,900)
        self.tabs=QTabWidget()
        self.view=LayoutView()
        self.reports=Reports()
        self.tabs.addTab(self.view,'Layout & simulation')
        self.tabs.addTab(self.reports,'Analytics')
        self.setCentralWidget(self.tabs)
        self.view.created.connect(self.add_object)
        self.view.changed.connect(self.change_objects)
        self.view.selected.connect(self.inspect)
        self.view.calibration.connect(self.calibrate)
        self.view.delete_requested.connect(self.delete)
        self.view.copy_requested.connect(self.copy)
        self.view.paste_requested.connect(self.paste)
        self.build_docks()
        self.build_menus()
        self.build_controls()
        self.cloud=CloudController(self)
        self.refresh()
        self.resizeDocks([self.inspector_dock,self.rules_dock],[580,220],Qt.Vertical)
        geometry=self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        self.statusBar().showMessage('New project: import a floor plan, draw rooms, then connect them with paths.')

    def effective(self):
        return self.project.scenario(self.active)

    def action(self,menu,title,callback,shortcut=None):
        action=QAction(title,self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda checked=False:callback())
        menu.addAction(action)
        return action

    def build_menus(self):
        bar=self.menuBar()
        file=bar.addMenu('&File')
        self.action(file,'New project',self.new,'Ctrl+N')
        self.action(file,'Open project…',self.open,'Ctrl+O')
        self.action(file,'Save',self.save,'Ctrl+S')
        self.action(file,'Save a cloud copy...',lambda:self.save(True),'Ctrl+Shift+S')
        self.action(file,'Download project file...',lambda:self.cloud.download())
        cloud=bar.addMenu('&Cloud')
        self.action(cloud,'Cloud projects...',lambda:self.cloud.browse(),'Ctrl+Shift+O')
        self.action(cloud,'Sync now',lambda:self.cloud.sync())
        self.action(cloud,'Save to cloud',self.save)
        self.action(cloud,'Download project file...',lambda:self.cloud.download())
        self.recent_menu=file.addMenu('Recent projects')
        self.refresh_recent()
        self.action(file,'Close project',self.new)
        file.addSeparator()
        self.action(file,'Export results CSV…',self.export)
        self.action(file,'Export full result JSON…',self.export_json)
        self.action(file,'Exit',self.close,'Alt+F4')
        edit=bar.addMenu('&Edit')
        self.action(edit,'Undo',self.undo,'Ctrl+Z')
        self.action(edit,'Redo',self.redo,'Ctrl+Y')
        self.action(edit,'Copy',self.copy,'Ctrl+C')
        self.action(edit,'Paste',self.paste,'Ctrl+V')
        self.action(edit,'Delete',self.delete,'Delete')
        edit.addSeparator()
        self.action(edit,'Search event log',self.focus_log_search,'Ctrl+F')
        view=bar.addMenu('&View')
        self.action(view,'Fit layout',self.view.fit,'F')
        snap=QAction('Snap to 10-pixel grid',self,checkable=True)
        snap.toggled.connect(lambda value:setattr(self.view,'snap',value))
        view.addAction(snap)
        layers=view.addMenu('Layers')
        for kind in ('background','room','path','door','sensor','entrance','exit'):
            action=QAction(kind.title(),self,checkable=True)
            action.setChecked(True)
            action.toggled.connect(lambda checked,k=kind:self.layer(k,checked))
            layers.addAction(action)
        for dock in (self.inspector_dock,self.rules_dock,self.log_dock):
            view.addAction(dock.toggleViewAction())
        self.action(view,'Bottleneck overlay',self.overlay)
        project=bar.addMenu('&Project')
        self.action(project,'Import background…',self.import_background)
        self.action(project,'Calibrate scale (two clicks)',lambda:self.set_tool('calibrate'))
        self.action(project,'Project / run settings…',self.project_settings)
        self.action(project,'Validate',lambda:self.preflight(True))
        self.action(project,'Duplicate scenario…',self.duplicate_scenario)
        self.action(project,'Rename scenario…',self.rename_scenario)
        self.action(project,'Delete scenario',self.delete_scenario)
        self.action(project,'Stored run history',self.history)
        simulation=bar.addMenu('&Simulation')
        for title,callback in [('Run / Resume',self.run_visual),('Pause',self.pause),('Stop',self.stop),
            ('Reset / Edit',self.reset),('Event step',self.step),('Manual release',self.manual_release),('Fast analysis',self.fast)]:
            self.action(simulation,title,callback)
        analytics=bar.addMenu('&Analytics')
        self.action(analytics,'Show results',lambda:self.tabs.setCurrentIndex(1))
        self.action(analytics,'Repeated simulations…',self.repeat)
        self.action(analytics,'Timing advisor',self.advisor)
        self.action(analytics,'Compare scenarios',self.compare)
        self.action(analytics,'Map overlay',self.overlay)
        help_menu=bar.addMenu('&Help')
        self.action(help_menu,'Open example project',self.open_example)
        self.action(help_menu,'User guide',self.guide)
        self.action(help_menu,'About',lambda:QMessageBox.information(self,'HauntSim',
            'HauntSim 1.0\nStandalone discrete-event planning studio.\nNo hardware or live control interfaces.'))

    def build_docks(self):
        self.inspector_dock=QDockWidget('Object properties',self)
        self.inspector_dock.setMinimumWidth(325)
        self.inspector=QScrollArea()
        self.inspector.setWidgetResizable(True)
        self.inspector_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.RightDockWidgetArea,self.inspector_dock)
        self.rules_dock=QDockWidget('WHEN / IF / THEN rules',self)
        self.rules_dock.setMaximumHeight(260)
        widget=QWidget()
        layout=QVBoxLayout(widget)
        self.rule_list=QListWidget()
        self.rule_list.itemDoubleClicked.connect(lambda item:self.edit_rule())
        layout.addWidget(self.rule_list)
        row=QHBoxLayout()
        for title,fn in [('Add',self.add_rule),('Edit',self.edit_rule),('Delete',self.delete_rule)]:
            b=QPushButton(title)
            b.clicked.connect(fn)
            row.addWidget(b)
        layout.addLayout(row)
        self.rules_dock.setWidget(widget)
        self.addDockWidget(Qt.RightDockWidgetArea,self.rules_dock)
        self.log_dock=QDockWidget('Event log (last 1,000 matching events)',self)
        widget=QWidget()
        layout=QVBoxLayout(widget)
        search_row=QHBoxLayout()
        search_row.addWidget(QLabel('Search:'))
        self.log_filter=QComboBox()
        self.log_filter.setEditable(True)
        self.log_filter.addItems(['','room','door','sensor','release','flow_failure','room_overstay','group:1'])
        self.log_filter.lineEdit().setPlaceholderText('Event, object, details, or group:12')
        self.log_filter.currentTextChanged.connect(lambda _:self.refresh_log())
        search_row.addWidget(self.log_filter,1)
        self.log_autoscroll=QPushButton('Auto-scroll')
        self.log_autoscroll.setCheckable(True)
        self.log_autoscroll.setChecked(self.settings.value('log_autoscroll',True,type=bool))
        self.log_autoscroll.setToolTip('Keep the event log scrolled to the newest matching line')
        self.log_autoscroll.toggled.connect(lambda value:self.settings.setValue('log_autoscroll',value))
        self.log_autoscroll.toggled.connect(lambda value:self.scroll_log_to_bottom() if value else None)
        search_row.addWidget(self.log_autoscroll)
        layout.addLayout(search_row)
        self.log_text=QPlainTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        self.log_dock.setWidget(widget)
        self.addDockWidget(Qt.BottomDockWidgetArea,self.log_dock)
        self.log_dock.hide()

    def build_controls(self):
        tools=QToolBar('Drawing tools',self)
        self.addToolBar(Qt.LeftToolBarArea,tools)
        for tool in ('select','pan','room','path','door','sensor','entrance','exit','calibrate'):
            action=QAction(tool.title(),self)
            action.triggered.connect(lambda checked=False,t=tool:self.set_tool(t))
            tools.addAction(action)
        controls=QToolBar('Simulation controls',self)
        self.addToolBar(controls)
        for title,callback in [('Run',self.run_visual),('Pause',self.pause),('Stop',self.stop),
            ('Reset / Edit',self.reset),('Step',self.step),('Release',self.manual_release),('Fast',self.fast)]:
            self.action(controls,title,callback)
        controls.addSeparator()
        self.speed=QComboBox()
        self.speed.addItems(['1x','2x','5x','10x','25x','50x'])
        controls.addWidget(self.speed)
        self.preset=QComboBox()
        self.preset.addItems(['60 minutes','10 minutes','30 minutes','2 hours','Custom…'])
        self.preset.currentIndexChanged.connect(self.set_duration)
        controls.addWidget(self.preset)
        controls.addSeparator()
        controls.addWidget(QLabel(' Scenario: '))
        self.scenario_combo=QComboBox()
        self.scenario_combo.currentTextChanged.connect(self.switch_scenario)
        controls.addWidget(self.scenario_combo)
        self.progress=QProgressBar()
        self.progress.setMaximumWidth(140)
        self.progress.hide()
        controls.addWidget(self.progress)
        self.cancel_button=QPushButton('Cancel analysis')
        self.cancel_button.clicked.connect(self.cancel_job)
        self.cancel_button.hide()
        controls.addWidget(self.cancel_button)
        self.status_label=QLabel('Ready')
        self.statusBar().addPermanentWidget(self.status_label)

    def set_tool(self,tool):
        if not self.view.editable and tool not in ('select','pan'):
            self.notice('Reset the simulation and select Base to edit the layout.')
            return
        self.view.set_tool(tool)
        self.statusBar().showMessage({'room':'Click two opposite corners.',
            'path':'Click route vertices; double-click or Enter to finish. Start/end near room centers.',
            'calibrate':'Click two ends of a known dimension.',
            'door':'Click the hinge / slide origin. Associate the door in a path’s properties.',
            'sensor':'Click near a path. The nearest route position is selected automatically.'}.get(tool,
            'Select an object to edit its properties. Drag white handles to edit geometry.'))

    def notice(self,text):
        QMessageBox.information(self,'HauntSim',text)

    def error(self,text):
        QMessageBox.warning(self,'HauntSim',str(text))

    def can_edit(self):
        if self.engine or self.worker:
            self.notice('Use Reset / Edit, or cancel the current analysis, before changing the project.')
            return False
        return True

    def checkpoint(self):
        self.property_edit_key=None
        self.undo_history.append(deepcopy(self.project))
        self.undo_history=self.undo_history[-60:]
        self.redo_history.clear()
        self.dirty=True

    def refresh(self):
        self.view.editable=not self.engine and not self.worker and self.active=='Base'
        self.view.rebuild(self.effective())
        self.rule_list.clear()
        for r in self.effective().rules:
            condition=r.get('condition','always')
            target=self.effective().by_id().get(r.get('condition_target',''),{}).get('name','')
            condition_text='' if condition=='always' else f" IF {condition}{' · '+target if target else ''}"
            remembered=' · remembered' if condition!='always' and r.get('wait_for_condition',False) else ''
            self.rule_list.addItem(f"{'●' if r['enabled'] else '○'} {r['name']}\n"
                                   f"{r['event']}{condition_text} → {r['action']}{remembered}")
        self.scenario_combo.blockSignals(True)
        self.scenario_combo.clear()
        self.scenario_combo.addItems(['Base']+list(self.project.scenarios))
        self.scenario_combo.setCurrentText(self.active)
        self.scenario_combo.blockSignals(False)
        self.refresh_duration()
        self.update_title()

    def update_title(self):
        name=Path(self.filename).name if self.filename else self.project.name
        if hasattr(self,'cloud') and self.cloud.active:
            row=self.cloud.store.get(self.cloud.active)
            if row:
                name=row['name']
        self.setWindowTitle(f"{'* ' if self.dirty else ''}{name} — HauntSim")

    def inspect(self,oid):
        if self.updating_properties:
            return
        self.property_edit_key=None
        self.current_id=oid
        obj=self.effective().by_id().get(oid)
        if not obj:
            self.inspector.setWidget(QLabel('Select a room, path, door, sensor, entrance or exit.'))
            return
        panel=QWidget()
        layout=QVBoxLayout(panel)
        form=Form(obj,self.effective())
        layout.addWidget(form)
        form.setEnabled(not self.engine and not self.worker)
        form.edited.connect(lambda key:self.edit_property(oid,form,key))
        form.editing_finished.connect(lambda:self.finish_property_edit(oid,form))
        if self.last_result:
            r=self.last_result
            data=r.get('rooms',{}).get(oid,r.get('doors',{}).get(oid,{}))
            failures=[v for v in r.get('failures',[]) if oid in (v['location'],v['cause'])]
            metrics=QLabel('Last run\n'+json.dumps(data,indent=2)+f'\nRelated flow failures: {len(failures)}')
            metrics.setWordWrap(True)
            layout.addWidget(metrics)
        self.inspector.setWidget(panel)

    def edit_property(self,oid,form,key):
        if self.engine or self.worker or oid!=self.current_id:
            return
        obj=self.effective().by_id().get(oid)
        if not obj:
            return
        value=form.values()[key]
        if obj[key]==value:
            return
        obj[key]=value
        # Keep the active form alive: rebuilding it would lose focus on every keystroke.
        self.updating_properties=True
        try:
            self.change_objects([obj],merge_key=(self.active,oid,key))
            form.sync(self.effective().by_id()[oid],exclude=(key,))
        finally:
            self.updating_properties=False

    def finish_property_edit(self,oid,form):
        self.property_edit_key=None
        if oid==self.current_id:
            obj=self.effective().by_id().get(oid)
            if obj:
                form.sync(obj)

    def add_object(self,obj):
        if not self.can_edit() or self.active!='Base':
            return
        self.checkpoint()
        obj['name'] += ' '+str(1+sum(o['kind']==obj['kind'] for o in self.project.objects))
        self.project.objects.append(obj)
        self.refresh()
        for item in self.view.scene().items():
            if hasattr(item,'obj') and item.obj['id']==obj['id']:
                item.setSelected(True)

    def change_objects(self,objects,merge_key=None):
        if not self.can_edit():
            return
        if merge_key is None or merge_key!=self.property_edit_key:
            self.checkpoint()
        self.property_edit_key=merge_key
        if self.active=='Base':
            changes={o['id']:o for o in objects}
            old_objects=self.project.by_id()
            for obj in objects:
                old=old_objects[obj['id']]
                if obj['kind']=='sensor' and (obj['x'],obj['y'])!=(old['x'],old['y']):
                    path=old_objects.get(obj['path'])
                    if path and path['kind']=='path':
                        obj['fraction']=nearest_fraction(path['points'],[obj['x'],obj['y']])
                elif obj['kind']=='door' and (obj['x'],obj['y'])!=(old['x'],old['y']):
                    nearest=self.view.nearest_path([obj['x'],obj['y']])
                    if nearest[1]:
                        obj['path']=nearest[1]['id']
            # Moving connected nodes adjusts route endpoints, keeping connectivity visually honest.
            for old in self.project.objects:
                if old['id'] in changes and old['kind'] in ('room','entrance','exit'):
                    new=changes[old['id']]
                    dx,dy=new['x']-old['x'],new['y']-old['y']
                    for path in self.project.objects:
                        if path['kind']=='path':
                            for key,index in [('source',0),('target',-1)]:
                                if path[key]==old['id']:
                                    path['points'][index][0]+=dx
                                    path['points'][index][1]+=dy
            self.project.objects=[changes.get(o['id'],o) for o in self.project.objects]
            by_id=self.project.by_id()
            for sensor in self.project.objects:
                if sensor['kind']=='sensor' and sensor['path'] in by_id:
                    path=by_id[sensor['path']]
                    if path['kind']=='path':
                        sensor['x'],sensor['y']=interpolate(path['points'],sensor['fraction'])
        else:
            override=self.project.scenarios[self.active].setdefault('objects',{})
            geometry={'id','kind','x','y','width','height','points','name','notes'}
            for obj in objects:
                override[obj['id']]={k:v for k,v in obj.items() if k not in geometry}
        self.refresh()

    def undo(self):
        if self.can_edit() and self.undo_history:
            self.redo_history.append(deepcopy(self.project))
            self.project=self.undo_history.pop()
            if self.active not in self.project.scenarios:
                self.active='Base'
            self.dirty=True
            self.refresh()

    def redo(self):
        if self.can_edit() and self.redo_history:
            self.undo_history.append(deepcopy(self.project))
            self.project=self.redo_history.pop()
            self.dirty=True
            self.refresh()

    def copy(self):
        ids=self.view.selected_ids()
        self.clipboard=deepcopy([o for o in self.effective().objects if o['id'] in ids])

    def paste(self):
        if not self.clipboard or not self.can_edit() or self.active!='Base':
            return
        self.checkpoint()
        objects=deepcopy(self.clipboard)
        mapping={o['id']:uid() for o in objects}
        for obj in objects:
            obj['id']=mapping[obj['id']]
            obj['name']+=' copy'
            obj['x']+=25
            obj['y']+=25
            if 'points' in obj:
                obj['points']=[[x+25,y+25] for x,y in obj['points']]
            for key in ('source','target','path','door'):
                if obj.get(key) in mapping:
                    obj[key]=mapping[obj[key]]
        self.project.objects.extend(objects)
        self.refresh()

    def delete(self):
        ids=self.view.selected_ids()
        if not ids or not self.can_edit() or self.active!='Base':
            return
        if QMessageBox.question(self,'Delete objects',f'Delete {len(ids)} selected objects? References will be checked by validation.')!=QMessageBox.Yes:
            return
        self.checkpoint()
        self.project.objects=[o for o in self.project.objects if o['id'] not in ids]
        self.refresh()

    def layer(self,kind,visible):
        self.view.hidden.discard(kind) if visible else self.view.hidden.add(kind)
        self.view.rebuild(self.effective())
        if self.engine:
            self.view.animate(self.engine)

    def calibrate(self,scale,units):
        if self.can_edit():
            self.checkpoint()
            self.project.settings.update(pixels_per_unit=scale,units=units)
            self.refresh()

    def import_background(self):
        if not self.can_edit():
            return
        filename,_=QFileDialog.getOpenFileName(self,'Import floor plan','','Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)')
        if filename:
            try:
                data=Path(filename).read_bytes()
                if len(data)>50_000_000 or QImage.fromData(data).isNull():
                    raise ValueError('Choose a supported image smaller than 50 MB.')
                self.checkpoint()
                self.project.background=data
                self.refresh()
                self.view.fit()
            except Exception as exc:
                self.error(exc)

    def refresh_duration(self):
        settings=self.effective().settings
        durations=[3600,600,1800,7200]
        index=4
        if settings['stop']=='time' and settings.get('duration_preset')!='custom':
            if settings['duration'] in durations:
                index=durations.index(settings['duration'])
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(index)
        self.preset.blockSignals(False)
        self.preset.setEnabled(not self.engine and not self.worker)

    def project_settings(self,custom=False):
        if not self.can_edit():
            return
        settings=self.effective().settings
        metadata=('duration_preset','custom_duration','custom_stop','custom_limit')
        initial=dict(name=self.project.name,**{k:v for k,v in settings.items() if k not in metadata})
        if custom:
            for key in ('duration','stop','limit'):
                initial[key]=settings.get('custom_'+key,settings[key])
        values=edit_values(self,'Project and run settings',initial)
        if values:
            self.checkpoint()
            self.project.name=values.pop('name')
            values.update(duration_preset='custom',custom_duration=values['duration'],
                          custom_stop=values['stop'],custom_limit=values['limit'])
            if self.active=='Base':
                self.project.settings=values
            else:
                self.project.scenarios[self.active]['settings']=values
            self.refresh()
        else:
            self.refresh_duration()

    def set_duration(self,index):
        if self.engine or self.worker:
            self.refresh_duration()
            return
        if index==4:
            self.project_settings(custom=True)
            return
        if index not in range(4):
            return
        settings=self.effective().settings
        self.checkpoint()
        target=self.project.settings if self.active=='Base' else self.project.scenarios[self.active].setdefault('settings',{})
        if settings.get('duration_preset')=='custom' or settings['stop']!='time' or settings['duration'] not in (3600,600,1800,7200):
            target.update(custom_duration=settings['duration'],custom_stop=settings['stop'],custom_limit=settings['limit'])
        target.update(duration=[3600,600,1800,7200][index],stop='time',duration_preset='preset')
        self.refresh()

    def set_rules(self,rules):
        self.checkpoint()
        if self.active=='Base':
            self.project.rules=rules
        else:
            self.project.scenarios[self.active]['rules']=rules
        self.refresh()

    def add_rule(self):
        if not self.can_edit():
            return
        values=edit_values(self,'New event rule',dict(id=uid(),name='Release next group',enabled=True,
            event='sensor_crossed',source='',condition='always',condition_target='',wait_for_condition=True,
            action='admit',target='',delay=0.),self.effective(),
            note='WHEN the selected event occurs, IF the condition holds, THEN perform the action. Empty source matches any source. Remembering an event keeps one pending activation and fires it when the condition later becomes true.')
        if values:
            self.set_rules(self.effective().rules+[values])

    def edit_rule(self):
        if not self.can_edit():
            return
        row=self.rule_list.currentRow()
        rules=self.effective().rules
        if 0<=row<len(rules):
            rules[row].setdefault('wait_for_condition',False)
            values=edit_values(self,'Edit event rule',rules[row],self.effective())
            if values:
                rules[row]=values
                self.set_rules(rules)

    def delete_rule(self):
        if not self.can_edit():
            return
        row=self.rule_list.currentRow()
        rules=self.effective().rules
        if 0<=row<len(rules) and QMessageBox.question(self,'Delete rule','Delete the selected rule?')==QMessageBox.Yes:
            rules.pop(row)
            self.set_rules(rules)

    def switch_scenario(self,name):
        if not name or name==self.active:
            return
        if self.engine or self.worker:
            self.scenario_combo.blockSignals(True)
            self.scenario_combo.setCurrentText(self.active)
            self.scenario_combo.blockSignals(False)
            self.notice('Reset or finish the current run before switching scenarios.')
            return
        self.active=name
        self.refresh()

    def duplicate_scenario(self):
        if not self.can_edit():
            return
        name,ok=QInputDialog.getText(self,'Duplicate scenario','New scenario name')
        if ok and name.strip():
            name=name.strip()
            if name=='Base' or name in self.project.scenarios:
                return self.error('Choose a unique scenario name.')
            self.checkpoint()
            self.project.scenarios[name]=deepcopy(self.project.scenarios.get(self.active,{}))
            self.active=name
            self.refresh()

    def rename_scenario(self):
        if not self.can_edit() or self.active=='Base':
            return
        name,ok=QInputDialog.getText(self,'Rename scenario','New name',text=self.active)
        if ok and name.strip() and name not in ['Base']+list(self.project.scenarios):
            self.checkpoint()
            self.project.scenarios[name]=self.project.scenarios.pop(self.active)
            self.active=name
            self.refresh()

    def delete_scenario(self):
        if not self.can_edit() or self.active=='Base':
            return
        if QMessageBox.question(self,'Delete scenario',f'Delete {self.active}?')==QMessageBox.Yes:
            self.checkpoint()
            del self.project.scenarios[self.active]
            self.active='Base'
            self.refresh()

    def preflight(self,show=False):
        try:
            errors,warnings=validate(self.effective())
        except Exception as exc:
            self.error(f'Invalid project data: {exc}')
            return False
        if errors:
            self.error('Fix these errors before running:\n\n'+'\n'.join(errors))
            return False
        if show:
            self.notice('No blocking errors.\n\n'+'\n'.join(warnings))
        return True

    def init_engine(self):
        if self.worker:
            return False
        if self.engine:
            if self.engine.stopped:
                self.notice('Use Reset / Edit to start a new run.')
                return False
            return True
        if not self.preflight():
            return False
        self.engine=Engine(self.effective())
        self.view.engine=self.engine
        self.view.set_tool('select')
        self.refresh()
        return True

    def run_visual(self):
        if self.init_engine():
            self.last_tick=time.monotonic()
            self.timer.start()
            self.tabs.setCurrentIndex(0)

    def pause(self):
        self.timer.stop()

    def tick(self):
        if not self.engine:
            return
        elapsed=min(.25,time.monotonic()-self.last_tick)
        self.last_tick=time.monotonic()
        target=self.engine.now+elapsed*int(self.speed.currentText()[:-1])
        settings=self.engine.project.settings
        if settings['stop']=='time':
            target=min(target,settings['duration'])
        try:
            self.engine.advance(target,10000)
            self.render_status()
            if self.engine.stopped or (settings['stop']=='time' and self.engine.now>=settings['duration']):
                self.stop()
            elif not self.engine.queue and settings['stop']!='time':
                self.pause()
                self.statusBar().showMessage('No pending events. Release manually, inspect rules, or Stop to collect results.')
        except Exception as exc:
            self.pause()
            self.error(exc)

    def step(self):
        self.pause()
        if self.init_engine():
            try:
                self.engine.step()
                self.render_status()
                if self.engine.stopped:
                    self.stop()
            except Exception as exc:
                self.error(exc)

    def manual_release(self):
        if self.init_engine():
            if self.engine.now==0 and self.engine.queue and self.engine.queue[0][2]=='start':
                self.engine.step()
            self.engine.release()
            self.render_status()

    def render_status(self):
        e=self.engine
        self.view.animate(e)
        active=[g for g in e.groups.values() if g.completed is None]
        done=[g for g in e.groups.values() if g.completed is not None]
        recent=[g for g in done if g.completed>=e.now-300]
        failures=len(e.failures)+sum(g.state=='blocked' for g in active)
        self.status_label.setText(f'{e.now/60:.2f} min | Inside {len(active)} groups / {sum(g.guests for g in active)} guests | '
            f'Done {len(done)} / {sum(g.guests for g in done)} | Last 5m: {len(recent)} groups | Failures {failures}')
        if self.log_dock.isVisible() and (not hasattr(self,'last_log') or time.monotonic()-self.last_log>.5):
            self.refresh_log()
            self.last_log=time.monotonic()

    def stop(self):
        self.pause()
        if self.engine:
            self.engine.stopped=True
            self.engine.reason=self.engine.reason or 'Stopped at visual run boundary'
            if not getattr(self.engine,'result_collected',False):
                self.accept_result(summarize(self.engine,self.active))
                self.engine.result_collected=True

    def reset(self):
        if self.worker:
            self.cancel_job()
            return
        self.pause()
        self.engine=None
        self.view.engine=None
        self.view.hot=set()
        self.refresh()
        self.status_label.setText('Ready to edit')

    def refresh_log(self):
        if not self.engine:
            return
        scrollbar=self.log_text.verticalScrollBar()
        previous=scrollbar.value()
        query=self.log_filter.currentText().lower()
        rows=[]
        rule_names={r['id']:r['name'] for r in self.engine.project.rules}
        for row in self.engine.log:
            source=self.engine.objects.get(row['source'],{}).get('name',rule_names.get(row['source'],row['source']))
            text=f"{row['time']:010.3f}  {row['event']}  group:{row['group']}  {source}  {row['detail']}"
            if not query or query in text.lower():
                rows.append(text)
        self.log_text.setPlainText('\n'.join(rows[-1000:]))
        if self.log_autoscroll.isChecked():
            self.scroll_log_to_bottom()
        else:
            scrollbar.setValue(min(previous,scrollbar.maximum()))

    def focus_log_search(self):
        self.log_dock.show()
        self.log_dock.raise_()
        editor=self.log_filter.lineEdit()
        editor.setFocus(Qt.ShortcutFocusReason)
        editor.selectAll()

    def scroll_log_to_bottom(self):
        scrollbar=self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_job(self,function,callback):
        if self.worker:
            return
        self.pause()
        self.worker=Worker(function,self)
        self.worker.result.connect(callback)
        self.worker.failed.connect(self.error)
        self.worker.progress.connect(lambda n,t:(self.progress.setMaximum(t),self.progress.setValue(n)))
        self.worker.finished.connect(self.job_finished)
        self.progress.setRange(0,0)
        self.progress.show()
        self.cancel_button.show()
        self.refresh()
        self.worker.start()

    def job_finished(self):
        worker=self.worker
        self.worker=None
        worker.deleteLater()
        self.progress.hide()
        self.cancel_button.hide()
        self.refresh()

    def cancel_job(self):
        if self.worker:
            self.worker.requestInterruption()

    def fast(self):
        if self.worker or not self.preflight():
            return
        p=self.effective()
        if p.settings['stop']=='manual':
            self.notice('Fast analysis uses the configured duration for manual-stop projects.')
            p.settings['stop']='time'
        scenario=self.active
        self.start_job(lambda cancel,progress:summarize(Engine(p).run(cancel),scenario),self.accept_result)

    def accept_result(self,result):
        self.last_result=result
        self.project.results.append(compact(result))
        self.project.results=self.project.results[-20:]
        self.dirty=True
        self.reports.show_result(result)
        self.tabs.setCurrentIndex(1)
        self.update_title()

    def analysis_project(self):
        p=self.effective()
        p.settings['stop']='time'
        return p

    def repeat(self):
        if self.worker or not self.preflight():
            return
        count,ok=QInputDialog.getInt(self,'Repeated simulations','Runs (consecutive reproducible seeds)',100,1,100000)
        if ok:
            p=self.analysis_project()
            self.start_job(lambda c,progress:repeated(p,count,c,progress),self.repeated_result)

    def repeated_result(self,result):
        self.reports.show_repeated(result)
        self.tabs.setCurrentIndex(1)

    def advisor(self):
        if self.worker or not self.preflight():
            return
        p=self.analysis_project()
        self.advice_source=(self.active,self.effective().data())
        self.start_job(lambda c,progress:advise(p,c,progress),self.advice_result)

    def advice_result(self,result):
        self.advice=result
        source=self.advice_source
        objects=self.effective().by_id()
        rows=[[objects[oid]['name'],objects[oid]['duration']['typical'],v['duration']['typical']]
              for oid,v in result['overrides'].items()]
        page=QWidget()
        layout=QVBoxLayout(page)
        explanation=QLabel(result['explanation'])
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(table(['Room','Current typical s','Suggested typical s'],rows))
        if result['baseline']:
            keys=['guests_per_hour','groups_per_hour','interior_failures','overstay_seconds','traversal_average']
            layout.addWidget(table(['Metric','Current','Suggested'],[[k,result['baseline'][k],result['suggested'][k]] for k in keys]))
        button=QPushButton('Save recommendation as a new scenario')
        button.clicked.connect(lambda checked=False,r=result,s=source:self.apply_advice(r,s))
        layout.addWidget(button)
        self.reports.addTab(page,'Timing advisor')
        self.reports.setCurrentWidget(page)
        self.tabs.setCurrentIndex(1)

    def apply_advice(self,advice=None,source=None):
        if not self.can_edit():
            return
        advice=advice or self.advice
        source=source or self.advice_source
        current=self.effective().data()
        expected=deepcopy(source[1])
        # Stored reports do not affect recommendations; configuration edits do.
        for data in (current,expected):
            data['results']=[]
        if source[0]!=self.active or current!=expected:
            return self.notice('The project or scenario changed after this advice was calculated. Run the timing advisor again before applying it.')
        name='Advisor '+str(len(self.project.scenarios)+1)
        while name in self.project.scenarios:
            name+=' copy'
        self.checkpoint()
        scenario=deepcopy(self.project.scenarios.get(self.active,{}))
        overrides=scenario.setdefault('objects',{})
        for oid,values in advice['overrides'].items():
            overrides.setdefault(oid,{}).update(values)
        self.project.scenarios[name]=scenario
        self.active=name
        self.refresh()

    def compare(self):
        if self.worker:
            return
        project=deepcopy(self.project)
        names=['Base']+list(project.scenarios)
        for name in names:
            errors,_=validate(project.scenario(name))
            if errors:
                return self.error(name+':\n'+'\n'.join(errors))
        def work(cancel,progress):
            results=[]
            for i,name in enumerate(names):
                if cancel():
                    break
                p=project.scenario(name)
                p.settings['stop']='time'
                results.append(summarize(Engine(p,seed=project.settings['seed']).run(cancel),name))
                progress(i+1,len(names))
            return results
        self.start_job(work,lambda results:(self.reports.show_comparison(results),self.tabs.setCurrentIndex(1)))

    def overlay(self):
        if not self.last_result:
            return self.notice('Run a simulation first.')
        r=self.last_result
        self.view.hot={rid for rid,v in r['rooms'].items() if v['overstays'] or v['utilization']>.85 or v['caused_failures']}
        self.view.hot.update(v['location'] for v in r['failures'])
        self.view.hot.update(v['cause'] for v in r['failures'])
        self.view.hot.update(v['location'] for v in r.get('spacing',[]))
        self.view.scene().update()
        self.tabs.setCurrentIndex(0)
        self.statusBar().showMessage('Red: high utilization, overstays, blockages or spacing conflict. Select objects for run metrics.')

    def export(self):
        if not self.last_result:
            return self.notice('Run a simulation first.')
        filename,_=QFileDialog.getSaveFileName(self,'Export analytics','','CSV (*.csv)')
        if filename:
            try:
                export_csv(self.last_result,filename)
            except Exception as exc:
                self.error(exc)

    def export_json(self):
        if not self.last_result:
            return self.notice('Run a simulation first.')
        filename,_=QFileDialog.getSaveFileName(self,'Export reproducible full results','','JSON (*.json)')
        if filename:
            try:
                Path(filename).write_text(json.dumps(self.last_result,indent=2),encoding='utf-8')
            except Exception as exc:
                self.error(exc)

    def history(self):
        self.reports.show_comparison(self.project.results)
        self.tabs.setCurrentIndex(1)

    def confirm_unsaved(self):
        if self.worker:
            self.notice('Cancel the analysis and wait for it to finish before closing or opening another project.')
            return False
        if not self.dirty:
            return True
        answer=QMessageBox.question(self,'Unsaved changes','Save changes to this project?',
            QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
        if answer==QMessageBox.Save:
            return self.save()
        return answer==QMessageBox.Discard

    def set_project(self,project,filename=''):
        self.cloud.active=None
        self.reset()
        self.project=project
        self.filename=filename
        self.active='Base'
        self.dirty=False
        self.undo_history=[]
        self.redo_history=[]
        self.last_result=None
        self.reports.clear()
        self.reports.addTab(QLabel('Run a simulation to inspect this project.'),'Results')
        self.tabs.setCurrentIndex(0)
        self.refresh()
        self.view.fit()

    def new(self):
        if self.confirm_unsaved():
            self.set_project(Project())

    def open_example(self):
        if self.confirm_unsaved():
            self.set_project(example())
            self.dirty=True
            self.refresh()

    def open(self,filename=None):
        if not self.confirm_unsaved():
            return
        if not filename:
            filename,_=QFileDialog.getOpenFileName(self,'Open project','','HauntSim (*.hauntsim)')
        if filename:
            try:
                project=load(filename)
                # Structural validation before replacing the current document.
                validate(project)
                self.set_project(project,filename)
                self.add_recent(filename)
            except Exception as exc:
                self.error(f'Could not open project:\n{exc}')

    def save(self,save_as=False):
        self.property_edit_key=None
        return self.cloud.save(copy=save_as)

    def add_recent(self,filename):
        paths=self.settings.value('recent',[],type=list)
        paths=[filename]+[p for p in paths if p!=filename]
        self.settings.setValue('recent',paths[:10])
        self.refresh_recent()

    def refresh_recent(self):
        self.recent_menu.clear()
        for filename in self.settings.value('recent',[],type=list):
            self.action(self.recent_menu,filename,lambda f=filename:self.open(f))

    def guide(self):
        text=QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText((Path(__file__).parents[1]/'README.md').read_text(encoding='utf-8'))
        self.reports.addTab(text,'User guide')
        self.reports.setCurrentWidget(text)
        self.tabs.setCurrentIndex(1)

    def closeEvent(self,event):
        if self.confirm_unsaved():
            self.timer.stop()
            self.cloud.stop()
            self.settings.setValue('geometry',self.saveGeometry())
            event.accept()
        else:
            event.ignore()


def main():
    app=QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet('QToolBar { spacing: 5px; padding: 5px; } QPushButton { padding: 5px 9px; } '
                      'QDockWidget { font-weight: 600; } QTableWidget { gridline-color: #d5dce2; }')
    window=MainWindow()
    window.show()
    if len(sys.argv)>1:
        window.open(sys.argv[1])
    sys.exit(app.exec())
