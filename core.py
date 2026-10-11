from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
_ARCHIVE_INIT_LOCK=threading.Lock()
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from PIL import Image


class Cancelled(Exception):
    pass


def safe_name(value: str, fallback="untitled") -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', value).strip(' .')
    value = value[:110].rstrip(' .') or fallback
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', value, re.I):
        value = '_' + value
    return value


def validate_url(value: str) -> str:
    from link_input import normalize_url
    return normalize_url(value).rstrip('/')


@dataclass
class Work:
    title: str
    url: str
    thumbnail: str = ''
    latest: str = ''
    genre: str = ''
    cover: str = ''
    publisher: str = ''


@dataclass
class Episode:
    title: str
    url: str
    date: str
    number: float
    folder: str


def parse_catalog(html: str, base: str) -> list[Work]:
    soup = BeautifulSoup(html, 'html.parser')
    found: dict[str, Work] = {}
    for a in soup.select('a[href]'):
        href = urljoin(base, a['href'])
        if not re.search(r'/webtoon/[^/]+\.html', urlsplit(href).path):
            continue
        title = a.get('title') or a.get('alt')
        heading = a.select_one('h3')
        if not title and heading:
            title = heading.get_text(' ', strip=True).removeprefix('UP').strip()
        if not title:
            continue
        work = found.setdefault(href, Work(title=title, url=href))
        img = a.select_one('img[data-original], img.thumb2, img.back-img-style')
        if img:
            work.thumbnail = urljoin(base, img.get('data-original') or img.get('src') or '')
        card = a.find_parent(class_='card') or a
        platform = card.select_one('.platfrom-style img, .platform-style img')
        if platform:
            work.publisher = publisher_name(platform.get('alt') or platform.get('src', ''))
        if card.select_one('h3'):
            paragraphs = card.select('p')
            if len(paragraphs) >= 2:
                work.genre = paragraphs[0].get_text(' ', strip=True)
                work.latest = paragraphs[1].get_text(' ', strip=True)
    return list(found.values())


def publisher_name(value: str) -> str:
    names = {'naver':'네이버', 'daum':'다음', 'kakao':'카카오', 'rejin':'레진', 'lezhin':'레진',
             'tomics':'투믹스', 'toptoon':'탑툰', 'comica':'코미카', 'battlecomics':'배틀코믹',
             'comicgt':'코믹GT', 'ktoon':'케이툰', 'anytoon':'애니툰', 'anitoon':'애니툰', 'foxtoon':'폭스툰',
             'peanutoon':'피너툰', 'bomtoon':'봄툰', 'bom':'봄툰', 'comico':'코미코', 'mootoon':'무툰','etc':'기타'}
    if value in names.values():
        return value
    token = Path(urlsplit(value).path).stem.lower()
    return names.get(token, value if value and '://' not in value and '/' not in value else '')


def parse_episodes(html: str, base: str, work_title: str) -> list[Episode]:
    soup = BeautifulSoup(html, 'html.parser')
    found = {}
    for a in soup.select('a[href]'):
        url = urljoin(base, a['href'])
        if not re.search(r'/webtoons/[^/]+/[^/]+\.html', urlsplit(url).path):
            continue
        text = a.get_text(' ', strip=True)
        date_match = re.search(r'20\d{2}-\d{2}-\d{2}', text)
        date = date_match.group() if date_match else ''
        title = re.sub(r'20\d{2}-\d{2}-\d{2}', '', text).strip()
        label = title.removeprefix(work_title).strip()
        numbers = re.findall(r'(\d+(?:\.\d+)?)(?:-(\d+))?\s*화', label)
        number = float(numbers[-1][0]) if numbers else -1
        # Keep seasons, parts and extras, but strip unrelated story subtitles.
        match = re.search(r'^(.*?\d+(?:\.\d+)?(?:-\d+)?\s*화)(\s*\([^)]+\))?', label)
        folder = (match.group(0).strip() if match else label) or safe_name(urlsplit(url).path.split('/')[-1])
        folder = re.sub(r'(?<!\d)0+(\d+)(?=화)', r'\1', folder)
        found[url] = Episode(title, url, date, number, safe_name(folder))
    # Publication dates preserve season resets. Numeric ties sort 1, 2, 10 correctly.
    def natural(value):
        return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r'(\d+)', value))
    episodes = sorted(found.values(), key=lambda e: (e.date or '0000', e.number, natural(e.folder), e.url))
    plain = all(re.fullmatch(r'\d+(?:\.\d+)?(?:-\d+)?\s*화(?:\s*\([^)]+\))?', e.folder) for e in episodes)
    if plain or not any(e.date for e in episodes):
        episodes.sort(key=lambda e: (e.number, natural(e.folder), e.url))
    used = set()
    for e in episodes:
        if e.folder.casefold() in used:
            e.folder += '_' + Path(urlsplit(e.url).path).stem
        used.add(e.folder.casefold())
    return episodes


