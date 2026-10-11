"""Delete only registered, unchanged images inside the selected archive."""
import hashlib,json,re,sqlite3
from pathlib import Path
from datetime import datetime,timedelta,timezone
from contextlib import closing
from core import safe_name

def safe_file(root,value):
    root=Path(root).resolve();raw=root/value
    if Path(value).is_absolute() or '..' in Path(value).parts:raise ValueError('보관함 경로를 확인하세요.')
    cursor=raw
    while cursor!=root:
        if cursor.is_symlink() or (hasattr(cursor,'is_junction') and cursor.is_junction()):raise ValueError('연결된 경로는 자동 삭제하지 않습니다.')
        cursor=cursor.parent
    path=raw.resolve()
    if not path.is_relative_to(root):raise ValueError('보관함 밖의 파일은 삭제하지 않습니다.')
    return path

def plan_cleanup(root,entries,now=None):
    root=Path(root).resolve();dbfile=root/'.toonshelf.sqlite3'
    if not dbfile.is_file():return []
    safe_file(root,'.toonshelf.sqlite3')
    now=now or datetime.now(timezone.utc);plan=[]
    with closing(sqlite3.connect(dbfile)) as db:
        db.row_factory=sqlite3.Row
        for entry in entries:
            keep,days=int(entry['keep_count']),int(entry['delete_days'])
            if not keep and not days:continue
            episodes=[dict(r) for r in db.execute('''SELECT e.*,COUNT(i.key) AS images,SUM(i.size) AS bytes
                FROM episodes e JOIN images i ON i.episode_key=e.key WHERE e.work_key=? GROUP BY e.key
                ORDER BY CASE WHEN e.sequence>0 THEN e.sequence ELSE e.number END DESC,e.folder DESC''',(entry['key'],))]
            protected={e['key'] for e in episodes[:keep]}
            if keep and any(e['status'] not in ('complete',) for e in episodes[:keep]):continue
            for episode in episodes:
                if episode['key'] in protected:continue
                aged=False
                try:
                    stamp=datetime.fromisoformat(episode['last_downloaded'].replace('Z','+00:00'))
                    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
                    aged=bool(days and stamp<=now-timedelta(days=days))
                except (ValueError,TypeError):pass
                if keep or aged:
                    files=[dict(r) for r in db.execute('SELECT key,path,sha,size FROM images WHERE episode_key=?',(episode['key'],))]
                    plan.append(dict(work_key=entry['key'],title=entry['work']['title'],episode=episode['folder'],episode_key=episode['key'],files=files,bytes=episode['bytes']))
    return plan

def mirror_files(root,item,sha):
    cache=root/'.toonshelf-reader'/hashlib.sha256(item['work_key'].encode()).hexdigest()[:24]
    marker=cache/'managed.json'
    try:
        safe_file(root,str(marker.relative_to(root)))
        if json.loads(marker.read_text(encoding='utf-8')).get('work')!=item['work_key']:return []
        result=[]
        for folder in cache.iterdir():
            if not re.fullmatch(r'\d{4,}_.*',folder.name) or not folder.name.endswith('_'+safe_name(item['episode'])):continue
            safe_file(root,str(folder.relative_to(root)))
            for file in folder.iterdir():
                if re.fullmatch(r'\d{6}\.[a-zA-Z0-9]+',file.name):
                    safe_file(root,str(file.relative_to(root)))
                    if file.is_file() and hashlib.sha256(file.read_bytes()).hexdigest()==sha:result.append(file)
        return result
    except (OSError,ValueError):return []

def apply_cleanup(root,plan,control,emit):
    root=Path(root).resolve();deleted=0;freed=0;errors=[];works=set()
    safe_file(root,'.toonshelf.sqlite3')
    with closing(sqlite3.connect(root/'.toonshelf.sqlite3',timeout=15)) as db:
        for item in plan:
            control.check()
            for file in item['files']:
                control.check()
                try:
                    # Recheck both the database and actual bytes immediately before removal.
                    current=db.execute('SELECT path,sha FROM images WHERE key=?',(file['key'],)).fetchone()
                    if not current or current!=(file['path'],file['sha']):raise ValueError('파일 기록이 변경되어 보존했습니다.')
                    path=safe_file(root,file['path'])
                    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=file['sha']:raise ValueError('누락·변경된 파일을 보존했습니다.')
                    mirrors=mirror_files(root,item,file['sha'])
                    # Locked OpenComic files fail safely before removing the original.
                    for mirror in mirrors:mirror.unlink()
                    path.unlink();db.execute('DELETE FROM images WHERE key=?',(file['key'],));db.commit()
                    deleted+=1;freed+=file['size'];works.add(item['work_key'])
                    try:path.parent.rmdir()
                    except OSError:pass
                except (OSError,ValueError) as exc:errors.append(item['title']+' / '+item['episode']+': '+str(exc))
            db.execute("UPDATE episodes SET status='pruned',detail='자동 보관 정리' WHERE key=? AND NOT EXISTS(SELECT 1 FROM images WHERE episode_key=?)",(item['episode_key'],item['episode_key']));db.commit()
            emit('log',item['title']+' · '+item['episode']+' 정리 확인')
    if works:
        from library import LibraryArchive
        archive=LibraryArchive(root)
        try:
            for work in works:archive.manifest(work)
        finally:archive.close()
    return dict(deleted=deleted,bytes=freed,errors=errors)
