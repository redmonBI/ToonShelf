import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['TOONSHELF_TESTING']='1'
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QPushButton
from pagination import Pagination,page_numbers
import themes

class AppearanceTests(unittest.TestCase):
 def test_focus_controls_restore_navigation_and_keep_reading_position(self):
  import app
  from reading_ui import OfflineLibrary
  from PySide6.QtTest import QTest
  q=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)):
   w=app.Window();w.cover_timer.stop();pane=OfflineLibrary(w);w.offline=pane;w.content_stack.addWidget(pane);w.content_stack.setCurrentWidget(pane);pane.stack.setCurrentIndex(1);pane.loading.hide()
   pane.images=[dict(width=300,height=1200,path='',error='검증 이미지') for _ in range(5)]
   w.show();QTest.qWait(250);pane.apply_width();QTest.qWait(50);bar=pane.read_scroll.verticalScrollBar();bar.setValue(int(bar.maximum()*.45));height=pane.read_scroll.viewport().height()
   w.set_view_preference('reader_focus',True);QTest.qWait(300)
   self.assertGreater(pane.read_scroll.viewport().height(),height);self.assertFalse(w.app_toolbar.isVisible());self.assertFalse(w.sidebar.isVisible());self.assertFalse(pane.reader_bar.isVisible());self.assertFalse(pane.reader_footer.isVisible());self.assertTrue(pane.quick.isVisible());self.assertAlmostEqual(bar.value()/bar.maximum(),.45,delta=.01)
   pane.escape();QTest.qWait(300);self.assertTrue(w.app_toolbar.isVisible());self.assertTrue(pane.reader_bar.isVisible());self.assertTrue(pane.reader_footer.isVisible());self.assertFalse(pane.quick.isVisible());self.assertAlmostEqual(bar.value()/bar.maximum(),.45,delta=.01)
   w.set_view_preference('reader_focus',True);w.show_catalog();q.processEvents();self.assertTrue(w.sidebar.isVisible());self.assertTrue(w.app_toolbar.isVisible());self.assertTrue(w.cfg['reader_focus']);w.close();q.processEvents()
 def test_custom_background_only_colors_space_and_survives_restart(self):
  import app
  from reading_ui import OfflineLibrary
  from PySide6.QtGui import QImage,QColor
  q=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)):
   w=app.Window();w.cover_timer.stop();pane=OfflineLibrary(w);w.offline=pane;w.content_stack.addWidget(pane)
   w.set_view_preference('reader_background','#AbC123');self.assertEqual(w.cfg['reader_background'],'#abc123')
   canvas=pane.canvas;canvas.resize(800,200);canvas.width_read=100;canvas.items=[dict(error='')];canvas.offsets=[0,100];image=QImage(100,100,QImage.Format_RGB32);image.fill(QColor('red'));canvas.cache[0]=image
   rendered=canvas.grab().toImage();self.assertEqual(rendered.pixelColor(10,50).name(),'#abc123');self.assertEqual(rendered.pixelColor(rendered.width()//2,50).name(),'#ff0000')
   w.apply_theme('dark');self.assertEqual(canvas.background.name(),'#abc123')
   with self.assertRaises(ValueError):w.set_view_preference('reader_background','invalid')
   w.close();q.processEvents();other=app.Window();other.cover_timer.stop();self.assertEqual(other.cfg['reader_background'],'#abc123');other.close();q.processEvents();themes.apply(q,'white')
 def test_settings_center_applies_saves_and_reopens_preferences(self):
  import app
  from preferences_ui import SettingsCenter
  q=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)):
   w=app.Window();w.cover_timer.stop();before=dict(w.cfg);dialog=SettingsCenter(w,1);self.assertEqual(w.cfg,before);self.assertEqual(dialog.tabs.count(),4)
   dialog.reader_hide_top.setChecked(True);dialog.reader_hide_bottom.setChecked(True);dialog.read_width.setValue(1000);dialog.set_background('#f4ecd8');dialog.menu_compact.setChecked(True)
   saved=json.loads((Path(tmp)/'settings.json').read_text(encoding='utf-8'));self.assertTrue(saved['reader_hide_top']);self.assertTrue(saved['reader_hide_bottom']);self.assertEqual(saved['reader_width'],1000);self.assertEqual(saved['reader_background'],'#f4ecd8')
   dialog.close();reopened=SettingsCenter(w);self.assertTrue(reopened.reader_hide_top.isChecked());self.assertEqual(reopened.read_width.value(),1000);reopened.set_background('');self.assertEqual(w.cfg['reader_background'],'');reopened.close()
   with patch.object(w,'updates_dialog') as update:
    manager=SettingsCenter(w,3);manager.show();q.processEvents();next(b for b in manager.findChildren(QPushButton) if b.text()=='업데이트 확인·기존 폴더 패치').click();q.processEvents();self.assertFalse(manager.isVisible());update.assert_called_once()
   w.close();q.processEvents()
 def test_panel_controls_persist_and_navigation_stays_available(self):
  import app
  q=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)):
   w=app.Window();w.cover_timer.stop();w.show();q.processEvents()
   w.menu_toggle.click();w.rules_toggle.click();q.processEvents()
   self.assertEqual(w.sidebar.width(),68);self.assertFalse(w.right_rail.isVisible());self.assertTrue(w.compact_download.isVisible())
   self.assertEqual(w.library_nav.accessibleName(),'▣   다운로드 작품')
   self.assertEqual(w.library_nav.text(),'▣')
   w.url.setText('[https://blacktoon423.com](https://blacktoon423.com)')
   self.assertEqual(w.read_cfg()['site_url'],'https://blacktoon423.com');self.assertEqual(w.url.text(),'https://blacktoon423.com')
   w.close();q.processEvents()
   other=app.Window();other.cover_timer.stop();other.show();q.processEvents()
   self.assertEqual(other.sidebar.width(),68);self.assertFalse(other.right_rail.isVisible())
   other.menu_toggle.click();other.rules_toggle.click();q.processEvents()
   self.assertEqual(other.sidebar.width(),186);self.assertTrue(other.right_rail.isVisible());self.assertFalse(other.compact_download.isVisible())
   other.close();q.processEvents()
 def test_large_page_range_is_bounded_and_jump_clamps(self):
  self.assertEqual(page_numbers(1,675),[1,2,3,4,5,675])
  self.assertEqual(page_numbers(674,675),[1,671,672,673,674,675])
  self.assertEqual(page_numbers(9,0),[1])
  self.assertLessEqual(len(page_numbers(338,675)),7)
  q=QApplication.instance() or QApplication([]);pager=Pagination();calls=[];pager.requested.connect(calls.append)
  pager.update_pages(0,675);pager.findChildren(QPushButton)[3].click()
  self.assertTrue(calls);pager.jump.setValue(300);pager.go();self.assertEqual(calls[-1],299)
  pager.update_pages(674,1);self.assertEqual(pager.current,0);self.assertFalse(pager.next.isEnabled());pager.close()
 def test_real_page_buttons_filters_and_theme_persistence(self):
  import app
  from core import Work
  from reading_ui import OfflineLibrary
  q=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as tmp,patch.object(app,'STATE',Path(tmp)):
   w=app.Window();w.cover_timer.stop()
   w.works=[Work(f'작품 {n:03}',f'https://example.com/{n}') for n in range(150)]
   w.render()
   with patch.object(w,'launch'):
    button=next(b for b in w.pager.findChildren(QPushButton) if b.text()=='3');button.click()
    self.assertEqual(w.page_index,2);self.assertEqual(set(w.cards),{x.url for x in w.works[48:72]})
    w.go_page(999);self.assertEqual(w.page_index,6)
    w.search.setText('작품 001');self.assertEqual(w.page_index,0);self.assertEqual(w.pager.total,1)
    w.cover_timer.stop()
   shelf=OfflineLibrary(w);shelf.rows=[dict(key=str(n),title=f'작품{n}',genre='',publisher='',last_downloaded='',size=1,episodes=1,thumbnail_image=None) for n in range(70)];shelf.render();shelf.go_page(3);self.assertEqual(shelf.page,3)
   for value in themes.THEMES:
    w.apply_theme(value);self.assertNotIn('@',q.styleSheet());self.assertEqual(shelf.canvas.palette().window().color().name(),themes.colors(value)['bg'])
    self.assertEqual(json.loads((Path(tmp)/'settings.json').read_text(encoding='utf-8'))['theme'],value)
   self.assertTrue(shelf.shutdown());shelf.close();w.close();q.processEvents()
   reopened=app.Window();self.assertEqual(reopened.cfg['theme'],'emphasis');reopened.close();q.processEvents()
   themes.apply(q,'white')

if __name__=='__main__':unittest.main()
