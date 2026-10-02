"""Analytics tables and lightweight Qt charts (no plotting dependency)."""
import json
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QComboBox,QTableWidget,QTableWidgetItem,
    QTabWidget,QPlainTextEdit,QSplitter,QLabel)


class Chart(QWidget):
    def __init__(self):
        super().__init__()
        self.points=[]
        self.caption=''
        self.setMinimumHeight(230)

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(),QColor('#17242e'))
        rect=QRectF(65,30,max(1,self.width()-90),max(1,self.height()-75))
        painter.setPen(QColor('#cedae4'))
        painter.drawText(12,20,self.caption)
        painter.drawLine(rect.bottomLeft(),rect.bottomRight())
        painter.drawLine(rect.bottomLeft(),rect.topLeft())
        if not self.points:
            return
        xmax=max(1,max(p[0] for p in self.points))
        ymax=max(1,max(p[1] for p in self.points))
        for i in range(5):
            y=rect.bottom()-rect.height()*i/4
            painter.drawText(5,int(y),f'{ymax*i/4:.1f}')
        painter.drawText(int(rect.right()-70),self.height()-12,f'{xmax:.0f}')
        painter.setPen(QPen(QColor('#5edbc0'),2))
        previous=None
        for x,y in self.points:
            point=QPointF(rect.left()+x/xmax*rect.width(),rect.bottom()-y/ymax*rect.height())
            if previous is not None:
                painter.drawLine(previous,QPointF(point.x(),previous.y()))
                painter.drawLine(QPointF(point.x(),previous.y()),point)
            else:
                painter.drawEllipse(point,2,2)
            previous=point


def table(headers,rows):
    widget=QTableWidget(len(rows),len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.NoEditTriggers)
    widget.setAlternatingRowColors(True)
    for row,values in enumerate(rows):
        for col,value in enumerate(values):
            widget.setItem(row,col,QTableWidgetItem(f'{value:.3f}' if isinstance(value,float) else str(value)))
    widget.resizeColumnsToContents()
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


class Reports(QTabWidget):
    def __init__(self):
        super().__init__()
        self.addTab(QLabel('Run a simulation to inspect throughput and flow failures.'),'Results')
        self.result=None

    def show_result(self,result):
        self.result=result
        self.clear()
        self.addTab(table(['Metric','Value'],[(k.replace('_',' ').title(),v) for k,v in result['metrics'].items()]),'Summary')
        self.addTab(table(['Room','Utilization','Visits','Intended s','Actual s','Overstays','Overstay s','Caused failures'],
            [[v[k] for k in ('name','utilization','visits','intended','actual','overstays','overstay_seconds','caused_failures')]
             for v in result['rooms'].values()]),'Rooms')
        self.addTab(table(['Type','Group','Location','Start','End','Seconds','Cause'],
            [[kind]+[v[k] for k in ('group','location','start','end','duration','cause')]
             for kind,key in [('Interior failure','failures'),('Room overstay','overstays')] for v in result.get(key,[])]),'Flow failures')
        text=QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText('\n\n'.join(result['explanations'])+'\n\n'+result.get('termination',''))
        self.addTab(text,'Diagnosis')
        chart_page=QWidget()
        layout=QVBoxLayout(chart_page)
        choice=QComboBox()
        names=['Groups inside','Guests inside','Completed groups','Completed guests','Groups / 5 minutes',
               'Guests / 5 minutes','Room utilization','Room overstay seconds','Blocked seconds by location',
               'Failures over time','Entrance latency']
        choice.addItems(names)
        chart=Chart()
        def change(index):
            if index<4:
                points=[(p[0],p[index+1]) for p in result.get('series',[])]
                suffix=' · time (s)'
            elif index<6:
                points=[(p['start'],p['groups' if index==4 else 'guests']) for p in result.get('windows',{}).get('5',[])]
                suffix=' · bucket start (s)'
            elif index<8:
                points=[(i+1,v['utilization' if index==6 else 'overstay_seconds']) for i,v in enumerate(result['rooms'].values())]
                suffix=' · room index (see Rooms tab)'
            elif index==8:
                totals={}
                for row in result.get('failures',[]):
                    totals[row['location']]=totals.get(row['location'],0)+row['duration']
                points=[(i+1,v) for i,v in enumerate(totals.values())]
                suffix=' · location index (see Flow failures)'
            elif index==9:
                points=[(v['start'],i+1) for i,v in enumerate(sorted(result.get('failures',[]),key=lambda v:v['start']))]
                suffix=' · time (s)'
            else:
                points=[(v['admission'],v['latency']) for v in result.get('latencies',[])]
                suffix=' · admission time (s)'
            chart.points=points
            chart.caption=names[index]+suffix
            chart.update()
        choice.currentIndexChanged.connect(change)
        layout.addWidget(choice)
        layout.addWidget(chart)
        change(0)
        self.addTab(chart_page,'Charts')
        self.addTab(table(['Minutes','Bucket start','Groups','Guests'],
            [[minutes,v['start'],v['groups'],v['guests']] for minutes,rows in result.get('windows',{}).items() for v in rows]),'Throughput intervals')
        self.addTab(table(['Entity','Metric','Value'],
            [[did,k,v] for did,values in result['doors'].items() for k,v in values.items()] +
            [[sid,'sensor triggers',count] for sid,count in result['sensors'].items()]),'Doors & sensors')
        self.addTab(table(['Group','Path','Walking seconds','Actual path occupancy seconds'],
            [[v[k] for k in ('group','path','travel','actual')] for v in result.get('paths',[])]),'Path travel')
        self.addTab(table(['Group','Other group','Path','Time','Distance (pixels)'],
            [[v[k] for k in ('group','other','location','time','distance')] for v in result.get('spacing',[])]),'Spacing conflicts')

    def show_comparison(self,results):
        keys=['groups_per_hour','guests_per_hour','traversal_average','interior_failures','room_overstays','max_groups','release_latency']
        self.addTab(table(['Scenario']+keys,[[r['scenario']]+[r['metrics'][k] for k in keys] for r in results]),'Comparison')
        self.setCurrentIndex(self.count()-1)

    def show_repeated(self,result):
        text=QPlainTextEdit()
        text.setReadOnly(True)
        lines=[]
        for k,v in result.items():
            lines.append(k.replace('_',' ').title()+': '+(json.dumps(v,indent=2) if isinstance(v,dict) else f'{v:.3f}' if isinstance(v,float) else str(v)))
        text.setPlainText('\n\n'.join(lines))
        self.addTab(text,'Repeated runs')
        self.setCurrentIndex(self.count()-1)
