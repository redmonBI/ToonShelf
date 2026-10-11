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

if __name__=='__main__':unittest.main()
