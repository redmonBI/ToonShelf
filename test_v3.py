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
from automation_store import AutoStore,SEOUL,enqueue_occurrences,select_episodes,in_window
from transfer_policy import TransferPolicy,validate_policy,stream_image
from datetime import datetime,timedelta,timezone

class AutomaticTests(unittest.TestCase):
    def cfg(self,root):return dict(site_url='https://new.test',output_dir=str(root),min_width=100,min_height=100,delay=0,image_selector='#imgs img',start_episode=1,end_episode=0)
    def schedule(self,store,at=None,**values):
        store.save_schedule(dict(enabled=True,days=[0],time='21:00',scope='selected',cleanup=False,**values),at or datetime(2026,10,12,20,tzinfo=SEOUL))
    def test_lists_reopen_and_library_rows_are_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'auto.db';store=AutoStore(path);self.assertFalse(store.schedule()['enabled'])
            store.add([dict(title='작품',url='https://old.test/w/1',chapters=[],key='extra')]);store.update('/w/1',category='held',tail=5,keep_count=20,delete_days=30,selected=0)
            row=AutoStore(path).entries()[0];self.assertEqual(row['category'],'held');self.assertEqual(row['keep_count'],20);self.assertNotIn('chapters',row['work']);self.assertFalse(store.chosen('selected'));self.assertEqual(len(store.chosen('all')),1)
            store.remove('/w/1');self.assertFalse(store.entries())
    def test_weekly_slot_once_across_restarts_and_next_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=AutoStore(root/'auto.db');queue=QueueStore(root/'q.db');store.add([Work('a','https://old.test/w/1'),Work('b','https://old.test/w/2')]);store.update('/w/2',selected=0);self.schedule(store)
            now=datetime(2026,10,12,21,0,tzinfo=SEOUL);ids=enqueue_occurrences(store,queue,self.cfg(root),now);self.assertEqual(len(ids),1);self.assertEqual(queue.rows()[0]['work']['url'],'https://new.test/w/1');self.assertEqual(queue.rows()[0]['cfg']['latest_count'],10)
            self.assertFalse(enqueue_occurrences(AutoStore(root/'auto.db'),queue,self.cfg(root),now+timedelta(minutes=5)));queue.change(ids[0],'complete');self.assertEqual(len(enqueue_occurrences(store,queue,self.cfg(root),now+timedelta(days=7))),1)
    def test_past_time_configuration_waits_until_next_selected_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=AutoStore(root/'auto.db');store.add([Work('a','https://a/w/1')]);self.schedule(store,datetime(2026,10,12,22,tzinfo=SEOUL))
            self.assertFalse(store.claim_due(self.cfg(root),datetime(2026,10,12,23,tzinfo=SEOUL)));self.assertEqual(len(store.claim_due(self.cfg(root),datetime(2026,10,19,22,tzinfo=SEOUL))),1)
    def test_seoul_weekday_is_used_for_utc_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=AutoStore(root/'a.db');store.add([Work('a','https://a/w/1')]);store.save_schedule(dict(enabled=True,days=[0],time='00:30',scope='all',cleanup=False),datetime(2026,10,11,14,tzinfo=timezone.utc))
            self.assertEqual(len(store.claim_due(self.cfg(root),datetime(2026,10,11,16,tzinfo=timezone.utc))),1)
    def test_crash_after_queue_registration_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=AutoStore(root/'auto.db');queue=QueueStore(root/'q.db');store.add([Work('a','https://a/w/1')]);self.schedule(store);now=datetime(2026,10,12,22,tzinfo=SEOUL)
            with patch.object(store,'mark',side_effect=RuntimeError('crash')):
                with self.assertRaises(RuntimeError):enqueue_occurrences(store,queue,self.cfg(root),now)
            self.assertEqual(len(queue.rows()),1);queue.change(queue.rows()[0]['id'],'complete');self.assertFalse(enqueue_occurrences(AutoStore(root/'auto.db'),queue,self.cfg(root),now));self.assertEqual(len(queue.rows()),1);self.assertEqual(store.history()[0]['status'],'queued')
    def test_disabling_schedule_cancels_unregistered_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=AutoStore(root/'a.db');store.add([Work('a','https://a/w/1')]);self.schedule(store);store.claim_due(self.cfg(root),datetime(2026,10,12,22,tzinfo=SEOUL))
            schedule=store.schedule();schedule['enabled']=False;store.save_schedule(schedule);self.assertFalse(store.claim_due(self.cfg(root),datetime(2026,10,12,23,tzinfo=SEOUL)));self.assertEqual(store.history()[0]['status'],'cancelled')
    def test_latest_ranges_download_newest_first_without_renumbering(self):
        from core import Episode
        episodes=[Episode(str(i),str(i),'',i,str(i)) for i in range(1,51)]
        for count in (1,5,10,20,30):self.assertEqual([e.number for e in select_episodes(episodes,dict(latest_count=count))],list(range(50,50-count,-1)))
        self.assertEqual([e.number for e in select_episodes(episodes,dict(start_episode=3,end_episode=5))],[3,4,5]);self.assertEqual(len(select_episodes(episodes,dict(latest_count=100))),50)
    def test_queue_persists_tail_and_distinguishes_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);queue=QueueStore(root/'q.db');work=Work('a','https://a/w/1');cfg=self.cfg(root)
            self.assertEqual(len(queue.add([work],dict(cfg,latest_count=1,network_policy={'limit_mib':1},policy_file='policy.json'))),1);self.assertEqual(len(queue.add([work],dict(cfg,latest_count=10))),1)
            row=QueueStore(root/'q.db').rows()[0];self.assertEqual(row['cfg']['network_policy']['limit_mib'],1);self.assertEqual(row['cfg']['policy_file'],'policy.json')
    def test_time_windows_cross_midnight_and_overlapping_limits(self):
        at=datetime(2026,10,12,23,tzinfo=SEOUL);self.assertTrue(in_window(at,'22:00','06:00'));self.assertFalse(in_window(at.replace(hour=6),'22:00','06:00'));self.assertTrue(in_window(at,'00:00','00:00'))
        p=TransferPolicy(dict(network_policy=dict(limit_mib=10,rules=[dict(start='22:00',end='06:00',mib=2),dict(start='23:00',end='00:00',mib=1)])),calendar=lambda:at);self.assertEqual(p.limit(),1024**2)
        with self.assertRaises(ValueError):validate_policy(dict(limit_mib=1025))
        with self.assertRaises(ValueError):validate_policy(dict(start='25:00'))
    def test_live_policy_reload_and_incomplete_write_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json';clock=[0.];path.write_text(json.dumps(dict(network_policy=dict(limit_mib=2))));p=TransferPolicy(dict(policy_file=str(path)),clock=lambda:clock[0]);self.assertEqual(p.limit(),2*1024**2)
            clock[0]=2;path.write_text('{');self.assertEqual(p.limit(),2*1024**2);clock[0]=4;path.write_text(json.dumps(dict(network_policy=dict(limit_mib=1))));self.assertEqual(p.limit(),1024**2)
    def test_window_wait_is_interruptible_and_resumes(self):
        from core import Cancelled
        from unittest.mock import Mock
        now=[datetime(2026,10,12,20,tzinfo=SEOUL)];p=TransferPolicy(dict(network_policy=dict(window_enabled=True,start='21:00',end='22:00')),calendar=lambda:now[0]);control=Mock();control.delay.side_effect=Cancelled();events=[]
        with self.assertRaises(Cancelled):p.gate(control,lambda *a:events.append(a))
        control.delay.side_effect=lambda seconds:now.__setitem__(0,now[0].replace(hour=21));p.gate(control,lambda *a:events.append(a));self.assertIn(('transfer_wait',True),events);self.assertIn(('transfer_wait',False),events)
    def test_real_stream_is_paced_and_cookies_headers_preserved(self):
        import threading
        from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
        from core import Control
        data=b'x'*(256*1024);headers=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):headers.append(dict(self.headers));self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            p=TransferPolicy(dict(network_policy=dict(limit_mib=1)));start=time.monotonic();result=stream_image(f'http://127.0.0.1:{server.server_port}/image',{'User-Agent':'Test UA','Referer':'http://127.0.0.1/'},[dict(name='session',value='test',domain='127.0.0.1',path='/',secure=False)],p,Control(),lambda *a:None)
            self.assertEqual(result,data);self.assertGreaterEqual(time.monotonic()-start,.22);self.assertEqual(headers[0]['Cookie'],'session=test');self.assertEqual(headers[0]['User-Agent'],'Test UA')
        finally:server.shutdown();server.server_close();thread.join(2)
    def archive_fixture(self,root):
        from library import LibraryArchive
        from core import Episode
        from PIL import Image
        archive=LibraryArchive(root);work=Work('작품','https://a/work/1');stream=io.BytesIO();Image.new('RGB',(120,150),'blue').save(stream,format='PNG');data=stream.getvalue()
        for n in range(1,6):
            e=Episode(f'{n}화',f'https://a/ep/{n}','2026-10-01',n,f'{n}화');archive.record_episode(work,e,n);archive.save(work,e,f'https://a/img/{n}.png',data,(100,100));archive.episode_status(work,e,'complete','')
        entry=dict(key='/work/1',work={'title':'작품'},keep_count=2,delete_days=0);return archive,entry
    def test_retention_keeps_newest_and_preserves_unknown_and_modified_files(self):
        from retention import plan_cleanup,apply_cleanup
        from core import Control
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,entry=self.archive_fixture(root);(root/'작품'/'1화'/'notes.txt').write_text('keep');(root/'작품'/'2화'/'2.png').write_bytes(b'edited')
            plan=plan_cleanup(root,[entry]);self.assertEqual([r['episode'] for r in plan],['3화','2화','1화']);result=apply_cleanup(root,plan,Control(),lambda *a:None);self.assertEqual(result['deleted'],2);self.assertEqual(len(result['errors']),1)
            self.assertTrue((root/'작품'/'5화'/'5.png').exists());self.assertTrue((root/'작품'/'4화'/'4.png').exists());self.assertEqual((root/'작품'/'2화'/'2.png').read_bytes(),b'edited');self.assertTrue((root/'작품'/'1화'/'notes.txt').exists());archive.close()
    def test_period_cutoff_protects_newest_and_unknown_dates(self):
        from retention import plan_cleanup
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,entry=self.archive_fixture(root);archive.db.execute("UPDATE episodes SET last_downloaded='2026-09-01T00:00:00+00:00'");archive.db.execute("UPDATE episodes SET last_downloaded='' WHERE number=2");archive.db.commit();entry.update(keep_count=0,delete_days=30)
            plan=plan_cleanup(root,[entry],datetime(2026,10,11,tzinfo=timezone.utc));self.assertEqual(len(plan),4);self.assertNotIn('2화',[e['episode'] for e in plan]);entry['keep_count']=2;self.assertNotIn('5화',[e['episode'] for e in plan_cleanup(root,[entry])]);archive.close()
    def test_incomplete_latest_defers_retention(self):
        from retention import plan_cleanup
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,entry=self.archive_fixture(root);archive.db.execute("UPDATE episodes SET status='partial' WHERE number=5");archive.db.commit();self.assertFalse(plan_cleanup(root,[entry]));archive.close()
    def test_cleanup_rejects_outside_path_and_rechecks_changed_database(self):
        from retention import plan_cleanup,apply_cleanup,safe_file
        from core import Control
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,entry=self.archive_fixture(root);plan=plan_cleanup(root,[entry]);archive.db.execute("UPDATE images SET path='../outside.png' WHERE key=?",(plan[0]['files'][0]['key'],));archive.db.commit();result=apply_cleanup(root,plan[:1],Control(),lambda *a:None);self.assertEqual(result['deleted'],0);self.assertTrue(result['errors'])
            with self.assertRaises(ValueError):safe_file(root,'../outside.png')
            unsafe=plan_cleanup(root,[entry])[:1];result=apply_cleanup(root,unsafe,Control(),lambda *a:None);self.assertEqual(result['deleted'],0);self.assertTrue(result['errors'])
            with patch.object(Path,'is_junction',return_value=True):
                with self.assertRaises(ValueError):safe_file(root,'작품/1화/1.png')
            archive.close()
    def test_managed_opencomic_mirrors_are_cleaned_with_originals(self):
        from retention import plan_cleanup,apply_cleanup
        from reading import prepare_opencomic
        from core import Control
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,entry=self.archive_fixture(root);chapters=archive.episodes('/work/1')
            for e in chapters:e['files']=archive.ordered_images(e['key'])
            paths=prepare_opencomic(root,dict(key='/work/1',chapters=chapters),Control(),lambda *a:None);apply_cleanup(root,plan_cleanup(root,[entry]),Control(),lambda *a:None)
            self.assertFalse(list(Path(paths[0]).glob('*.png')));self.assertTrue(list(Path(paths[-1]).glob('*.png')));archive.close()
    def test_auto_ui_preferences_and_async_preview_stay_responsive(self):
        import app
        from automation_ui import AutomationDialog
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        qt=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)):
            w=app.Window();w.cover_timer.stop();w.auto_store.add([Work('작품','https://a/work/1')]);d=AutomationDialog(w);d.show();qt.processEvents();d.list.cellWidget(0,2).setCurrentIndex(2);d.list.cellWidget(0,3).setCurrentIndex(4);d.list.cellWidget(0,4).setValue(10);d.limit.setValue(3);d.save_policy();self.assertEqual(w.auto_store.entries()[0]['category'],'planned');self.assertEqual(w.auto_store.entries()[0]['tail'],20);self.assertEqual(w.cfg['network_policy']['limit_mib'],3)
            ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(15)
            with patch('retention.plan_cleanup',side_effect=lambda *a:(time.sleep(.3) or [])):
                d.preview();end=time.monotonic()+.6
                while time.monotonic()<end:qt.processEvents();time.sleep(.01)
            self.assertGreater(len(ticks),10);self.assertFalse(w.auto_job.isRunning());self.assertTrue(w.auto_preview.isVisible());w.auto_preview.close();timer.stop();d.close();w.close();qt.processEvents()
    def test_window_scheduler_downloads_once_and_leaves_held_jobs_alone(self):
        import app
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QThread,Signal
        from core import Control
        qt=QApplication.instance() or QApplication([])
        class FakeJob(QThread):
            event=Signal(str,object);done=Signal(str,object)
            def __init__(self,kind,cfg,works=()):super().__init__();self.kind=kind;self.cfg=cfg;self.works=works;self.control=Control()
            def run(self):self.done.emit('download',dict(saved=0,skipped=1,filtered=0,failed=0,episodes=1))
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)),patch.object(app,'Job',FakeJob),patch('automation_store.local_now',return_value=datetime(2026,10,12,22,tzinfo=SEOUL)):
            w=app.Window();w.cover_timer.stop();w.auto_store.add([Work('예약작품','https://a/work/1')]);w.auto_store.update('/work/1',tail=30);self.schedule(w.auto_store)
            held=w.queue.add([Work('보류','https://a/work/2')],dict(w.cfg,output_dir=tmp))[0];w.queue.change(held,'held');w.automation_tick();end=time.monotonic()+.6
            while time.monotonic()<end:qt.processEvents();time.sleep(.01)
            rows=w.queue.rows();self.assertEqual(len(rows),2);self.assertEqual(rows[0]['status'],'held');self.assertEqual(rows[1]['status'],'complete');self.assertEqual(rows[1]['cfg']['latest_count'],30)
            w.auto_last_check=0;w.automation_tick();qt.processEvents();self.assertEqual(len(w.queue.rows()),2);w.close();qt.processEvents()

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
    def test_community_is_editable_by_every_github_account(self):
        data=self.seed_post()
        self.assertFalse(apply_request(data,{'action':'delete','id':'1'},'another_friend','owner',2)['posts'])
        sites=apply_request(data,{'action':'site_add','name':'x','url':'https://a','news_url':'https://a/news'},'friend','owner',3)
        self.assertFalse(apply_request(sites,{'action':'site_delete','id':'3'},'another_friend','owner',5)['sites'])
        edited=apply_request(data,{'action':'edit','id':'1','author':'이름','title':'수정','genre':'액션','body':'내용'},'another_friend','owner',4)
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
    def test_pasted_site_link_is_normalized_across_input_paths(self):
        from core import validate_url
        from community_rules import url
        for value in ['https://blacktoon423.com','http://blacktoon423.com','[https://blacktoon423.com](https://blacktoon423.com)','<https://blacktoon423.com>','blacktoon423.com','\ufeffhttps://blacktoon423.com\u200b']:
            expected='http://blacktoon423.com' if value.startswith('http:') else 'https://blacktoon423.com'
            self.assertEqual(url(value),expected);self.assertEqual(validate_url(value),expected)
        request={'action':'site_add','name':'블랙툰','url':'[주소](https://blacktoon423.com)','news_url':'[안내](https://example.com/news?a=1#new)'}
        result=apply_request({},request,'owner','owner','paste')
        self.assertEqual(result['sites'][0]['url'],'https://blacktoon423.com')
        self.assertEqual(result['sites'][0]['news_url'],'https://example.com/news?a=1#new')
        self.assertEqual(url('example.com:8443/path'),'https://example.com:8443/path')
    def test_pasted_link_does_not_allow_unsafe_destinations(self):
        from link_input import normalize_url
        for value in ['javascript:alert(1)','file:///C:/','[주소](javascript:alert(1))','https://user:secret@example.com','https://example.com:99999','https://bad host.com','https://example.com\\evil','']:
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_url(value)
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
