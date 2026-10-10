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
