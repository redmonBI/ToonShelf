import json,sqlite3,tempfile,unittest
from contextlib import closing
from unittest.mock import patch
from pathlib import Path
from datetime import datetime
from core import Work,Episode
from collections_store import CollectionStore,filter_works
from automation_store import AutoStore,SEOUL
class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=CollectionStore(self.root/'collections.db');self.a=Work('A','https://example.com/webtoon/a.html',genre='판타지',publisher='네이버');self.b=Work('B','https://example.com/webtoon/b.html',genre='액션',publisher='카카오')
    def tearDown(self):self.tmp.cleanup()
    def test_filter_favorite_day_genre_publisher(self):
        self.s.update(self.a,favorite=True,weekday=1,genre='무협 판타지');self.s.update(self.b,weekday=2)
        self.assertEqual(filter_works([self.b,self.a],self.s,favorite_first=True),[self.a,self.b]);self.assertEqual(filter_works([self.a,self.b],self.s,weekday=1,genre='무협',publisher='네이버',favorite_only=True),[self.a]);self.assertEqual(filter_works([self.a,self.b],self.s,weekday=6),[])
    def test_collection_snapshot_and_validation(self):
        self.s.update(self.a,favorite=True,weekday=6);data=self.s.export_data();target=CollectionStore(self.root/'other.db');target.import_data(data);self.assertEqual(target.entries(),self.s.entries());data['collections'][0]['weekday']=8
        with self.assertRaises(ValueError):target.import_data(data)
        self.assertEqual(target.entries(),self.s.entries())
    def test_baseline_new_episode_dedup_and_empty(self):
        e1=Episode('1화','https://example.com/webtoons/a/1.html','',1,'1화');e2=Episode('2화','https://example.com/webtoons/a/2.html','',2,'2화')
        self.assertEqual(self.s.observe(self.a,[e1]),0);self.assertEqual(self.s.observe(self.a,[e1,e2]),1);self.assertEqual(self.s.observe(self.a,[e1,e2]),0);self.s.observe(self.a,[]);self.assertEqual(self.s.observe(self.a,[e2]),0);self.assertEqual(self.s.unread_count(),1);self.s.mark_read();self.assertEqual(self.s.unread_count(),0)
    def test_site_domain_rotation_keeps_episode_baseline(self):
        e=Episode('1화','https://example.com/webtoons/1.html','',1,'1화');self.s.observe(self.a,[e]);self.a.url='https://changed.com/webtoon/a.html';e.url='https://changed.com/webtoons/1.html';self.assertEqual(self.s.observe(self.a,[e]),0)
    def test_auto_migration_and_weekday_selection(self):
        path=self.root/'auto.db'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE entries(key TEXT PRIMARY KEY,work TEXT,category TEXT,selected INT,tail INT,keep_count INT,delete_days INT)');db.commit()
        store=AutoStore(path);store.add([self.a,self.b]);store.update('/webtoon/a.html',weekday=0)
        cfg={'site_url':'https://example.com'};self.assertEqual(len(store.payload(cfg,'all','manual')),2)
        store.save_schedule(dict(enabled=True,days=[0,1],time='10:00',scope='all',cleanup=False),datetime(2026,10,11,9,tzinfo=SEOUL))
        monday=store.claim_due(cfg,datetime(2026,10,12,11,tzinfo=SEOUL));self.assertEqual(len(monday[0]['payload']),2);store.mark(monday[0]['slot'],'queued','')
        tuesday=store.claim_due(cfg,datetime(2026,10,13,11,tzinfo=SEOUL));self.assertEqual([i['work']['title'] for i in tuesday[0]['payload']],['B'])
    def test_auto_import_never_enables_cleanup(self):
        a=AutoStore(self.root/'auto.db');a.add([self.a]);a.update('/webtoon/a.html',weekday=4);a.save_schedule(dict(enabled=True,days=[4],time='10:00',scope='all',cleanup=True));b=AutoStore(self.root/'other-auto.db');b.import_data(a.export_data());self.assertEqual(b.entries()[0]['weekday'],4);self.assertFalse(b.schedule()['cleanup'])
    def test_check_updates_only_observes_successful_favorites_and_automatic(self):
        from collections_store import check_updates
        from core import Control
        self.s.update(self.a,favorite=True);self.s.update(self.b,favorite=False);auto=AutoStore(self.root/'auto.db');auto.add([self.b]);events=[]
        class BrowserFixture:
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def episodes(self,work):
                if work.title=='B':raise PermissionError('403')
                return [Episode('1화','https://changed.com/webtoons/1.html','',1,'1화')]
        with patch('core.Browser',BrowserFixture),patch.object(Control,'delay'):
            result=check_updates(self.s,auto,{'site_url':'https://changed.com'},Control(),lambda k,v:events.append((k,v)))
        self.assertEqual(result['checked'],2);self.assertEqual(result['added'],0);self.assertEqual(len(result['errors']),1)
        with self.s.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM episode_baselines').fetchone()[0],1)
if __name__=='__main__':unittest.main()
