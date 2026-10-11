"""Nonblocking account dialog. Host owns apply/export of local metadata."""
import json
from urllib.parse import urlsplit
from datetime import datetime,timezone,timedelta
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QCheckBox,QPushButton,QTabWidget,QWidget,QProgressBar,QTableWidget,QTableWidgetItem,QMessageBox,QComboBox,QAbstractItemView)

MENU_NAMES={'catalog':'작품 목록','library':'내 작품 라이브러리','archive':'다운로드 기록','downloads':'다운로드','automatic':'자동 다운로드','power':'완료 후 종료','community':'친구 추천','sites':'사이트·최신 링크','settings':'설정','folder':'저장 폴더'}
SEOUL=timezone(timedelta(hours=9))

def history_time(value):
    try:
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp(),stamp.astimezone(SEOUL).strftime('%Y-%m-%d %H:%M')
    except (ValueError,TypeError,OverflowError):return 0,str(value or '—')

def size_text(value):
    try:size=max(0,int(value or 0))
    except (ValueError,TypeError):return '—'
    if size>=1024**3:return f'{size/1024**3:.2f} GB'
    if size>=1024**2:return f'{size/1024**2:.1f} MB'
    if size>=1024:return f'{size/1024:.1f} KB'
    return f'{size} B'

def history_title(entry):
    work=entry.get('work',{})
    return str(work.get('title','')) if isinstance(work,dict) else str(entry.get('title',''))

class AccountTask(QThread):
    result=Signal(object);error=Signal(str)
    def __init__(self,fn,parent=None):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.result.emit(self.fn())
        except Exception as exc:self.error.emit(str(exc))

