"""Small typed forms; users never need to edit Python or JSON."""
from copy import deepcopy
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QFormLayout, QLineEdit, QDoubleSpinBox,
    QSpinBox, QCheckBox, QComboBox, QHBoxLayout, QDialog, QVBoxLayout,
    QDialogButtonBox, QLabel, QScrollArea)
from .model import EVENTS, ACTIONS, CONDITIONS

LABELS = {'seconds':'Travel override (s; 0 = use scale)', 'fraction':'Position along path (0–1)',
    'spacing':'Minimum group spacing (layout pixels)', 'pixels_per_unit':'Pixels per real-world unit',
    'exterior_groups':'Exterior groups (0 = unlimited)', 'initial_release':'Release first group at start',
    'duration':'Scene duration (s): min / typical / max', 'acceptable_min':'Minimum acceptable scene (s)',
    'acceptable_max':'Maximum acceptable scene (s)', 'preferred':'Preferred scene duration (s)',
    'weight':'Branch selection weight', 'angle':'Closed angle (degrees)', 'open_angle':'Open angle (relative degrees)',
    'opening':'Opening duration (s)', 'closing':'Closing duration (s)', 'hold':'Hold-open duration (s)',
    'cooldown':'Debounce / cooldown (s)', 'delay':'Action delay (s)', 'random_seed':'Choose a random seed',
    'limit':'Completed group / guest target', 'stop':'Stop condition', 'capacity':'Capacity (groups)',
    'speed':'Walking speed (units/s): min / typical / max', 'group_size':'Group size: min / typical / max',
    'wait_for_condition':'Remember the event until its condition becomes true'}
LABELS['automatic']='Automatically open when a group reaches the door'
INTS = {'seed','exterior_groups','limit','capacity'}
ENUMS = {'style':['swing','slide','passage'], 'units':['feet','meters'],
         'stop':['time','groups','guests','manual'], 'event':EVENTS, 'action':ACTIONS,
         'condition':CONDITIONS}


class Form(QWidget):
    edited = Signal(str)
    editing_finished = Signal()

    def __init__(self, values, project=None, omit=(), parent=None):
        super().__init__(parent)
        self.original = deepcopy(values)
        self.widgets = {}
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.setRowWrapPolicy(QFormLayout.WrapAllRows)
        for key, value in values.items():
            if key in omit or key in ('points','kind'):
                continue
            label = LABELS.get(key,key.replace('_',' ').title())
            if key=='duration' and isinstance(value,(int,float)):
                label = 'Run duration (seconds)'
            if isinstance(value,dict) and set(value)=={'min','typical','max'}:
                widget = QWidget()
                row = QHBoxLayout(widget)
                row.setContentsMargins(0,0,0,0)
                controls = []
                for part in ('min','typical','max'):
                    spin = QDoubleSpinBox()
                    spin.setRange(0,1e6)
                    spin.setDecimals(3)
                    spin.setValue(value[part])
                    spin.setToolTip(part.title())
                    row.addWidget(spin)
                    controls.append(spin)
                self.widgets[key] = ('range',controls)
            elif isinstance(value,bool):
                widget = QCheckBox()
                widget.setChecked(value)
                self.widgets[key] = ('bool',widget)
            elif key in ENUMS:
                widget = QComboBox()
                widget.addItems(ENUMS[key])
                widget.setCurrentText(str(value))
                self.widgets[key] = ('enum',widget)
            elif project and key in ('source','target','door','path','condition_target'):
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItem('Any / none','')
                for obj in project.objects + project.rules:
                    if key in ('door','path') and obj.get('kind') != key:
                        continue
                    widget.addItem(f"{obj['name']} [{obj['id']}]",obj['id'])
                index = widget.findData(value)
                if index>=0:
                    widget.setCurrentIndex(index)
                else:
                    widget.setEditText(str(value))
                widget.setToolTip('Select an object; custom signals may use a typed text identifier.')
                self.widgets[key] = ('ref',widget)
            elif isinstance(value,(float,int)):
                widget = QSpinBox() if key in INTS else QDoubleSpinBox()
                widget.setRange(-1e6 if key in ('x','y','angle','open_angle','slide_x','slide_y') else 0, 2_000_000_000 if key=='seed' else 1_000_000)
                if isinstance(widget,QDoubleSpinBox):
                    widget.setDecimals(3)
                widget.setValue(value)
                self.widgets[key] = ('number',widget)
            else:
                widget = QLineEdit(str(value))
                widget.setReadOnly(key=='id')
                self.widgets[key] = ('text',widget)
            layout.addRow(label,widget)
        for key,(kind,control) in self.widgets.items():
            if key=='id':
                continue
            controls=control if kind=='range' else [control]
            for widget in controls:
                if kind in ('number','range'):
                    widget.valueChanged.connect(lambda value,k=key:self.edited.emit(k))
                    widget.editingFinished.connect(self.editing_finished.emit)
                elif kind=='text':
                    widget.textEdited.connect(lambda value,k=key:self.edited.emit(k))
                    widget.editingFinished.connect(self.editing_finished.emit)
                elif kind=='bool':
                    widget.toggled.connect(lambda value,k=key:self.edited.emit(k))
                elif kind in ('enum','ref'):
                    widget.currentTextChanged.connect(lambda value,k=key:self.edited.emit(k))
                    if widget.isEditable():
                        widget.lineEdit().editingFinished.connect(self.editing_finished.emit)

    def sync(self,values,exclude=()):
        """Refresh derived fields without emitting edits or disturbing the active input."""
        self.original=deepcopy(values)
        for key,(kind,control) in self.widgets.items():
            if key in exclude:
                continue
            controls=control if kind=='range' else [control]
            values_to_set=[values[key][part] for part in ('min','typical','max')] if kind=='range' else [values[key]]
            for widget,value in zip(controls,values_to_set):
                with QSignalBlocker(widget):
                    if kind in ('number','range'):
                        widget.setValue(value)
                    elif kind=='bool':
                        widget.setChecked(value)
                    elif kind=='text':
                        widget.setText(str(value))
                    elif kind=='enum':
                        widget.setCurrentText(value)
                    else:
                        index=widget.findData(value)
                        if index>=0:
                            widget.setCurrentIndex(index)
                        else:
                            widget.setEditText(value)

    def values(self):
        values = deepcopy(self.original)
        for key,(kind,widget) in self.widgets.items():
            if kind=='range':
                value = dict(zip(('min','typical','max'),[w.value() for w in widget]))
            elif kind=='bool':
                value = widget.isChecked()
            elif kind=='number':
                value = widget.value()
            elif kind=='enum':
                value = widget.currentText()
            elif kind=='ref':
                value = widget.currentData() if widget.currentIndex()>=0 and widget.currentText()==widget.itemText(widget.currentIndex()) else widget.currentText()
            else:
                value = widget.text()
            values[key] = value
        return values


def edit_values(parent, title, values, project=None, omit=(), note=''):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(590, min(780,150+len(values)*38))
    layout = QVBoxLayout(dialog)
    if note:
        text = QLabel(note)
        text.setWordWrap(True)
        layout.addWidget(text)
    form = Form(values,project,omit)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(form)
    layout.addWidget(scroll)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return form.values() if dialog.exec()==QDialog.Accepted else None
