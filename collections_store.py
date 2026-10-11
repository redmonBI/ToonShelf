"""Account-portable collections and persistent episode notifications (no image data)."""
import json,sqlite3
from pathlib import Path
from contextlib import contextmanager
from dataclasses import asdict,is_dataclass
from urllib.parse import urlsplit
from datetime import datetime,timezone
DAYS=['월요일','화요일','수요일','목요일','금요일','토요일','일요일']
def work_dict(work):return asdict(work) if is_dataclass(work) else dict(work)
def work_key(work):
    value=work_dict(work);return urlsplit(value.get('url','')).path or str(value.get('key',value.get('title','')))
def stamp():return datetime.now(timezone.utc).isoformat()
def as_work(value):
    from core import Work
    return Work(**{k:v for k,v in work_dict(value).items() if k in Work.__dataclass_fields__})

class CollectionStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS collections(key TEXT PRIMARY KEY,work TEXT,favorite INT,weekday INT,genre TEXT,publisher TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS episode_baselines(key TEXT PRIMARY KEY,identifiers TEXT,checked TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY,key TEXT,work TEXT,episode TEXT,created TEXT,unread INT)')
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def entries(self):
        with self.db() as db:rows=db.execute('SELECT * FROM collections ORDER BY key').fetchall()
        return [dict(r,work=json.loads(r['work'])) for r in rows]
    def get(self,work):
        with self.db() as db:row=db.execute('SELECT * FROM collections WHERE key=?',(work_key(work),)).fetchone()
        return dict(row,work=json.loads(row['work'])) if row else None
    def update(self,work,**values):
        if not set(values)<={'favorite','weekday','genre','publisher'}:raise ValueError('작품 설정 항목을 확인하세요.')
        if 'weekday' in values and int(values['weekday']) not in range(-1,7):raise ValueError('요일을 확인하세요.')
        if 'favorite' in values:values['favorite']=int(bool(values['favorite']))
        w=work_dict(work);key=work_key(w)
        with self.db() as db:
            db.execute('INSERT INTO collections VALUES(?,?,0,-1,?,?) ON CONFLICT(key) DO UPDATE SET work=excluded.work',(key,json.dumps(w,ensure_ascii=False),w.get('genre',''),w.get('publisher','')))
            if values:db.execute('UPDATE collections SET '+','.join(k+'=?' for k in values)+' WHERE key=?',(*values.values(),key))
    def observe(self,work,episodes):
        """The initial successful lookup establishes a quiet baseline; new URL paths alert once."""
        w=work_dict(work);key=work_key(w);items={urlsplit(work_dict(e)['url']).path:work_dict(e) for e in episodes}
        if not items:return 0 # An empty/error-shaped response must not reset a valid baseline.
        created=stamp();added=0
        with self.db() as db:
            old=db.execute('SELECT identifiers FROM episode_baselines WHERE key=?',(key,)).fetchone()
            known=set(json.loads(old[0])) if old else set(items)
            for identifier in items.keys()-known:
                import hashlib
                uid=hashlib.sha256((key+'\n'+identifier).encode()).hexdigest()
                added+=db.execute('INSERT OR IGNORE INTO notices VALUES(?,?,?,?,?,1)',(uid,key,json.dumps(w,ensure_ascii=False),json.dumps(items[identifier],ensure_ascii=False),created)).rowcount
            db.execute('INSERT OR REPLACE INTO episode_baselines VALUES(?,?,?)',(key,json.dumps(sorted(known|set(items))),created))
        return added
    def notices(self,unread_only=False):
        with self.db() as db:rows=db.execute('SELECT * FROM notices '+('WHERE unread=1 ' if unread_only else '')+'ORDER BY created DESC,id DESC LIMIT 500').fetchall()
        return [dict(r,work=json.loads(r['work']),episode=json.loads(r['episode'])) for r in rows]
    def mark_read(self,ids=None):
        with self.db() as db:
            if ids is None:db.execute('UPDATE notices SET unread=0')
            else:db.executemany('UPDATE notices SET unread=0 WHERE id=?',[(i,) for i in ids])
    def unread_count(self):
        with self.db() as db:return db.execute('SELECT COUNT(*) FROM notices WHERE unread=1').fetchone()[0]
    def export_data(self):
        with self.db() as db:baselines=[dict(r) for r in db.execute('SELECT * FROM episode_baselines')]
        return dict(collections=self.entries(),baselines=baselines,notices=self.notices())
    def import_data(self,data):
        # A sync snapshot replaces only collection metadata, never local image files.
        entries=data.get('collections',[]);baselines=data.get('baselines',[]);notices=data.get('notices',[])
        validated=[]
        for e in entries:
            w=work_dict(e['work']);key=work_key(w);day=int(e.get('weekday',-1))
            if day not in range(-1,7):raise ValueError('동기화 요일을 확인하세요.')
            validated.append((key,json.dumps(w,ensure_ascii=False),int(bool(e.get('favorite'))),day,str(e.get('genre','')),str(e.get('publisher',''))))
        with self.db() as db:
            db.execute('DELETE FROM collections');db.executemany('INSERT INTO collections VALUES(?,?,?,?,?,?)',validated)
            for b in baselines:db.execute('INSERT OR REPLACE INTO episode_baselines VALUES(?,?,?)',(b['key'],b['identifiers'],b['checked']))
            for n in notices:db.execute('INSERT OR REPLACE INTO notices VALUES(?,?,?,?,?,?)',(n['id'],n['key'],json.dumps(n['work'],ensure_ascii=False),json.dumps(n['episode'],ensure_ascii=False),n['created'],int(bool(n['unread']))))

def filter_works(works,store,weekday=None,genre='',publisher='',favorite_only=False,favorite_first=False,search=''):
    metadata={e['key']:e for e in store.entries()};result=[]
    for work in works:
        value=work_dict(work);m=metadata.get(work_key(value),{});g=m.get('genre',value.get('genre',''));p=m.get('publisher',value.get('publisher',''));favorite=bool(m.get('favorite'))
        if weekday is not None and m.get('weekday',-1)!=weekday:continue
        if genre and genre.casefold() not in g.casefold():continue
        if publisher and publisher.casefold()!=p.casefold():continue
        if favorite_only and not favorite:continue
        if search.casefold() not in value.get('title','').casefold():continue
        result.append(work)
    if favorite_first:result.sort(key=lambda w:not bool(metadata.get(work_key(w),{}).get('favorite')))
    return result

def check_updates(store,auto_store,cfg,control,emit):
    from core import Browser
    from urllib.parse import urlunsplit
    candidates={e['key']:e['work'] for e in store.entries() if e['favorite']}
    candidates.update({e['key']:e['work'] for e in auto_store.entries()})
    base=urlsplit(cfg['site_url']);added=0;errors=[]
    with Browser(dict(cfg,_download_job=False),control,emit) as browser:
        for index,(key,w) in enumerate(candidates.items()):
            control.check();value=dict(w);old=urlsplit(value['url']);value['url']=urlunsplit((base.scheme,base.netloc,old.path,old.query,''))
            try:added+=store.observe(value,browser.episodes(as_work(value)))
            except Exception as exc:
                from core import Cancelled
                if isinstance(exc,Cancelled):raise
                errors.append(value['title']+' · '+str(exc));emit('log',errors[-1])
            emit('notification_progress',dict(done=index+1,total=len(candidates)))
            control.delay(.5)
    return dict(added=added,checked=len(candidates),errors=errors)