def parse_images(html: str, base: str, selector: str) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    result = []
    for img in soup.select(selector):
        raw = img.get('data-original') or img.get('data-src') or img.get('src') or ''
        url = urljoin(base, raw)
        if urlsplit(url).scheme in ('http', 'https') and url not in result:
            result.append(url)
    return result


class Archive:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / '.toonshelf.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS images (key TEXT PRIMARY KEY, path TEXT, sha TEXT, width INT, height INT, size INT, saved TEXT DEFAULT CURRENT_TIMESTAMP)')
        self.db.execute('CREATE TABLE IF NOT EXISTS episodes (key TEXT PRIMARY KEY, title TEXT, status TEXT, detail TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP)')
        self.db.commit()

    def key(self, work: Work, episode: Episode, image: str) -> str:
        # Domain changes do not invalidate an unchanged work/episode/image path.
        return '|'.join([urlsplit(work.url).path, urlsplit(episode.url).path, urlsplit(image).path])

    def existing(self, key: str) -> bool:
        row = self.db.execute('SELECT path,sha FROM images WHERE key=?', (key,)).fetchone()
        if not row:
            return False
        path = self.root / row[0]
        return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row[1]

    def save(self, work: Work, episode: Episode, url: str, data: bytes, minimum: tuple[int, int]):
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            image.verify()
        if width < minimum[0] or height < minimum[1]:
            return None
        folder = self.root / safe_name(work.title) / episode.folder
        folder.mkdir(parents=True, exist_ok=True)
        raw = unquote(urlsplit(url).path.rsplit('/', 1)[-1])
        filename = safe_name(raw, hashlib.sha256(url.encode()).hexdigest()[:16] + '.img')
        dest = folder / filename
        sha = hashlib.sha256(data).hexdigest()
        prior = self.db.execute('SELECT path FROM images WHERE key=?', (self.key(work, episode, url),)).fetchone()
        recorded_path = (self.root / prior[0]) if prior else None
        if recorded_path is not None and recorded_path.parent == folder:
            dest = recorded_path
        # Different URLs with an identical filename must never overwrite each other.
        if dest.exists() and dest != recorded_path and hashlib.sha256(dest.read_bytes()).hexdigest() != sha:
            suffix = hashlib.sha256(url.encode()).hexdigest()[:8]
            dest = folder / (Path(filename).stem + '_' + suffix + Path(filename).suffix)
        temp = dest.with_name(dest.name + '.part')
        temp.write_bytes(data)
        temp.replace(dest)
        self.db.execute('INSERT OR REPLACE INTO images(key,path,sha,width,height,size) VALUES(?,?,?,?,?,?)',
                        (self.key(work, episode, url), str(dest.relative_to(self.root)), sha, width, height, len(data)))
        self.db.commit()
        return dest

    def episode_status(self, work, episode, status, detail):
        key = urlsplit(work.url).path + '|' + urlsplit(episode.url).path
        self.db.execute('INSERT OR REPLACE INTO episodes(key,title,status,detail) VALUES(?,?,?,?)', (key, episode.title, status, detail))
        self.db.commit()

    def close(self):
        self.db.close()


