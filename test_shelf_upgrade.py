import os,json,tempfile,time,unittest
os.environ['TOONSHELF_TESTING']='1'
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from core import Work,Episode,Control,Browser
from library import LibraryArchive
from reading import shelf_index
from shelf_collections import enrich_shelf
from list_sharing import list_requests
from community_rules import apply_request

class ShelfDataTests(unittest.TestCase):
    def test_catalog_weekday_survives_later_all_tab(self):
        from unittest.mock import MagicMock
        browser=Browser({'site_url':'https://example.com'},Control(),lambda *a:None);browser.page=MagicMock()
        def locate(selector):
            node=MagicMock();node.count.return_value=1 if selector in ('.nav_pday[attr-id="1"]','#profile-tab','a.toon-link img[data-original]') else 0;node.is_visible.return_value=True;node.inner_text.return_value='수요일' if selector=='.nav_pday[attr-id="1"]' else '일반 웹툰';node.evaluate_all.return_value=[];return node
        browser.page.locator.side_effect=locate
        with patch.object(browser,'visit',return_value=''),patch.object(browser,'rendered_catalog',side_effect=[[Work('Demo','https://example.com/a')],[Work('Demo','https://example.com/a')],[Work('Demo','https://example.com/a')]]):
            rows=browser.catalog();self.assertEqual(len(rows),1);self.assertEqual(rows[0].weekday,2)
    def fixture(self,root):
        archive=LibraryArchive(root);work=Work('Demo','https://example.com/webtoon/1.html',weekday=2)
        episodes=[Episode(f'{i}화',f'https://example.com/webtoons/1/{i}.html','2026-10-11',i,f'{i}화') for i in range(1,4)]
        archive.record_work(work)
        for i,e in enumerate(episodes,1):archive.record_episode(work,e,i)
        archive.record_plan(work,episodes,{'latest_count':1})
        from io import BytesIO
        data=BytesIO();Image.new('RGB',(200,600),'red').save(data,'PNG')
        def save(e):
            archive.save(work,e,f'https://example.com/{int(e.number)}.png',data.getvalue(),(100,100));archive.db.execute("UPDATE episodes SET status='complete' WHERE url=?",(e.url,));archive.db.commit()
        return archive,work,episodes,save
    def test_full_inventory_and_latest_subset_do_not_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,work,episodes,save=self.fixture(root);save(episodes[-1]);rows=shelf_index(root,[],Control(),lambda *a:None,False);view=enrich_shelf(rows,[],[]);self.assertEqual(view[0]['storage_scope'],'recent');self.assertEqual(view[0]['weekday'],2);self.assertEqual(view[0]['known_total'],3)
            for e in episodes[:-1]:save(e)
            self.assertEqual(enrich_shelf(shelf_index(root,[],Control(),lambda *a:None,False),[],[])[0]['storage_scope'],'full');archive.close()
    def test_failed_missing_and_unknown_do_not_claim_full(self):
        row={'url':'https://example.com/a','expected_episode_keys':['1','2'],'chapters':[{'key':'1','status':'complete','images':1},{'key':'2','status':'failed','images':1}]}
        self.assertEqual(enrich_shelf([row],[],[])[0]['storage_scope'],'partial');row['chapters'][1].update(status='complete',missing=1);self.assertEqual(enrich_shelf([row],[],[])[0]['storage_scope'],'partial');row['expected_episode_keys']=[];self.assertEqual(enrich_shelf([row],[],[])[0]['storage_scope'],'partial')
    def test_weekday_override_and_automatic_list_fallback(self):
        row={'url':'https://example.com/a','weekday':2}
        self.assertEqual(enrich_shelf([row],[],[{'key':'/a','weekday':4,'tail':10}])[0]['weekday'],4)
        self.assertEqual(enrich_shelf([row],[{'key':'/a','weekday':1}],[{'key':'/a','weekday':4}])[0]['weekday'],1)
    def test_shared_list_is_sanitized_and_retry_is_idempotent(self):
        entries=[{'work':dict(title='Demo',url='https://example.com/a',genre='Fantasy',publisher='Demo',password='SECRET',save_path='C:/PRIVATE'),'weekday':2,'tail':10}]
        request=list_requests(entries,[],'Friend')[0];self.assertNotIn('SECRET',json.dumps(request));self.assertNotIn('PRIVATE',json.dumps(request));data=apply_request({},request,'friend','owner',1);self.assertEqual(data['posts'][0]['kind'],'work_list');self.assertEqual(len(data['posts'][0]['works']),1);self.assertEqual(data,apply_request(data,request,'friend','owner',1))
        bad=dict(request,works=[dict(request['works'][0],weekday=9)])
        with self.assertRaises(ValueError):apply_request({},bad,'friend','owner',2)
    def test_large_list_chunks_preserve_every_work_and_fit_request_limit(self):
        entries=[{'work':dict(title='Demo'+str(i),url='https://example.com/'+str(i),genre='Fantasy'),'weekday':i%7} for i in range(600)]
        requests=list_requests(entries,[],'Friend');self.assertEqual(sum(len(r['works']) for r in requests),600);self.assertGreater(len(requests),1)
        for i,r in enumerate(requests):self.assertLess(len(json.dumps(r,ensure_ascii=False,indent=2))+14,64000);apply_request({},r,'friend','owner',i)
        with self.assertRaises(ValueError):list_requests([],[],'Friend')
    def test_legacy_database_keeps_images_and_migrates_weekday(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive,work,episodes,save=self.fixture(Path(tmp));save(episodes[-1]);archive.close();reopened=LibraryArchive(Path(tmp));self.assertEqual(reopened.works(False)[0]['weekday'],2);self.assertEqual(reopened.works(False)[0]['images'],1);reopened.close()

class ShelfUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt=QApplication.instance() or QApplication([]);cls.qt.setQuitOnLastWindowClosed(False)
    def setUp(self):
        import app
        from PySide6.QtCore import QTimer
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state=patch.object(app,'STATE',self.root);self.state.start();self.host=app.Window();self.host.path.setText(str(self.root));self.host.show_offline();self.pane=self.host.offline
        for t in self.host.findChildren(QTimer):t.stop()
        self.pump(lambda:not self.pane.task or not self.pane.task.isRunning())
    def pump(self,predicate):
        end=time.monotonic()+4
        while not predicate() and time.monotonic()<end:self.qt.processEvents();time.sleep(.01)
        self.qt.processEvents();self.assertTrue(predicate())
    def tearDown(self):
        from PySide6.QtCore import QCoreApplication,QEvent
        self.pump(self.pane.shutdown);self.host.close();self.qt.processEvents();self.host.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);self.qt.processEvents();self.state.stop();self.tmp.cleanup()
    def row(self):
        file=self.root/'demo.png';Image.new('RGB',(200,900),'blue').save(file)
        chapters=[dict(key=str(i),folder=f'{i}화',files=[dict(path='demo.png',position=1)],order_verified=1,status='complete',images=1,missing=0) for i in (1,2)]
        return dict(title='Demo',url='https://example.com/demo',key='/demo',genre='Fantasy',publisher='Demo',chapters=chapters,episodes=2,size=100,images=2,last_downloaded='',weekday=2,expected_episode_keys=['1','2'])
    def test_weekday_scope_tabs_and_today_automatically_filter(self):
        self.pane.rows=[self.row(),dict(self.row(),title='Recent',url='https://example.com/recent',expected_episode_keys=['1','2','3'],latest_count=10,weekday=4)];self.pane.scope_tabs.setCurrentIndex(1);self.assertEqual([r['title'] for r in self.pane.filtered()],['Recent']);self.pane.scope_tabs.setCurrentIndex(2);self.assertEqual([r['title'] for r in self.pane.filtered()],['Demo'])
        from datetime import datetime
        from automation_store import SEOUL
        with patch('automation_store.local_now',return_value=datetime(2026,10,14,tzinfo=SEOUL)):self.pane.today.setChecked(True);self.assertEqual(self.pane.collection_filters.day.currentData(),2);self.assertEqual(len(self.pane.filtered()),1)
    def test_slim_reader_gains_height_and_keeps_navigation(self):
        self.host.resize(1200,900);self.host.show();self.pane.open_work(self.row());self.pump(lambda:bool(self.pane.images) and not self.pane.task.isRunning());normal=self.pane.read_scroll.height();self.pane.set_slim(True);self.qt.processEvents();self.assertGreater(self.pane.read_scroll.height(),normal+100);self.assertTrue(self.host.sidebar.isHidden());self.assertTrue(self.host.app_toolbar.isHidden());self.assertFalse(self.pane.slim_bar.isHidden());self.assertEqual(self.pane.slim_bar.height(),32);self.pane.slim_chapters.setCurrentIndex(1);self.pump(lambda:self.pane.chapter==1 and not self.pane.task.isRunning());self.pane.show_tools();self.qt.processEvents();self.assertFalse(self.host.sidebar.isHidden());self.assertTrue(self.pane.slim_bar.isHidden())
    def test_share_preview_contains_whole_list_and_opens_only_on_click(self):
        from share_list_ui import ShareListDialog
        self.host.auto_store.add([Work('A','https://example.com/a'),Work('B','https://example.com/b')])
        with patch('share_list_ui.launch_request',return_value='Prepared') as launch:
            dialog=ShareListDialog(self.host);self.assertEqual(dialog.table.rowCount(),2);launch.assert_not_called();dialog.author.setText('Friend');dialog.submit();launch.assert_called_once();self.assertEqual(len(launch.call_args.args[1]['works']),2);self.assertFalse(dialog.send.isEnabled());dialog.reject()

if __name__=='__main__':unittest.main()
