import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from core import Control
from reading import chapter_images,prepare_opencomic,local_path
from download_metrics import DownloadMetrics

class ReadingTests(unittest.TestCase):
    def test_resume_choice_keyboard_and_adjustable_autoscroll(self):
        from PySide6.QtCore import QTimer,Qt
        from reading_ui import OfflineLibrary
        import app,json
        qt=QApplication.instance() or QApplication([])
        def pump(seconds=.3):
            end=time.monotonic()+seconds
            while time.monotonic()<end:qt.processEvents();time.sleep(.01)
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)),patch.dict(os.environ,{'TOONSHELF_TESTING':'1'}):
            host=app.Window()
            for timer in host.findChildren(QTimer):timer.stop()
            pane=OfflineLibrary(host);pane.root=Path(tmp);pane.resize(900,700);pane.show();work=self.fixture(Path(tmp));pane.open_work(work);pump()
            bar=pane.read_scroll.verticalScrollBar();bar.setValue(int(bar.maximum()*.4));pane.save_position();saved=host.cfg['reading_positions']['work'];self.assertIn('updated_at',saved)
            self.assertAlmostEqual(json.loads((Path(tmp)/'settings.json').read_text(encoding='utf-8'))['reading_positions']['work']['fraction'],.4,delta=.01)
            pane.back();pane.open_work(work);self.assertTrue(pane.resume_prompt.isVisible());next(b for b in pane.resume_prompt.buttons() if b.text()=='이어서 보기').click();pump();self.assertAlmostEqual(bar.value()/bar.maximum(),.4,delta=.03)
            QTest.keyClick(pane.read_scroll,Qt.Key_Space);self.assertGreater(bar.value()/bar.maximum(),.4)
            before=bar.value();QTest.keyClick(pane.read_scroll,Qt.Key_PageUp);self.assertLess(bar.value(),before)
            pane.scroll_speed.setValue(200);pane.toggle_auto_scroll();before=bar.value();pump(.15);self.assertGreater(bar.value(),before);self.assertEqual(host.cfg['reader_scroll_speed'],200)
            pane.back();self.assertFalse(pane.auto_timer.isActive());pane.shutdown();pane.close();host.close();qt.processEvents()
    def fixture(self,root):
        files=[]
        for n,name in enumerate(['10.png','2.png']):
            p=root/name;Image.new('RGB',(300,1200),'red' if n else 'blue').save(p)
            files.append({'path':name,'position':n+1})
        chapters=[{'key':'e1','folder':'1화','order_verified':1,'files':files}, {'key':'e2','folder':'2화','order_verified':1,'files':files}]
        for i,e in enumerate(chapters):e.update(sequence=i+1,upload_date='',first_downloaded='',last_downloaded='',images=2,size=10000,missing=0,status='complete')
        return {'key':'work','title':'작품','chapters':chapters}
    def test_bridge_preserves_originals_and_orders_chapters_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=self.fixture(root);before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.png')}
            paths=prepare_opencomic(root,work,Control(),lambda *a:None)
            self.assertEqual([Path(p).name for p in paths],['0001_1화','0002_2화'])
            self.assertEqual((Path(paths[0])/'000001.png').read_bytes(),(root/'10.png').read_bytes())
            self.assertEqual(prepare_opencomic(root,work,Control(),lambda *a:None),paths)
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.png')})
    def test_legacy_recorded_order_beats_random_names_and_reports_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=self.fixture(root);e=work['chapters'][0];e['order_verified']=0
            rows=chapter_images(root,e,Control());self.assertEqual(Path(rows[0]['path']).name,'10.png')
            (root/'2.png').write_bytes(b'broken');rows=chapter_images(root,e,Control());self.assertTrue(rows[1]['error'])
            with self.assertRaises(ValueError):local_path(root,'../escape.png')
    def test_metrics_pause_excluded_and_estimates_need_samples(self):
        now=[0.];m=DownloadMetrics(lambda:now[0]);self.assertIsNone(m.snapshot()['remaining'])
        now[0]=3;m.record({'bytes':3000,'completed':3,'total':9});self.assertAlmostEqual(m.snapshot()['remaining'],6)
        m.pause(True);now[0]=103;self.assertTrue(m.snapshot()['paused']);m.pause(False)
        now[0]=106;m.record({'bytes':3000,'completed':6,'total':9});self.assertAlmostEqual(m.snapshot()['remaining'],3)
    def test_library_scan_leaves_ui_responsive_and_reader_changes_chapter(self):
        from PySide6.QtCore import QTimer
        from reading_ui import OfflineLibrary
        from library_ui import LibraryDialog
        import app
        application=QApplication.instance() or QApplication([])
        def pump(seconds):
            end=time.monotonic()+seconds
            while time.monotonic()<end:application.processEvents();time.sleep(.01)
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)):
            os.environ['TOONSHELF_TESTING']='1';host=app.Window();host.cover_timer.stop();host.path.setText(tmp)
            work=self.fixture(Path(tmp));work.update(genre='판타지',publisher='카카오',episodes=2,images=4,size=10000,last_downloaded='',thumbnail_image=None,missing=0,order_verified=1)
            def delayed(*args):time.sleep(.25);return [work]
            ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(15)
            with patch('reading.shelf_index',side_effect=delayed):
                dialog=LibraryDialog(host);dialog.show();pump(.45)
                self.assertGreater(len(ticks),5);self.assertEqual(len(dialog.rows),1);dialog.close()
            pane=OfflineLibrary(host);pane.root=Path(tmp);pane.show();pane.open_work(work);pump(.35)
            self.assertEqual(len(pane.images),2,pane.status.text());pane.read_scroll.verticalScrollBar().setValue(100);pane.save_position();pane.move(1);pump(.35)
            self.assertEqual(pane.chapter,1);pane.move(-1);pump(.35);self.assertGreater(pane.read_scroll.verticalScrollBar().value(),0)
            self.assertLessEqual(pane.canvas.cache_bytes,80*1024**2);timer.stop();self.assertTrue(pane.shutdown());pane.close();host.close();application.processEvents()

if __name__=='__main__':unittest.main()
