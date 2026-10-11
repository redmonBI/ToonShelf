import os,tempfile,unittest,json
os.environ['TOONSHELF_TESTING']='1';os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from core import Work
from work_metadata import match_catalog,extract_date,merged_work
from collections_store import CollectionStore,filter_works
from automation_store import AutoStore
from shelf_collections import enrich_shelf
class MetadataTests(unittest.TestCase):
    def test_exact_title_unique_matching_and_ambiguous_protection(self):
        original=Work('별빛 의 여행','https://old.example/webtoon/a.html');site=Work('별빛의 여행','https://new.example/webtoon/b.html',publisher='네이버',weekday=2,weekdays=[2,5]);match,reason=match_catalog(original,[site]);self.assertEqual(match['publisher'],'네이버');merged=merged_work(original,match,reason);self.assertEqual(merged['url'],original.url);self.assertEqual(merged['metadata_url'],site.url)
        self.assertIsNone(match_catalog(original,[site,Work(site.title,'https://new.example/webtoon/c.html')])[0])
    def test_multi_weekday_and_date_filter_with_manual_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=CollectionStore(Path(tmp)/'c.db');w=Work('Demo','https://example.org/a',publisher='네이버',weekdays=[0,4],updated_date='2026-10-11')
            self.assertEqual(filter_works([w],s,weekday=[2,4],publisher='네이버',start_date='2026-10-10',end_date='2026-10-11'),[w]);self.assertEqual(filter_works([w],s,weekday=[]),[]);self.assertEqual(filter_works([w],s,start_date='bad'),[])
            s.update(w,weekday=1);self.assertEqual(filter_works([w],s,weekday=[0,4]),[]);self.assertEqual(filter_works([w],s,weekday=[1]),[w])
    def test_metadata_refresh_preserves_manual_values_and_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=CollectionStore(Path(tmp)/'c.db');a=AutoStore(Path(tmp)/'a.db');w=Work('A','https://example.org/a',genre='old');a.add([w]);a.update('/a',tail=20,selected=0,weekday=1);c.update(w,genre='사용자 장르',favorite=True)
            new=dict(vars(w),genre='사이트 장르',publisher='네이버',updated_date='2026-10-11',weekdays=[4]);a.apply_metadata([new]);c.apply_metadata([new]);self.assertEqual(c.get(w)['genre'],'사용자 장르');self.assertEqual(c.get(w)['publisher'],'네이버');self.assertEqual(a.entries()[0]['tail'],20);self.assertEqual(a.entries()[0]['weekday'],1);self.assertEqual(a.entries()[0]['selected'],0)
    def test_empty_library_merges_automatic_works_without_fake_chapters(self):
        entries=[dict(key='/a',work=dict(title='A',url='https://example.org/a',genre='',publisher='',weekdays=[2]),selected=1,category='planned',tail=10),dict(key='/b',work=dict(title='B',url='https://example.org/b'),selected=0,category='held')]
        rows=enrich_shelf([],[],entries);self.assertEqual([w['storage_scope'] for w in rows],['planned','empty']);self.assertFalse(any(w['has_download'] for w in rows));self.assertEqual(rows[0]['chapters'],[])
    def test_date_is_real_calendar_date(self):
        self.assertEqual(extract_date('UP 2026.10.11'),'2026-10-11');self.assertEqual(extract_date('2026-02-31'),'')
    def test_checkboxes_select_multiple_and_unchecking_all_is_empty(self):
        from PySide6.QtWidgets import QApplication
        from weekday_checks import WeekdayChecks
        q=QApplication.instance() or QApplication([]);widget=WeekdayChecks();self.assertIsNone(widget.currentData());widget.boxes[0].setChecked(True);widget.boxes[4].setChecked(True);self.assertEqual(widget.currentData(),[0,4]);widget.set_days([]);self.assertEqual(widget.currentData(),[])
if __name__=='__main__':unittest.main()
