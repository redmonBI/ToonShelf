"""Multi-select weekday filter; the legacy single-day API remains supported."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QHBoxLayout,QCheckBox

class WeekdayChecks(QWidget):
    currentIndexChanged=Signal(int)
    def __init__(self):
        super().__init__();lay=QHBoxLayout(self);lay.setContentsMargins(0,0,0,0);lay.setSpacing(8)
        self.all=QCheckBox('모든 요일');self.all.setChecked(True);lay.addWidget(self.all);self.boxes={}
        for day,name in [(i,n) for i,n in enumerate('월화수목금토일')]+[(-1,'미지정')]:
            c=QCheckBox(name);c.setAccessibleName(name+'요일 필터' if day>=0 else name);lay.addWidget(c);self.boxes[day]=c;c.toggled.connect(self.changed)
        lay.addStretch();self.all.toggled.connect(self.all_changed)
    def all_changed(self,value):
        if value:
            for c in self.boxes.values():c.blockSignals(True);c.setChecked(False);c.blockSignals(False)
        self.currentIndexChanged.emit(self.currentIndex())
    def changed(self,*_):
        self.all.blockSignals(True);self.all.setChecked(False);self.all.blockSignals(False);self.currentIndexChanged.emit(self.currentIndex())
    def currentData(self):
        if self.all.isChecked():return None
        selected=[d for d,c in self.boxes.items() if c.isChecked()]
        return selected[0] if len(selected)==1 else selected
    def currentIndex(self):
        data=self.currentData();return 0 if data is None else self.findData(data) if isinstance(data,int) else -1
    def findData(self,value):return 0 if value is None else value+2 if isinstance(value,int) and value in range(-1,7) else -1
    def setCurrentIndex(self,index):self.set_days(None if index==0 else [index-2] if index in range(1,9) else [])
    def set_days(self,value):
        days=None if value is None else [value] if isinstance(value,int) else value
        self.all.blockSignals(True);self.all.setChecked(days is None);self.all.blockSignals(False)
        for d,c in self.boxes.items():c.blockSignals(True);c.setChecked(days is not None and d in days);c.blockSignals(False)
        self.currentIndexChanged.emit(self.currentIndex())
