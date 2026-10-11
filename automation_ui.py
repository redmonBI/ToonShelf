from PySide6.QtCore import Qt,QTime,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QWidget,QTabWidget,
    QLabel,QPushButton,QLineEdit,QComboBox,QSpinBox,QCheckBox,QTimeEdit,QTableWidget,
    QTableWidgetItem,QHeaderView,QAbstractItemView,QProgressBar,QMessageBox)
from automation_store import CATEGORIES
from transfer_policy import validate_policy
from collections_store import DAYS,work_key,filter_works
from notifications_ui import CollectionFilters

COUNTS=[0,1,5,10,20,30]
def tail_combo(count):
    c=QComboBox()
    for n in COUNTS:c.addItem('전체 회차' if not n else f'최신 {n}화',n)
    c.setCurrentIndex(COUNTS.index(count) if count in COUNTS else 0);return c
def button(text,fn):
    b=QPushButton(text);b.clicked.connect(fn);return b
def table(headers):
    t=QTableWidget(0,len(headers));t.setHorizontalHeaderLabels(headers);t.verticalHeader().hide();t.verticalHeader().setDefaultSectionSize(56);t.setSelectionBehavior(QAbstractItemView.SelectRows);t.setEditTriggers(QAbstractItemView.NoEditTriggers);t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive);t.horizontalHeader().setStretchLastSection(True);return t

