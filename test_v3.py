import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from core import Work
from queue_store import QueueStore
from power import PowerPlan
from community_rules import apply_request
from sharing import prepare_update,version_tuple,issue_link

class V3Tests(unittest.TestCase):
    def test_queue_restore_and_priority_and_deduplication(self):
        with tempfile.TemporaryDirectory() as t:
            q=QueueStore(Path(t)/'queue.db');cfg={'output_dir':t,'start_episode':1,'end_episode':0}
            a,b=q.add([Work('a','https://a/1'),Work('b','https://a/2')],cfg)
            self.assertFalse(q.add([Work('a','https://a/1')],cfg))
            q.change(b,priority=5);self.assertEqual(q.next()['id'],b)
            q.change(b,'paused',progress={'current':{'episode':'24화'},'image_progress':{'index':17,'total':87}})
            restored=QueueStore(q.path);row=next(r for r in restored.rows() if r['id']==b)
            self.assertEqual(row['status'],'stopped');self.assertEqual(row['progress']['image_progress']['index'],17)
            q.change(a,'cancelled');self.assertIsNone(q.next())
    def test_pause_history_is_durable(self):
        with tempfile.TemporaryDirectory() as t:
            q=QueueStore(Path(t)/'q.db');ids=q.add([Work('a','https://a/1')]*2,{'output_dir':t})
            self.assertEqual(len(ids),1);q.change(ids[0],'held');self.assertEqual(q.resumable()[0]['status'],'held')
    def test_power_is_not_armed_on_restart_and_is_cancellable(self):
        with tempfile.TemporaryDirectory() as t:
            clock=[100];calls=[];p=PowerPlan(Path(t)/'power.log',calls.append,lambda:clock[0])
            self.assertFalse(p.due(True));p.arm({'action':'pc','trigger':'timer','minutes':2})
            clock[0]=219;self.assertFalse(p.due());clock[0]=220;self.assertTrue(p.due())
            p.execute();self.assertFalse(calls);clock[0]=279;self.assertFalse(p.fire_due())
            p.cancel();clock[0]=300;self.assertFalse(p.fire_due());self.assertFalse(calls)
            self.assertFalse(PowerPlan(p.history,calls.append,lambda:clock[0]).armed)
    def test_normal_shutdown_does_not_imply_force(self):
        with tempfile.TemporaryDirectory() as t:
            clock=[100];calls=[];p=PowerPlan(Path(t)/'p.log',calls.append,lambda:clock[0])
            for action in ['pc','force']:
                p.arm({'action':action,'trigger':'complete'});self.assertTrue(p.due(True));p.execute();clock[0]+=60;p.fire_due()
            self.assertEqual(calls[0],['shutdown.exe','/s','/t','0']);self.assertIn('/f',calls[1])
    def test_invalid_power_deadline(self):
        with tempfile.TemporaryDirectory() as t:
            p=PowerPlan(Path(t)/'p.log',lambda x:None,lambda:100)
            with self.assertRaises(ValueError):p.arm({'action':'pc','trigger':'at','timestamp':90})
    def seed_post(self):
        return apply_request({}, {'action':'recommend','author':'친구','title':'작품','genre':'판타지','body':'추천 이유'},'friend','owner',1,'2026-10-10T01:00:00Z')
    def test_community_permissions_are_server_side(self):
        data=self.seed_post()
        with self.assertRaises(PermissionError):apply_request(data,{'action':'delete','id':'1'},'friend','owner',2)
        with self.assertRaises(PermissionError):apply_request(data,{'action':'site_add','name':'x','url':'https://a'},'friend','owner',3)
        edited=apply_request(data,{'action':'edit','id':'1','author':'이름','title':'수정','genre':'액션','body':'내용'},'owner','owner',4)
        self.assertEqual(edited['posts'][0]['title'],'수정');self.assertEqual(edited['posts'][0]['created'],data['posts'][0]['created'])
    def test_votes_are_unique_by_account_and_requests_idempotent(self):
        data=self.seed_post();v={'action':'vote','id':'1'}
        data=apply_request(data,v,'friend','owner',2)
        self.assertEqual(apply_request(data,v,'friend','owner',2),data)
        data=apply_request(data,v,'friend2','owner',3);self.assertEqual(len(data['posts'][0]['votes']),2)
        data=apply_request(data,v,'friend','owner',4);self.assertEqual(data['posts'][0]['votes'],['friend2'])
    def test_sharing_rejects_dangerous_urls(self):
        with self.assertRaises(ValueError):apply_request({}, {'action':'site_add','name':'x','url':'javascript:alert(1)'},'owner','owner',1)
        self.assertTrue(issue_link('owner/repo',{'action':'vote','id':'1'}).startswith('https://github.com/owner/repo/issues/new?'))
        self.assertGreater(version_tuple('v3.0.0'),version_tuple('2.0.1'))
    def test_verified_update_and_zip_traversal(self):
        for name,valid in [('ToonShelf/ToonShelf.exe',True),('../escape.exe',False)]:
            memory=io.BytesIO()
            with ZipFile(memory,'w') as z:z.writestr(name,b'fake test executable')
            blob=memory.getvalue();sha=hashlib.sha256(blob).hexdigest();asset_name='ToonShelf_3.0.0_Windows.zip'
            base='https://github.com/owner/repo/releases/download/v3.0.0/'
            release={'tag_name':'v3.0.0','assets':[{'name':asset_name,'size':len(blob),'browser_download_url':base+asset_name},
                {'name':'SHA256SUMS.txt','browser_download_url':base+'SHA256SUMS.txt'}]}
            def open_url(u,**kw):return io.BytesIO((sha+'  '+asset_name+'\n').encode() if u.endswith('.txt') else blob)
            with tempfile.TemporaryDirectory() as t,patch('urllib.request.urlopen',side_effect=open_url):
                if valid:
                    r=prepare_update(release,t,'owner/repo');self.assertTrue((Path(r['path'])/'ToonShelf.exe').exists())
                else:
                    with self.assertRaises(ValueError):prepare_update(release,t,'owner/repo')
                    self.assertFalse(list(Path(t).iterdir()))

