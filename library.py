from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

from PIL import Image, ImageOps
from core import Archive, Browser, Work, Episode, Control, safe_name, parse_images


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def format_time(value, mode='seoul'):
    if not value:
        return '미확인'
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        target = timezone.utc if mode == 'utc' else timezone(timedelta(hours=9))
        return stamp.astimezone(target).strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return value


def size_text(size):
    size = float(size)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024 or unit == 'TB':
            return f'{size:,.1f} {unit}'
        size /= 1024


def genres(value):
    return [g for g in re.split(r'[\s,;|]+', value.strip()) if g]


class LibraryArchive(Archive):
    """Adds V2 metadata without changing image paths or old download records."""
    def __init__(self, root):
        super().__init__(root)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS works (
            key TEXT PRIMARY KEY, title TEXT, url TEXT, genre TEXT DEFAULT '', publisher TEXT DEFAULT '',
            cover TEXT DEFAULT '', genre_override TEXT, publisher_override TEXT)''')
        episode_columns = {'work_key': "TEXT DEFAULT ''", 'url': "TEXT DEFAULT ''", 'upload_date': "TEXT DEFAULT ''",
                           'folder': "TEXT DEFAULT ''", 'number': 'REAL DEFAULT -1', 'sequence': 'INT DEFAULT 0',
                           'first_downloaded': "TEXT DEFAULT ''", 'last_downloaded': "TEXT DEFAULT ''",
                           'order_verified': 'INT DEFAULT 0'}
        image_columns = {'episode_key': "TEXT DEFAULT ''", 'position': 'INT DEFAULT 0',
                         'last_downloaded': "TEXT DEFAULT ''", 'original_name': "TEXT DEFAULT ''"}
        for table, columns in [('episodes', episode_columns), ('images', image_columns)]:
            known = {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}
            for name, declaration in columns.items():
                if name not in known:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
        legacy = self.db.execute("SELECT rowid,* FROM images WHERE episode_key='' ORDER BY rowid").fetchall()
        counters = {}
        for row in legacy:
            parts = row['key'].split('|', 2)
            path_parts = Path(row['path']).parts
            if len(parts) != 3 or len(path_parts) < 3:
                continue
            work_key, episode_path, image_path = parts
            episode_key = work_key + '|' + episode_path
            counters[episode_key] = counters.get(episode_key, 0) + 1
            title, folder = path_parts[0], path_parts[1]
            self.db.execute('INSERT OR IGNORE INTO works(key,title,url) VALUES(?,?,?)', (work_key, title, work_key))
            self.db.execute("INSERT OR IGNORE INTO episodes(key,title,status,detail) VALUES(?,?,'complete','이전 버전 기록')", (episode_key, title+' '+folder))
            match = re.search(r'(\d+(?:\.\d+)?)\s*화', folder)
            number = float(match.group(1)) if match else -1
            self.db.execute('UPDATE episodes SET work_key=?,url=?,folder=?,number=? WHERE key=?', (work_key, episode_path, folder, number, episode_key))
            self.db.execute('UPDATE images SET episode_key=?,position=?,last_downloaded=?,original_name=? WHERE key=?',
                            (episode_key, counters[episode_key], row['saved'], Path(image_path).name, row['key']))
        if legacy:
            self.db.execute('''UPDATE episodes SET
                first_downloaded=COALESCE((SELECT MIN(saved) FROM images WHERE episode_key=episodes.key),''),
                last_downloaded=COALESCE((SELECT MAX(last_downloaded) FROM images WHERE episode_key=episodes.key),'')''')
        self.db.execute('CREATE INDEX IF NOT EXISTS image_episode_idx ON images(episode_key,position)')
        self.db.commit()

    @staticmethod
    def work_key(work):
        from urllib.parse import urlsplit
        return urlsplit(work.url).path

    def record_work(self, work):
        self.db.execute('''INSERT INTO works(key,title,url,genre,publisher,cover) VALUES(?,?,?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET title=excluded.title,url=excluded.url,
            genre=CASE WHEN excluded.genre<>'' THEN excluded.genre ELSE works.genre END,
            publisher=CASE WHEN excluded.publisher<>'' THEN excluded.publisher ELSE works.publisher END,
            cover=CASE WHEN excluded.cover<>'' THEN excluded.cover ELSE works.cover END''',
            (self.work_key(work), work.title, work.url, work.genre, work.publisher, work.cover))
        self.db.commit()

    def record_episode(self, work, episode, sequence=0):
        from urllib.parse import urlsplit
        key = self.work_key(work)+'|'+urlsplit(episode.url).path
        self.db.execute('''INSERT INTO episodes(key,title,status,detail,work_key,url,upload_date,folder,number,sequence)
            VALUES(?,?,'pending','',?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
            title=excluded.title,work_key=excluded.work_key,url=excluded.url,folder=excluded.folder,
            number=excluded.number,sequence=excluded.sequence,
            upload_date=CASE WHEN excluded.upload_date<>'' THEN excluded.upload_date ELSE episodes.upload_date END''',
            (key, episode.title, self.work_key(work), episode.url, episode.date, episode.folder, episode.number, sequence))
        self.db.commit()
        return key

    def record_order(self, work, episode, urls):
        from urllib.parse import urlsplit
        episode_key = self.work_key(work)+'|'+urlsplit(episode.url).path
        for position, url in enumerate(urls, 1):
            self.db.execute('UPDATE images SET position=? WHERE key=?', (position, self.key(work, episode, url)))
        self.db.execute('UPDATE episodes SET order_verified=1 WHERE key=?', (episode_key,))
        self.db.commit()

    def save(self, work, episode, url, data, minimum, position=1):
        from urllib.parse import urlsplit
        key = self.key(work, episode, url)
        prior = self.db.execute('SELECT saved FROM images WHERE key=?', (key,)).fetchone()
        self.record_work(work)
        ep_key = self.work_key(work)+'|'+urlsplit(episode.url).path
        if not self.db.execute('SELECT 1 FROM episodes WHERE key=?', (ep_key,)).fetchone():
            self.record_episode(work, episode)
        path = super().save(work, episode, url, data, minimum)
        if path:
            now = utc_now()
            first = prior['saved'] if prior else now
            self.db.execute('UPDATE images SET episode_key=?,position=?,original_name=?,saved=?,last_downloaded=? WHERE key=?',
                (ep_key, position, urlsplit(url).path.rsplit('/',1)[-1], first, now, key))
            self.db.execute('''UPDATE episodes SET first_downloaded=CASE WHEN first_downloaded='' THEN ? ELSE first_downloaded END,
                last_downloaded=? WHERE key=?''', (first, now, ep_key))
            self.db.commit()
        return path

    def episode_status(self, work, episode, status, detail):
        from urllib.parse import urlsplit
        key = self.work_key(work)+'|'+urlsplit(episode.url).path
        self.db.execute('UPDATE episodes SET title=?,status=?,detail=?,updated=? WHERE key=?',
                        (episode.title,status,detail,utc_now(),key))
        self.db.commit()

    def seed_catalog(self, works):
        known = {r['key'] for r in self.db.execute('SELECT key FROM works')}
        for w in works:
            if self.work_key(w) in known:
                self.record_work(w)

    def properties(self, key, genre, publisher):
        self.db.execute('UPDATE works SET genre_override=?,publisher_override=? WHERE key=?', (genre,publisher,key))
        self.db.commit()

    def works(self, verify_files=True):
        rows=[dict(row) for row in self.db.execute('''SELECT w.key,w.title,w.url,w.cover,
            COALESCE(w.genre_override,w.genre) AS genre,COALESCE(w.publisher_override,w.publisher) AS publisher,
            COUNT(DISTINCT i.episode_key) AS episodes,COUNT(i.key) AS images,COALESCE(SUM(i.size),0) AS size,
            MAX(i.last_downloaded) AS last_downloaded,
            COALESCE(MIN(e.order_verified),0) AS order_verified
            FROM works w JOIN episodes e ON e.work_key=w.key JOIN images i ON i.episode_key=e.key
            GROUP BY w.key ORDER BY last_downloaded DESC,w.title''')]
        for w in rows:
            if not verify_files:
                w['expected_size']=w['size'];w['missing']=0;continue
            w['expected_size']=w['size'];w['size']=0;w['missing']=0
            for row in self.db.execute('SELECT i.path FROM images i JOIN episodes e ON e.key=i.episode_key WHERE e.work_key=?',(w['key'],)):
                path=(self.root/row['path']).resolve()
                if path.is_relative_to(self.root) and path.is_file():w['size']+=path.stat().st_size
                else:w['missing']+=1
        return rows

    def episodes(self, work_key, verify_files=True):
        rows=[dict(row) for row in self.db.execute('''SELECT e.*,COUNT(i.key) AS images,COALESCE(SUM(i.size),0) AS size
            FROM episodes e JOIN images i ON i.episode_key=e.key WHERE work_key=? GROUP BY e.key
            ORDER BY CASE WHEN e.sequence>0 THEN e.sequence ELSE e.number END,e.folder''',(work_key,))]
        for e in rows:
            if not verify_files:
                e['expected_size']=e['size'];e['missing']=0;continue
            e['expected_size']=e['size'];e['size']=0;e['missing']=0
            for row in self.db.execute('SELECT path FROM images WHERE episode_key=?',(e['key'],)):
                path=(self.root/row['path']).resolve()
                if path.is_relative_to(self.root) and path.is_file():e['size']+=path.stat().st_size
                else:e['missing']+=1
        return rows

    def ordered_images(self, episode_key):
        return [dict(row) for row in self.db.execute('SELECT * FROM images WHERE episode_key=? ORDER BY position,key',(episode_key,))]

    def manifest(self, work_key):
        work = next((w for w in self.works() if w['key']==work_key), None)
        if not work:
            return
        payload = {'version':2, 'work':work, 'episodes':[]}
        for e in self.episodes(work_key):
            payload['episodes'].append({**e,'images_in_reading_order':self.ordered_images(e['key'])})
        path = self.root / safe_name(work['title']) / '_toonshelf_manifest.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        temp = path.with_suffix('.json.part')
        temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)


def refresh_metadata(cfg, root, keys, catalog, control, emit):
    archive = LibraryArchive(Path(root))
    try:
        archive.seed_catalog(catalog)
        with Browser(cfg,control,emit) as browser:
            from urllib.parse import urlsplit,urlunsplit
            host = urlsplit(cfg['site_url'])
            for key in keys:
                row = archive.db.execute('SELECT * FROM works WHERE key=?',(key,)).fetchone()
                if not row:
                    continue
                work = Work(row['title'],urlunsplit((host.scheme,host.netloc,key,'','')),genre=row['genre'],cover=row['cover'],publisher=row['publisher'])
                archive.record_work(work)
                saved = {e['key'] for e in archive.episodes(key)}
                episodes = browser.episodes(work)
                for sequence,e in enumerate(episodes,1):
                    control.check()
                    ekey = key+'|'+urlsplit(e.url).path
                    if ekey not in saved:
                        continue
                    archive.record_episode(work,e,sequence)
                    html = browser.visit(e.url,cfg['image_selector'])
                    urls = parse_images(html,e.url,cfg['image_selector'])
                    if not urls:
                        raise RuntimeError(f'{e.folder}: 이미지 순서를 확인하지 못했습니다.')
                    available = {urlsplit(u).path for u in urls}
                    missing = [r for r in archive.ordered_images(ekey) if r['key'].split('|',2)[-1] not in available]
                    if missing:
                        raise RuntimeError(f'{e.folder}: 기존 파일 {len(missing)}장의 원본 주소가 달라 순서를 확인하지 못했습니다.')
                    archive.record_order(work,e,urls)
                    emit('log',f'{work.title} / {e.folder}: 업로드일 {e.date or "미확인"} · 읽는 순서 확인')
                archive.manifest(key)
        return {'works':len(keys)}
    finally:
        archive.close()


def export_mobile(root, keys, destination, options, control, emit):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination==root or root.is_relative_to(destination) or destination.is_relative_to(root):
        raise ValueError('기기용 파일은 원본 저장 폴더와 겹치지 않는 별도 폴더를 선택하세요.')
    archive = LibraryArchive(root)
    stage = None
    stage_created = False
    import shutil
    import uuid
    try:
        works = [w for w in archive.works() if w['key'] in keys]
        plans=[]
        input_bytes=0
        for w in works:
            for e in archive.episodes(w['key']):
                if options.get('episode_keys') and e['key'] not in options['episode_keys']:
                    continue
                if not e['order_verified']:
                    raise ValueError(f"{w['title']} / {e['folder']}: ‘날짜·읽는 순서 확인’을 먼저 실행하세요.")
                if e['status']!='complete':
                    raise ValueError(f"{e['folder']}: 회차 다운로드를 완료한 뒤 내보내세요.")
                images=archive.ordered_images(e['key'])
                for i in images:
                    path=(root/i['path']).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        raise ValueError(f"원본 파일을 찾지 못했습니다: {i['path']}")
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=i['sha']:
                        raise ValueError(f"손상 파일입니다. 다시 다운로드하세요: {i['path']}")
                    if i['position']<1:
                        raise ValueError('이미지 순서가 확인되지 않았습니다.')
                    input_bytes+=path.stat().st_size
                plans.append((w,e,images))
        if not plans:
            raise ValueError('내보낼 다운로드 자료가 없습니다.')
        destination.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(destination).free < input_bytes*1.1:
            raise ValueError('내보내기 폴더의 여유 공간이 부족합니다.')
        stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S')
        final=destination/f'ToonShelf_{stamp}_{uuid.uuid4().hex[:4]}'
        stage=destination/(final.name+'.incomplete')
        stage.mkdir()
        stage_created=True
        output_bytes=0
        report={'version':2,'created':utc_now(),'options':options,'source_bytes':input_bytes,'episodes':[]}
        for index,(w,e,images) in enumerate(plans,1):
            control.check()
            group=stage
            if options.get('group')=='genre':
                group/=safe_name((genres(w['genre']) or ['미분류'])[0])
            elif options.get('group')=='publisher':
                group/=safe_name(w['publisher'] or '미분류')
            group/=safe_name(w['title'])
            group.mkdir(parents=True,exist_ok=True)
            prefix=f"{e['sequence']:04d}_{e['folder']}"
            entry={'work':w['title'],'genre':w['genre'],'publisher':w['publisher'],'episode':e['folder'],
                   'upload_date':e['upload_date'],'first_downloaded':e['first_downloaded'],'images':[]}
            if options.get('format')=='cbz':
                target=group/(prefix+'.cbz')
                writer=ZipFile(target.with_suffix('.cbz.part'),'w',ZIP_STORED)
            else:
                target=group/prefix
                target.mkdir()
                writer=None
            try:
                for n,i in enumerate(images,1):
                    control.check()
                    source=root/i['path']
                    data=source.read_bytes()
                    extension=source.suffix or '.img'
                    if options.get('optimize'):
                        with Image.open(BytesIO(data)) as image:
                            # Animation cannot be flattened without dropping frames.
                            if not getattr(image,'is_animated',False):
                                image=ImageOps.exif_transpose(image)
                                resized=False
                                if image.width>options.get('width',1600):
                                    width=options.get('width',1600)
                                    image=image.resize((width,max(1,round(image.height*width/image.width))),Image.Resampling.LANCZOS)
                                    resized=True
                                if image.mode in ('RGBA','LA') or 'transparency' in image.info:
                                    rgba=image.convert('RGBA')
                                    rgb=Image.new('RGB',rgba.size,'white')
                                    rgb.paste(rgba,mask=rgba.getchannel('A'))
                                else:
                                    rgb=image.convert('RGB')
                                stream=BytesIO()
                                rgb.save(stream,'JPEG',quality=options.get('quality',85),optimize=True)
                                if resized or len(stream.getvalue())<len(data):
                                    data=stream.getvalue()
                                    extension='.jpg'
                    filename=f'{n:06d}{extension}'
                    if writer:
                        writer.writestr(filename,data)
                    else:
                        (target/filename).write_bytes(data)
                    entry['images'].append({'position':n,'file':filename,'original':source.name,'bytes':len(data)})
                if writer:
                    writer.writestr('_reading_order.json',json.dumps(entry,ensure_ascii=False,indent=2))
            finally:
                if writer:
                    writer.close()
            if writer:
                target.with_suffix('.cbz.part').replace(target)
            else:
                (target/'_reading_order.json').write_text(json.dumps(entry,ensure_ascii=False,indent=2),encoding='utf-8')
            report['episodes'].append(entry)
            emit('log',f"기기용 내보내기 {index}/{len(plans)}: {w['title']} / {e['folder']}")
            emit('export_progress',{'value':index,'total':len(plans)})
        output_bytes=sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        report.update(output_bytes=output_bytes,episode_count=len(plans),image_count=sum(len(i['images']) for i in report['episodes']))
        info_path=stage/'_export_info.json'
        for _ in range(3):
            info_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            report['output_bytes']=sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        stage.replace(final)
        stage=None
        return {**report,'path':str(final)}
    finally:
        archive.close()
        if stage_created and stage and stage.is_relative_to(destination) and stage.name.endswith('.incomplete'):
            shutil.rmtree(stage)
