"""ToonShelf private metadata sync service, behind an HTTPS reverse proxy."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

MAX_BODY = 4 * 1024 * 1024
SESSION_SECONDS = 30 * 86400

class APIError(Exception):
    def __init__(self,status,message):self.status=status;super().__init__(message)

def password_hash(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex()

def credentials(username,password):
    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,64}',username):raise APIError(400,'아이디는 영문·숫자·._- 3~64자로 입력하세요.')
    if not isinstance(password,str) or not 8<=len(password)<=256:raise APIError(400,'비밀번호는 8~256자로 입력하세요.')

def metadata(value):
    if not isinstance(value,dict):raise APIError(400,'동기화 데이터 형식이 올바르지 않습니다.')
    allowed={'preferences','lists','favorites','history','works','reading'}
    if set(value)-allowed:raise APIError(400,'지원하지 않는 동기화 항목입니다.')
    for key,item in value.items():
        if not isinstance(item,(dict,list)):raise APIError(400,'동기화 항목은 목록 또는 객체여야 합니다.')
    raw=json.dumps(value,ensure_ascii=False)
    if len(raw.encode())>MAX_BODY-1024:raise APIError(413,'동기화 데이터가 너무 큽니다.')
    # Download payloads cannot contain a machine's full storage paths or credentials.
    forbidden={'password','token','cookie','cookies','download_dir','save_path','absolute_path','local_path'}
    def inspect(obj):
        if isinstance(obj,dict):
            for key,item in obj.items():
                if key.lower() in forbidden:raise APIError(400,'비밀 정보나 전체 저장 경로는 동기화할 수 없습니다.')
                inspect(item)
        elif isinstance(obj,list):
            for item in obj:inspect(item)
        elif isinstance(obj,str) and (re.match(r'^[A-Za-z]:[\\/]',obj) or obj.startswith('\\\\')):raise APIError(400,'전체 저장 경로는 동기화할 수 없습니다.')
    inspect(value)
    return raw

class Service:
    def __init__(self,path,master_username=None,master_password=None):
        self.path=str(path);Path(path).parent.mkdir(parents=True,exist_ok=True)
        with closing(self.db()) as db:
            db.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE COLLATE NOCASE,display_name TEXT,salt TEXT,password_hash TEXT,role TEXT,created REAL,last_seen REAL);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id) ON DELETE CASCADE,expires REAL);
CREATE TABLE IF NOT EXISTS snapshots(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,revision INTEGER,payload TEXT,updated REAL);
CREATE TABLE IF NOT EXISTS global_config(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER,payload TEXT);
INSERT OR IGNORE INTO global_config VALUES(1,0,'{"menu_labels":{}}');''');db.commit()
        if master_username and master_password:self.provision_master(master_username,master_password)
    def db(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
    def provision_master(self,username,password):
        # Explicit operator secret may be shorter than public registration minimum.
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,64}',username) or not password:raise ValueError('Invalid master environment credentials')
        with closing(self.db()) as db:
            row=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            if row:
                if row['role']!='master':raise RuntimeError('Master username already belongs to a normal account; operator intervention required')
                return
            salt=secrets.token_hex(16);uid=secrets.token_hex(16);now=time.time()
            db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(uid,username,username,salt,password_hash(password,salt),'master',now,now));db.execute('INSERT INTO snapshots VALUES(?,0,?,?)',(uid,'{}',now));db.commit()
    def user(self,db,token):
        if not token:raise APIError(401,'로그인이 필요합니다.')
        digest=hashlib.sha256(token.encode()).hexdigest()
        row=db.execute('SELECT users.* FROM users JOIN sessions ON sessions.user_id=users.id WHERE sessions.hash=? AND sessions.expires>?',(digest,time.time())).fetchone()
        if not row:raise APIError(401,'로그인이 만료되었습니다. 다시 로그인하세요.')
        db.execute('UPDATE users SET last_seen=? WHERE id=?',(time.time(),row['id']));return dict(row)
    @staticmethod
    def public(user):return {k:user[k] for k in ('id','username','display_name','role','created','last_seen')}
    @staticmethod
    def admin(user):
        if user['role']!='master':raise APIError(403,'마스터 계정만 사용할 수 있습니다.')
    def request(self,method,path,data=None,token=''):
        data=data or {};parts=urlsplit(path);route=parts.path;query=parse_qs(parts.query)
        with closing(self.db()) as db:
            if route=='/v1/register' and method=='POST':
                username=data.get('username','').strip();password=data.get('password','');credentials(username,password)
                if data.get('admin_visibility_consent') is not True:raise APIError(400,'마스터의 동기화 정보 조회 안내에 동의해야 합니다.')
                display=str(data.get('display_name',username)).strip()[:80] or username;salt=secrets.token_hex(16);uid=secrets.token_hex(16);now=time.time()
                try:db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(uid,username,display,salt,password_hash(password,salt),'user',now,now))
                except sqlite3.IntegrityError:raise APIError(409,'이미 사용 중인 아이디입니다.')
                db.execute('INSERT INTO snapshots VALUES(?,0,?,?)',(uid,'{}',now));db.commit();return {'registered':True}
            if route=='/v1/login' and method=='POST':
                row=db.execute('SELECT * FROM users WHERE username=?',(str(data.get('username',''))[:64],)).fetchone()
                # Equal expensive verification also for absent users.
                salt=row['salt'] if row else '00'*16
                candidate=password_hash(str(data.get('password',''))[:256],salt)
                if not row or not hmac.compare_digest(candidate,row['password_hash']):raise APIError(401,'아이디 또는 비밀번호가 올바르지 않습니다.')
                session=secrets.token_urlsafe(48);expires=time.time()+SESSION_SECONDS
                db.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),));db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(session.encode()).hexdigest(),row['id'],expires));db.commit();return {'token':session,'expires':expires,'user':self.public(row)}
            user=self.user(db,token)
            if route=='/v1/me' and method=='GET':result={'user':self.public(user)}
            elif route=='/v1/logout' and method=='POST':
                db.execute('DELETE FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),));result={'logged_out':True}
            elif route=='/v1/snapshot' and method=='GET':
                row=db.execute('SELECT * FROM snapshots WHERE user_id=?',(user['id'],)).fetchone();result={'revision':row['revision'],'payload':json.loads(row['payload']),'updated':row['updated']}
            elif route=='/v1/snapshot' and method=='PUT':
                raw=metadata(data.get('payload'));revision=data.get('revision')
                if type(revision)!=int or revision<0:raise APIError(400,'동기화 버전이 올바르지 않습니다.')
                updated=time.time();changed=db.execute('UPDATE snapshots SET revision=revision+1,payload=?,updated=? WHERE user_id=? AND revision=?',(raw,updated,user['id'],revision)).rowcount
                if not changed:raise APIError(409,'다른 기기에서 변경되었습니다. 먼저 서버 목록을 불러오세요.')
                result={'revision':revision+1,'updated':updated}
            elif route=='/v1/config' and method=='GET':
                row=db.execute('SELECT * FROM global_config WHERE id=1').fetchone();result={'revision':row['revision'],'payload':json.loads(row['payload'])}
            elif route=='/v1/config' and method=='PUT':
                self.admin(user);labels=data.get('menu_labels',{})
                if not isinstance(labels,dict) or len(labels)>30 or any(not re.fullmatch('[a-z_]{1,40}',k) or not isinstance(v,str) or not 1<=len(v.strip())<=40 for k,v in labels.items()):raise APIError(400,'메뉴 이름 형식이 올바르지 않습니다.')
                changed=db.execute('UPDATE global_config SET revision=revision+1,payload=? WHERE id=1 AND revision=?',(json.dumps({'menu_labels':labels},ensure_ascii=False),data.get('revision'))).rowcount
                if not changed:raise APIError(409,'메뉴 설정이 변경되었습니다. 다시 불러오세요.')
                result={'saved':True}
            elif route=='/v1/admin/users' and method=='GET':
                self.admin(user);search=query.get('q',[''])[0][:100];result={'users':[]}
                for row in db.execute('SELECT users.*,snapshots.payload FROM users LEFT JOIN snapshots ON snapshots.user_id=users.id ORDER BY last_seen DESC'):
                    payload=json.loads(row['payload'] or '{}')
                    if search and search.casefold() not in (row['username']+' '+row['display_name']+' '+json.dumps(payload,ensure_ascii=False)).casefold():continue
                    item=self.public(row);history=payload.get('history',[]);item['download_records']=len(history) if isinstance(history,list) else 0;item['works']=len(payload.get('works',[]));result['users'].append(item)
            elif route.startswith('/v1/admin/users/'):
                self.admin(user);uid=route.rsplit('/',1)[-1];row=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
                if not row:raise APIError(404,'계정이 없습니다.')
                if method=='DELETE':
                    if row['role']=='master':raise APIError(403,'마스터 계정은 삭제할 수 없습니다.')
                    db.execute('DELETE FROM users WHERE id=?',(uid,));result={'deleted':True}
                elif method=='GET':
                    snap=db.execute('SELECT * FROM snapshots WHERE user_id=?',(uid,)).fetchone();result={'user':self.public(row),'revision':snap['revision'],'payload':json.loads(snap['payload'])}
                else:raise APIError(405,'지원하지 않는 작업입니다.')
            else:raise APIError(404,'요청을 찾을 수 없습니다.')
            db.commit();return result

class AuthThrottle:
    def __init__(self):self.lock=threading.Lock();self.attempts={}
    def check(self,ip):
        now=time.monotonic()
        with self.lock:
            self.attempts={key:[stamp for stamp in stamps if now-stamp<60] for key,stamps in self.attempts.items() if stamps and now-stamps[-1]<60}
            stamps=self.attempts.setdefault(ip,[])
            if len(stamps)>=10:raise APIError(429,'로그인 요청이 많습니다. 잠시 후 다시 시도하세요.')
            stamps.append(now)

class Handler(BaseHTTPRequestHandler):
    throttle=AuthThrottle()
    def log_message(self,*args):pass # Never log authentication request bodies or bearer tokens.
    def do_GET(self):self.handle_api()
    def do_POST(self):self.handle_api()
    def do_PUT(self):self.handle_api()
    def do_DELETE(self):self.handle_api()
    def handle_api(self):
        try:
            self.connection.settimeout(20)
            if self.command=='POST' and urlsplit(self.path).path in ('/v1/login','/v1/register'):self.throttle.check(self.client_address[0])
            size=int(self.headers.get('Content-Length','0'))
            if size<0 or size>MAX_BODY:raise APIError(413,'요청이 너무 큽니다.')
            data=json.loads(self.rfile.read(size)) if size else {}
            if not isinstance(data,dict):raise APIError(400,'요청 형식이 올바르지 않습니다.')
            auth=self.headers.get('Authorization','');token=auth[7:] if auth.startswith('Bearer ') else ''
            result=self.server.service.request(self.command,self.path,data,token);status=200
        except APIError as exc:status=exc.status;result={'error':str(exc)}
        except (ValueError,TypeError):status=400;result={'error':'요청 형식이 올바르지 않습니다.'}
        except Exception:status=500;result={'error':'서버 처리 오류입니다.'}
        raw=json.dumps(result,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

def main():
    service=Service(os.environ.get('TOONSHELF_DB','/data/accounts.sqlite3'),os.environ.get('TOONSHELF_MASTER_USER'),os.environ.get('TOONSHELF_MASTER_PASSWORD'))
    http=ThreadingHTTPServer((os.environ.get('TOONSHELF_BIND','0.0.0.0'),int(os.environ.get('PORT','8080'))),Handler);http.service=service;http.serve_forever()

if __name__=='__main__':main()
