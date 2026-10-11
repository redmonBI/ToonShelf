"""Desktop account coordination: private profiles, asynchronous metadata sync."""
import json,hashlib,copy,uuid,platform
from pathlib import Path
from datetime import datetime,timezone
from PySide6.QtCore import QObject,QTimer
from account_client import AccountClient
from account_ui import AccountTask
from automation_store import AutoStore
from collections_store import CollectionStore,as_work
from queue_store import QueueStore

SYNC_KEYS={'theme','menu_compact','rules_hidden','rules_folded','queue_view','reader_focus','reader_slim','reader_hide_top','reader_hide_bottom','reader_background','reader_width','reader_mode','hidden_genres','catalog_sort','latest_count','notifications_enabled','download_concurrency','network_policy'}
ACCOUNT_SERVER='https://toon-shelf-sync.lovable.app/api/public'

class PendingConflict(ValueError):
    """Unsent local metadata and a newer server revision require an explicit choice."""

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temporary.replace(path)

def portable_work(value):
    if not isinstance(value,dict):
        from dataclasses import asdict
        value=asdict(value)
    return {k:v for k,v in value.items() if k in ('title','url','thumbnail','latest','genre','publisher')}

def sanitize_snapshot(value):
    if isinstance(value,list):return [sanitize_snapshot(v) for v in value]
    if isinstance(value,dict):return {k:sanitize_snapshot(v) for k,v in value.items() if k not in ('cover','path','thumbnail_image','output_dir','policy_file','library_roots','opencomic_exe')}
    return value

