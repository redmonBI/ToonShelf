"""Desktop integration without network, personal state, or real downloads."""
import json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
os.environ['TOONSHELF_TESTING']='1'
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QThread,Signal,QTimer
from PySide6.QtGui import QColor,QPalette
from PySide6.QtWidgets import QApplication,QScrollArea,QTabWidget
from core import Control,Work
from transfer_policy import TransferPolicy
import app,themes

class ControlledWorker(QThread):
    event=Signal(str,object);done=Signal(str,object)
    instances=[]
    def __init__(self,kind,cfg,works=()):
        super().__init__();self.kind=kind;self.cfg=cfg;self.works=works;self.control=Control();self.release=threading.Event();type(self).instances.append(self)
    def run(self):
        work=self.works[0]
        self.event.emit('current',{'title':work.title,'episode':work.title+' episode','date':'2026-10-11','index':0,'total':2})
        self.event.emit('transfer_progress',{'bytes':1024,'completed':1,'total':4})
        while not self.release.wait(.01) and not self.control.stopped.is_set():pass
        if self.control.stopped.is_set():self.done.emit('cancelled','stopped')
        else:self.done.emit('download',{'saved':1,'skipped':0,'filtered':0,'failed':0,'episodes':1})

class DesktopIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.qt=QApplication.instance() or QApplication([]);cls.qt.setQuitOnLastWindowClosed(False)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.exceptions=[];self.window=None;ControlledWorker.instances=[]
        self.state_patch=patch.object(app,'STATE',self.root);self.job_patch=patch.object(app,'Job',ControlledWorker)
        self.hook_patch=patch.object(sys,'excepthook',lambda *args:self.exceptions.append(args))
        self.state_patch.start();self.job_patch.start();self.hook_patch.start()
        self.window=app.Window()
        for timer in self.window.findChildren(QTimer):timer.stop()
        self.window.cfg['download_concurrency']=2;self.window.cfg['retry_once']=False
    def pump(self,condition,timeout=3):
        end=time.monotonic()+timeout
        while not condition() and time.monotonic()<end:self.qt.processEvents();time.sleep(.005)
        self.qt.processEvents();self.assertTrue(condition(),'Qt event condition timed out');self.assertFalse(self.exceptions,'Unhandled Qt callback exception')
    def tearDown(self):
        if self.window:
            self.window.queue_running=False;self.window.automation_closed=True
            for worker in ControlledWorker.instances:worker.control.stopped.set();worker.release.set()
            for worker in ControlledWorker.instances:worker.wait(3000)
            for _ in range(10):self.qt.processEvents();time.sleep(.002)
            self.window.accounts_service.client.user=None
            for timer in self.window.findChildren(QTimer):timer.stop()
            self.window.close();self.qt.processEvents();self.window.deleteLater();self.qt.processEvents()
        self.hook_patch.stop();self.job_patch.stop();self.state_patch.stop();self.tmp.cleanup()
        self.assertFalse(self.exceptions,'Unhandled Qt callback exception')
    def add(self,works,**overrides):
        return self.window.queue.add(works,dict(self.window.cfg,output_dir=str(self.root/'downloads'),**overrides))
    def test_two_workers_route_events_and_stop_only_selected_work(self):
        ids=self.add([Work('Alpha','https://example.com/a'),Work('Beta','https://example.com/b'),Work('Gamma','https://example.com/c')]);self.window.run_queue()
        self.assertEqual(set(self.window.queue_jobs),set(ids[:2]));self.assertEqual(self.window.queue.rows()[2]['status'],'pending')
        self.pump(lambda:all(r['progress'].get('transfer_progress') for r in self.window.queue.rows()[:2]))
        rows=self.window.queue.rows()
        self.assertEqual(rows[0]['progress']['current']['title'],'Alpha');self.assertEqual(rows[1]['progress']['current']['title'],'Beta')
        self.assertEqual(self.window.queue_metrics[ids[0]].bytes,1024);self.assertEqual(self.window.queue_metrics[ids[1]].bytes,1024)
        untouched=self.window.queue_jobs[ids[1]];self.window.change_queue(ids[0],'held')
        self.pump(lambda:ids[0] not in self.window.queue_jobs and ids[2] in self.window.queue_jobs)
        self.assertFalse(untouched.control.stopped.is_set());self.assertIs(self.window.queue_jobs[ids[1]],untouched)
        self.assertEqual(self.window.queue.rows()[0]['status'],'held')
        for worker in self.window.queue_jobs.values():worker.release.set()
        self.pump(lambda:not self.window.queue_jobs)
        self.assertEqual([r['status'] for r in self.window.queue.rows()],['held','complete','complete'])
    def test_same_work_directory_lease_blocks_overlapping_ranges(self):
        first=self.add([Work('Same','https://one.example/work/1')],latest_count=1)[0]
        second=self.add([Work('Same','https://two.example/work/1')],latest_count=10)[0]
        other=self.add([Work('Other','https://one.example/work/2')],latest_count=10)[0]
        self.window.run_queue();self.assertEqual(set(self.window.queue_jobs),{first,other})
        self.assertEqual(next(r for r in self.window.queue.rows() if r['id']==second)['status'],'pending')
        self.window.queue_jobs[first].release.set();self.pump(lambda:second in self.window.queue_jobs)
        self.assertNotIn(first,self.window.queue_jobs);self.assertIn(other,self.window.queue_jobs)
    def test_pause_resume_is_per_work_and_preserves_other_worker(self):
        ids=self.add([Work('One','https://example.com/1'),Work('Two','https://example.com/2')]);self.window.run_queue()
        self.window.change_queue(ids[0],'paused')
        self.assertTrue(self.window.queue_jobs[ids[0]].control.paused.is_set());self.assertFalse(self.window.queue_jobs[ids[1]].control.paused.is_set())
        self.window.change_queue(ids[0],'pending');self.assertFalse(self.window.queue_jobs[ids[0]].control.paused.is_set())
        self.assertEqual(next(r for r in self.window.queue.rows() if r['id']==ids[0])['status'],'running')
    def test_account_profile_policy_path_is_live_and_isolated(self):
        coordinator=self.window.accounts_service;coordinator.client.user={'id':'integration-user','display_name':'Tester'}
        coordinator.apply({'preferences':{'theme':'dark','network_policy':{'limit_mib':2}},'lists':{},'favorites':{},'history':[],'reading':{}})
        expected=self.root/'accounts'/'integration-user'/'settings.json';self.assertEqual(Path(self.window.policy_path()),expected)
        policy=TransferPolicy({'policy_file':self.window.policy_path()});self.assertEqual(policy.limit(),2*1024**2)
        self.window.cfg['network_policy']={'limit_mib':1};self.window.persist_settings();policy.last_read=-100
        self.assertEqual(policy.limit(),1024**2);self.assertEqual(json.loads(expected.read_text(encoding='utf-8'))['network_policy']['limit_mib'],1)
        ids=self.add([Work('Profile work','https://example.com/profile')]);self.window.run_queue();self.assertEqual(Path(self.window.queue_jobs[ids[0]].cfg['policy_file']),expected)
        self.assertEqual(self.window.queue_jobs[ids[0]].cfg['network_policy']['limit_mib'],1)
    def test_main_and_existing_dialog_widgets_change_theme_together(self):
        from preferences_ui import SettingsCenter
        settings=SettingsCenter(self.window);scroll=QScrollArea(self.window);tabs=QTabWidget(settings)
        for name in ('dark','gray','rainbow','emphasis','white'):
            self.window.apply_theme(name,persist=False);self.qt.processEvents();color=QColor(themes.colors(name)['bg'])
            self.assertEqual(self.window.centralWidget().palette().color(QPalette.Window),color)
            self.assertEqual(scroll.viewport().palette().color(QPalette.Window),color)
            self.assertEqual(settings.palette().color(QPalette.Window),color)
            self.assertEqual(tabs.palette().color(QPalette.Disabled,QPalette.Text),QColor(themes.colors(name)['muted']))
        settings.reject();scroll.deleteLater()

if __name__=='__main__':unittest.main()
