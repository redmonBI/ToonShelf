"""Durable recurring lists. All calendar decisions use Korean time."""
import json,sqlite3
from pathlib import Path
from datetime import datetime,timedelta,timezone
from contextlib import contextmanager
from dataclasses import asdict
from urllib.parse import urlsplit,urlunsplit

SEOUL=timezone(timedelta(hours=9))
CATEGORIES={'watching':'보고 있음','held':'보류 중','planned':'볼 예정'}
def local_now():return datetime.now(SEOUL)
def minute(value):
    h,m=map(int,value.split(':'))
    if not 0<=h<=23 or not 0<=m<=59:raise ValueError('시간을 확인하세요.')
    return h*60+m
def in_window(now,start,end):
    start,end=minute(start),minute(end);value=now.hour*60+now.minute
    return True if start==end else start<=value<end if start<end else value>=start or value<end

class AutoStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS entries(key TEXT PRIMARY KEY,work TEXT,category TEXT,selected INT,tail INT,keep_count INT,delete_days INT)')
            if 'weekday' not in [r[1] for r in db.execute('PRAGMA table_info(entries)')]:db.execute('ALTER TABLE entries ADD COLUMN weekday INT NOT NULL DEFAULT -1')
            db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS runs(slot TEXT PRIMARY KEY,payload TEXT,status TEXT,detail TEXT,created TEXT)')
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def entries(self):
        with self.db() as db:rows=db.execute('SELECT * FROM entries ORDER BY category,key').fetchall()
        return [{**dict(r),'work':json.loads(r['work'])} for r in rows]
    def add(self,works,category='watching'):
        if category not in CATEGORIES:raise ValueError('작품 분류를 확인하세요.')
        with self.db() as db:
            for work in works:
                value=asdict(work) if not isinstance(work,dict) else work
                from core import Work
                value={k:v for k,v in value.items() if k in Work.__dataclass_fields__}
                db.execute('INSERT INTO entries(key,work,category,selected,tail,keep_count,delete_days) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET work=excluded.work',
                    (urlsplit(value['url']).path,json.dumps(value,ensure_ascii=False),category,1,10,10,0))
    def update(self,key,**values):
        if not values or not set(values)<={'category','selected','tail','keep_count','delete_days','weekday'}:raise ValueError('설정 항목을 확인하세요.')
        if 'weekday' in values and int(values['weekday']) not in range(-1,7):raise ValueError('요일을 확인하세요.')
        if 'category' in values and values['category'] not in CATEGORIES:raise ValueError('작품 분류를 확인하세요.')
        for field in ('tail','keep_count','delete_days'):
            if field in values and not 0<=int(values[field])<=10000:raise ValueError('회차·기간 값을 확인하세요.')
        with self.db() as db:db.execute('UPDATE entries SET '+','.join(k+'=?' for k in values)+' WHERE key=?',(*values.values(),key))
    def remove(self,key):
        with self.db() as db:db.execute('DELETE FROM entries WHERE key=?',(key,))
    def schedule(self):
        with self.db() as db:r=db.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()
        return json.loads(r[0]) if r else dict(enabled=False,days=[0],time='21:00',scope='selected',cleanup=False,activated='')
    def save_schedule(self,value,now=None):
        minute(value['time'])
        if value['scope'] not in ('all','selected') or any(d not in range(7) for d in value['days']):raise ValueError('예약 설정을 확인하세요.')
        value=dict(value,activated=(now or local_now()).astimezone(SEOUL).isoformat())
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('schedule',?)",(json.dumps(value),))
            db.execute("UPDATE runs SET status='cancelled',detail='예약 설정 변경' WHERE status='prepared'")
    def chosen(self,scope):return [e for e in self.entries() if scope=='all' or e['selected']]
    def claim_due(self,cfg,now=None):
        now=(now or local_now()).astimezone(SEOUL);schedule=self.schedule()
        target=now.replace(hour=minute(schedule['time'])//60,minute=minute(schedule['time'])%60,second=0,microsecond=0)
        if schedule['enabled'] and now.weekday() in schedule['days'] and now>=target and schedule.get('activated','')<=target.isoformat():
            slot=target.isoformat();payload=self.payload(cfg,schedule['scope'],slot,weekday=now.weekday())
            with self.db() as db:db.execute("INSERT OR IGNORE INTO runs VALUES(?,?,'prepared','',?)",(slot,json.dumps(payload,ensure_ascii=False),now.isoformat()))
        with self.db() as db:rows=db.execute("SELECT slot,payload FROM runs WHERE status='prepared' ORDER BY slot").fetchall()
        return [dict(slot=r['slot'],payload=json.loads(r['payload'])) for r in rows]
    def payload(self,cfg,scope,slot,weekday=None):
        base=urlsplit(cfg['site_url']);items=[]
        for e in self.chosen(scope):
            if weekday is not None and e.get('weekday',-1) not in (-1,weekday):continue
            work=dict(e['work']);old=urlsplit(work['url']);work['url']=urlunsplit((base.scheme,base.netloc,old.path,old.query,''))
            options=dict(cfg,start_episode=1,end_episode=0,latest_count=e['tail'],automation_run=slot,automation_key=e['key'])
            items.append(dict(work=work,cfg=options))
        return items
    def export_data(self):return dict(entries=self.entries(),schedule=self.schedule())
    def import_data(self,data):
        entries=data.get('entries',[])
        # Validate a snapshot before altering the local list.
        for e in entries:
            if e.get('category','watching') not in CATEGORIES or int(e.get('weekday',-1)) not in range(-1,7):raise ValueError('자동 목록 동기화 값을 확인하세요.')
            for k in ('tail','keep_count','delete_days'):
                if not 0<=int(e.get(k,0))<=10000:raise ValueError('자동 목록 회차 값을 확인하세요.')
            if not e['work'].get('url'):raise ValueError('작품 주소가 없습니다.')
        with self.db() as db:
            db.execute('DELETE FROM entries')
            for e in entries:db.execute('INSERT INTO entries(key,work,category,selected,tail,keep_count,delete_days,weekday) VALUES(?,?,?,?,?,?,?,?)',(urlsplit(e['work']['url']).path,json.dumps(e['work'],ensure_ascii=False),e.get('category','watching'),int(bool(e.get('selected',1))),int(e.get('tail',10)),int(e.get('keep_count',10)),int(e.get('delete_days',0)),int(e.get('weekday',-1))))
        # Imported destructive cleanup is deliberately not enabled on another PC.
        if 'schedule' in data:self.save_schedule(dict(data['schedule'],cleanup=False))
    def mark(self,slot,status,detail):
        with self.db() as db:db.execute('UPDATE runs SET status=?,detail=? WHERE slot=?',(status,str(detail),slot))
    def log(self,detail,status='complete'):
        stamp=local_now().isoformat()
        with self.db() as db:db.execute('INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?)',('log:'+stamp,'[]',status,str(detail),stamp))
    def history(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT slot,status,detail,created FROM runs ORDER BY created DESC LIMIT 100')]

def enqueue_occurrences(store,queue,cfg,now=None):
    from core import Work
    ids=[]
    for run in store.claim_due(cfg,now):
        before=len(ids)
        for item in run['payload']:ids+=queue.add([Work(**item['work'])],item['cfg'])
        store.mark(run['slot'],'queued',f"대상 {len(run['payload'])}개 · 신규 대기열 {len(ids)-before}개")
    return ids

def select_episodes(episodes,cfg):
    count=int(cfg.get('latest_count',0))
    if count>0:return list(reversed(episodes[-count:]))
    start,end=cfg.get('start_episode',1),cfg.get('end_episode',0)
    return [e for e in episodes if e.number<0 or (e.number>=start and (not end or e.number<=end))]
