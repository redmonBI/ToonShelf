import hashlib
import json
import tempfile
import threading
from contextlib import closing
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from account_server.server import Service,APIError,Handler,AuthThrottle
from account_client import AccountClient,AccountError,endpoint

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.service=Service(self.root/'accounts.db','operator_test','test-only-operator-password')
        self.service.request('POST','/v1/register',{'username':'reader_one','password':'reader-password-one','display_name':'Reader','admin_visibility_consent':True})
        self.service.request('POST','/v1/register',{'username':'reader_two','password':'reader-password-two','admin_visibility_consent':True})
        self.first=self.login('reader_one','reader-password-one');self.second=self.login('reader_two','reader-password-two');self.master=self.login('operator_test','test-only-operator-password')
    def tearDown(self):self.temp.cleanup()
    def login(self,name,password):return self.service.request('POST','/v1/login',{'username':name,'password':password})['token']
    def test_hashes_and_sessions_not_plaintext(self):
        with closing(self.service.db()) as db:
            user=db.execute('SELECT * FROM users WHERE username=?',('reader_one',)).fetchone();self.assertEqual(len(user['salt']),32);self.assertEqual(len(user['password_hash']),64);self.assertNotEqual(user['password_hash'],'reader-password-one')
            self.assertIsNone(db.execute('SELECT * FROM sessions WHERE hash=?',(self.first,)).fetchone());self.assertIsNotNone(db.execute('SELECT * FROM sessions WHERE hash=?',(hashlib.sha256(self.first.encode()).hexdigest(),)).fetchone())
    def test_consent_and_registration_validation(self):
        for data in [dict(username='sample',password='sample-long-password'),dict(username='sample',password='x',admin_visibility_consent=True),dict(username='../sample',password='sample-password',admin_visibility_consent=True)]:
            with self.assertRaises(APIError):self.service.request('POST','/v1/register',data)
    def test_master_short_secret_provisioning(self):
        service=Service(self.root/'short.db','short_master','1234');self.assertEqual(service.request('POST','/v1/login',{'username':'short_master','password':'1234'})['user']['role'],'master')
    def test_auth_isolation_and_revision_conflict(self):
        self.service.request('PUT','/v1/snapshot',{'revision':0,'payload':{'favorites':['work-a']}},self.first)
        self.assertEqual(self.service.request('GET','/v1/snapshot',token=self.second)['payload'],{})
        with self.assertRaises(APIError) as error:self.service.request('PUT','/v1/snapshot',{'revision':0,'payload':{'favorites':['stale']}},self.first)
        self.assertEqual(error.exception.status,409);self.assertEqual(self.service.request('GET','/v1/snapshot',token=self.first)['payload']['favorites'],['work-a'])
    def test_server_admin_role_enforced(self):
        uid=self.service.request('GET','/v1/me',token=self.second)['user']['id']
        for method,path,data in [('GET','/v1/admin/users',{}),('GET','/v1/admin/users/'+uid,{}),('DELETE','/v1/admin/users/'+uid,{}),('PUT','/v1/config',{'revision':0,'menu_labels':{'library':'Shelf'}})]:
            with self.assertRaises(APIError) as error:self.service.request(method,path,data,self.first)
            self.assertEqual(error.exception.status,403)
    def test_admin_search_inspect_delete_revokes(self):
        self.service.request('PUT','/v1/snapshot',{'revision':0,'payload':{'works':[{'title':'Moon'}],'history':[{'device':'Tablet','folder':'Moon/1화','episode':1,'downloaded':'2026-10-11'}]}},self.second)
        users=self.service.request('GET','/v1/admin/users?q=Moon',token=self.master)['users'];self.assertEqual(len(users),1);self.assertEqual(users[0]['download_records'],1);uid=users[0]['id']
        self.assertEqual(self.service.request('GET','/v1/admin/users/'+uid,token=self.master)['payload']['works'][0]['title'],'Moon')
        self.service.request('DELETE','/v1/admin/users/'+uid,token=self.master)
        with self.assertRaises(APIError):self.service.request('GET','/v1/me',token=self.second)
        own=self.service.request('GET','/v1/me',token=self.master)['user']['id']
        with self.assertRaises(APIError):self.service.request('DELETE','/v1/admin/users/'+own,token=self.master)
    def test_logout_and_expiration(self):
        self.service.request('POST','/v1/logout',token=self.first)
        with self.assertRaises(APIError):self.service.request('GET','/v1/me',token=self.first)
        with closing(self.service.db()) as db:db.execute('UPDATE sessions SET expires=0 WHERE hash=?',(hashlib.sha256(self.second.encode()).hexdigest(),));db.commit()
        with self.assertRaises(APIError):self.service.request('GET','/v1/me',token=self.second)
    def test_global_labels_revision_and_member_read(self):
        self.service.request('PUT','/v1/config',{'revision':0,'menu_labels':{'library':'My Shelf'}},self.master)
        self.assertEqual(self.service.request('GET','/v1/config',token=self.first)['payload']['menu_labels']['library'],'My Shelf')
        with self.assertRaises(APIError) as error:self.service.request('PUT','/v1/config',{'revision':0,'menu_labels':{'library':'Stale'}},self.master)
        self.assertEqual(error.exception.status,409)
    def test_sensitive_fields_and_full_path_rejected(self):
        for payload in [{'history':[{'local_path':'private'}]},{'preferences':{'cookie':'secret'}},{'history':[{'folder':'C:\\private\\work'}]},{'images':[]}]:
            with self.assertRaises(APIError):self.service.request('PUT','/v1/snapshot',{'revision':0,'payload':payload},self.first)
    def test_preexisting_user_not_promoted(self):
        with self.assertRaises(RuntimeError):self.service.provision_master('reader_one','another-secret')
    def test_http_client_and_switch_isolation(self):
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.service=self.service;thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            client=AccountClient(self.root/'client',f'http://127.0.0.1:{http.server_port}')
            client.login('reader_one','reader-password-one');client.pull();client.push({'favorites':['private-one']});first_id=client.user['id']
            client.login('reader_two','reader-password-two');self.assertIsNone(client.revision)
            with self.assertRaises(AccountError):client.push({'favorites':['wrong-account']})
            self.assertEqual(client.pull()['payload'],{});self.assertTrue((self.root/'client'/'accounts'/first_id/'snapshot.json').exists())
            token=client.token;client.logout();self.assertEqual(client.token,'')
            with self.assertRaises(APIError):self.service.request('GET','/v1/me',token=token)
        finally:http.shutdown();http.server_close();thread.join()
    def test_https_requirement(self):
        self.assertEqual(endpoint('https://example.com/api/'),'https://example.com/api');self.assertTrue(endpoint('http://localhost:8080'))
        for url in ['http://example.com','https://user:password@example.com','javascript:abc','https://example.com?token=x']:
            with self.assertRaises(ValueError):endpoint(url)
    def test_login_rate_limit(self):
        throttle=AuthThrottle()
        for _ in range(10):throttle.check('test-client')
        with self.assertRaises(APIError) as error:throttle.check('test-client')
        self.assertEqual(error.exception.status,429);throttle.check('different-client')
    @unittest.skipUnless(__import__('os').name=='nt','Windows DPAPI')
    def test_dpapi_roundtrip(self):
        from account_client import protect
        raw=b'test-only-session-token';encrypted=protect(raw);self.assertNotEqual(raw,encrypted);self.assertEqual(protect(encrypted,True),raw)
    def test_account_dialog_worker_does_not_freeze(self):
        import os,time
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QWidget
        from PySide6.QtCore import QTimer
        from account_ui import AccountDialog
        app=QApplication.instance() or QApplication([]);host=QWidget();host.account_client=AccountClient(self.root/'dialog');dialog=AccountDialog(host)
        ticks=[];results=[];timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        dialog.run(lambda:(time.sleep(.25),{'ok':True})[1],results.append)
        deadline=time.monotonic()+3
        while dialog.job.isRunning() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
        dialog.job.wait();app.processEvents();timer.stop();self.assertEqual(results,[{'ok':True}]);self.assertGreater(len(ticks),10);dialog.close();host.close();app.processEvents()
    def test_dialog_switch_guard_and_readable_master_works(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QWidget
        from account_ui import AccountDialog
        app=QApplication.instance() or QApplication([]);host=QWidget();host.account_client=AccountClient(self.root/'guard');host.account_can_switch=lambda:False;dialog=AccountDialog(host)
        self.assertTrue(host.accounts_dialog_open);dialog.login();dialog.logout();dialog.pull();self.assertIsNone(dialog.job)
        imports=[];devices=[];host.account_import_local=lambda:imports.append(True);host.account_set_device=devices.append;dialog.import_local();self.assertEqual(imports,[]);host.account_can_switch=lambda:True;dialog.import_local();self.assertEqual(imports,[True]);dialog.device_name.setText('Travel laptop');dialog.set_device();self.assertEqual(devices,['Travel laptop']);dialog.device_name.clear();dialog.set_device();self.assertEqual(len(devices),1)
        dialog.on_result({},lambda _:(_ for _ in ()).throw(ValueError('apply failed')));self.assertEqual(dialog.status.text(),'apply failed')
        dialog.render_inspect({'user':{'display_name':'Friend'},'payload':{'works':[{'title':'Moon','url':'https://example.com/work/1','genre':'Fantasy','publisher':'Example'}],'history':[{'work':{'title':'Moon','url':'https://example.com/work/1'},'episodes':3,'when':'2026-10-11T10:00:00Z'}],'reading':{'/work/1':{'episode':'3화'}}}})
        self.assertEqual(dialog.work_table.item(0,0).text(),'Moon');self.assertEqual(dialog.work_table.item(0,3).text(),'3화');self.assertEqual(dialog.work_table.item(0,4).text(),'1');self.assertEqual(len(dialog.label_fields),10)
        dialog.work_search.setText('absent');self.assertEqual(dialog.work_table.rowCount(),0);dialog.accept();self.assertFalse(host.accounts_dialog_open);host.close();app.processEvents()
    def test_personal_history_korean_time_search_and_pages(self):
        import os
        from types import SimpleNamespace
        from datetime import datetime,timezone,timedelta
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QWidget
        from account_ui import AccountDialog
        app=QApplication.instance() or QApplication([]);host=QWidget();host.account_client=AccountClient(self.root/'history');base=datetime(2026,10,11,tzinfo=timezone.utc)
        records=[dict(work={'title':f'Work {index}'},when=(base+timedelta(minutes=index)).isoformat(),device='Travel laptop' if index==204 else 'Home PC',folder=f'Work {index}',last_episode='12화',status='complete',downloaded_bytes=2*1024**2,saved_images=24) for index in range(205)]
        host.accounts_service=SimpleNamespace(history=records,device={'label':'Home PC'});dialog=AccountDialog(host)
        self.assertEqual(dialog.history_table.rowCount(),100);self.assertEqual(dialog.history_page.count(),3);self.assertEqual(dialog.history_table.item(0,0).text(),'Work 204');self.assertEqual(dialog.history_table.item(0,1).text(),'2026-10-11 12:24');self.assertEqual(dialog.history_table.item(0,5).text(),'완료');self.assertEqual(dialog.history_table.item(0,6).text(),'2.0 MB')
        dialog.history_page.setCurrentIndex(2);self.assertEqual(dialog.history_table.rowCount(),5);self.assertFalse(dialog.history_next.isEnabled());dialog.history_search.setText('travel');self.assertEqual(dialog.history_table.rowCount(),1);self.assertEqual(dialog.history_page.count(),1);self.assertEqual(dialog.history_table.item(0,0).text(),'Work 204')
        host.accounts_service.history=[];dialog.refresh();self.assertEqual(dialog.history_table.rowCount(),0);dialog.accept();host.close();app.processEvents()

class PendingProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ['TOONSHELF_TESTING']='1';os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.qt=QApplication.instance() or QApplication([])
    def setUp(self):
        from PySide6.QtWidgets import QWidget,QLabel,QPushButton,QComboBox,QPlainTextEdit
        from automation_store import AutoStore
        from collections_store import CollectionStore
        from queue_store import QueueStore
        from app_services import AccountCoordinator
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.host=QWidget();h=self.host;h.cfg={'theme':'white'};h.auto_store=AutoStore(self.root/'guest_auto.db');h.collection_store=CollectionStore(self.root/'guest_collection.db');h.queue=QueueStore(self.root/'guest_queue.db');h.queue_jobs={};h.job=h.auto_job=h.notification_job=None;h.batch_ids=set();h.selected=set();h.queue_metrics={};h.latest=QComboBox();h.latest.addItem('All',0);h.start=QPushButton();h.end=QPushButton();h.account_button=QPushButton();h.status=QLabel();h.logs=QPlainTextEdit()
        h.apply_theme=lambda *a,**k:None;h.set_menu_compact=lambda *a:None;h.set_rules_hidden=lambda *a:None;h.apply_view_preferences=lambda:None;h.persist_settings=lambda:None;h.refresh_notifications=lambda:None;h.account_apply_labels=lambda _:None
        self.service=AccountCoordinator(h,self.root);self.service.timer.stop();self.service.pending_timer.stop();self.service.client.user={'id':'pending-test-user','display_name':'Test'};self.service.client.revision=0;self.service.apply({'preferences':{'theme':'white'}})
    def tearDown(self):
        self.service.stop();self.host.close();self.qt.processEvents();self.temp.cleanup()
    def dirty(self):self.host.cfg['theme']='dark';return self.service.stage_pending()
    def test_close_checkpoint_and_same_revision_recovery(self):
        self.host.cfg['theme']='dark';self.service.stop();self.assertTrue(self.service.pending_file().exists());self.service.client.clear_session();self.service.signed_out();self.service.client.user={'id':'pending-test-user','display_name':'Test'};self.service.client.revision=0;self.service.apply({'preferences':{'theme':'white'}});self.assertEqual(self.host.cfg['theme'],'dark');self.assertTrue(self.service.pending_file().exists());self.assertNotEqual(self.service.hash(self.service.snapshot()),self.service.last_hash)
    def test_newer_server_preserves_pending_until_explicit_choice(self):
        from app_services import PendingConflict
        staged=self.dirty();self.service.client.revision=1
        with self.assertRaises(PendingConflict):self.service.apply({'preferences':{'theme':'gray'}})
        self.assertEqual(self.host.cfg['theme'],'dark');self.assertEqual(self.service.read_pending('pending-test-user')['base_revision'],0)
        self.service.apply({'preferences':{'theme':'gray'}},pending_choice='server');self.assertEqual(self.host.cfg['theme'],'gray');self.assertFalse(self.service.pending_file().exists());backup=list(self.service.pending_file().parent.glob('pending_preserved_*.json'));self.assertEqual(len(backup),1);self.assertEqual(json.loads(backup[0].read_text(encoding='utf-8'))['payload'],staged['payload'])
    def test_keep_local_rebases_only_after_explicit_choice(self):
        self.dirty();self.service.client.revision=3;self.service.apply({'preferences':{'theme':'gray'}},pending_choice='local');self.assertEqual(self.host.cfg['theme'],'dark');self.assertEqual(self.service.read_pending('pending-test-user')['base_revision'],3)
    def test_logout_flush_uses_original_revision_and_retains_failed_payload(self):
        from unittest.mock import patch
        staged=self.dirty();self.service.client.revision=7
        with patch.object(self.service.client,'request',side_effect=AccountError('conflict',409)) as request:
            warning=self.service.flush_pending(staged);self.assertTrue(warning);self.assertEqual(request.call_args.args[2]['revision'],0);self.assertTrue(self.service.pending_file().exists())
        self.service.client.revision=0
        with patch.object(self.service.client,'request',return_value={'revision':1}):self.assertEqual(self.service.flush_pending(staged),'')
        self.assertFalse(self.service.pending_file().exists());self.assertEqual(self.service.last_hash,self.service.hash(staged['payload']))
    def test_remote_already_has_uploaded_payload_acks_interrupted_upload(self):
        staged=self.dirty();self.service.client.revision=1;self.service.apply(staged['payload']);self.assertFalse(self.service.pending_file().exists());self.assertEqual(self.host.cfg['theme'],'dark')
    def test_stop_persistence_error_does_not_break_close(self):
        from unittest.mock import patch
        with patch.object(self.service,'stage_pending',side_effect=OSError('unwritable')):self.service.stop()
        self.assertIn('unwritable',self.host.status.text())

class RememberedSessionTests(unittest.TestCase):
    def test_expired_session_reauthenticates_once_and_keeps_revision(self):
        from account_client import AccountClient,AccountError
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder,patch('account_client.protect',side_effect=lambda raw,decrypt=False:raw):
            client=AccountClient(folder,'https://example.com');user={'id':'a'}
            with patch.object(client,'request',return_value={'token':'old','user':user}):client.login('reader','secret',True)
            client.revision=7
            with patch.object(client,'request',side_effect=[AccountError('expired',401),{'token':'new','user':user}]) as request:
                client.restore();self.assertEqual(request.call_count,2);self.assertEqual(client.token,'new');self.assertEqual(client.revision,7)
            restored=AccountClient(folder,'https://example.com');self.assertEqual(restored.token,'new');self.assertEqual(restored.remembered['username'],'reader');restored.clear_session();self.assertFalse(restored.token_path.exists())
    def test_network_failure_preserves_remembered_session(self):
        from account_client import AccountClient,AccountError
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder,patch('account_client.protect',side_effect=lambda raw,decrypt=False:raw):
            client=AccountClient(folder,'https://example.com')
            with patch.object(client,'request',return_value={'token':'old','user':{'id':'a'}}):client.login('reader','secret',True)
            with patch.object(client,'request',side_effect=AccountError('offline')):
                with self.assertRaises(AccountError):client.restore()
            self.assertTrue(client.token_path.exists());self.assertEqual(client.token,'old')

if __name__=='__main__':unittest.main()