class AccountDialog(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.client=host.account_client;self.job=None;host.accounts_dialog_open=True;self.finished.connect(self.dialog_finished);self.setWindowTitle('ToonShelf · 내 계정');self.resize(1050,800)
        layout=QVBoxLayout(self);title=QLabel('어디서든 이어지는 내 목록');title.setStyleSheet('font-size:24px;font-weight:700');layout.addWidget(title)
        hint=QLabel('작품 이미지와 전체 PC 경로는 전송하지 않습니다. 마스터는 동기화한 목록·읽기·다운로드 이력을 조회할 수 있습니다.');hint.setWordWrap(True);layout.addWidget(hint)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        login=QWidget();form=QFormLayout(login);self.tabs.addTab(login,'로그인·계정 생성')
        self.server=QLineEdit(self.client.server);self.server.setPlaceholderText('https://계정서버주소');form.addRow('계정 서버',self.server)
        self.username=QLineEdit();form.addRow('아이디',self.username);self.password=QLineEdit();self.password.setEchoMode(QLineEdit.Password);form.addRow('비밀번호',self.password);self.display=QLineEdit();form.addRow('표시 이름',self.display)
        self.remember=QCheckBox('이 Windows 계정에서 자동 로그인');form.addRow(self.remember);self.consent=QCheckBox('마스터의 동기화 정보 조회 안내에 동의합니다');form.addRow(self.consent)
        row=QHBoxLayout();row.addWidget(self.button('로그인',self.login));row.addWidget(self.button('계정 생성',self.register));row.addWidget(self.button('로그아웃·계정 변경',self.logout));form.addRow(row)
        sync=QWidget();sync_layout=QVBoxLayout(sync);self.tabs.addTab(sync,'동기화')
        self.identity=QLabel();self.identity.setTextFormat(Qt.PlainText);sync_layout.addWidget(self.identity);note=QLabel('서버에서 불러오면 현재 화면 목록·환경 설정을 해당 계정으로 전환합니다. 이미 저장한 이미지와 로컬 다운로드 작업은 유지됩니다. 서버 정보가 바뀌면 저장을 중단하고 먼저 불러오도록 안내합니다.');note.setWordWrap(True);sync_layout.addWidget(note)
        sync_layout.addWidget(self.button('서버 목록·설정 불러오기',self.pull));sync_layout.addWidget(self.button('현재 계정의 목록·설정·이력 저장',self.push));self.import_local_button=self.button('이 PC의 기존 목록 가져오기',self.import_local);self.import_local_button.setEnabled(hasattr(host,'account_import_local'));sync_layout.addWidget(self.import_local_button)
        device_form=QFormLayout();device=getattr(getattr(host,'accounts_service',None),'device',{});self.device_name=QLineEdit(device.get('label','이 PC'));self.device_name.setMaxLength(80);device_form.addRow('이 기기의 표시 이름',self.device_name);self.device_button=self.button('기기 이름 저장',self.set_device);self.device_button.setEnabled(hasattr(host,'account_set_device'));device_form.addRow(self.device_button);sync_layout.addLayout(device_form);device_note=QLabel('예: 집 PC, 노트북. 이후 다운로드 이력에는 이 이름과 작품 폴더만 기록합니다.');device_note.setWordWrap(True);sync_layout.addWidget(device_note);sync_layout.addStretch()
        history=QWidget();history_layout=QVBoxLayout(history);self.history_index=self.tabs.addTab(history,'내 다운로드 이력');history_note=QLabel('어느 기기에서 언제, 어떤 작품을 몇 화까지 받았는지 확인하세요. 시간은 한국 시간으로 표시하며, 이미지는 이력에 포함되지 않습니다.');history_note.setWordWrap(True);history_layout.addWidget(history_note)
        history_filter=QHBoxLayout();self.history_search=QLineEdit();self.history_search.setPlaceholderText('작품명·기기 이름 검색');self.history_search.textChanged.connect(lambda _:self.render_history(True));history_filter.addWidget(self.history_search,1);history_filter.addWidget(self.button('이력 새로 보기',self.refresh));history_layout.addLayout(history_filter)
        self.history_table=QTableWidget(0,8);self.history_table.setHorizontalHeaderLabels(['작품명','다운로드 일시 (한국)','기기','저장 폴더','최종 회차','결과','다운로드 용량','저장 이미지']);self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows);self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.history_table.setAlternatingRowColors(True);self.history_table.horizontalHeader().setStretchLastSection(True)
        for column,width in enumerate([180,155,115,170,85,90,115,90]):self.history_table.setColumnWidth(column,width)
        history_layout.addWidget(self.history_table,1);history_pages=QHBoxLayout();self.history_summary=QLabel();history_pages.addWidget(self.history_summary,1);self.history_previous=self.button('이전',lambda:self.history_page.setCurrentIndex(max(0,self.history_page.currentIndex()-1)));history_pages.addWidget(self.history_previous);self.history_page=QComboBox();self.history_page.currentIndexChanged.connect(lambda _:self.render_history());history_pages.addWidget(self.history_page);self.history_next=self.button('다음',lambda:self.history_page.setCurrentIndex(min(self.history_page.count()-1,self.history_page.currentIndex()+1)));history_pages.addWidget(self.history_next);history_layout.addLayout(history_pages);self.history_records=[]
        admin=QWidget();admin_root=QVBoxLayout(admin);self.admin_index=self.tabs.addTab(admin,'마스터 관리');admin_tabs=QTabWidget();admin_root.addWidget(admin_tabs);usage=QWidget();admin_layout=QVBoxLayout(usage);admin_tabs.addTab(usage,'사용 현황·작품')
        self.search=QLineEdit();self.search.setPlaceholderText('계정·작품 검색');admin_layout.addWidget(self.search);admin_layout.addWidget(self.button('사용 현황 조회',self.users));self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['사용자','작품 수','다운로드 기록','마지막 접속']);self.table.horizontalHeader().setStretchLastSection(True);admin_layout.addWidget(self.table)
        row=QHBoxLayout();row.addWidget(self.button('목록·읽는 작품 조회',self.inspect));row.addWidget(self.button('선택 계정 삭제',self.delete));admin_layout.addLayout(row)
        self.summary=QLabel('계정을 선택하고 목록·읽는 작품 조회를 누르세요.');self.summary.setTextFormat(Qt.PlainText);admin_layout.addWidget(self.summary)
        filters=QHBoxLayout();self.work_search=QLineEdit();self.work_search.setPlaceholderText('조회 작품명·장르·제공처 검색');self.work_search.textChanged.connect(self.render_works);filters.addWidget(self.work_search,1);self.work_sort=QComboBox();self.work_sort.addItems(['많이 다운로드한 작품','최근 다운로드','작품명']);self.work_sort.currentIndexChanged.connect(self.render_works);filters.addWidget(self.work_sort);admin_layout.addLayout(filters)
        self.work_table=QTableWidget(0,7);self.work_table.setHorizontalHeaderLabels(['작품명','장르','제공처','읽던 회차','다운로드 횟수','다운로드 회차','최근 다운로드']);self.work_table.setSelectionBehavior(QAbstractItemView.SelectRows);self.work_table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.work_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.work_table.horizontalHeader().setStretchLastSection(True);self.work_table.setColumnWidth(0,220);self.work_table.setColumnWidth(6,150);admin_layout.addWidget(self.work_table,1)
        row=QHBoxLayout();row.addWidget(self.button('선택 작품을 내 목록에 가져오기',self.import_works));row.addWidget(self.button('선택 작품 다운로드',self.download_works));admin_layout.addLayout(row);self.inspected=None;self.work_rows=[]
        menu=QWidget();menu_form=QFormLayout(menu);admin_tabs.addTab(menu,'공유 메뉴 이름');self.label_fields={}
        note=QLabel('이름을 변경하면 로그인한 계정에 다음 동기화 때 적용됩니다. 빈칸은 기본 이름을 사용합니다.');note.setWordWrap(True);menu_form.addRow(note)
        for key,name in MENU_NAMES.items():
            field=QLineEdit();field.setPlaceholderText(name);field.setMaxLength(40);field.setText(getattr(self.client,'menu_labels',{}).get(key,''));self.label_fields[key]=field;menu_form.addRow(name,field)
        menu_form.addRow(self.button('공유 메뉴 이름 저장',self.save_labels))
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress);self.status=QLabel('계정 서버 연결을 설정하세요.');self.status.setTextFormat(Qt.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status);layout.addWidget(self.button('닫기',self.accept));self.refresh()
    def button(self,text,fn):
        button=QPushButton(text);button.clicked.connect(fn);return button
    def dialog_finished(self,*_):self.host.accounts_dialog_open=False
    def switch_allowed(self):
        try:
            callback=getattr(self.host,'account_can_switch',None)
            if callback and callback() is False:raise ValueError('진행 중인 작업이 끝난 뒤 계정을 변경하세요.')
            return True
        except Exception as exc:self.status.setText(str(exc));return False
    def refresh(self):
        user=self.client.user or {};self.identity.setText(f"{user.get('display_name','로그인하지 않음')} · {user.get('username','')}");self.tabs.setTabVisible(self.admin_index,user.get('role')=='master')
        service=getattr(self.host,'accounts_service',None)
        if service is not None:records=getattr(service,'history',[])
        else:
            try:records=self.host.account_snapshot().get('history',[]) if hasattr(self.host,'account_snapshot') else []
            except Exception:records=[]
        self.history_records=sorted((entry for entry in records[-5000:] if isinstance(entry,dict)),key=lambda entry:history_time(entry.get('when',entry.get('downloaded','')))[0],reverse=True) if isinstance(records,list) else []
        self.render_history()
    def render_history(self,reset=False):
        query=self.history_search.text().strip().casefold();rows=[entry for entry in self.history_records if query in (history_title(entry)+' '+str(entry.get('device',''))).casefold()];pages=max(1,(len(rows)+99)//100);page=0 if reset else max(0,min(self.history_page.currentIndex(),pages-1))
        if self.history_page.count()!=pages:
            self.history_page.blockSignals(True);self.history_page.clear();self.history_page.addItems([str(index+1)+' 페이지' for index in range(pages)]);self.history_page.blockSignals(False)
        self.history_page.blockSignals(True);self.history_page.setCurrentIndex(page);self.history_page.blockSignals(False);self.history_previous.setEnabled(page>0);self.history_next.setEnabled(page<pages-1);self.history_summary.setText(f'최근순 · {len(rows):,}건 · {page+1}/{pages} 페이지 · 페이지당 100건')
        shown=rows[page*100:(page+1)*100];self.history_table.setRowCount(len(shown));statuses={'complete':'완료','completed':'완료','partial':'일부 실패','failed':'실패','stopped':'중지','cancelled':'취소','running':'다운로드 중','queued':'대기','paused':'일시정지','held':'보류'}
        for row,entry in enumerate(shown):
            status=str(entry.get('status',''));values=[history_title(entry),history_time(entry.get('when',entry.get('downloaded','')))[1],entry.get('device','—'),entry.get('folder','—'),entry.get('last_episode','') or '—',statuses.get(status,status or '—'),size_text(entry.get('downloaded_bytes',0)),entry.get('saved_images',0)]
            for column,value in enumerate(values):self.history_table.setItem(row,column,QTableWidgetItem(str(value)))
    def run(self,fn,done=None):
        if self.job and self.job.isRunning():return
        self.progress.show();self.tabs.setEnabled(False);self.status.setText('계정 서버와 연결 중…');self.job=AccountTask(fn,self);self.job.result.connect(lambda data:self.on_result(data,done));self.job.error.connect(lambda message:self.status.setText(message));self.job.finished.connect(self.job_finished);self.job.start()
    def on_result(self,data,callback):
        self.status.setText('완료되었습니다.');self.refresh()
        try:
            if callback:callback(data)
        except Exception as exc:self.status.setText(str(exc))
    def job_finished(self):self.progress.hide();self.tabs.setEnabled(True);self.refresh()
    def login(self):
        if not self.switch_allowed():return
        try:self.client.connect(self.server.text())
        except Exception as exc:self.status.setText(str(exc));return
        name=self.username.text();password=self.password.text();remember=self.remember.isChecked();self.password.clear()
        def work():
            self.client.login(name,password,remember);return {'snapshot':self.client.pull(),'config':self.client.config()}
        self.run(work,self.apply_login)
    def apply_login(self,data):
        self.host.account_apply(data['snapshot']['payload'])
        if hasattr(self.host,'account_apply_labels'):self.host.account_apply_labels(data['config']['payload'].get('menu_labels',{}))
        for key,field in self.label_fields.items():field.setText(data['config']['payload'].get('menu_labels',{}).get(key,''))
        self.tabs.setCurrentIndex(1)
    def register(self):
        if not self.switch_allowed():return
        try:self.client.connect(self.server.text())
        except Exception as exc:self.status.setText(str(exc));return
        name=self.username.text();password=self.password.text();display=self.display.text();consent=self.consent.isChecked();self.password.clear();self.run(lambda:self.client.register(name,password,display,consent),lambda _:self.status.setText('계정이 생성되었습니다. 로그인하세요.'))
    def logout(self):
        if not self.switch_allowed():return
        def work():
            try:self.client.logout();return ''
            except Exception as exc:return str(exc)+' 로컬 자동 로그인은 해제했습니다. 서버 세션은 연결 복구 후 별도로 해제하거나 만료까지 유지될 수 있습니다.'
        def done(warning):
            if hasattr(self.host,'account_signed_out'):self.host.account_signed_out()
            self.tabs.setCurrentIndex(0)
            if warning:self.status.setText(warning)
        self.run(work,done)
    def pull(self):
        if self.switch_allowed():self.run(self.client.pull,lambda data:self.host.account_apply(data['payload']))
    def push(self):
        try:payload=self.host.account_snapshot()
        except Exception as exc:self.status.setText(str(exc));return
        self.run(lambda:self.client.push(payload))
    def import_local(self):
        if not self.switch_allowed():return
        try:
            if not hasattr(self.host,'account_import_local'):raise ValueError('기존 목록 가져오기를 사용할 수 없습니다.')
            self.host.account_import_local();self.refresh();self.status.setText('이 PC의 기존 목록을 현재 계정에 가져왔습니다. 이미지는 전송하지 않습니다.')
        except Exception as exc:self.status.setText(str(exc))
    def set_device(self):
        value=self.device_name.text().strip()
        if not value:self.status.setText('이 기기의 표시 이름을 입력하세요.');return
        try:
            if not hasattr(self.host,'account_set_device'):raise ValueError('기기 이름을 저장할 수 없습니다.')
            self.host.account_set_device(value);self.status.setText('기기 이름을 저장했습니다. 다음 다운로드 이력부터 적용됩니다.')
        except Exception as exc:self.status.setText(str(exc))
    def users(self):
        search=self.search.text();self.run(lambda:self.client.users(search),self.render_users)
    def render_users(self,data):
        from datetime import datetime
        self.rows=data['users'];self.table.setRowCount(len(self.rows))
        for row,user in enumerate(self.rows):
            values=[user['display_name']+' ('+user['username']+')',str(user['works']),str(user['download_records']),datetime.fromtimestamp(user['last_seen']).strftime('%Y-%m-%d %H:%M')]
            for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(value))
    def selected(self):
        row=self.table.currentRow();return self.rows[row] if row>=0 and row<len(getattr(self,'rows',[])) else None
    def inspect(self):
        user=self.selected()
        if user:self.run(lambda:self.client.inspect_user(user['id']),self.render_inspect)
    def render_inspect(self,data):self.inspected=data;self.render_works()
    def render_works(self,*_):
        if not self.inspected:return
        payload=self.inspected.get('payload',{});works={};history=payload.get('history',[]);reading=payload.get('reading',{})
        def key(work):return urlsplit(work.get('url','')).path or work.get('title','')
        for work in payload.get('works',[]):
            if isinstance(work,dict):works[key(work)]=dict(work=work,count=0,episodes=0,last='')
        for entry in history if isinstance(history,list) else []:
            work=entry.get('work',{})
            if not isinstance(work,dict):continue
            item=works.setdefault(key(work),dict(work=work,count=0,episodes=0,last=''));item['count']+=1;item['episodes']+=int(entry.get('episodes',0) or 0);item['last']=max(item['last'],str(entry.get('when',entry.get('downloaded',''))))
        rows=list(works.values());query=self.work_search.text().strip().casefold();rows=[row for row in rows if query in ' '.join(str(row['work'].get(field,'')) for field in ('title','genre','publisher')).casefold()]
        index=self.work_sort.currentIndex();rows.sort(key=(lambda row:(row['count'],row['last'])) if index==0 else (lambda row:row['last']) if index==1 else (lambda row:row['work'].get('title','')),reverse=index<2)
        self.work_rows=rows;self.work_table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            work=item['work'];position=reading.get(key(work),reading.get(work.get('url',''),{})) if isinstance(reading,dict) else {};chapter=position.get('episode',position.get('chapter','')) if isinstance(position,dict) else position
            values=[work.get('title',''),work.get('genre',''),work.get('publisher',''),chapter or '—',item['count'],item['episodes'],item['last'][:16].replace('T',' ') or '—']
            for c,value in enumerate(values):self.work_table.setItem(r,c,QTableWidgetItem(str(value)))
        user=self.inspected['user'];self.summary.setText(f"{user['display_name']} · 작품 {len(works)}개 · 다운로드 기록 {len(history)}건 · 표시 {len(rows)}개")
    def selected_works(self):return [self.work_rows[index.row()]['work'] for index in self.work_table.selectionModel().selectedRows()]
    def import_works(self):
        works=self.selected_works()
        if works and hasattr(self.host,'account_import_works'):
            try:self.host.account_import_works(works);self.status.setText(f'{len(works)}개 작품을 내 목록에 가져왔습니다.')
            except Exception as exc:self.status.setText(str(exc))
        else:self.status.setText('가져올 작품을 선택하세요.')
    def download_works(self):
        works=self.selected_works()
        if not works:self.status.setText('다운로드할 작품을 선택하세요.');return
        try:
            from collections_store import as_work
            self.host.enqueue_works([as_work(work) for work in works]);self.status.setText(f'{len(works)}개 작품을 다운로드 목록에 추가했습니다.')
        except Exception as exc:self.status.setText(str(exc))
    def delete(self):
        user=self.selected()
        if user and QMessageBox.question(self,'계정 삭제',user['display_name']+' 계정과 서버 목록·이력을 영구 삭제할까요?')==QMessageBox.Yes:
            search=self.search.text()
            def work():self.client.delete_user(user['id']);return self.client.users(search)
            self.run(work,self.render_users)
    def save_labels(self):
        labels={key:field.text().strip() for key,field in self.label_fields.items() if field.text().strip()}
        def work():self.client.config();self.client.set_labels(labels);return labels
        self.run(work,lambda labels:getattr(self.host,'account_apply_labels',lambda _:None)(labels))
    def closeEvent(self,event):
        if self.job and self.job.isRunning():self.status.setText('연결 작업이 끝나면 닫을 수 있습니다.');event.ignore()
        else:super().closeEvent(event)
    def reject(self):
        if self.job and self.job.isRunning():return
        super().reject()
    def accept(self):
        if self.job and self.job.isRunning():return
        super().accept()
