"""Qt scene editor, route handles, calibrated background, and simulation rendering."""
from copy import deepcopy
import math
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QPainterPath, QPainterPathStroker, QPixmap, QPolygonF
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsEllipseItem, QMenu, QInputDialog)
from .model import new_object, interpolate, nearest_fraction

COLORS = dict(room='#356d83', path='#49bfa9', door='#eeb65d', sensor='#cf84e9',
              entrance='#6ddc91', exit='#ed9999')


class ObjectItem(QGraphicsItem):
    def __init__(self, obj, view):
        super().__init__()
        self.obj, self.view = obj, view
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"{obj['name']} · {obj['kind']}\n{obj['id']}")
        # Keep routes and small controls selectable over filled room backgrounds.
        self.setZValue({'room':0, 'path':1, 'door':2}.get(obj['kind'],3))
        if obj['kind']!='path':
            self.setPos(obj['x'],obj['y'])

    def boundingRect(self):
        o = self.obj
        if o['kind']=='path':
            xs, ys = [p[0] for p in o['points']], [p[1] for p in o['points']]
            return QRectF(min(xs)-14,min(ys)-20,max(xs)-min(xs)+28,max(ys)-min(ys)+40)
        if o['kind']=='room':
            return QRectF(-o['width']/2-3,-o['height']/2-3,o['width']+6,o['height']+6)
        size = max(45.,o.get('width',0)+math.hypot(o.get('slide_x',0),o.get('slide_y',0))+8)
        return QRectF(-size,-size,2*size,2*size)

    def shape(self):
        """Hit-test visible geometry, not the broad rectangle used for repainting."""
        o = self.obj
        shape = QPainterPath()
        if o['kind']=='room':
            shape.addRoundedRect(QRectF(-o['width']/2,-o['height']/2,o['width'],o['height']),8,8)
            return shape
        if o['kind']=='path':
            shape.moveTo(QPointF(*o['points'][0]))
            for point in o['points'][1:]:
                shape.lineTo(QPointF(*point))
        elif o['kind']=='door':
            fraction = self.view.engine.door_fraction(o['id']) if self.view.engine and o['id'] in self.view.engine.doors else 0
            angle = math.radians(o['angle'] + (o['open_angle']*fraction if o['style']!='slide' else 0))
            origin = QPointF(o['slide_x']*fraction,o['slide_y']*fraction) if o['style']=='slide' else QPointF()
            shape.moveTo(origin)
            shape.lineTo(origin+QPointF(o['width']*math.cos(angle),o['width']*math.sin(angle)))
        else:
            shape.addEllipse(QPointF(),14,14)
            return shape
        # A small tolerance makes narrow route/door lines comfortable to click.
        stroke = QPainterPathStroker()
        stroke.setWidth(10)
        stroke.setCapStyle(Qt.RoundCap)
        stroke.setJoinStyle(Qt.RoundJoin)
        hit = stroke.createStroke(shape)
        if o['kind']=='door':
            hinge = QPainterPath()
            hinge.addEllipse(QPointF(),6,6)
            hit = hit.united(hinge)
        return hit

    def paint(self, painter, option, widget=None):
        o, k = self.obj, self.obj['kind']
        color = QColor('#ff6464' if o['id'] in self.view.hot else COLORS[k])
        if not o['enabled']:
            color.setAlpha(70)
        painter.setPen(QPen(QColor('#ffffff') if self.isSelected() else color, 2.5))
        fill = QColor(color)
        fill.setAlpha(65)
        painter.setBrush(fill)
        if k=='room':
            rect = QRectF(-o['width']/2,-o['height']/2,o['width'],o['height'])
            painter.drawRoundedRect(rect,8,8)
            painter.setPen(QColor('#eef5fa'))
            painter.drawText(rect,Qt.AlignCenter,o['name'])
        elif k=='path':
            points = [QPointF(*p) for p in o['points']]
            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            # An open route must not inherit the translucent room/marker fill.
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            for a,b in zip(points,points[1:]):
                middle = (a+b)/2
                angle = math.atan2(b.y()-a.y(),b.x()-a.x())
                arrow = [middle, middle-QPointF(11*math.cos(angle-.5),11*math.sin(angle-.5)),
                         middle-QPointF(11*math.cos(angle+.5),11*math.sin(angle+.5))]
                painter.setBrush(color)
                painter.drawPolygon(QPolygonF(arrow))
        elif k=='door':
            fraction = self.view.engine.door_fraction(o['id']) if self.view.engine and o['id'] in self.view.engine.doors else 0
            painter.save()
            if o['style']=='slide':
                painter.translate(o['slide_x']*fraction,o['slide_y']*fraction)
                painter.rotate(o['angle'])
            else:
                painter.rotate(o['angle']+o['open_angle']*fraction)
            painter.setPen(QPen(color,5))
            painter.drawLine(QPointF(0,0),QPointF(o['width'],0))
            painter.restore()
            if self.isSelected() and not self.view.engine and o['style']=='swing':
                # Show the configured open position while keeping the hinge fixed.
                painter.save()
                painter.setPen(QPen(color,2,Qt.DashLine))
                painter.rotate(o['angle'])
                radius=o['width']
                painter.drawArc(QRectF(-radius,-radius,2*radius,2*radius),
                                0,round(-o['open_angle']*16))
                painter.rotate(o['open_angle'])
                painter.drawLine(QPointF(0,0),QPointF(radius,0))
                painter.restore()
            painter.drawEllipse(QPointF(0,0),4,4)
            painter.drawText(QPointF(-25,-18),o['name'])
        else:
            painter.drawEllipse(QPointF(0,0),12,12)
            painter.drawText(QPointF(-35,-20),o['name'])

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if not self.view.editable:
            return
        changes = []
        for item in self.scene().selectedItems():
            if not isinstance(item,ObjectItem):
                continue
            obj = deepcopy(item.obj)
            x,y = item.pos().x(),item.pos().y()
            if self.view.snap:
                x,y = round(x/10)*10,round(y/10)*10
            if obj['kind']=='path':
                if abs(x)+abs(y)<.01:
                    continue
                obj['points'] = [[px+x,py+y] for px,py in obj['points']]
            else:
                if (x,y)==(obj['x'],obj['y']):
                    continue
                obj.update(x=x,y=y)
            changes.append(obj)
        if changes:
            self.view.changed.emit(changes)


