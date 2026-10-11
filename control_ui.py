import json
import webbrowser
from datetime import datetime,timezone,timedelta
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QTimer,QDateTime
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,
 QAbstractItemView,QComboBox,QSpinBox,QCheckBox,QFormLayout,QDateTimeEdit,QMessageBox,QLineEdit,QPlainTextEdit,QProgressBar)
from sharing import REPOSITORY,VERSION,community,releases,issue_link,prepare_update,version_tuple

def button(text,fn):
    b=QPushButton(text);b.clicked.connect(fn);return b
class Task(QThread):
    done=Signal(bool,object)
    def __init__(self,fn):super().__init__();self.fn=fn
    def run(self):
        try:self.done.emit(True,self.fn())
        except Exception as e:self.done.emit(False,str(e))

class TaskDialog(QDialog):
    def __init__(self,parent):super().__init__(parent);self.tasks=[]
    def task(self,fn,callback):
        job=Task(fn);self.tasks.append(job);job.done.connect(callback)
        job.finished.connect(lambda:self.tasks.remove(job));job.start()
    def closeEvent(self,e):
        if any(t.isRunning() for t in self.tasks):
            QMessageBox.information(self,'처리 중','현재 요청이 끝난 뒤 닫아주세요.');e.ignore()
        else:e.accept()

class QueueDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent);self.owner=parent;self.setWindowTitle('작품별 다운로드 대기열');self.resize(1120,660)
        lay=QVBoxLayout(self);lay.addWidget(QLabel('DOWNLOAD QUEUE  /  진행을 기억하는 작품 대기열'))
        lay.addWidget(QLabel('중단·보류·취소는 파일을 삭제하지 않습니다. 우선 작업은 현재 작품 다음에 시작합니다.'))
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['작품','상태','우선순위','회차 / 이미지','시도','저장 위치','최근 기록'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table)
        row=QHBoxLayout()
        for text,action in [('재개','pending'),('중단','stopped'),('보류','held'),('취소','cancelled'),('우선','priority')]:
            row.addWidget(button(text,lambda checked=False,a=action:self.change(a)))
        row.addWidget(button('전체 대기열 실행',parent.run_queue));row.addWidget(button('전체 일시정지 / 계속',parent.pause));lay.addLayout(row)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(150);lay.addWidget(self.detail)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(1500);self.finished.connect(lambda:self.timer.stop());self.refresh()
    def selected(self):
        indexes={i.row() for i in self.table.selectedIndexes()}
        return [self.rows[i]['id'] for i in indexes if i<len(self.rows)]
    def refresh(self):
        selected=set(self.selected()) if hasattr(self,'rows') else set()
        self.rows=self.owner.queue.rows();self.table.setRowCount(len(self.rows))
        names={'pending':'대기','running':'진행','paused':'일시정지','held':'보류','stopped':'중단','cancelled':'취소','complete':'완료','partial':'일부 실패','failed':'실패'}
        for n,r in enumerate(self.rows):
            p=r['progress'];current=p.get('current',{});img=p.get('image_progress',{})
            values=[r['work']['title'],names[r['status']],str(r['priority']),f"{current.get('episode','—')} · {img.get('index',0)}/{img.get('total',0)}",str(r['attempts']),r['cfg']['output_dir'],r['updated']]
            for col,val in enumerate(values):self.table.setItem(n,col,QTableWidgetItem(val))
            if r['id'] in selected:
                for col in range(self.table.columnCount()):self.table.item(n,col).setSelected(True)
        self.table.resizeColumnsToContents()
    def change(self,action):
        for id in self.selected():self.owner.change_queue(id,action)
        self.refresh()
    def show_detail(self):
        ids=self.selected()
        r=next((r for r in self.rows if r['id'] in ids),None)
        if r:self.detail.setPlainText(r['error'] or json.dumps(r['result'] or r['progress'],ensure_ascii=False,indent=2))

class PowerDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent);self.owner=parent;self.setWindowTitle('완료 후 동작 · 종료 예약');self.resize(540,430)
        lay=QFormLayout(self)
        self.action=QComboBox();self.action.addItems(['프로그램 종료','PC 종료','PC 강제 종료'])
        self.trigger=QComboBox();self.trigger.addItems(['대기열 완료 후','지정 시각에','타이머'])
        self.minutes=QSpinBox();self.minutes.setRange(1,10080);self.minutes.setValue(60);self.minutes.setSuffix(' 분')
        self.at=QDateTimeEdit(QDateTime.currentDateTimeUtc().addSecs(9*3600+3600));self.at.setDisplayFormat('yyyy-MM-dd HH:mm');self.at.setCalendarPopup(True)
        self.retry=QCheckBox('실패 작품은 한 번 더 시도한 뒤 완료 처리');self.retry.setChecked(parent.cfg.get('retry_once',False))
        for title,w in [('종료 동작',self.action),('실행 조건',self.trigger),('타이머',self.minutes),('종료 시각 · 한국 시간',self.at),('',self.retry)]:lay.addRow(title,w)
        note=QLabel('PC 종료는 60초 예고 후 실행되며 취소할 수 있습니다.\n강제 종료는 다른 앱의 저장되지 않은 작업도 종료합니다.\n보류·일시정지·중단 작품이 있으면 완료 후 종료하지 않습니다.\n타이머·지정 시각은 다운로드 중에도 작동합니다.');note.setWordWrap(True);lay.addRow(note)
        lay.addRow(button('설정 적용 · 예약 켜기',self.arm));lay.addRow(button('예약 취소',self.cancel))
        self.info=QLabel(parent.power_description());self.info.setWordWrap(True);lay.addRow(self.info)
    def arm(self):
        try:
            spec={'action':['app','pc','force'][self.action.currentIndex()],'trigger':['complete','at','timer'][self.trigger.currentIndex()],
                'minutes':self.minutes.value(),'timestamp':datetime.strptime(self.at.dateTime().toString('yyyy-MM-dd HH:mm'),'%Y-%m-%d %H:%M').replace(tzinfo=timezone(timedelta(hours=9))).timestamp()}
            self.owner.cfg['retry_once']=self.retry.isChecked();self.owner.persist_settings();self.owner.power.arm(spec)
            self.info.setText(self.owner.power_description())
        except Exception as e:QMessageBox.warning(self,'예약 확인',str(e))
    def cancel(self):
        try:self.owner.power.cancel();self.info.setText('종료 예약을 취소했습니다.')
        except Exception as e:QMessageBox.warning(self,'취소 확인',str(e))