class AutomationDialog(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.store=host.auto_store;self.setWindowTitle('ToonShelf · 자동 다운로드');self.resize(1150,820)
        lay=QVBoxLayout(self);lay.setContentsMargins(24,20,24,20);title=QLabel('매주 돌아오는 나의 작품');title.setStyleSheet('font-size:25px;font-weight:700');lay.addWidget(title)
        note=QLabel('한국 시간 기준 · 프로그램 실행 중 예약을 처리합니다. 꺼져 있던 동안의 예약은 당일 재실행 시 한 번 처리합니다.');note.setWordWrap(True);lay.addWidget(note)
        self.tabs=QTabWidget();lay.addWidget(self.tabs,1)
        page=QWidget();p=QVBoxLayout(page);tools=QHBoxLayout();self.filter=QComboBox();self.filter.addItems(['모든 작품']+list(CATEGORIES.values()));self.filter.currentIndexChanged.connect(self.render);self.search=QLineEdit();self.search.setPlaceholderText('자동 목록 안에서 작품 검색');self.search.textChanged.connect(self.render);tools.addWidget(self.filter);tools.addWidget(self.search,1)
        tools.addWidget(button('체크한 사이트 작품 추가',self.add_selected));tools.addWidget(button('읽고 있는 작품 추가',self.add_current));p.addLayout(tools)
        self.collection_filters=CollectionFilters(self.render,self);p.addWidget(self.collection_filters)
        self.list=table(['예약 체크','작품명','목록 분류','업데이트 범위','남길 최신 회차','보관 기간 (일)','작품 요일','즐겨찾기']);p.addWidget(self.list,1)
        for i,width in enumerate([90,250,150,150,160,160]):self.list.setColumnWidth(i,width)
        hint=QLabel('최신 회차는 새로 조회하며 최근 회차부터 받습니다. 0화 보관 / 0일은 해당 삭제 규칙을 사용하지 않습니다.\n삭제 규칙은 자동 정리 설정을 켠 뒤 적용합니다. 최신 N화 보호가 기간 삭제보다 우선합니다. 목록에서 빼도 작품 파일은 남습니다.');hint.setWordWrap(True);p.addWidget(hint)
        row=QHBoxLayout();row.addWidget(button('전체 체크',lambda:self.check_all(True)));row.addWidget(button('전체 체크 해제',lambda:self.check_all(False)));row.addWidget(button('선택 행을 목록에서 빼기',self.remove));row.addStretch();row.addWidget(button('체크한 작품 지금 업데이트',lambda:self.start('selected')));row.addWidget(button('목록 전체 지금 업데이트',lambda:self.start('all')));p.addLayout(row);self.tabs.addTab(page,'작품 목록')
        page=QWidget();form=QFormLayout(page);form.setVerticalSpacing(18);schedule=self.store.schedule();self.enabled=QCheckBox('요일·시간 자동 다운로드 사용');self.enabled.setChecked(schedule['enabled']);form.addRow(self.enabled)
        days=QHBoxLayout();self.days=[]
        for i,name in enumerate(['월','화','수','목','금','토','일']):
            c=QCheckBox(name);c.setChecked(i in schedule['days']);self.days.append(c);days.addWidget(c)
        form.addRow('매주 요일',days);self.time=QTimeEdit(QTime.fromString(schedule['time'],'HH:mm'));self.time.setDisplayFormat('HH:mm');form.addRow('예약 시간 (한국)',self.time)
        self.scope=QComboBox();self.scope.addItems(['체크한 작품만','목록 전체']);self.scope.setCurrentIndex(schedule['scope']=='all');form.addRow('예약 대상',self.scope)
        self.cleanup=QCheckBox('자동 보관 정리 사용 · 등록 이미지 영구 삭제');self.cleanup.setChecked(schedule.get('cleanup',False));form.addRow(self.cleanup)
        hint=QLabel('정리는 이 PC의 현재 저장 폴더와 위 예약 대상 작품에만 적용합니다.\n최신 보관 회차가 불완전하거나 뷰어·다운로드·내보내기 작업 중이면 정리를 보류합니다.\n기간은 마지막 다운로드일 기준입니다. 변경한 이미지와 미등록 파일은 삭제하지 않습니다.\n읽기용 OpenComic 연결 파일도 함께 정리합니다. 휴지통을 거치지 않습니다.\n예약을 저장할 때 이미 지난 시간은 다음 지정 요일부터 적용합니다.');hint.setWordWrap(True);form.addRow(hint)
        form.addRow(button('예약·자동 정리 설정 저장',self.save_schedule));form.addRow(button('정리 대상 미리보기',self.preview));self.tabs.addTab(page,'요일·시간 / 자동 정리')
        page=QWidget();form=QFormLayout(page);form.setVerticalSpacing(18);policy=host.cfg.get('network_policy',{})
        self.limit=QSpinBox();self.limit.setRange(0,1024);self.limit.setSuffix(' MB/s');self.limit.setValue(policy.get('limit_mib',0));form.addRow('최고 이미지 전송 속도',self.limit)
        self.window=QCheckBox('다운로드를 아래 시간 안에서만 진행');self.window.setChecked(policy.get('window_enabled',False));form.addRow(self.window)
        self.begin=QTimeEdit(QTime.fromString(policy.get('start','00:00'),'HH:mm'));self.finish=QTimeEdit(QTime.fromString(policy.get('end','00:00'),'HH:mm'))
        self.begin.setDisplayFormat('HH:mm');self.finish.setDisplayFormat('HH:mm');row=QHBoxLayout();row.addWidget(self.begin);row.addWidget(QLabel('부터'));row.addWidget(self.finish);row.addWidget(QLabel('까지'));form.addRow('매일 허용 시간',row)
        self.rules=table(['시작','종료','최고 속도 MB/s']);self.rules.setMaximumHeight(240);form.addRow('시간대별 속도',self.rules)
        self.rules.setColumnWidth(0,180);self.rules.setColumnWidth(1,180)
        for rule in policy.get('rules',[]):self.add_rule(rule)
        row=QHBoxLayout();row.addWidget(button('시간대 추가',lambda:self.add_rule()));row.addWidget(button('선택 시간대 삭제',self.remove_rule));form.addRow(row)
        hint=QLabel('0 = 제한 없음 · 1~1024 MB/s (1 GB/s) · 1 MB = 1,048,576바이트\n속도는 작품 이미지 전송 기준이며 페이지·표지 조회는 제외합니다.\n시간대가 겹치면 더 낮은 제한을 적용합니다. 시작 = 종료는 하루 전체입니다.\n허용 시간이 끝나면 다음 요청·이미지 조각부터 대기하고, 다음 시간에 이어갑니다.\n저장 후 진행 중 다운로드에도 적용합니다. 서버 접근 제한은 우회하지 않습니다.');hint.setWordWrap(True);form.addRow(hint);form.addRow(button('속도·허용 시간 설정 저장',self.save_policy));self.tabs.addTab(page,'속도·진행 시간')
        page=QWidget();p=QVBoxLayout(page);self.history=table(['예약 / 실행 시각','상태','처리 내용']);self.history.setColumnWidth(0,250);self.history.setColumnWidth(1,120);p.addWidget(self.history);p.addWidget(button('실행 기록 새로고침',self.refresh_history));self.tabs.addTab(page,'실행 기록')
        self.status=QLabel();self.status.setWordWrap(True);lay.addWidget(self.status);self.busy=QProgressBar();self.busy.setRange(0,0);self.busy.setFixedHeight(8);lay.addWidget(self.busy);self.busy.hide();lay.addWidget(button('닫기',self.accept),alignment=Qt.AlignRight)
        self.render();self.refresh_history();self.timer=QTimer(self);self.timer.timeout.connect(self.activity);self.timer.start(500);self.finished.connect(self.timer.stop)
    def render(self):
        if not hasattr(self,'list'):return
        rows=self.store.entries();category=list(CATEGORIES)[self.filter.currentIndex()-1] if self.filter.currentIndex() else None
        self.rows=[e for e in rows if (not category or e['category']==category) and self.search.text().casefold() in e['work']['title'].casefold()];self.list.setRowCount(len(self.rows))
        collection=getattr(self.host,'collection_store',None)
        if collection:
            day=self.collection_filters.day.currentData()
            filtered=filter_works([e['work'] for e in self.rows],collection,genre=self.collection_filters.genre.text().strip(),publisher=self.collection_filters.publisher.text().strip(),favorite_only=self.collection_filters.favorite.currentIndex()==1,favorite_first=self.collection_filters.favorite.currentIndex()==2)
            order={work_key(w):i for i,w in enumerate(filtered)}
            self.rows=[e for e in self.rows if e['key'] in order and (day is None or e.get('weekday',-1)==day)]
            self.rows.sort(key=lambda e:order[e['key']])
        self.list.setRowCount(len(self.rows))
        for i,e in enumerate(self.rows):
            c=QCheckBox();c.setChecked(bool(e['selected']));c.toggled.connect(lambda value,k=e['key']:self.store.update(k,selected=int(value)));self.list.setCellWidget(i,0,c);self.list.setItem(i,1,QTableWidgetItem(e['work']['title']))
            c=QComboBox();c.addItems(list(CATEGORIES.values()));c.setCurrentIndex(list(CATEGORIES).index(e['category']));c.currentIndexChanged.connect(lambda index,k=e['key']:self.store.update(k,category=list(CATEGORIES)[index]));self.list.setCellWidget(i,2,c)
            c=tail_combo(e['tail']);c.currentIndexChanged.connect(lambda index,k=e['key'],c=c:self.store.update(k,tail=c.itemData(index)));self.list.setCellWidget(i,3,c)
            for column,field in [(4,'keep_count'),(5,'delete_days')]:
                spin=QSpinBox();spin.setRange(0,10000);spin.setValue(e[field]);spin.valueChanged.connect(lambda value,k=e['key'],field=field:self.store.update(k,**{field:value}));self.list.setCellWidget(i,column,spin)
            day=QComboBox();day.addItem('예약 요일 모두',-1)
            for d,name in enumerate(DAYS):day.addItem(name,d)
            day.setCurrentIndex(e.get('weekday',-1)+1);day.currentIndexChanged.connect(lambda _,k=e['key'],w=e['work'],c=day:self.set_day(k,w,c.currentData()));self.list.setCellWidget(i,6,day)
            favorite=QCheckBox('★');favorite.setChecked(bool((collection.get(e['work']) or {}).get('favorite')) if collection else False);favorite.setEnabled(collection is not None)
            favorite.toggled.connect(lambda v,w=e['work']:self.host.collection_store.update(w,favorite=v));self.list.setCellWidget(i,7,favorite)
    def set_day(self,key,work,day):
        self.store.update(key,weekday=day)
        if getattr(self.host,'collection_store',None):self.host.collection_store.update(work,weekday=day)
    def add_selected(self):
        works=[w for w in self.host.works if w.url in self.host.selected]
        if not works:self.status.setText('사이트 작품 목록에서 추가할 작품을 체크하세요.');return
        self.store.add(works);self.copy_days(works);self.render();self.status.setText(f'{len(works)}개 작품 추가 · 분류와 업데이트 범위를 설정하세요.')
    def add_current(self):
        pane=getattr(self.host,'offline',None)
        if not pane or not pane.work:self.status.setText('내 작품 라이브러리에서 작품을 먼저 여세요.');return
        self.store.add([pane.work]);self.copy_days([pane.work]);self.render();self.status.setText('읽고 있는 작품을 자동 목록에 추가했습니다.')
    def copy_days(self,works):
        collection=getattr(self.host,'collection_store',None)
        if collection:
            for work in works:
                metadata=collection.get(work)
                if metadata:self.store.update(work_key(work),weekday=metadata['weekday'])
    def check_all(self,value):
        for e in self.rows:self.store.update(e['key'],selected=int(value))
        self.render()
    def remove(self):
        for i in sorted({index.row() for index in self.list.selectedIndexes()},reverse=True):self.store.remove(self.rows[i]['key'])
        self.render()
    def start(self,scope):self.host.automation_action('enqueue',scope)
    def save_schedule(self):
        days=[i for i,c in enumerate(self.days) if c.isChecked()]
        if self.enabled.isChecked() and not days:self.status.setText('예약 요일을 하나 이상 선택하세요.');return
        self.store.save_schedule(dict(enabled=self.enabled.isChecked(),days=days,time=self.time.time().toString('HH:mm'),scope='all' if self.scope.currentIndex() else 'selected',cleanup=self.cleanup.isChecked()));self.status.setText('예약·정리 설정을 저장했습니다. 실행 중인 작품의 정리는 보류합니다.')
    def preview(self):self.host.automation_action('preview','all' if self.scope.currentIndex() else 'selected')
    def add_rule(self,rule=None):
        rule=rule or dict(start='18:00',end='23:00',mib=1);i=self.rules.rowCount();self.rules.insertRow(i)
        for c,key in [(0,'start'),(1,'end')]:
            widget=QTimeEdit(QTime.fromString(rule[key],'HH:mm'));widget.setDisplayFormat('HH:mm');self.rules.setCellWidget(i,c,widget)
        spin=QSpinBox();spin.setRange(0,1024);spin.setValue(rule['mib']);self.rules.setCellWidget(i,2,spin)
    def remove_rule(self):
        if self.rules.currentRow()>=0:self.rules.removeRow(self.rules.currentRow())
    def save_policy(self):
        value=dict(limit_mib=self.limit.value(),window_enabled=self.window.isChecked(),start=self.begin.time().toString('HH:mm'),end=self.finish.time().toString('HH:mm'),rules=[])
        for i in range(self.rules.rowCount()):value['rules'].append(dict(start=self.rules.cellWidget(i,0).time().toString('HH:mm'),end=self.rules.cellWidget(i,1).time().toString('HH:mm'),mib=self.rules.cellWidget(i,2).value()))
        self.host.cfg['network_policy']=validate_policy(value);self.host.persist_settings();self.status.setText('전송 속도·허용 시간을 저장했습니다. 진행 중인 작품에도 적용됩니다.')
    def refresh_history(self):
        rows=self.store.history();self.history.setRowCount(len(rows))
        for i,r in enumerate(rows):
            for c,key in enumerate(['created','status','detail']):self.history.setItem(i,c,QTableWidgetItem({'prepared':'등록 준비','queued':'대기열 등록','complete':'처리 완료','failed':'오류','cancelled':'취소'}.get(r[key],r[key]) if key=='status' else r[key]))
    def activity(self):
        active=bool(self.host.auto_job and self.host.auto_job.isRunning());self.busy.setVisible(active)
        if active:self.status.setText('자동 다운로드 설정 처리·정리 준비 중…')
        elif getattr(self.host,'auto_notice','') and self.host.auto_notice!=getattr(self,'last_notice',''):
            self.status.setText(self.host.auto_notice);self.last_notice=self.host.auto_notice
