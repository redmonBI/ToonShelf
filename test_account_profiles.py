"""Real desktop profile isolation tests; no cloud, media access or credentials."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from core import Work
from PySide6.QtWidgets import QApplication

class AccountProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.qt=QApplication.instance() or QApplication([])
    def setUp(self):
        import app
        self.app=app;self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state_patch=patch.object(app,'STATE',self.root);self.state_patch.start();self.env_patch=patch.dict('os.environ',{'TOONSHELF_TESTING':'1'});self.env_patch.start()
        (self.root/'settings.json').write_text(json.dumps(dict(theme='gray',latest_count=5,network_policy={'limit_mib':2},output_dir=str(self.root/'private-images'),reading_positions={'guest':17})),encoding='utf-8')
        self.window=app.Window();self.window.cover_timer.stop();self.service=self.window.accounts_service;self.service.timer.stop();self.window.automation_timer.stop();self.window.notification_timer.stop();self.window.update_timer.stop();self.window.queue_timer.stop()
        self.guest_work=Work('Guest','https://example.com/webtoon/guest.html',cover=str(self.root/'private-cover.jpg'));self.window.auto_store.add([self.guest_work]);self.window.collection_store.update(self.guest_work,favorite=True,weekday=1)
    def tearDown(self):
        self.service.client.clear_session();self.window.close();self.qt.processEvents();self.window.deleteLater();self.qt.processEvents();self.env_patch.stop();self.state_patch.stop();self.tmp.cleanup()
    def login(self,uid,payload):
        self.service.client.user={'id':uid,'display_name':uid,'role':'user'};self.service.client.token='not-a-real-session';self.service.client.revision=0;self.window.account_apply(payload)
    def test_two_accounts_and_logout_do_not_bleed_lists_or_settings(self):
        self.login('alpha',{});self.assertEqual(self.window.auto_store.entries(),[]);self.assertEqual(self.window.collection_store.entries(),[])
        alpha=Work('Alpha','https://example.com/webtoon/alpha.html');self.window.auto_store.add([alpha]);self.window.collection_store.update(alpha,favorite=True);self.window.cfg['theme']='dark';self.window.cfg['reading_positions']={'alpha':80};self.window.persist_settings()
        self.login('beta',{});self.assertEqual(self.window.auto_store.entries(),[]);self.assertEqual(self.window.collection_store.entries(),[]);self.assertEqual(self.window.cfg['reading_positions'],{})
        beta=Work('Beta','https://example.com/webtoon/beta.html');self.window.auto_store.add([beta]);self.window.collection_store.update(beta,favorite=True)
        self.service.client.clear_session();self.window.account_signed_out();self.assertEqual([e['work']['title'] for e in self.window.auto_store.entries()],['Guest']);self.assertEqual([e['work']['title'] for e in self.window.collection_store.entries()],['Guest']);self.assertEqual(self.window.cfg['theme'],'gray');self.assertEqual(self.window.cfg['reading_positions'],{'guest':17});self.assertEqual(self.window.latest.currentData(),5)
    def test_empty_remote_snapshot_clears_cached_account_metadata(self):
        self.login('alpha',{});self.window.auto_store.add([self.guest_work]);self.window.collection_store.update(self.guest_work,favorite=True);self.window.account_apply({});self.assertEqual(self.window.auto_store.entries(),[]);self.assertEqual(self.window.collection_store.entries(),[])
    def test_guest_preferences_changed_after_launch_restore_on_logout(self):
        self.window.cfg['theme']='rainbow';self.window.cfg['network_policy']={'limit_mib':11};self.window.latest.setCurrentIndex(self.window.latest.findData(20));self.window.persist_settings();self.login('alpha',{});self.service.client.clear_session();self.window.account_signed_out();self.assertEqual(self.window.cfg['theme'],'rainbow');self.assertEqual(self.window.cfg['network_policy']['limit_mib'],11);self.assertEqual(self.window.latest.currentData(),20)
    def test_device_display_name_is_recorded_without_machine_path(self):
        self.login('alpha',{});self.window.account_set_device('서재 PC');self.service.record_download({'id':'q','work':{'title':'Alpha','url':'https://example.com/webtoon/a.html'},'cfg':{},'progress':{}},{'saved':1,'episodes':1},'complete');record=self.window.account_snapshot()['history'][0];self.assertEqual(record['device'],'서재 PC');self.assertEqual(json.loads((self.root/'device.json').read_text(encoding='utf-8'))['label'],'서재 PC');self.assertNotIn(str(self.root),json.dumps(record))
    def test_cloud_payload_excludes_paths_downloads_and_session(self):
        self.login('alpha',{});self.window.auto_store.add([self.guest_work]);self.window.collection_store.update(self.guest_work,favorite=True);self.window.cfg.update(output_dir=str(self.root/'private-images'),opencomic_exe=str(self.root/'viewer.exe'),library_roots=[str(self.root)],policy_file=str(self.root/'private-settings.json'),password='never-share-this',token='never-share-this')
        self.service.record_download({'id':'queue-id','work':{'title':'Guest','url':self.guest_work.url,'cover':str(self.root/'private.jpg')},'cfg':{'output_dir':str(self.root/'images'),'latest_count':10},'progress':{'current':{'episode':'10화'}}},{'saved':5,'episodes':1},'complete')
        payload=self.window.account_snapshot();raw=json.dumps(payload,ensure_ascii=False);self.assertNotIn(str(self.root),raw);self.assertNotIn('never-share-this',raw);self.assertNotIn('not-a-real-session',raw);self.assertNotIn('cover',raw);self.assertEqual(payload['history'][0]['last_episode'],'10화');self.assertEqual(payload['history'][0]['device'],'이 PC')
    def test_profile_policy_file_matches_live_global_limit(self):
        self.login('alpha',{'preferences':{'network_policy':{'limit_mib':7}}});cfg=self.window.read_cfg();expected=self.root/'accounts'/'alpha'/'settings.json';self.assertEqual(Path(cfg['policy_file']),expected);self.assertEqual(json.loads(expected.read_text(encoding='utf-8'))['network_policy']['limit_mib'],7)
        self.service.client.clear_session();self.window.account_signed_out();cfg=self.window.read_cfg();self.assertEqual(Path(cfg['policy_file']),self.root/'settings.json');self.assertEqual(cfg['network_policy']['limit_mib'],2)
    def test_import_guest_metadata_does_not_import_images_or_enable_cleanup(self):
        self.window.auto_store.save_schedule(dict(enabled=True,days=[1],time='21:00',scope='all',cleanup=True));self.login('alpha',{});self.window.account_import_local();self.assertEqual([e['work']['title'] for e in self.window.auto_store.entries()],['Guest']);self.assertTrue(self.window.collection_store.entries()[0]['favorite']);self.assertFalse(self.window.auto_store.schedule()['cleanup']);self.assertNotIn(str(self.root),json.dumps(self.window.account_snapshot()));self.assertFalse((self.root/'accounts'/'alpha'/'Downloads').exists())
    def test_switch_refuses_active_download_without_changing_profile(self):
        self.login('alpha',{});self.window.queue_jobs['active']=object();self.service.client.user={'id':'beta','display_name':'Beta','role':'user'}
        try:
            with self.assertRaises(ValueError):self.window.account_apply({})
            self.assertEqual(self.service.profile_id,'alpha');self.assertEqual(self.window.auto_store.path.parent,self.root/'accounts'/'alpha')
        finally:self.window.queue_jobs.clear()

if __name__=='__main__':unittest.main()
