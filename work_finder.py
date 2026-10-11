"""Find catalog works without leaving the personal weekly list."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QProgressBar
from PySide6.QtCore import Qt
from core import Browser
from library_ui import LibraryTask
from collections_store import as_work,work_key

class WorkFinder(QDialog):
    def __init__(self,host,on_add):
        super().__init__(host);self.host=host;self.on_add=on_add;self.task=None;self.dismissed=False;self.works=list(host.works);self.setWindowTitle('내 웹툰 목록 · 작품 검색·추가');self.resize(850,650)
        lay=QVBoxLayout(self);row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('작품명 · 장르 · 제공처 검색');self.search.textChanged.connect(self.render);row.addWidget(self.search,1);load=QPushButton('사이트 전체 목록 갱신');load.clicked.connect(self.load);row.addWidget(load);lay.addLayout(row)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['작품','장르','제공처']);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table,1)
        self.busy=QProgressBar();self.busy.setRange(0,0);self.busy.hide();lay.addWidget(self.busy);self.status=QLabel();lay.addWidget(self.status);row=QHBoxLayout();add=QPushButton('선택 작품을 내 웹툰 목록에 추가');add.clicked.connect(self.add);row.addWidget(add);close=QPushButton('닫기');close.clicked.connect(self.reject);row.addWidget(close);lay.addLayout(row);self.finished.connect(self.dismiss);self.render()
    def render(self):
        query=self.search.text().casefold();self.rows=[w for w in self.works if query in ' '.join((w.title,w.genre,w.publisher)).casefold()][:500];self.table.setRowCount(len(self.rows))
        for i,w in enumerate(self.rows):
            for c,value in enumerate((w.title,w.genre,w.publisher)):self.table.setItem(i,c,QTableWidgetItem(value))
        self.status.setText(f'검색 {len(self.rows)}개 · 여러 작품 선택 후 추가 · 한 번에 최대 500개 표시')
    def load(self):
        if self.task and self.task.isRunning():return
        try:cfg=self.host.read_cfg()
        except ValueError as e:self.status.setText(str(e));return
        def work(control,emit):
            with Browser(cfg,control,emit) as browser:return browser.catalog()
        self.task=LibraryTask(work);self.task.setParent(self.host);self.busy.show();self.status.setText('사이트 목록을 불러오는 중…');self.task.done.connect(self.loaded);self.task.finished.connect(self.busy.hide);self.task.start()
    def loaded(self,state,result):
        if self.dismissed:return
        if state=='success':self.works=result;self.render()
        else:self.status.setText('목록 확인 '+str(result))
    def add(self):
        selected=[self.rows[i.row()] for i in self.table.selectionModel().selectedRows()]
        if not selected:self.status.setText('추가할 작품을 선택하세요.');return
        self.on_add(selected);self.status.setText(f'{len(selected)}개 작품을 목록에 추가했습니다.')
    def dismiss(self,*_):
        self.dismissed=True
        if self.task and self.task.isRunning():self.task.control.stopped.set()
