"""Bounded page controls for libraries with hundreds of pages."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QHBoxLayout,QPushButton,QLabel,QSpinBox

def page_numbers(current,total):
 total=max(1,total);current=max(1,min(total,current))
 start=max(1,min(current-2,total-4));end=min(total,start+4)
 return sorted({1,total,*range(start,end+1)})

class Pagination(QWidget):
 requested=Signal(int)  # zero based
 def __init__(self):
  super().__init__();self.current=0;self.total=1
  lay=QHBoxLayout(self);lay.setContentsMargins(0,0,0,0);lay.setSpacing(5)
  self.prev=QPushButton('‹ 이전');self.prev.setObjectName('pageStep');self.prev.clicked.connect(lambda:self.requested.emit(self.current-1));lay.addWidget(self.prev)
  lay.addStretch();self.numbers=QHBoxLayout();self.numbers.setSpacing(4);lay.addLayout(self.numbers)
  lay.addStretch();self.next=QPushButton('다음 ›');self.next.setObjectName('pageStep');self.next.clicked.connect(lambda:self.requested.emit(self.current+1));lay.addWidget(self.next)
  self.jump=QSpinBox();self.jump.setRange(1,1);self.jump.setPrefix('이동 ');self.jump.setFixedWidth(100);self.jump.setToolTip('원하는 페이지 번호를 입력하고 Enter를 누르세요.');self.jump.editingFinished.connect(self.go);lay.addWidget(self.jump)
  self.update_pages(0,1)
 def go(self):
  target=self.jump.value()-1
  if target!=self.current:self.requested.emit(target)
 def update_pages(self,current,total):
  self.total=max(1,total);self.current=max(0,min(self.total-1,current))
  self.prev.setEnabled(self.current>0);self.next.setEnabled(self.current<self.total-1)
  self.jump.setRange(1,self.total);self.jump.setValue(self.current+1);self.jump.setEnabled(self.total>1)
  while self.numbers.count():
   item=self.numbers.takeAt(0)
   if item.widget():item.widget().hide();item.widget().deleteLater()
  previous=0
  for page in page_numbers(self.current+1,self.total):
   if previous and page-previous>1:self.numbers.addWidget(QLabel('…'))
   b=QPushButton(str(page));b.setObjectName('pageButton');b.setCheckable(True);b.setChecked(page==self.current+1);b.setAccessibleName(f'{page} 페이지');b.setToolTip(f'{page} / {self.total} 페이지')
   b.clicked.connect(lambda checked=False,p=page:self.requested.emit(p-1));self.numbers.addWidget(b);previous=page