class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['TOONSHELF_TESTING']='1'
        from PySide6.QtWidgets import QApplication
        cls.qt=QApplication.instance() or QApplication([])
    def test_refresh_can_run_alongside_queue_and_failed_job_retries_once(self):
        import app
        from PySide6.QtCore import QThread,Signal
        from core import Control
        class FakeJob(QThread):
            event=Signal(str,object);done=Signal(str,object)
            def __init__(self,kind,cfg,works=()):super().__init__();self.kind=kind;self.cfg=cfg;self.works=works;self.control=Control()
            def run(self):
                if self.kind=='download':
                    self.event.emit('current',{'title':self.works[0].title,'episode':'1화','date':'2026-10-10','index':0,'total':1})
                    time.sleep(.08);self.done.emit('download',{'saved':1,'skipped':0,'filtered':0,'failed':1,'episodes':1})
                else:
                    self.event.emit('catalog',[{'title':'새 작품','url':'https://a/webtoon/2.html'}]);self.done.emit('scan',1)
        with tempfile.TemporaryDirectory() as t,patch.object(app,'STATE',Path(t)),patch.object(app,'Job',FakeJob):
            window=app.Window();window.cover_timer.stop();window.cfg['retry_once']=True
            window.queue.add([Work('작품','https://a/webtoon/1.html')],dict(window.cfg,output_dir=t))
            window.run_queue();active=window.queue_job;window.scan();self.assertIsNot(window.job,active)
            end=time.time()+4
            while time.time()<end and (window.queue_job or (window.job and window.job.isRunning())):
                self.qt.processEvents();time.sleep(.01)
            row=window.queue.rows()[0]
            self.assertEqual(row['attempts'],2);self.assertEqual(row['status'],'partial');self.assertEqual(window.works[0].title,'새 작품')
            self.assertEqual(row['progress']['current']['episode'],'1화')
            window.cover_timer.stop();window.queue_timer.stop();window.disk_timer.stop();window.update_timer.stop();window.close()
