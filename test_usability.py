import json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
os.environ['TOONSHELF_TESTING']='1';os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import app
from core import Work
from site_registry import SiteRegistry,revise_site
from community_rules import apply_request

class UsabilityTests(unittest.TestCase):
    def test_startup_manual_prompt_and_login_failure_do_not_enqueue(self):
        from startup import begin
        self.window.accounts_service.startup_ready=True
        with patch.object(self.window,'automation_action') as enqueue:
            self.window.cfg['startup_download']='manual';begin(self.window);enqueue.assert_not_called()
            self.window.cfg['startup_download']='automatic';self.window.accounts_service.startup_error='offline';begin(self.window);enqueue.assert_not_called()
            self.window.accounts_service.startup_error='';begin(self.window);enqueue.assert_called_once_with('enqueue','all')
            enqueue.reset_mock();self.window.cfg['startup_download']='prompt';begin(self.window);self.window.startup_prompt.reject();enqueue.assert_not_called()
    def test_window_can_shrink_and_scroll_horizontally(self):
        self.window.show();self.window.resize(520,520);self.qt.processEvents();self.assertLess(self.window.geometry().width(),600);self.assertGreater(self.window.window_scroll.horizontalScrollBar().maximum(),0)
    @classmethod
    def setUpClass(cls):cls.qt=QApplication.instance() or QApplication([]);cls.qt.setQuitOnLastWindowClosed(False)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.env=patch.object(app,'STATE',self.root);self.env.start();self.window=app.Window()
        for timer in self.window.findChildren(QTimer):timer.stop()
    def tearDown(self):
        from PySide6.QtCore import QThread
        for task in self.window.findChildren(QThread):
            if hasattr(task,'control'):task.control.stopped.set()
            task.wait(3000)
        self.window.close();self.qt.processEvents();self.window.deleteLater();self.qt.processEvents();self.env.stop();self.tmp.cleanup()
    def pump(self,predicate):
        end=time.monotonic()+3
        while not predicate() and time.monotonic()<end:self.qt.processEvents();time.sleep(.01)
        self.qt.processEvents();self.assertTrue(predicate())
    def test_notification_close_cancels_and_window_auto_exits(self):
        from notifications_ui import NotificationsDialog
        def slow(*args):
            time.sleep(.12);args[-2].check();return {'checked':0,'added':0,'errors':[]}
        d=NotificationsDialog(self.window);d.show()
        with patch('notifications_ui.check_updates',side_effect=slow):
            d.check();d.close();self.assertFalse(d.isVisible());self.assertTrue(d.task.control.stopped.is_set());self.window.show();self.window.close();self.pump(lambda:not self.window.isVisible())
        self.assertFalse(d.task.isRunning())
    def test_task_popup_escape_drops_late_callback(self):
        from control_ui import TaskDialog
        d=TaskDialog(self.window);result=[];d.show();d.task(lambda:(time.sleep(.1),1)[1],lambda *r:result.append(r));d.reject();self.assertFalse(d.isVisible());self.pump(lambda:not d.tasks);self.assertEqual(result,[])
    def test_panel_modes_and_numeric_editors_visible(self):
        self.window.show();self.window.set_rules_fold(True);self.assertTrue(self.window.rules_body.isHidden());self.window.set_rules_fold(False)
        self.window.set_queue_view(2);self.assertFalse(self.window.queue_compact.isHidden());self.assertTrue(self.window.queue_detail.isHidden())
        self.window.pager.update_pages(4,100);self.qt.processEvents();self.assertIn('5',self.window.pager.jump.text());self.assertGreater(self.window.pager.jump.lineEdit().contentsRect().width(),45)
        self.assertEqual(self.window.width.value(),100);self.assertGreater(self.window.width.lineEdit().contentsRect().width(),20)
    def test_compact_queue_bounded_and_running_first(self):
        ids=self.window.queue.add([Work(str(i),'https://example.com/'+str(i)) for i in range(20)],self.window.cfg);self.window.queue.change(ids[-1],'running')
        self.window.queue_compact.refresh();self.assertEqual(len(self.window.queue_compact.cards),5);self.assertIn(ids[-1],self.window.queue_compact.cards)
    def test_registered_site_current_history_and_manual_input(self):
        registry=SiteRegistry(self.root);a=registry.update({},'블랙툰','https://example.com');b=registry.update(a,'블랙툰','https://next.example.com',planned=['https://future.example.com']);self.assertEqual(len(registry.local()),1);self.assertEqual([h['url'] for h in b['history']],['https://example.com','https://next.example.com'])
        registry.cache_shared([{'name':'공유 사이트','url':'https://shared.example.com'}]);self.window.refresh_site_choices();self.window.site_choices.setCurrentIndex(1);self.assertEqual(self.window.url.text(),'https://next.example.com');self.window.url.setText('https://manual.example.com');self.assertEqual(self.window.read_cfg()['site_url'],'https://manual.example.com')
    def test_shared_address_edit_keeps_full_history(self):
        from sites_ui import history_date
        self.assertEqual(history_date('2026-10-11T01:00:00Z'),'2026-10-11 10:00')
        data=apply_request({},dict(action='site_add',name='Site',url='https://old.example.com'),'friend','owner',1,date='2026-10-10T01:00:00Z');data=apply_request(data,dict(action='site_edit',id='1',name='Site',url='https://new.example.com',planned_urls=['https://future.example.com']),'another_friend','owner',2,date='2026-10-11T01:00:00Z');site=data['sites'][0];self.assertEqual(site['url'],'https://new.example.com');self.assertEqual(len(site['history']),2);self.assertEqual(site['planned_urls'],['https://future.example.com'])
    def test_finder_adds_search_results_without_main_selection(self):
        from work_finder import WorkFinder
        self.window.works=[Work('Alpha','https://example.com/a'),Work('Beta','https://example.com/b')];d=WorkFinder(self.window,self.window.auto_store.add);d.search.setText('beta');self.assertEqual(d.table.rowCount(),1);d.table.selectRow(0);d.add();self.assertEqual(self.window.auto_store.entries()[0]['work']['title'],'Beta');self.assertFalse(self.window.selected);d.reject()

