"""Episode notification center and reusable collection filters."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QLineEdit,QTableWidget,QTableWidgetItem,QHeaderView,QProgressBar,QCheckBox
from collections_store import DAYS,work_key,filter_works,check_updates,as_work
from datetime import datetime
from automation_store import SEOUL

class CollectionFilters(QWidget):
    def __init__(self,changed,parent=None):
        super().__init__(parent);lay=QHBoxLayout(self);lay.setContentsMargins(0,0,0,0)
        self.day=QComboBox();self.day.addItem('모든 요일',None);self.day.addItem('요일 미지정',-1)
        for i,name in enumerate(DAYS):self.day.addItem(name,i)
        self.genre=QLineEdit();self.genre.setPlaceholderText('장르 필터');self.genre.setMaximumWidth(150)
        self.publisher=QLineEdit();self.publisher.setPlaceholderText('제공처 필터');self.publisher.setMaximumWidth(150)
        self.favorite=QComboBox();self.favorite.addItems(['모든 작품','즐겨찾기만','즐겨찾기 우선'])
        for widget in (self.day,self.genre,self.publisher,self.favorite):lay.addWidget(widget)
        self.day.currentIndexChanged.connect(changed);self.favorite.currentIndexChanged.connect(changed);self.genre.textChanged.connect(changed);self.publisher.textChanged.connect(changed)
    def apply(self,works,store):return filter_works(works,store,weekday=self.day.currentData(),genre=self.genre.text().strip(),publisher=self.publisher.text().strip(),favorite_only=self.favorite.currentIndex()==1,favorite_first=self.favorite.currentIndex()==2)

class WorkSettingsDialog(QDialog):
    def __init__(self,host,work):
        from PySide6.QtWidgets import QFormLayout
        super().__init__(host);self.host=host;self.setWindowTitle('작품 분류 · 즐겨찾기');self.resize(430,320);self.work=work;self.store=host.collection_store;existing=self.store.get(work) or {};lay=QFormLayout(self)
        self.favorite=QCheckBox('즐겨찾기에 추가');self.favorite.setChecked(bool(existing.get('favorite')));lay.addRow(self.favorite)
        self.day=QComboBox();self.day.addItem('요일 미지정',-1)
        for i,name in enumerate(DAYS):self.day.addItem(name,i)
        self.day.setCurrentIndex(int(existing.get('weekday',-1))+1);lay.addRow('연재 / 정리 요일',self.day)
        from collections_store import work_dict
        value=work_dict(work);self.genre=QLineEdit(existing.get('genre',value.get('genre','')));self.publisher=QLineEdit(existing.get('publisher',value.get('publisher','')));lay.addRow('장르',self.genre);lay.addRow('제공처',self.publisher)
        save=QPushButton('저장');save.clicked.connect(self.save);lay.addRow(save)
    def save(self):
        self.store.update(self.work,favorite=self.favorite.isChecked(),weekday=self.day.currentData(),genre=self.genre.text().strip(),publisher=self.publisher.text().strip())
        auto=getattr(self.host,'auto_store',None)
        if auto:auto.update(work_key(self.work),weekday=self.day.currentData())
        self.accept()

class NotificationsDialog(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.store=host.collection_store;self.task=None;self.setWindowTitle('ToonShelf · 새 회차 알림');self.resize(950,650);lay=QVBoxLayout(self)
        title=QLabel('새로운 이야기가 도착했어요');title.setStyleSheet('font-size:24px;font-weight:700');lay.addWidget(title)
        note=QLabel('즐겨찾기와 자동 다운로드 작품을 확인합니다. 첫 조회는 기준만 저장하고, 다음 조회부터 새 회차를 알려드립니다.');note.setWordWrap(True);lay.addWidget(note)
        self.enabled=QCheckBox('프로그램 실행 중 30분마다 새 회차 확인');self.enabled.setChecked(host.cfg.get('notifications_enabled',False));self.enabled.toggled.connect(self.save);lay.addWidget(self.enabled)
        row=QHBoxLayout();check=QPushButton('지금 새 회차 확인');check.clicked.connect(self.check);row.addWidget(check);read=QPushButton('모두 읽음');read.clicked.connect(self.mark_all);row.addWidget(read);row.addStretch();lay.addLayout(row)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['작품 / 새 회차','등록 확인','알림','자동 목록','바로 받기']);self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(52);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);lay.addWidget(self.table,1)
        self.status=QLabel();self.status.setWordWrap(True);lay.addWidget(self.status);self.busy=QProgressBar();self.busy.setRange(0,0);self.busy.hide();lay.addWidget(self.busy);close=QPushButton('닫기');close.clicked.connect(self.accept);lay.addWidget(close,alignment=Qt.AlignRight);self.refresh()
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(1000);self.finished.connect(self.timer.stop)
    def save(self,value):self.host.cfg['notifications_enabled']=bool(value);self.host.persist_settings()
    def mark_all(self):self.store.mark_read();self.refresh();self.notify()
    def notify(self):
        fn=getattr(self.host,'refresh_notifications',None)
        if fn:fn()
    def refresh(self):
        rows=self.store.notices();signature=repr(rows)
        if signature==getattr(self,'signature',None):return
        self.signature=signature;self.table.setRowCount(len(rows));automatic={e['key'] for e in self.host.auto_store.entries()}
        for i,n in enumerate(rows):
            self.table.setItem(i,0,QTableWidgetItem(n['work']['title']+' · '+n['episode']['title']));self.table.setItem(i,1,QTableWidgetItem(datetime.fromisoformat(n['created']).astimezone(SEOUL).strftime('%m/%d %H:%M')));self.table.setItem(i,2,QTableWidgetItem('새 회차' if n['unread'] else '확인함'))
            b=QPushButton('등록됨' if n['key'] in automatic else '자동 목록 추가');b.setEnabled(n['key'] not in automatic);b.clicked.connect(lambda _,n=n:self.add_auto(n));self.table.setCellWidget(i,3,b)
            b=QPushButton('최신 회차 받기');b.clicked.connect(lambda _,n=n:self.download(n));self.table.setCellWidget(i,4,b)
    def add_auto(self,n):
        self.host.auto_store.add([n['work']]);metadata=self.store.get(n['work'])
        if metadata:self.host.auto_store.update(n['key'],weekday=metadata['weekday'])
        self.signature=None;self.refresh();self.status.setText('자동 목록에 등록했습니다. 요일과 보관 설정은 자동 다운로드에서 바꿀 수 있습니다.')
    def download(self,n):
        try:
            cfg=dict(self.host.read_cfg(),latest_count=1,start_episode=1,end_episode=0)
            self.host.enqueue_works([as_work(n['work'])],cfg)
            self.store.mark_read([n['id']]);self.refresh();self.notify();self.status.setText('최신 회차를 다운로드 대기열에 추가했습니다.')
        except Exception as exc:self.status.setText(str(exc))
    def check(self):
        if self.task and self.task.isRunning():return
        try:cfg=self.host.read_cfg()
        except ValueError as exc:self.status.setText(str(exc));return
        from library_ui import LibraryTask
        self.task=LibraryTask(lambda control,emit:check_updates(self.store,self.host.auto_store,cfg,control,emit));self.host.notification_job=self.task;self.busy.show();self.status.setText('작품별 새 회차 확인 중…')
        self.task.done.connect(self.done);self.task.finished.connect(lambda:self.busy.hide());self.task.start()
    def done(self,state,result):
        self.status.setText(f"{result['checked']}개 작품 확인 · 새 회차 {result['added']}개 · 오류 {len(result['errors'])}건" if state=='success' else '확인 '+('중단' if state=='cancelled' else '실패 · '+str(result)));self.refresh();self.notify()
    def reject(self):
        if self.task and self.task.isRunning():self.task.control.stopped.set();self.status.setText('확인을 중단하는 중…');return
        super().reject()
    def accept(self):
        if self.task and self.task.isRunning():self.task.control.stopped.set();self.status.setText('확인을 중단하는 중…');return
        super().accept()
