import hashlib
import tempfile
import unittest
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock, patch
from io import BytesIO
from pathlib import Path

from PIL import Image
from core import Archive, Browser, Control, Episode, Work, download, parse_episodes, parse_images, safe_name, validate_url


def image(width, height, color='green'):
    stream = BytesIO()
    Image.new('RGB', (width, height), color).save(stream, format='PNG')
    return stream.getvalue()


class CoreTests(unittest.TestCase):
    def browser_stub(self):
        browser = Browser({}, Control(), Mock())
        browser.image_cache = OrderedDict()
        browser.image_cache_bytes = 0
        browser.user_agent = 'Actual browser UA'
        browser.ctx = SimpleNamespace(request=Mock())
        return browser

    def test_browser_delivered_image_is_not_requested_again(self):
        b = self.browser_stub()
        b.capture_images = True
        response = SimpleNamespace(url='https://cdn.test/a.jpg', status=200,
            request=SimpleNamespace(resource_type='image'), headers={'content-type':'image/jpeg'}, body=lambda:b'original')
        b.capture_image_response(response)
        self.assertEqual(b.fetch(response.url,'https://site.test/episode/1'), b'original')
        b.ctx.request.get.assert_not_called()
        self.assertEqual(b.image_cache_bytes,0)

    def test_cross_origin_referrer_and_browser_agent(self):
        b=self.browser_stub()
        b.ctx.request.get.return_value=SimpleNamespace(status=200,ok=True,body=lambda:b'image')
        self.assertEqual(b.fetch('https://cdn.test/a.jpg','https://site.test/episode/1'),b'image')
        headers=b.ctx.request.get.call_args.kwargs['headers']
        self.assertEqual(headers['Referer'],'https://site.test/')
        self.assertEqual(headers['User-Agent'],'Actual browser UA')
        b.fetch('https://site.test/a.jpg','https://site.test/episode/1')
        self.assertEqual(b.ctx.request.get.call_args.kwargs['headers']['Referer'],'https://site.test/episode/1')

    def test_denied_images_are_not_cached_or_retried(self):
        b=self.browser_stub();b.capture_images=True
        response=SimpleNamespace(status=403,request=SimpleNamespace(resource_type='image'))
        b.capture_image_response(response)
        b.ctx.request.get.return_value=response
        with self.assertRaises(PermissionError):
            b.fetch('https://cdn.test/a.jpg','https://site.test/episode/1')
        self.assertEqual(b.ctx.request.get.call_count,1)
        self.assertFalse(b.image_cache)

    def test_invalid_nested_url_is_not_requested(self):
        b=self.browser_stub()
        with self.assertRaises(ValueError):
            b.fetch('https://cdn.test/https://other.test/a.svg','https://site.test/1')
        b.ctx.request.get.assert_not_called()

    def test_one_denied_image_continues_to_next_episode(self):
        work=Work('work','https://site.test/work/1')
        episodes=[Episode('ep',f'https://site.test/ep/{n}','',n,f'{n}') for n in [1,2]]
        browser=Mock();browser.__enter__=Mock(return_value=browser);browser.__exit__=Mock(return_value=False)
        browser.episodes.return_value=episodes
        browser.visit.return_value='<div id="imgs"><img src="https://cdn.test/a.jpg"><img src="https://cdn.test/b.jpg"></div>'
        browser.fetch.side_effect=[PermissionError('403'),b'data',b'data',b'data']
        archive=Mock();archive.existing.return_value=False;archive.save.return_value=Path('saved.jpg')
        cfg={'output_dir':'.','image_selector':'#imgs img','min_width':100,'min_height':100,'delay':0}
        with patch('core.Browser',return_value=browser),patch('library.LibraryArchive',return_value=archive):
            result=download(cfg,[work],Control(),Mock())
        self.assertEqual(result['episodes'],2)
        self.assertEqual(result['saved'],3)
        self.assertEqual(result['failed'],1)
        self.assertEqual([c.args[2] for c in archive.episode_status.call_args_list],['partial','complete'])

    def test_repeated_denials_stop_further_requests(self):
        work=Work('work','https://site.test/work/1')
        browser=Mock();browser.__enter__=Mock(return_value=browser);browser.__exit__=Mock(return_value=False)
        browser.episodes.return_value=[Episode('ep','https://site.test/ep/1','',1,'1')]
        browser.visit.return_value='<div id="imgs">'+''.join(f'<img src="https://cdn.test/{n}.jpg">' for n in range(5))+'</div>'
        browser.fetch.side_effect=PermissionError('403')
        archive=Mock();archive.existing.return_value=False
        cfg={'output_dir':'.','image_selector':'#imgs img','min_width':100,'min_height':100,'delay':0}
        with patch('core.Browser',return_value=browser),patch('library.LibraryArchive',return_value=archive):
            with self.assertRaises(PermissionError):
                download(cfg,[work],Control(),Mock())
        self.assertEqual(browser.fetch.call_count,3)
        archive.close.assert_called_once()

    def test_episode_order_and_parts(self):
        html = ''.join(f'<a href="/webtoons/1/{i}.html">작품 {name}<span>{date}</span></a>' for i, name, date in
            [(3, '10화', '2026-10-03'), (2, '2화', '2026-10-02'), (1, '1화', '2026-10-01'),
             (4, '외전 1화', '2026-10-04'), (5, '시즌2 1화', '2026-10-05'), (6, '2화 (하)', '2026-10-06')])
        episodes = parse_episodes(html, 'https://example.com', '작품')
        self.assertEqual([e.folder for e in episodes], ['1화', '2화', '10화', '외전 1화', '시즌2 1화', '2화 (하)'])

    def test_image_scope_and_lazy_loading(self):
        html = '<img src="/ad.jpg"><div id="toon_content_imgs"><img data-original="/a.jpg" src="/loading.gif"><img src="/b.jpg"><img src="/b.jpg"></div>'
        self.assertEqual(parse_images(html, 'https://example.com', '#toon_content_imgs img'), ['https://example.com/a.jpg', 'https://example.com/b.jpg'])

    def test_size_original_names_resume_and_damage(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Archive(Path(tmp))
            work = Work('작품', 'https://old.com/webtoon/1.html')
            ep = Episode('작품 1화', 'https://old.com/webtoons/1/11.html', '2026-10-01', 1, '1화')
            self.assertIsNone(archive.save(work, ep, 'https://img.com/tiny.png', image(99,200), (100,100)))
            self.assertIsNone(archive.save(work, ep, 'https://img.com/short.png', image(200,99), (100,100)))
            path = archive.save(work, ep, 'https://img.com/original.png', image(100,100), (100,100))
            self.assertEqual(path.relative_to(Path(tmp)), Path('작품/1화/original.png'))
            key = archive.key(work, ep, 'https://img.com/original.png')
            self.assertTrue(archive.existing(key))
            work.url = 'https://new.com/webtoon/1.html'
            ep.url = 'https://new.com/webtoons/1/11.html'
            self.assertEqual(key, archive.key(work, ep, 'https://newcdn.com/original.png'))
            path.write_bytes(b'broken')
            self.assertFalse(archive.existing(key))
            repaired = archive.save(work, ep, 'https://newcdn.com/original.png', image(100,100), (100,100))
            self.assertEqual(path, repaired)
            self.assertTrue(archive.existing(key))
            archive.close()

    def test_numeric_order_despite_reposted_dates(self):
        html = '<a href="/webtoons/1/2.html">작품 2화 2026-10-01</a><a href="/webtoons/1/1.html">작품 1화 2026-10-05</a>'
        self.assertEqual([e.folder for e in parse_episodes(html, 'https://a', '작품')], ['1화', '2화'])

    def test_collision_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Archive(Path(tmp))
            work = Work('작품', 'https://a/webtoon/1.html')
            ep = Episode('', 'https://a/webtoons/1/1.html', '', 1, '1화')
            first = archive.save(work, ep, 'https://a/folder1/a.png', image(100,100), (100,100))
            second = archive.save(work, ep, 'https://a/folder2/a.png', image(100,100,'red'), (100,100))
            self.assertNotEqual(first, second)
            self.assertNotEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
            self.assertFalse(list(Path(tmp).rglob('*.part')))
            archive.close()

    def test_windows_names(self):
        self.assertEqual(safe_name('../CON'), '_CON')
        self.assertEqual(safe_name('CON.png'), '_CON.png')
        self.assertEqual(safe_name('제목: 테스트?'), '제목_ 테스트_')
        with self.assertRaises(ValueError):
            validate_url('file:///C:/')


if __name__ == '__main__':
    unittest.main()

