import hashlib
import json
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
from core import Archive,Work,Episode,Control,publisher_name
from library import LibraryArchive,export_mobile,format_time


def picture(color,size=(200,300)):
    stream=BytesIO();Image.new('RGB',size,color).save(stream,'PNG');return stream.getvalue()


class LibraryTests(unittest.TestCase):
    def fixture(self,root):
        a=LibraryArchive(root)
        w=Work('검증 작품','https://example.com/webtoon/1.html',genre='판타지 액션',publisher='네이버')
        e=Episode('검증 작품 1화','https://example.com/webtoons/1/10.html','2026-10-08',1,'1화')
        a.record_work(w);a.record_episode(w,e,1)
        urls=['https://image.test/z.png','https://image.test/a.png']
        a.record_order(w,e,urls)
        a.save(w,e,urls[0],picture('red'),(100,100),1)
        a.save(w,e,urls[1],picture('blue'),(100,100),2)
        a.episode_status(w,e,'complete','')
        return a,w,e,urls

    def test_order_cbz_and_unchanged_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'archive';out=Path(tmp)/'export'
            a,w,e,urls=self.fixture(root)
            original=(root/'검증 작품/1화/z.png').read_bytes();a.close()
            result=export_mobile(root,['/webtoon/1.html'],out,{'format':'cbz','optimize':False,'group':'publisher'},Control(),lambda *a:None)
            cbz=next(Path(result['path']).rglob('*.cbz'))
            self.assertEqual(cbz.name,'0001_1화.cbz')
            with ZipFile(cbz) as z:
                self.assertEqual(z.namelist()[:2],['000001.png','000002.png'])
                self.assertEqual(z.read('000001.png'),original)
                self.assertEqual(z.testzip(),None)
            self.assertEqual((root/'검증 작품/1화/z.png').read_bytes(),original)
            self.assertEqual(result['output_bytes'],sum(p.stat().st_size for p in Path(result['path']).rglob('*') if p.is_file()))

    def test_legacy_dates_unknown_until_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old=Archive(root);w=Work('기존','https://a/webtoon/1.html');e=Episode('기존 1화','https://a/webtoons/1/1.html','2020-01-01',1,'1화')
            old.save(w,e,'https://a/z.png',picture('red'),(100,100));old.episode_status(w,e,'complete','');old.close()
            new=LibraryArchive(root)
            rows=new.episodes('/webtoon/1.html')
            self.assertEqual(rows[0]['upload_date'],'')
            self.assertEqual(rows[0]['order_verified'],0)
            self.assertTrue(rows[0]['first_downloaded'])
            new.close()
            with self.assertRaisesRegex(ValueError,'순서 확인'):
                export_mobile(root,['/webtoon/1.html'],root.parent/(root.name+'_export'),{'format':'cbz'},Control(),lambda *a:None)

    def test_custom_classification_survives_site_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,w,e,urls=self.fixture(Path(tmp))
            a.properties('/webtoon/1.html','무협','카카오')
            a.record_work(w)
            self.assertEqual(a.works()[0]['genre'],'무협');self.assertEqual(a.works()[0]['publisher'],'카카오')
            a.close()

    def test_download_date_not_changed_by_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,w,e,urls=self.fixture(Path(tmp))
            before=a.episodes('/webtoon/1.html')[0]
            a.record_episode(w,e,1);a.record_order(w,e,urls)
            after=a.episodes('/webtoon/1.html')[0]
            self.assertEqual(before['first_downloaded'],after['first_downloaded'])
            self.assertEqual(before['last_downloaded'],after['last_downloaded'])
            self.assertEqual(after['upload_date'],'2026-10-08');a.close()

    def test_export_rejects_corruption_and_original_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'archive';a,w,e,urls=self.fixture(root);a.close()
            with self.assertRaises(ValueError):export_mobile(root,['/webtoon/1.html'],root,{},Control(),lambda *a:None)
            (root/'검증 작품/1화/z.png').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'손상'):
                export_mobile(root,['/webtoon/1.html'],Path(tmp)/'out',{},Control(),lambda *a:None)

    def test_seoul_time(self):
        self.assertEqual(format_time('2026-10-09 00:30:00'),'2026-10-09 09:30')
        self.assertEqual(format_time('2026-10-09 00:30:00','utc'),'2026-10-09 00:30')

    def test_publisher_icons(self):
        for slug,name in [('naver','네이버'),('kakao','카카오'),('anitoon','애니툰'),('bom','봄툰'),('etc','기타')]:
            self.assertEqual(publisher_name(f'https://site.test/style/img/{slug}.png?1'),name)

    def test_export_selected_episode_does_not_include_unfinished_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'archive';a,w,e,urls=self.fixture(root)
            second=Episode('검증 작품 2화','https://example.com/webtoons/1/11.html','2026-10-09',2,'2화')
            a.record_episode(w,second,2);a.record_order(w,second,['https://image.test/second.png'])
            a.save(w,second,'https://image.test/second.png',picture('green'),(100,100),1)
            a.episode_status(w,second,'partial','검증용 누락');a.close()
            result=export_mobile(root,['/webtoon/1.html'],Path(tmp)/'out',{'format':'cbz','episode_keys':['/webtoon/1.html|/webtoons/1/10.html']},Control(),lambda *a:None)
            self.assertEqual(result['episode_count'],1)

    def test_folder_export_resize_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'archive';a,w,e,urls=self.fixture(root)
            # A noisy PNG produces a meaningful JPEG reduction.
            noise=Image.effect_noise((1400,2000),80).convert('RGB');stream=BytesIO();noise.save(stream,'PNG')
            a.save(w,e,urls[0],stream.getvalue(),(100,100),1);a.close()
            result=export_mobile(root,['/webtoon/1.html'],Path(tmp)/'out',{'format':'folder','optimize':True,'quality':80,'width':700,'group':'genre'},Control(),lambda *a:None)
            files=list(Path(result['path']).rglob('000001.jpg'));self.assertEqual(len(files),1)
            with Image.open(files[0]) as image:self.assertEqual(image.size,(700,1000))
            self.assertTrue(list(Path(result['path']).rglob('_reading_order.json')))
            self.assertLess(result['output_bytes'],result['source_bytes'])


if __name__=='__main__':unittest.main()