class UpdateStorageTests(unittest.TestCase):
    def test_readonly_completed_stage_is_removed(self):
        import os,stat
        from update_storage import prepare_slot,cleanup_applied_stages
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);slot=prepare_slot(target/'Updates');(slot/'patch.json').write_text(json.dumps({'target':str(target)}));(slot/'result.json').write_text(json.dumps({'status':'complete','backup':str(target/'PreviousVersion')}));folder=slot/'ready/ToonShelf/_internal/readonly';folder.mkdir(parents=True);file=folder/'module.py';file.write_text('owned');os.chmod(file,stat.S_IREAD);os.chmod(folder,stat.S_IREAD | stat.S_IEXEC)
            self.assertEqual(cleanup_applied_stages(target),['current']);self.assertFalse(slot.exists())
    def test_previous_slot_reused_and_deletion_preserves_personal_data(self):
        import patch_update as p
        from update_storage import clear_previous,MARKER,list_storage
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'install';target.mkdir();(target/'ToonShelf.exe').write_bytes(b'old');(target/'state').mkdir();(target/'state/data').write_bytes(b'personal');(target/'Downloads').mkdir();(target/'Downloads/image.jpg').write_bytes(b'image');source=target/'Updates/current/ready/ToonShelf';source.mkdir(parents=True)
            for index in range(2):
                (source/'ToonShelf.exe').write_bytes(('new'+str(index)).encode());m=p.prepare_patch(dict(path=str(source),version='v3.4.'+str(index),sha256='a'*64),target,1);self.assertEqual(p.apply_patch(m,wait=lambda _:None,launch=lambda _:None),0)
            self.assertEqual(len(list(target.glob('PreviousVersion*'))),1);self.assertEqual((target/'PreviousVersion/ToonShelf.exe').read_bytes(),b'new0');self.assertEqual(len(list_storage(target)),2);clear_previous(target);self.assertEqual((target/'state/data').read_bytes(),b'personal');self.assertEqual((target/'Downloads/image.jpg').read_bytes(),b'image')
    def test_unknown_backup_and_personal_stage_cannot_be_deleted(self):
        from update_storage import clear_previous,clean_stage
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);previous=target/'PreviousVersion';previous.mkdir();(previous/'unknown.jpg').write_bytes(b'user');
            with self.assertRaises((ValueError,OSError)):clear_previous(target)
            self.assertTrue((previous/'unknown.jpg').exists());stage=target/'Updates/current';(stage/'Downloads').mkdir(parents=True);(stage/'Downloads/image.jpg').write_bytes(b'user')
            with self.assertRaises(ValueError):clean_stage(stage,target)
            self.assertTrue((stage/'Downloads/image.jpg').exists())
    def test_completed_stage_cleanup_and_unfinished_protection(self):
        from update_storage import clean_stage,prepare_slot
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);slot=prepare_slot(target/'Updates');(slot/'patch.json').write_text(json.dumps({'target':str(target)}));(slot/'result.json').write_text('{"status":"recovery_required"}')
            with self.assertRaises(ValueError):clean_stage(slot,target)
            (slot/'result.json').write_text('{"status":"complete"}');clean_stage(slot,target);self.assertFalse(slot.exists())
    def test_startup_cleanup_removes_only_new_completed_delivery(self):
        from update_storage import prepare_slot,cleanup_applied_stages
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);slot=prepare_slot(target/'Updates');(slot/'patch.json').write_text(json.dumps({'target':str(target)}));(slot/'result.json').write_text(json.dumps({'status':'complete','backup':str(target/'PreviousVersion')}));old=target/'Updates/ToonShelf_update_old';old.mkdir();(old/'patch.json').write_text(json.dumps({'target':str(target)}));(old/'result.json').write_text(json.dumps({'status':'complete','backup':str(old/'backup')}));self.assertEqual(cleanup_applied_stages(target),['current']);self.assertTrue(old.exists())

if __name__=='__main__':unittest.main()
