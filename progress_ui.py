"""Readable per-work queue progress and bounded throughput graphs."""
import math
from collections import deque
from PySide6.QtCore import Qt,QTimer,QPointF
from PySide6.QtGui import QPainter,QPen,QColor,QPainterPath
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea,QWidget,QFrame,QProgressBar
from library import size_text
from download_metrics import duration
import themes

STATUS={'pending':'대기','running':'다운로드 중','paused':'일시정지','held':'보류','stopped':'중단','cancelled':'취소','complete':'완료','partial':'일부 실패','failed':'실패'}

def finite(value):
    try:return max(0.,float(value)) if math.isfinite(float(value)) else 0.
    except (ValueError,TypeError):return 0.

def progress_percent(row):
    if row.get('status')=='complete':return 100
    p=row.get('progress',{});t=p.get('transfer_progress',{})
    if t.get('total'):return min(99,int(100*finite(t.get('completed'))/max(1,finite(t['total']))))
    # Per-image counts reset for each episode, so they cannot represent a whole work.
    return None

class Sparkline(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.samples=deque(maxlen=90);self.setMinimumHeight(75);self.setAccessibleName('최근 다운로드 속도 그래프')
    def add(self,value):self.samples.append(finite(value));self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);c=themes.colors(self.window().property('theme') or 'white')
        rect=self.rect().adjusted(6,8,-6,-8);p.setPen(QPen(QColor(c['border']),1));p.drawLine(rect.bottomLeft(),rect.bottomRight())
        if len(self.samples)<2:return
        maximum=max(1.,max(self.samples));points=[QPointF(rect.left()+i*rect.width()/(len(self.samples)-1),rect.bottom()-v/maximum*rect.height()) for i,v in enumerate(self.samples)]
        path=QPainterPath(points[0])
        for point in points[1:]:path.lineTo(point)
        area=QPainterPath(path);area.lineTo(rect.bottomRight());area.lineTo(rect.bottomLeft());area.closeSubpath();fill=QColor(c['accent']);fill.setAlpha(30);p.fillPath(area,fill);p.setPen(QPen(QColor(c['accent']),2));p.drawPath(path)

class WorkProgress(QFrame):
    def __init__(self,host,row):
        super().__init__();self.host=host;self.id=row['id'];self.setObjectName('card');layout=QVBoxLayout(self);layout.setContentsMargins(18,14,18,14)
        top=QHBoxLayout();self.title=QLabel();self.title.setStyleSheet('font-size:16px;font-weight:700');top.addWidget(self.title,1);self.status=QLabel();top.addWidget(self.status);layout.addLayout(top)
        self.detail=QLabel();self.detail.setWordWrap(True);layout.addWidget(self.detail);self.bar=QProgressBar();self.bar.setTextVisible(True);self.bar.setMinimumHeight(22);layout.addWidget(self.bar)
        self.graph=Sparkline();layout.addWidget(self.graph);self.speed=QLabel();layout.addWidget(self.speed)
        controls=QHBoxLayout();self.buttons={}
        for text,action in [('계속','pending'),('보류','held'),('중단','stopped'),('취소','cancelled'),('우선','priority')]:
            button=QPushButton(text);button.clicked.connect(lambda checked=False,a=action:host.change_queue(self.id,a));controls.addWidget(button);self.buttons[action]=button
        controls.addStretch();layout.addLayout(controls);self.update_row(row)
    def update_row(self,row):
        self.title.setText(row['work']['title']);status=row['status'];self.status.setText(STATUS.get(status,status));p=row.get('progress',{});current=p.get('current',{});image=p.get('image_progress',{})
        self.detail.setText(f"{current.get('episode','회차 확인 중')} · 이미지 {image.get('index',0)} / {image.get('total',0)}  |  {row.get('cfg',{}).get('output_dir','')}")
        value=progress_percent(row)
        if value is None and status=='running':self.bar.setRange(0,0);self.bar.setFormat('회차 정보 확인 중')
        else:self.bar.setRange(0,100);self.bar.setValue(value or 0);self.bar.setFormat('%p% · 이미지 수 기준 추정' if status!='complete' else '100% · 완료')
        meter=getattr(self.host,'queue_metrics',{}).get(self.id);snap=meter.snapshot() if meter else {}
        rate=finite(snap.get('speed')) if status=='running' else 0.;self.graph.add(rate)
        self.speed.setText(f"{size_text(rate)}/초 · 예상 남은 시간 {duration(snap.get('remaining'))}" if status=='running' else STATUS.get(status,status))
        active=status in ('running','paused','pending','held','stopped','failed','partial')
        for action,button in self.buttons.items():button.setEnabled(active)