class AccountCoordinator(QObject):
    def __init__(self,host,state):
        super().__init__(host);self.host=host;self.state=Path(state);self.client=AccountClient(state,host.cfg.get('account_server',''));host.account_client=self.client
        if not self.client.server and ACCOUNT_SERVER:self.client.connect(ACCOUNT_SERVER)
        self.job=None;self.last_hash='';self.profile_id=None;self.history=[];self.guest=(copy.deepcopy(host.cfg),host.auto_store,host.collection_store,host.queue)
        if self.history_file().exists():
            try:self.history=json.loads(self.history_file().read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
        self.device_file=self.state/'device.json'
        if self.device_file.exists():
            try:self.device=json.loads(self.device_file.read_text(encoding='utf-8'))
            except (OSError,ValueError):self.device={}
        else:self.device={}
        if not self.device:self.device={'id':uuid.uuid4().hex,'label':'이 PC'};self.device_file.write_text(json.dumps(self.device),encoding='utf-8')
        self.timer=QTimer(self);self.timer.timeout.connect(self.sync);self.timer.start(120000)
        self.pending_timer=QTimer(self);self.pending_timer.timeout.connect(self.checkpoint);self.pending_timer.start(5000)
        if self.client.token and not __import__('os').environ.get('TOONSHELF_TESTING'):QTimer.singleShot(1200,self.restore)
    def busy(self):return bool(self.job and self.job.isRunning())
    def run(self,fn,done):
        if self.busy():return False
        self.job=AccountTask(fn,self);self.job.result.connect(done);self.job.error.connect(lambda text:self.host.status.setText('계정 · '+text));self.job.start();return True
    def restore(self):
        if getattr(self.host,'automation_closed',False) or getattr(self.host,'accounts_dialog_open',False):return
        def work():self.client.restore();return dict(snapshot=self.client.pull(),config=self.client.config())
        def done(data):
            try:self.apply(data['snapshot']['payload']);self.host.account_apply_labels(data['config']['payload'].get('menu_labels',{}));self.host.status.setText('자동 로그인 · 계정 목록을 불러왔습니다')
            except Exception as e:self.host.status.setText('계정 · '+str(e))
        self.run(work,done)
    def assert_switchable(self):
        host=self.host
        if host.queue_jobs or (host.job and host.job.isRunning()) or (host.auto_job and host.auto_job.isRunning()) or (host.notification_job and host.notification_job.isRunning()):raise ValueError('진행 중인 다운로드·목록 확인이 끝난 뒤 계정을 변경하세요.')
    def history_file(self):return self.state/'accounts'/self.profile_id/'download_history.json' if self.profile_id else self.state/'guest_download_history.json'
    def pending_file(self,uid=None):return self.state/'accounts'/(uid or self.profile_id)/'pending.json'
    def read_pending(self,uid):
        path=self.pending_file(uid)
        if not path.exists():return None
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('user_id')!=uid or data.get('server')!=self.client.server:raise PendingConflict('미전송 목록의 계정 서버가 다릅니다. 기존 목록을 보존했으므로 원래 서버로 연결하세요.')
        return data
    def stage_pending(self):
        if not self.client.user or self.profile_id!=self.client.user['id'] or self.client.revision is None:return None
        value=self.snapshot();digest=self.hash(value);path=self.pending_file()
        if digest==self.last_hash:
            path.unlink(missing_ok=True);return None
        previous=self.read_pending(self.profile_id)
        staged=dict(user_id=self.profile_id,server=self.client.server,base_revision=previous['base_revision'] if previous else self.client.revision,baseline_hash=previous.get('baseline_hash',self.last_hash) if previous else self.last_hash,payload=value,created=datetime.now(timezone.utc).isoformat())
        atomic_json(path,staged);return staged
    def checkpoint(self):
        if self.busy() or getattr(self.host,'accounts_dialog_open',False):return
        try:self.stage_pending()
        except Exception as exc:self.host.status.setText('계정 변경사항 보관 · '+str(exc))
    def flush_pending(self,staged):
        if not staged:return ''
        if not self.client.user or self.client.user['id']!=staged['user_id'] or self.client.server!=staged['server']:return '기존 계정의 미전송 변경사항을 이 PC에 보관했습니다.'
        try:
            result=self.client.request('PUT','/v1/snapshot',{'revision':staged['base_revision'],'payload':staged['payload']});self.client.revision=result['revision'];self.client.cache({'revision':result['revision'],'payload':staged['payload']});self.last_hash=self.hash(staged['payload'])
            path=self.pending_file(staged['user_id']);current=self.read_pending(staged['user_id'])
            if current and self.hash(current['payload'])==self.last_hash and current['base_revision']==staged['base_revision']:path.unlink(missing_ok=True)
            elif current:
                current['base_revision']=result['revision'];current['baseline_hash']=self.last_hash;atomic_json(path,current)
            return ''
        except Exception as exc:return str(exc)+' 미전송 변경사항을 이 PC에 보관했습니다.'
    def snapshot(self):
        if self.client.user and self.profile_id!=self.client.user['id']:raise ValueError('계정 목록을 먼저 불러오세요.')
        host=self.host
        works={e['key']:portable_work(e['work']) for e in host.collection_store.entries()}
        from urllib.parse import urlsplit
        works.update({e['key']:portable_work(e['work']) for e in host.auto_store.entries()})
        pane=getattr(host,'offline',None)
        if pane and pane.work:works[urlsplit(pane.work['url']).path]=portable_work(pane.work)
        return sanitize_snapshot(dict(preferences={k:v for k,v in host.cfg.items() if k in SYNC_KEYS},lists=host.auto_store.export_data(),favorites=host.collection_store.export_data(),history=self.history,works=list(works.values()),reading=host.cfg.get('reading_positions',{})))
    def apply(self,payload,pending_choice=None):
        self.assert_switchable()
        if not self.client.user:raise ValueError('로그인이 필요합니다.')
        host=self.host;uid=self.client.user['id'];folder=self.state/'accounts'/uid;folder.mkdir(parents=True,exist_ok=True);pending=self.read_pending(uid)
        if pending and self.hash(payload)==self.hash(pending['payload']):self.pending_file(uid).unlink(missing_ok=True);pending=None
        if pending:
            if pending_choice=='server':
                backup=folder/('pending_preserved_'+uuid.uuid4().hex+'.json');atomic_json(backup,pending);self.pending_file(uid).unlink(missing_ok=True);pending=None
            elif pending['base_revision']!=self.client.revision:
                if pending_choice!='local':raise PendingConflict('다른 기기의 변경사항과 이 PC의 미전송 목록이 있습니다. 계정 화면에서 불러오기를 눌러 사용할 목록을 선택하세요.')
                pending['base_revision']=self.client.revision;pending['baseline_hash']=self.hash(payload);atomic_json(self.pending_file(uid),pending)
            if pending:payload=pending['payload']
        switching=self.profile_id!=uid
        if switching:
            if self.profile_id is None:self.guest=(copy.deepcopy(host.cfg),host.auto_store,host.collection_store,host.queue)
            pane=getattr(host,'offline',None)
            if pane:
                pane.back();pane.work=None
            host.queue_running=False;host.batch_ids.clear();host.selected.clear()
            host.auto_store=AutoStore(folder/'automation.sqlite3');host.collection_store=CollectionStore(folder/'collections.sqlite3');host.queue=QueueStore(folder/'queue.sqlite3');self.profile_id=uid;host.queue_metrics.clear()
            for key in SYNC_KEYS:host.cfg.pop(key,None)
            host.cfg['reading_positions']={}
        if payload:
            preferences=payload.get('preferences',{})
            host.cfg.update({k:v for k,v in preferences.items() if k in SYNC_KEYS})
        host.auto_store.import_data(payload.get('lists',{}));host.collection_store.import_data(payload.get('favorites',{}));host.cfg['reading_positions']=payload.get('reading',{})
        self.history=list(payload.get('history',[]));self.history_file().write_text(json.dumps(self.history,ensure_ascii=False),encoding='utf-8')
        host.apply_theme(host.cfg.get('theme','white'),persist=False);host.set_menu_compact(host.cfg.get('menu_compact',False),False);host.set_rules_hidden(host.cfg.get('rules_hidden',False),False)
        if hasattr(host,'set_rules_fold'):host.set_rules_fold(host.cfg.get('rules_folded',False),False);host.queue_view.setCurrentIndex(host.cfg.get('queue_view',0))
        host.latest.blockSignals(True);host.latest.setCurrentIndex(max(0,host.latest.findData(host.cfg.get('latest_count',0))));host.latest.blockSignals(False)
        host.start.setEnabled(not host.latest.currentData());host.end.setEnabled(not host.latest.currentData());host.apply_view_preferences();host.persist_settings();host.refresh_notifications()
        host.account_button.setText(self.client.user['display_name']+' · 계정');self.last_hash=pending.get('baseline_hash','') if pending else self.hash(self.snapshot())
    @staticmethod
    def hash(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    def sync(self):
        from PySide6.QtWidgets import QApplication
        if any(w.__class__.__name__=='UpdatesDialog' and w.isVisible() for w in QApplication.topLevelWidgets()):return
        if getattr(self.host,'accounts_dialog_open',False) or not self.client.user or self.profile_id!=self.client.user['id'] or self.client.revision is None or self.busy():return
        staged=self.stage_pending()
        def work():
            warning=self.flush_pending(staged)
            if warning:raise ValueError(warning)
            return self.client.config()
        def done(config):self.host.account_apply_labels(config['payload'].get('menu_labels',{}))
        self.run(work,done)
    def record_download(self,row,result,status):
        from urllib.parse import urlsplit
        from library import safe_name
        record=dict(id=uuid.uuid4().hex,work=portable_work(row['work']),when=datetime.now(timezone.utc).isoformat(),device_id=self.device['id'],device=self.device['label'],folder=safe_name(row['work']['title']),status=status,episodes=result.get('episodes',0),latest_count=row['cfg'].get('latest_count',0),last_episode=result.get('latest_episode',row.get('progress',{}).get('current',{}).get('episode','')),saved_images=result.get('saved',0),downloaded_bytes=int(self.host.queue_metrics.get(row['id']).bytes) if self.host.queue_metrics.get(row['id']) else 0)
        self.history.append(record);self.history=self.history[-5000:];path=self.history_file();path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(self.history,ensure_ascii=False),encoding='utf-8')
        self.stage_pending();QTimer.singleShot(1000,self.sync)
    def signed_out(self):
        self.assert_switchable();host=self.host;self.profile_id=None;self.last_hash='';self.history=[]
        cfg,automatic,collection,queue=self.guest
        host.auto_store=automatic;host.collection_store=collection;host.queue=queue;host.cfg=copy.deepcopy(cfg);host.queue_running=False;host.batch_ids.clear();host.queue_metrics.clear();host.selected.clear();host.apply_theme(host.cfg.get('theme','white'),False);host.set_menu_compact(host.cfg.get('menu_compact',False),False);host.set_rules_hidden(host.cfg.get('rules_hidden',False),False);host.persist_settings();host.account_button.setText('계정 · 로그인');host.refresh_notifications()
        host.latest.blockSignals(True);host.latest.setCurrentIndex(max(0,host.latest.findData(host.cfg.get('latest_count',0))));host.latest.blockSignals(False)
        host.start.setEnabled(not host.latest.currentData());host.end.setEnabled(not host.latest.currentData());host.apply_view_preferences()
        if hasattr(host,'set_rules_fold'):host.set_rules_fold(host.cfg.get('rules_folded',False),False);host.queue_view.setCurrentIndex(host.cfg.get('queue_view',0))
        pane=getattr(host,'offline',None)
        if pane:pane.back();pane.work=None
        if self.history_file().exists():
            try:self.history=json.loads(self.history_file().read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
    def import_local(self):
        self.assert_switchable()
        if not self.client.user or not self.profile_id:raise ValueError('로그인 후 사용할 수 있습니다.')
        cfg,automatic,collection,_=self.guest
        self.host.auto_store.import_data(automatic.export_data());self.host.collection_store.import_data(collection.export_data())
        self.host.cfg.update({k:v for k,v in cfg.items() if k in SYNC_KEYS});self.host.cfg['reading_positions']=copy.deepcopy(cfg.get('reading_positions',{}))
        guest_file=self.state/'guest_download_history.json'
        if guest_file.exists():
            known={r['id'] for r in self.history}
            self.history.extend(r for r in json.loads(guest_file.read_text(encoding='utf-8')) if r['id'] not in known)
        # This is a deliberate import, not a remote pull. Do not replace it with an old pending snapshot.
        payload=self.snapshot();path=self.pending_file();path.unlink(missing_ok=True);self.apply(payload);self.last_hash='';self.stage_pending();QTimer.singleShot(1000,self.sync)
    def set_device(self,label):
        label=str(label).strip()[:80]
        if not label:raise ValueError('이 PC의 표시 이름을 입력하세요.')
        self.device['label']=label;self.device_file.write_text(json.dumps(self.device,ensure_ascii=False),encoding='utf-8')
    def stop(self):
        self.timer.stop();self.pending_timer.stop()
        # Local persistence only: closing never starts a blocking network operation.
        try:self.stage_pending()
        except Exception as exc:
            self.host.status.setText('계정 변경사항 보관 실패 · '+str(exc))
            if hasattr(self.host,'logs'):self.host.logs.appendPlainText('미전송 계정 목록 보관 실패: '+str(exc))
