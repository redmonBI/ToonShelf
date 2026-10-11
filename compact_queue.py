from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QProgressBar
from progress_ui import Sparkline,progress_percent,STATUS

class CompactQueue(QWidget):
    def __init__(self,host):
        super().__init__();self.host=host;self.items=QVBoxLayout(self);self.items.setContentsMargins(0,0,0,0);self.cards={};self.summary=QLabel();self.summary.setWordWrap(True);self.items.addWidget(self.summary)
    def refresh(self):
        rows=[r for r in self.host.queue.rows() if r['status'] not in ('complete','cancelled')];rows.sort(key=lambda r:(r['status'] not in ('running','paused'),-r.get('priority',0),r['id']))
        self.summary.setText(f"진행 {sum(r['status']=='running' for r in rows)} · 대기 {sum(r['status']=='pending' for r in rows)} · 전체 {len(rows)}")
        ids={r['id'] for r in rows[:5]}
        for id in list(self.cards):
            if id not in ids:w,*_=self.cards.pop(id);self.items.removeWidget(w);w.deleteLater()
        for index,row in enumerate(rows[:5]):
            id=row['id']
            if id not in self.cards:
                w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(0,4,0,4);title=QLabel();title.setWordWrap(True);lay.addWidget(title);bar=QProgressBar();bar.setMinimumHeight(22);lay.addWidget(bar);graph=Sparkline();graph.setMinimumHeight(28);graph.setMaximumHeight(32);lay.addWidget(graph);self.cards[id]=(w,title,bar,graph)
            w,title,bar,graph=self.cards[id];self.items.removeWidget(w);self.items.insertWidget(index+1,w);value=progress_percent(row)
            title.setText(f"{row['work']['title']} · {STATUS.get(row['status'],row['status'])}");bar.setRange(0,100);bar.setValue(value or 0);bar.setFormat('%p%' if value is not None else '회차 확인 중' if row['status']=='running' else '0% · 대기')
            meter=self.host.queue_metrics.get(id);graph.add(meter.snapshot()['speed'] if meter and row['status']=='running' else 0)