class CommunityDialog(TaskDialog):
    def __init__(self,parent):
        super().__init__(parent);self.owner=parent;self.repo=parent.cfg.get('community_repo',REPOSITORY);self.data={};self.setWindowTitle('친구들과 추천 작품 공유');self.resize(1050,720)
        lay=QVBoxLayout(self);lay.addWidget(QLabel('COMMUNITY  /  친구들이 추천하는 다음 작품'))
        self.info=QLabel('공유 목록을 읽는 중…');self.info.setWordWrap(True);lay.addWidget(self.info)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['추천인','작품명','장르','동감','등록일','수정일']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table)
        self.body=QPlainTextEdit();self.body.setReadOnly(True);lay.addWidget(self.body)
        self.table.itemSelectionChanged.connect(self.detail)
        row=QHBoxLayout()
        for title,fn in [('새로고침',self.refresh),('추천 작성',lambda:self.form()),('동감 / 취소',self.vote),('수정',self.edit),('삭제',self.delete)]:row.addWidget(button(title,fn))
        lay.addLayout(row);lay.addWidget(QLabel('누구나 작성·동감·수정·삭제 가능합니다. GitHub 로그인 후 요청을 등록하면 자동 처리되며, 새로고침하면 반영됩니다.'))
        self.refresh()
    def refresh(self):self.task(lambda:community(self.repo),self.loaded)
    def loaded(self,ok,data):
        if not ok:self.info.setText('공유 목록을 읽지 못했습니다: '+str(data));return
        self.data=data;self.posts=sorted(data.get('posts',[]),key=lambda p:(len(p.get('votes',[])),p['created']),reverse=True)
        self.table.setRowCount(len(self.posts))
        for n,p in enumerate(self.posts):
            for c,v in enumerate([p['author'],p['title'],p['genre'],str(len(p.get('votes',[]))),p['created'],p['updated']]):self.table.setItem(n,c,QTableWidgetItem(v))
        self.table.resizeColumnsToContents();self.info.setText(f'추천 {len(self.posts)}개 · {self.repo} · GitHub 계정마다 동감 1개')
        self.owner.community_cache=data;self.owner.render()
    def selected(self):
        n=self.table.currentRow();return self.posts[n] if hasattr(self,'posts') and 0<=n<len(self.posts) else None
    def detail(self):
        p=self.selected()
        if p:self.body.setPlainText(p['body']+'\n\n'+p.get('link',''))
    def submit(self,payload):
        try:
            link=issue_link(self.repo,payload)
            if len(link)>7000:
                from PySide6.QtWidgets import QApplication
                from urllib.parse import urlencode
                QApplication.clipboard().setText('```json\n'+json.dumps(payload,ensure_ascii=False,indent=2)+'\n```')
                webbrowser.open(f'https://github.com/{self.repo}/issues/new?'+urlencode({'title':'[ToonShelf] '+payload['action']}))
                self.info.setText('긴 추천을 클립보드에 준비했습니다. GitHub 본문에 붙여넣고 Submit new issue를 누르세요.')
            else:
                webbrowser.open(link);self.info.setText('GitHub 작성 화면에서 Submit new issue를 누르면 요청이 등록됩니다. 자동 처리 후 새로고침하세요.')
        except Exception as e:QMessageBox.warning(self,'요청 확인',str(e))
    def form(self,post=None):
        d=QDialog(self);d.setWindowTitle('추천 수정' if post else '작품 추천');lay=QFormLayout(d);fields={}
        for key,title in [('author','추천인 이름'),('title','작품명'),('genre','장르'),('link','작품 링크 · 선택')]:
            fields[key]=QLineEdit((post or {}).get(key,''));lay.addRow(title,fields[key])
        body=QPlainTextEdit((post or {}).get('body',''));lay.addRow('추천 내용',body)
        def send():
            payload={k:w.text() for k,w in fields.items()};payload.update(action='edit' if post else 'recommend',body=body.toPlainText())
            if post:payload['id']=post['id']
            self.submit(payload);d.accept()
        lay.addRow(button('GitHub에 등록 요청',send));d.resize(560,430);d.exec()
    def vote(self):
        p=self.selected()
        if p:self.submit({'action':'vote','id':p['id']})
    def edit(self):
        if self.selected():self.form(self.selected())
    def delete(self):
        p=self.selected()
        if p and QMessageBox.question(self,'추천 삭제','선택한 추천을 삭제 요청할까요?')==QMessageBox.StandardButton.Yes:self.submit({'action':'delete','id':p['id']})

