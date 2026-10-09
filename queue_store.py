"""Durable work queue; a new SQLite connection is used for every operation."""
import json
import sqlite3
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from contextlib import contextmanager

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

class QueueStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.session() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,work TEXT NOT NULL,cfg TEXT NOT NULL,
                status TEXT NOT NULL,priority INTEGER DEFAULT 0,attempts INTEGER DEFAULT 0,progress TEXT DEFAULT '{}',
                result TEXT DEFAULT '{}',error TEXT DEFAULT '',created TEXT,updated TEXT)''')
            db.execute("UPDATE jobs SET status='stopped',error='이전 실행에서 중단됨',updated=? WHERE status IN ('running','paused')",(now(),))
            if 'retry_count' not in {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN retry_count INTEGER DEFAULT 0')
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        return db
    @contextmanager
    def session(self):
        db=self.connect()
        try:
            with db:yield db
        finally:db.close()
    def rows(self):
        with self.session() as db:rows=db.execute('SELECT * FROM jobs ORDER BY priority DESC,id').fetchall()
        return [self.decode(r) for r in rows]
    def decode(self,row):
        r=dict(row)
        for k in ['work','cfg','progress','result']:r[k]=json.loads(r[k])
        return r
    def add(self,works,cfg):
        cfg={k:v for k,v in cfg.items() if k in ['site_url','output_dir','min_width','min_height','start_episode','end_episode','delay','visible_browser','image_selector']}
        added=[];known=self.rows()
        with self.session() as db:
            for work in works:
                value=asdict(work)
                duplicate=any(r['work']['url']==work.url and r['cfg']['output_dir']==cfg['output_dir'] and
                    r['cfg'].get('start_episode')==cfg.get('start_episode') and r['cfg'].get('end_episode')==cfg.get('end_episode')
                    and r['status'] in ['pending','running','paused','held','stopped'] for r in known)
                if duplicate:continue
                cur=db.execute('INSERT INTO jobs(work,cfg,status,created,updated) VALUES(?,?,\'pending\',?,?)',
                    (json.dumps(value,ensure_ascii=False),json.dumps(cfg,ensure_ascii=False),now(),now()))
                added.append(cur.lastrowid)
                known.append({'work':value,'cfg':dict(cfg),'status':'pending'})
        return added
    def change(self,id,status=None,**values):
        if status is not None:values['status']=status
        if not set(values)<= {'status','priority','attempts','progress','result','error','retry_count'}:raise ValueError('Invalid queue field')
        if values.get('status') not in [None,'pending','running','paused','held','stopped','cancelled','complete','partial','failed']:
            raise ValueError('Invalid status')
        for k in ['progress','result']:
            if k in values:values[k]=json.dumps(values[k],ensure_ascii=False)
        values['updated']=now()
        with self.session() as db:
            db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',[*values.values(),id])
    def next(self):
        return next((r for r in self.rows() if r['status']=='pending'),None)
    def resumable(self):
        return [r for r in self.rows() if r['status'] in ['stopped','held','paused','failed','partial']]

