"""Offline reading index and non-destructive OpenComic bridge."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from PySide6.QtGui import QImageReader
from PySide6.QtCore import QSize
from library import LibraryArchive
from core import safe_name

def natural(value):
    return tuple((0,int(x)) if x.isdigit() else (1,x.casefold()) for x in re.split(r'(\d+)',str(value)))

def local_path(root, value):
    root=Path(root).resolve();p=(root/value).resolve()
    if not p.is_relative_to(root):raise ValueError('보관함 밖의 파일은 열 수 없습니다.')
    return p

def shelf_index(root, catalog, control, emit, thumbnails=True):
    root=Path(root).resolve()
    if not (root/'.toonshelf.sqlite3').is_file():return []
    archive=LibraryArchive(root)
    try:
        archive.seed_catalog(catalog);rows=archive.works(verify_files=False)
        for n,w in enumerate(rows):
            control.check();w['chapters']=archive.episodes(w['key'],verify_files=False)
            w['size']=sum(e['size'] for e in w['chapters']);w['missing']=sum(e['missing'] for e in w['chapters'])
            for e in w['chapters']:
                e['files']=archive.ordered_images(e['key'])
            if not thumbnails:
                emit('log',f"보관함 확인 중 · {n+1}/{len(rows)} 작품");continue
            cover=Path(w.get('cover') or '')
            if not cover.is_file():
                first=next((f for e in w['chapters'] for f in e['files']),None)
                cover=local_path(root,first['path']) if first else None
            if cover:
                reader=QImageReader(str(cover));s=reader.size()
                if s.isValid() and s.width()*s.height()<=120_000_000:
                    reader.setScaledSize(QSize(180,max(1,min(3000,int(s.height()*180/s.width())))))
                    im=reader.read()
                    if not im.isNull():w['thumbnail_image']=im.copy(0,0,im.width(),min(240,im.height()))
            emit('log',f"보관함 확인 중 · {n+1}/{len(rows)} 작품")
        return rows
    finally:archive.close()

def chapter_images(root, chapter, control):
    result=[]
    # Recorded positions, rather than original file names, determine reading order.
    files=chapter['files']
    if not chapter.get('order_verified'):
        files=sorted(files,key=lambda f:natural(f['path']))
    for f in files:
        control.check()
        try:
            path=local_path(root,f['path']);reader=QImageReader(str(path));size=reader.size()
            if not path.is_file() or not size.isValid():raise ValueError('누락되었거나 손상된 이미지')
            if size.width()*size.height()>120_000_000:raise ValueError('안전한 표시 크기를 초과한 이미지')
            result.append({'path':str(path),'width':size.width(),'height':size.height(),'error':''})
        except Exception as exc:result.append({'path':f['path'],'width':800,'height':130,'error':str(exc)})
    return result

def prepare_opencomic(root, work, control, emit):
    root=Path(root).resolve()
    cache=root/'.toonshelf-reader'/hashlib.sha256(work['key'].encode()).hexdigest()[:24]
    cache=cache.resolve()
    if not cache.is_relative_to(root):raise ValueError('읽기용 폴더가 보관함 밖에 있습니다.')
    cache.mkdir(parents=True,exist_ok=True)
    marker=cache/'managed.json'
    if not marker.exists():
        if any(cache.iterdir()):raise ValueError('관리되지 않는 읽기용 폴더입니다.')
        marker.write_text(json.dumps({'work':work['key']}),encoding='utf-8')
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')).get('work')!=work['key']:
        raise ValueError('읽기용 폴더를 확인하세요.')
    paths=[];total=sum(len(e['files']) for e in work['chapters']);count=0;copies=0
    for n,e in enumerate(work['chapters']):
        folder=(cache/f"{n+1:04d}_{safe_name(e['folder'])}").resolve()
        if not folder.is_relative_to(cache):raise ValueError('읽기용 회차 경로를 확인하세요.')
        folder.mkdir(exist_ok=True);paths.append(str(folder));expected=set()
        files=e['files'] if e.get('order_verified') else sorted(e['files'],key=lambda f:natural(f['path']))
        for i,f in enumerate(files):
            control.check();src=local_path(root,f['path'])
            if not src.is_file():continue
            dest=folder/f"{i+1:06d}{src.suffix.lower()}";expected.add(dest.name)
            if dest.exists() and os.path.samefile(src,dest):continue
            if dest.exists():dest.unlink()
            try:os.link(src,dest)
            except OSError:
                if shutil.disk_usage(cache).free<src.stat().st_size+16*1024**2:raise ValueError('읽기용 사본 저장 공간이 부족합니다.')
                shutil.copy2(src,dest);copies+=src.stat().st_size
            count+=1;emit('log',f'OpenComic 읽기 순서 준비 · {count}/{total}장')
        # Only our numbered mirror files may be removed; originals are untouched.
        for p in folder.iterdir():
            if p.is_file() and re.fullmatch(r'\d{6}\.[a-zA-Z0-9]+',p.name) and p.name not in expected:p.unlink()
    tmp=marker.with_suffix('.tmp');tmp.write_text(json.dumps({'work':work['key'],'chapters':paths,'copied_bytes':copies}),encoding='utf-8');tmp.replace(marker)
    return paths

def opencomic(exe, chapter):
    exe=Path(exe).resolve();chapter=Path(chapter).resolve()
    if not exe.is_file() or exe.suffix.lower()!='.exe':raise ValueError('설정에서 OpenComic 실행 파일을 선택하세요.')
    if not chapter.is_dir():raise ValueError('회차 폴더를 찾을 수 없습니다.')
    return subprocess.Popen([str(exe),str(chapter)],cwd=str(exe.parent))