class UpdatesDialog(TaskDialog):
    def __init__(self,parent):
        super().__init__(parent);self.owner=parent;self.setWindowTitle('업데이트 · 버전 기록');self.resize(800,620)
        lay=QVBoxLayout(self);self.info=QLabel('설치 버전 '+VERSION);lay.addWidget(self.info)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['버전','게시일','업데이트 이름']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table)
        self.notes=QPlainTextEdit();self.notes.setReadOnly(True);lay.addWidget(self.notes);self.table.itemSelectionChanged.connect(self.detail)
        self.check_button=button('업데이트 확인',self.refresh);lay.addWidget(self.check_button)
        self.install_button=button('선택 버전 패치 · 프로그램 재시작',self.install);lay.addWidget(self.install_button)
        self.busy=QProgressBar();self.busy.setRange(0,0);self.busy.hide();lay.addWidget(self.busy)
        lay.addWidget(QLabel('현재 폴더에 프로그램 파일만 패치하고 자동 재시작합니다. 설정·대기열·작품은 유지합니다. 실패하면 변경한 파일을 복구합니다.'))
        self.refresh()
    def refresh(self):self.task(lambda:releases(self.owner.cfg.get('community_repo',REPOSITORY)),self.loaded)
    def loaded(self,ok,data):
        if not ok:self.info.setText('확인 실패: '+str(data));return
        self.rows=[r for r in data if not r.get('draft') and not r.get('prerelease')];self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            for c,v in enumerate([r['tag_name'],r.get('published_at',''),r.get('name','')]):self.table.setItem(n,c,QTableWidgetItem(str(v)))
        self.info.setText(f'현재 {VERSION} · 공개 버전 {len(self.rows)}개');self.table.resizeColumnsToContents()
    def detail(self):
        n=self.table.currentRow()
        if hasattr(self,'rows') and 0<=n<len(self.rows):self.notes.setPlainText(self.rows[n].get('body') or '')
    def install(self):
        import sys
        if (getattr(self.owner,'accounts_service',None) and self.owner.accounts_service.busy()) or (getattr(self.owner,'notification_job',None) and self.owner.notification_job.isRunning()):QMessageBox.information(self,'작업 중','계정·새 회차 확인이 끝난 뒤 설치하세요.');return
        if not getattr(sys,'frozen',False):QMessageBox.information(self,'실행 파일 필요','배포된 ToonShelf.exe에서 자체 업데이트를 사용하세요.');return
        if getattr(self.owner,'queue_jobs',{}) or self.owner.queue_job or (self.owner.job and self.owner.job.isRunning()) or (self.owner.auto_job and self.owner.auto_job.isRunning()):QMessageBox.information(self,'작업 중','작업을 중단하고 기록을 저장한 뒤 설치하세요.');return
        n=self.table.currentRow()
        if not hasattr(self,'rows') or not 0<=n<len(self.rows):return
        if version_tuple(self.rows[n]['tag_name'])<=version_tuple(VERSION):
            QMessageBox.information(self,'최신 버전','현재 버전보다 새로운 버전을 선택하세요.');return
        self.info.setText('업데이트 다운로드 및 SHA-256 검사 중…')
        self.install_button.setEnabled(False);self.check_button.setEnabled(False);self.busy.show()
        from patch_update import prepare_patch
        import os
        selected=self.rows[n];target=Path(sys.executable).resolve().parent
        def prepare():
            result=prepare_update(selected,target/'Updates',self.owner.cfg.get('community_repo',REPOSITORY))
            result['manifest']=prepare_patch(result,target,os.getpid());return result
        self.task(prepare,self.installed)
    def installed(self,ok,result):
        self.busy.hide();self.install_button.setEnabled(True);self.check_button.setEnabled(True)
        if not ok:self.info.setText('패치 준비 실패: '+str(result));return
        if (getattr(self.owner,'accounts_service',None) and self.owner.accounts_service.busy()) or (getattr(self.owner,'notification_job',None) and self.owner.notification_job.isRunning()):self.info.setText('계정·새 회차 확인이 끝난 뒤 다시 업데이트하세요.');return
        if getattr(self.owner,'queue_jobs',{}) or self.owner.queue_job or (self.owner.job and self.owner.job.isRunning()) or (self.owner.update_job and self.owner.update_job.isRunning()) or (self.owner.auto_job and self.owner.auto_job.isRunning()):
            self.info.setText('패치 준비 완료 · 진행 중인 작업을 종료하고 다시 업데이트하세요.');return
        self.info.setText('패치 적용 준비 완료 · 프로그램을 재시작합니다…');self.busy.show();self.install_button.setEnabled(False)
        def apply():
            import subprocess
            try:
                if getattr(self.owner,'offline',None) and not self.owner.offline.shutdown():raise RuntimeError('뷰어 작업을 종료한 뒤 다시 시도하세요.')
                self.owner.read_cfg();self.owner.power.cancel()
                self.owner.cover_timer.stop()
                subprocess.Popen([str(Path(result['path'])/'ToonShelf.exe'),'--apply-update',result['manifest']],
                    cwd=result['path'],creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
                self.accept();self.owner.close()
            except Exception as e:
                self.busy.hide();self.install_button.setEnabled(True);self.info.setText('재시작 준비 실패: '+str(e))
        QTimer.singleShot(150,apply)