class QueueDashboard(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.cards={};self.page=0;self.setWindowTitle('다운로드 · 작품별 진행');self.resize(1020,800);layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,20)
        heading=QLabel('작품별 다운로드');heading.setStyleSheet('font-size:26px;font-weight:700');layout.addWidget(heading)
        self.overview=QLabel();layout.addWidget(self.overview);self.aggregate=Sparkline();layout.addWidget(self.aggregate)
        hint=QLabel('여러 작품의 진행 상황을 함께 확인합니다. 속도는 전체 합계이며, 각 작품의 예상 시간은 이미지 수로 추정합니다.');hint.setWordWrap(True);layout.addWidget(hint)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);body=QWidget();self.items=QVBoxLayout(body);self.items.setContentsMargins(2,2,14,2);self.items.setSpacing(14);self.items.addStretch();self.scroll.setWidget(body);layout.addWidget(self.scroll,1)
        row=QHBoxLayout()
        for text,callback in [('대기열 실행',host.run_queue),('전체 일시정지 / 계속',host.pause),('닫기',self.accept)]:b=QPushButton(text);b.clicked.connect(callback);row.addWidget(b)
        layout.addLayout(row);pages=QHBoxLayout();self.previous=QPushButton('이전 목록');self.next=QPushButton('다음 목록');self.page_label=QLabel();self.previous.clicked.connect(lambda:self.change_page(-1));self.next.clicked.connect(lambda:self.change_page(1));pages.addWidget(self.previous);pages.addWidget(self.page_label,1);pages.addWidget(self.next);layout.addLayout(pages);self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(1000);self.finished.connect(lambda:self.timer.stop());self.refresh()
    def change_page(self,delta):
        self.page=max(0,self.page+delta);self.refresh()
    def refresh(self):
        self.setProperty('theme',self.host.cfg.get('theme','white'));rows=self.host.queue.rows();ordered=sorted(rows,key=lambda r:(r['status'] not in ('running','paused'),-r.get('priority',0),r['id']));pages=max(1,(len(ordered)+24)//25);self.page=min(self.page,pages-1);visible=ordered[self.page*25:self.page*25+25];ids={r['id'] for r in visible};self.previous.setEnabled(self.page>0);self.next.setEnabled(self.page<pages-1);self.page_label.setText(f'{self.page+1} / {pages} · 전체 {len(rows)} 작품')
        for id in list(self.cards):
            if id not in ids:card=self.cards.pop(id);self.items.removeWidget(card);card.deleteLater()
        running=[r for r in rows if r['status']=='running'];rates=getattr(self.host,'queue_metrics',{})
        total=sum(finite(rates[r['id']].snapshot().get('speed')) for r in running if r['id'] in rates);self.aggregate.add(total)
        counts={s:sum(r['status']==s for r in rows) for s in ('running','pending','complete')}
        self.overview.setText(f"진행 {counts['running']} · 대기 {counts['pending']} · 완료 {counts['complete']}  |  전체 속도 {size_text(total)}/초")
        for index,row in enumerate(visible):
            if row['id'] not in self.cards:self.cards[row['id']]=WorkProgress(self.host,row)
            card=self.cards[row['id']];self.items.removeWidget(card);self.items.insertWidget(index,card);card.update_row(row)