class Browser:
    def __init__(self, cfg: dict, control, emit):
        self.cfg, self.control, self.emit = cfg, control, emit
        from transfer_policy import TransferPolicy
        self.policy=TransferPolicy(cfg if cfg.get('_download_job') else {})

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        errors = []
        for channel in ['chrome', 'msedge', None]:
            try:
                self.browser = self.pw.chromium.launch(channel=channel, headless=not self.cfg.get('visible_browser', False))
                break
            except Exception as exc:
                errors.append(str(exc).splitlines()[0])
        else:
            self.pw.stop()
            raise RuntimeError('Chrome 또는 Edge를 설치하세요. ' + ' / '.join(errors))
        self.ctx = self.browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
        self.page = self.ctx.new_page()
        self.image_cache = OrderedDict()
        self.image_cache_bytes = 0
        self.capture_images = False
        self.user_agent = self.page.evaluate('navigator.userAgent')
        self.page.on('response', self.capture_image_response)
        self.page.on('popup', lambda p: p.close())
        if self.cfg.get('_download_job'):
            self.ctx.route('**/*',lambda route:route.abort() if route.request.resource_type=='image' and self.capture_images and self.policy.managed() else route.continue_())
        return self

    def capture_image_response(self, response):
        # Reuse images delivered during an ordinary page load. No second request
        # is needed and the browser's cookies/referrer remain intact.
        if not self.capture_images or response.request.resource_type != 'image' or response.status != 200:
            return
        try:
            if not response.headers.get('content-type', '').lower().startswith('image/'):
                return
            data = response.body()
            limit = 64 * 1024 * 1024
            if not data or len(data) > limit:
                return
            old = self.image_cache.pop(response.url, b'')
            self.image_cache_bytes -= len(old)
            while self.image_cache and self.image_cache_bytes + len(data) > limit:
                _, old = self.image_cache.popitem(last=False)
                self.image_cache_bytes -= len(old)
            self.image_cache[response.url] = data
            self.image_cache_bytes += len(data)
        except Exception:
            # Aborted/lazy responses can still be fetched normally below.
            pass

    def __exit__(self, *args):
        self.browser.close()
        self.pw.stop()

    def visit(self, url: str, selector: str):
        self.control.check()
        self.policy.gate(self.control,self.emit)
        self.capture_images = False
        self.image_cache.clear()
        self.image_cache_bytes = 0
        self.capture_images = selector == self.cfg.get('image_selector', '#toon_content_imgs img')
        response = self.page.goto(url, wait_until='domcontentloaded', timeout=45000)
        if response and response.status in (401, 403):
            raise PermissionError(f'사이트 접근이 제한되었습니다 ({response.status}).')
        if response and response.status >= 400:
            raise RuntimeError(f'사이트 접속 오류 {response.status}. 주소를 확인하거나 브라우저 표시를 켜세요.')
        try:
            self.page.wait_for_selector(selector, state='attached', timeout=30000)
        except Exception as exc:
            raise RuntimeError('목록/본문이 로딩되지 않았습니다. 사이트 주소 또는 선택자 설정을 확인하세요. 보안 확인 화면은 직접 확인해야 합니다.') from exc
        # Settle asynchronous batches without assuming only the visible cards exist.
        last, stable = 0, 0
        for _ in range(12):
            self.control.check()
            count = self.page.locator(selector).count()
            stable = stable + 1 if count == last else 0
            if stable >= 3:
                break
            last = count
            self.page.wait_for_timeout(250)
        return self.page.content()

    def fetch(self, url: str, referer: str):
        self.control.check()
        self.policy.gate(self.control,self.emit)
        if re.search(r'https?://', urlsplit(url).path, re.I):
            raise ValueError('사이트 이미지 주소가 잘못되었습니다 (경로에 중복 URL).')
        cached = self.image_cache.pop(url, None)
        if cached is not None:
            self.image_cache_bytes -= len(cached)
            return cached
        # Match the normal browser's default strict-origin-when-cross-origin
        # policy rather than sending a full episode path to a different host.
        source, target = urlsplit(referer), urlsplit(url)
        effective_referer = referer
        if (source.scheme, source.netloc) != (target.scheme, target.netloc):
            effective_referer = source.scheme + '://' + source.netloc + '/'
        if source.scheme == 'https' and target.scheme == 'http':
            effective_referer = ''
        headers = {'User-Agent': self.user_agent, 'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'}
        if effective_referer:
            headers['Referer'] = effective_referer
        for attempt in range(3):
            self.control.check()
            try:
                if self.policy.managed():
                    from transfer_policy import stream_image
                    return stream_image(url,headers,self.ctx.cookies([url]),self.policy,self.control,self.emit)
                response = self.ctx.request.get(url, headers=headers, timeout=30000)
                if response.status in (401, 403):
                    self.emit('log', f'이미지 응답 {response.status}: {url}')
                    raise PermissionError(f'이미지 서버가 요청을 거절했습니다 ({response.status}). 저장된 이미지는 유지됩니다. 잠시 후 다시 시작하면 이어받습니다. 계속되면 브라우저 표시를 켜고 해당 회차를 확인하세요.')
                if not response.ok:
                    raise RuntimeError(f'이미지 응답 {response.status}')
                return response.body()
            except PermissionError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                self.control.delay(0.6 * (attempt + 1))

    def catalog(self):
        url = self.cfg['site_url']
        html = self.visit(url, 'a.toon-link img[data-original]')
        works = self.rendered_catalog()
        # The homepage defaults to UP; other weekday and completed tabs expose
        # additional works from the same public catalog.
        selectors = [f'.nav_pday[attr-id="{day}"]' for day in [1, 2, 3, 4, 5, 6, 7, 10]]
        selectors += ['#profile-tab']
        for selector in selectors:
            self.control.check()
            tab = self.page.locator(selector)
            if tab.count() != 1 or not tab.is_visible():
                continue
            self.emit('log', '요일·완결 목록 추가 확인 중')
            tab.click()
            self.page.wait_for_timeout(600)
            last, stable = -1, 0
            for _ in range(12):
                self.control.check()
                count = self.page.locator('a.toon-link img[data-original]').count()
                stable = stable + 1 if count == last else 0
                if stable >= 3:
                    break
                last = count
                self.page.wait_for_timeout(250)
            works += self.rendered_catalog()
        # Only explicit pagination links on the current host are followed.
        pending = self.page.locator('.pagination a[href]').evaluate_all('(nodes) => nodes.map(a => a.href)')
        visited = {url.rstrip('/')}
        while pending:
            target = pending.pop(0)
            if target.rstrip('/') in visited or urlsplit(target).netloc != urlsplit(url).netloc:
                continue
            visited.add(target.rstrip('/'))
            self.emit('log', f'목록 페이지 확인: {target}')
            self.visit(target, 'a.toon-link')
            works += self.rendered_catalog()
            pending += self.page.locator('.pagination a[href]').evaluate_all('(nodes) => nodes.map(a => a.href)')
        unique = {w.url: w for w in works}
        return list(unique.values())

    def rendered_catalog(self):
        values = self.page.locator('a.toon-link[href]').evaluate_all('''(nodes) => {
            const works = new Map();
            for (const a of nodes) {
                if (!/\\/webtoon\\/[^/]+\\.html/.test(new URL(a.href).pathname)) continue;
                const card = a.closest('.card') || a;
                const title = a.getAttribute('title') || a.getAttribute('alt') || card.querySelector('h3')?.textContent.replace(/^\\s*UP\\s*/, '').trim();
                if (!title) continue;
                const w = works.get(a.href) || {title, url:a.href, thumbnail:'', latest:'', genre:'', cover:'',publisher:''};
                const img = a.querySelector('img[data-original],img.thumb2,img.back-img-style');
                if (img) w.thumbnail = new URL(img.getAttribute('data-original') || img.getAttribute('src'), location.href).href;
                const ps = card.querySelectorAll('p');
                if (card.querySelector('h3') && ps.length >= 2) {
                    w.genre = ps[0].textContent.trim(); w.latest = ps[1].textContent.trim();
                }
                const platform = card.querySelector('.platfrom-style img, .platform-style img');
                if (platform) w.publisher = platform.getAttribute('alt') || platform.getAttribute('src') || '';
                works.set(a.href,w);
            }
            return Array.from(works.values());
        }''')
        self.emit('log', f'현재 탭 작품 {len(values):,}개 확인')
        for value in values:
            value['publisher'] = publisher_name(value.get('publisher', ''))
        return [Work(**w) for w in values]

    def episodes(self, work):
        html = self.visit(work.url, 'a[href*="/webtoons/"]')
        return parse_episodes(html, self.page.url, work.title)