class Handle(QGraphicsEllipseItem):
    def __init__(self, view, owner, index, point):
        super().__init__(-5,-5,10,10)
        self.view, self.owner, self.index = view,owner,index
        self.obj = deepcopy(owner.obj)
        self.drag_offset = QPointF()
        self.setPos(*point)
        self.setBrush(QColor('#ffffff'))
        self.setPen(QPen(QColor('#37bca5'),2))
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setZValue(5)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip('Drag to move this vertex. Right-click to delete it.' if self.obj['kind']=='path'
                        else 'Drag to adjust this handle.')

    def mousePressEvent(self,event):
        # Qt's default movable-item handler also moves selected scene items.
        # Own this gesture so only the handle's geometry changes during a drag.
        self.drag_offset = self.pos()-event.scenePos()
        event.accept()

    def preview(self,point):
        obj = deepcopy(self.obj)
        x,y = point.x(),point.y()
        if self.view.snap:
            x,y = round(x/10)*10,round(y/10)*10
        if obj['kind']=='path':
            obj['points'][self.index] = [x,y]
        elif obj['kind']=='room':
            obj['width'],obj['height'] = max(20,2*abs(x-obj['x'])), max(20,2*abs(y-obj['y']))
        else:
            obj['open_angle'] = math.degrees(math.atan2(y-obj['y'],x-obj['x']))-obj['angle']
        self.setPos(x,y)
        self.owner.prepareGeometryChange()
        self.owner.obj = obj
        self.owner.update()

    def mouseMoveEvent(self,event):
        self.preview(event.scenePos()+self.drag_offset)
        event.accept()

    def mouseReleaseEvent(self,event):
        self.preview(event.scenePos()+self.drag_offset)
        event.accept()
        # Persist once on release, preserving a single undo step for the gesture.
        if self.owner.obj != self.obj:
            self.view.changed.emit([deepcopy(self.owner.obj)])

    def contextMenuEvent(self,event):
        if self.obj['kind']!='path':
            return super().contextMenuEvent(event)
        menu=QMenu()
        remove=menu.addAction('Delete path vertex')
        remove.setEnabled(len(self.obj['points'])>2)
        chosen=menu.exec(event.screenPos())
        if chosen==remove:
            self.delete_vertex()
        event.accept()

    def delete_vertex(self):
        if self.obj['kind']!='path' or len(self.obj['points'])<=2:
            return False
        obj=deepcopy(self.obj)
        del obj['points'][self.index]
        self.view.changed.emit([obj])
        return True