class Control:
    def __init__(self):
        self.stopped = threading.Event()
        self.paused = threading.Event()

    def check(self):
        while self.paused.is_set():
            if self.stopped.wait(.15):
                raise Cancelled()
        if self.stopped.is_set():
            raise Cancelled()

    def delay(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            self.stopped.wait(min(.1, max(0, end-time.monotonic())))


def download(cfg, works, control, emit):
    from library import LibraryArchive
    from automation_store import select_episodes
    cfg=dict(cfg,_download_job=True)
    # Serialize schema creation/migration; independent works can then stream in parallel.
    with _ARCHIVE_INIT_LOCK:archive = LibraryArchive(Path(cfg['output_dir']))
    totals = {'saved': 0, 'skipped': 0, 'filtered': 0, 'failed': 0, 'episodes': 0}
    processed_images=0;seen_images=0
    try:
        with Browser(cfg, control, emit) as browser:
            plans = []
            for work in works:
                emit('log', f'{work.title}: 전체 회차 확인 중')
                episodes = browser.episodes(work)
                if not episodes:
                    raise RuntimeError(f'{work.title}: 회차를 찾지 못했습니다.')
                archive.record_work(work)
                for sequence, episode in enumerate(episodes, 1):
                    archive.record_episode(work, episode, sequence)
                episodes = select_episodes(episodes,cfg)
                plans += [(work, e) for e in episodes]
            emit('plan', len(plans))
            for index, (work, episode) in enumerate(plans):
                control.check()
                emit('current', {'title': work.title, 'episode': episode.folder, 'date': episode.date, 'index': index, 'total': len(plans)})
                errors, episode_saved, consecutive_denials = [], 0, 0
                try:
                    html = browser.visit(episode.url, cfg['image_selector'])
                    urls = parse_images(html, episode.url, cfg['image_selector'])
                    if not urls:
                        raise RuntimeError('본문 이미지가 없습니다.')
                    archive.record_order(work, episode, urls)
                    seen_images+=len(urls)
                    estimated_images=max(seen_images,round(seen_images/(index+1)*len(plans)))
                    for n, url in enumerate(urls):
                        control.check()
                        emit('image_progress', {'index': n+1, 'total': len(urls)})
                        key = archive.key(work, episode, url)
                        if archive.existing(key):
                            totals['skipped'] += 1
                            consecutive_denials = 0
                            processed_images+=1;emit('transfer_progress',{'bytes':0,'completed':processed_images,'total':estimated_images})
                            continue
                        received_bytes=0
                        try:
                            data = browser.fetch(url, episode.url)
                            received_bytes=len(data)
                            consecutive_denials = 0
                            path = archive.save(work, episode, url, data, (cfg['min_width'], cfg['min_height']), n+1)
                            if path:
                                totals['saved'] += 1
                                episode_saved += 1
                                emit('saved', {'path': str(path), 'bytes': len(data)})
                            else:
                                totals['filtered'] += 1
                        except Cancelled:
                            raise
                        except PermissionError as exc:
                            totals['failed'] += 1
                            errors.append(f'{url}: {exc}')
                            emit('log', f'{episode.folder} 이미지 {n+1}/{len(urls)} 접근 오류: {url}')
                            consecutive_denials += 1
                            # One unavailable image must not cancel all works.
                            # Repeated denials stop requests to a restricted server.
                            if consecutive_denials >= 3:
                                raise PermissionError('이미지 서버가 연속 3개 요청을 거절해 중단했습니다. 기존 저장 파일은 유지됩니다.') from exc
                        except Exception as exc:
                            totals['failed'] += 1
                            errors.append(f'{url}: {exc}')
                            emit('log', f'이미지 실패: {exc}')
                        processed_images+=1;emit('transfer_progress',{'bytes':received_bytes,'completed':processed_images,'total':estimated_images})
                        control.delay(cfg.get('delay', .25))
                    archive.episode_status(work, episode, 'partial' if errors else 'complete', json.dumps(errors, ensure_ascii=False))
                except Cancelled:
                    archive.episode_status(work, episode, 'interrupted', '사용자가 중단했습니다.')
                    raise
                except PermissionError as exc:
                    archive.episode_status(work, episode, 'failed', str(exc))
                    raise
                except Exception as exc:
                    errors.append(str(exc))
                    totals['failed'] += 1
                    archive.episode_status(work, episode, 'failed', str(exc))
                    emit('log', f'{episode.folder} 실패: {exc}')
                totals['episodes'] += 1
                if not errors and (episode.number>=totals.get('latest_episode_number',-1)):
                    totals['latest_episode_number']=episode.number;totals['latest_episode']=episode.folder
                archive.manifest(archive.work_key(work))
                emit('progress', {'value': index+1, 'total': len(plans), **totals})
                emit('log', f'{work.title} / {episode.folder}: 신규 {episode_saved}장' + (f' · 오류 {len(errors)}건' if errors else ''))
            return totals
    finally:
        archive.close()