class LayoutView(QGraphicsView):
    changed = Signal(list)
    created = Signal(dict)
    selected = Signal(str)
    calibration = Signal(float,str)
    delete_requested = Signal()
    copy_requested = Signal()
    paste_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QColor('#16222c'))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.tool = 'select'
        self.points, self.handles, self.markers = [], [], []
        self.project = None
        self.engine = None
        self.editable, self.snap = True, False
        self.hot = set()
        self.hidden = set()
        self.scene().selectionChanged.connect(self.selection)

    def rebuild(self, project):
        selected = self.selected_ids()
        self.scene().blockSignals(True)
        self.scene().clear()
        self.handles, self.markers = [], []
        self.project = project
        if project.background and 'background' not in self.hidden:
            pixmap = QPixmap()
            pixmap.loadFromData(project.background)
            item = self.scene().addPixmap(pixmap)
            item.setZValue(-10)
        for obj in project.objects:
            if obj['kind'] in self.hidden:
                continue
            item = ObjectItem(obj,self)
            self.scene().addItem(item)
            item.setFlag(QGraphicsItem.ItemIsMovable,self.editable)
            item.setSelected(obj['id'] in selected)
        rect = self.scene().itemsBoundingRect()
        self.setSceneRect(rect.adjusted(-150,-150,150,150) if not rect.isEmpty() else QRectF(0,0,1200,700))
        self.scene().blockSignals(False)
        self.selection()

    def selected_ids(self):
        return [i.obj['id'] for i in self.scene().selectedItems() if isinstance(i,ObjectItem)]

    def selection(self):
        for handle in self.handles:
            self.scene().removeItem(handle)
        self.handles = []
        selected = [i for i in self.scene().selectedItems() if isinstance(i,ObjectItem)]
        if len(selected)==1:
            obj = selected[0].obj
            self.selected.emit(obj['id'])
            if self.editable:
                points = obj.get('points',[])
                if obj['kind']=='door':
                    angle = math.radians(obj['angle']+obj['open_angle'])
                    points = [[obj['x']+obj['width']*math.cos(angle),obj['y']+obj['width']*math.sin(angle)]]
                elif obj['kind']=='room':
                    points = [[obj['x']+obj['width']/2,obj['y']+obj['height']/2]]
                for index,point in enumerate(points):
                    handle = Handle(self,selected[0],index,point)
                    self.scene().addItem(handle)
                    self.handles.append(handle)
        elif not selected:
            self.selected.emit('')

    def set_tool(self,tool):
        self.tool, self.points = tool, []
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool=='pan' else QGraphicsView.RubberBandDrag if tool=='select' else QGraphicsView.NoDrag)
        self.setCursor(Qt.ArrowCursor if tool=='select' else Qt.OpenHandCursor if tool=='pan' else Qt.CrossCursor)
        self.viewport().update()

    def wheelEvent(self,event):
        factor = 1.15 if event.angleDelta().y()>0 else 1/1.15
        if .05 < self.transform().m11()*factor < 20:
            self.scale(factor,factor)

    def mousePressEvent(self,event):
        if not self.editable or self.tool in ('select','pan') or event.button()!=Qt.LeftButton:
            return super().mousePressEvent(event)
        point = self.mapToScene(event.position().toPoint())
        xy = [point.x(),point.y()]
        if self.snap:
            xy = [round(v/10)*10 for v in xy]
        if self.tool in ('path','room','calibrate'):
            self.points.append(xy)
            if self.tool=='room' and len(self.points)==2:
                a,b = self.points
                obj = new_object('room',(a[0]+b[0])/2,(a[1]+b[1])/2)
                obj.update(width=max(20,abs(b[0]-a[0])),height=max(20,abs(b[1]-a[1])))
                self.points = []
                self.created.emit(obj)
            elif self.tool=='calibrate' and len(self.points)==2:
                distance = math.dist(*self.points)
                real,ok = QInputDialog.getDouble(self,'Calibrate scale',f'Known length ({self.project.settings["units"]})',8,.001,1e6,3)
                if ok and distance>0:
                    self.calibration.emit(distance/real,self.project.settings['units'])
                self.points=[]
            self.viewport().update()
        else:
            obj = new_object(self.tool,*xy)
            if self.tool in ('sensor','door'):
                best=self.nearest_path(xy)
                if best[1]:
                    obj['path']=best[1]['id']
                    if self.tool=='sensor':
                        obj['fraction']=best[2]
                        obj['x'],obj['y']=interpolate(best[1]['points'],best[2])
            self.created.emit(obj)

    def nearest_path(self,point):
        best=(float('inf'),None,0.)
        for path in self.project.objects:
            if path['kind']!='path' or not path['enabled']:
                continue
            fraction=nearest_fraction(path['points'],point)
            distance=math.dist(point,interpolate(path['points'],fraction))
            if distance<best[0]:
                best=(distance,path,fraction)
        return best

    def finish_path(self):
        if len(self.points)<2:
            return
        points=[]
        for p in self.points:
            if not points or math.dist(points[-1],p)>.1:
                points.append(p)
        if len(points)<2:
            return
        obj = new_object('path',points=points)
        nodes=[o for o in self.project.objects if o['kind'] in ('room','entrance','exit')]
        for key,point in [('source',points[0]),('target',points[-1])]:
            if nodes:
                node=min(nodes,key=lambda o:math.dist(point,[o['x'],o['y']]))
                if math.dist(point,[node['x'],node['y']]) < max(70,node.get('width',0)/2):
                    obj[key]=node['id']
        self.points=[]
        self.created.emit(obj)
        self.viewport().update()

    def mouseDoubleClickEvent(self,event):
        if self.tool=='path' and self.editable:
            self.finish_path()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter) and self.tool=='path':
            self.finish_path()
        elif event.key()==Qt.Key_Escape:
            self.set_tool('select')
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self,event):
        menu=QMenu(self)
        if self.editable:
            menu.addAction('Copy selected',self.copy_requested.emit)
            menu.addAction('Paste',self.paste_requested.emit)
            menu.addAction('Delete selected',self.delete_requested.emit)
            if self.tool=='path':
                menu.addAction('Finish path',self.finish_path)
        menu.addAction('Fit layout',self.fit)
        menu.exec(event.globalPos())

    def fit(self):
        self.fitInView(self.scene().itemsBoundingRect().adjusted(-30,-30,30,30),Qt.KeepAspectRatio)

    def drawForeground(self,painter,rect):
        if self.points:
            painter.setPen(QPen(QColor('#ffffff'),2,Qt.DashLine))
            painter.drawPolyline(QPolygonF([QPointF(*p) for p in self.points]))
            for p in self.points:
                painter.drawEllipse(QPointF(*p),4,4)

    def animate(self,engine):
        self.engine=engine
        for item in self.markers:
            self.scene().removeItem(item)
        self.markers=[]
        colors={'walking':'#6de9bd','scene':'#78bcff','blocked':'#ff5353','overstay':'#ff9b4f'}
        for g in engine.groups.values():
            if g.completed is not None:
                continue
            x,y=engine.position(g)
            marker=self.scene().addEllipse(-9,-9,18,18,QPen(QColor('#ffffff')),QBrush(QColor(colors[g.state])))
            marker.setPos(x,y)
            marker.setZValue(10)
            marker.setToolTip(f'Group {g.id} · {g.guests} guests\n{g.state} · {engine.objects[g.location]["name"]}\n'
                              f'{engine.now-g.admitted:.1f}s inside · speed {g.speed:.2f}\n'
                              f'Blocked {g.blocked+(engine.now-g.blocked_since if g.blocked_since is not None else 0):.1f}s\n{g.cause}')
            label=self.scene().addSimpleText(str(g.id))
            label.setBrush(QColor('#ffffff'))
            label.setPos(x+10,y-12)
            label.setZValue(11)
            self.markers.extend([marker,label])
        self.scene().update()
