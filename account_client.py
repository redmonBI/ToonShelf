"""HTTPS metadata client. Remembered sessions are encrypted by Windows DPAPI."""
import base64
import ctypes
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit, quote

class AccountError(Exception):
    def __init__(self,message,status=0):self.status=status;super().__init__(message)

def endpoint(value):
    value=str(value).strip().rstrip('/');parts=urlsplit(value)
    if parts.username or parts.password or parts.query or parts.fragment:raise ValueError('서버 주소에 인증 정보·쿼리를 넣을 수 없습니다.')
    if not parts.hostname or not (parts.scheme=='https' or parts.scheme=='http' and parts.hostname in ('localhost','127.0.0.1','::1')):raise ValueError('HTTPS 주소를 사용하세요. HTTP는 이 컴퓨터의 시험 서버에서만 가능합니다.')
    return value

def protect(raw,decrypt=False):
    if os.name!='nt':raise AccountError('자동 로그인 저장은 Windows에서 지원됩니다.')
    class Blob(ctypes.Structure):_fields_=[('length',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(raw);source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));dest=Blob()
    call=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    description=None if decrypt else 'ToonShelf session'
    if not call(ctypes.byref(source),description,None,None,None,1,ctypes.byref(dest)):raise AccountError('로그인 정보를 안전하게 저장하거나 읽을 수 없습니다.')
    try:return ctypes.string_at(dest.data,dest.length)
    finally:ctypes.windll.kernel32.LocalFree(dest.data)

class AccountClient:
    def __init__(self,state,server=''):
        self.state=Path(state);self.state.mkdir(parents=True,exist_ok=True);self.server=endpoint(server) if server else '';self.token='';self.user=None;self.revision=None;self.config_revision=0;self.menu_labels={}
        self.settings_path=self.state/'account_connection.json';self.token_path=self.state/'account_session.dpapi'
        if not server and self.settings_path.exists():
            try:self.server=endpoint(json.loads(self.settings_path.read_text(encoding='utf-8')).get('server',''))
            except (ValueError,OSError):pass
        if self.token_path.exists():
            try:
                saved=json.loads(protect(self.token_path.read_bytes(),True));self.token=saved['token'] if saved['server']==self.server else ''
            except Exception:self.token=''
    def connect(self,server):
        new=endpoint(server)
        if new!=self.server:self.clear_session()
        self.server=new;self.settings_path.write_text(json.dumps({'server':new}),encoding='utf-8')
    def request(self,method,path,payload=None):
        if not self.server:raise AccountError('계정 서버 주소를 먼저 설정하세요.')
        raw=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
        headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'ToonShelf'}
        if self.token:headers['Authorization']='Bearer '+self.token
        request=urllib.request.Request(self.server+path,data=raw,headers=headers,method=method)
        # Prevent token leakage through an HTTP redirect or a changed origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args):return None
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=20) as response:raw=response.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:raise AccountError('서버 응답이 너무 큽니다.')
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            try:message=json.loads(exc.read(4096)).get('error','서버 요청을 처리하지 못했습니다.')
            except Exception:message='서버 요청을 처리하지 못했습니다.'
            raise AccountError(message,exc.code) from exc
        except (urllib.error.URLError,TimeoutError,OSError) as exc:raise AccountError('계정 서버에 연결할 수 없습니다. 로컬 기능은 계속 사용할 수 있습니다.') from exc
    def register(self,username,password,display_name,consent):return self.request('POST','/v1/register',{'username':username,'password':password,'display_name':display_name,'admin_visibility_consent':consent})
    def login(self,username,password,remember=False):
        result=self.request('POST','/v1/login',{'username':username,'password':password});self.clear_session();self.token=result['token'];self.user=result['user'];self.revision=None
        if remember:
            raw=protect(json.dumps({'server':self.server,'token':self.token}).encode());temp=self.token_path.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(self.token_path)
        return result
    def restore(self):
        try:result=self.request('GET','/v1/me')
        except AccountError as exc:
            if exc.status==401:self.clear_session()
            raise
        self.user=result['user'];return result
    def clear_session(self):
        self.token='';self.user=None;self.revision=None;self.config_revision=0;self.menu_labels={};self.token_path.unlink(missing_ok=True)
    def logout(self):
        try:return self.request('POST','/v1/logout')
        finally:self.clear_session()
    def pull(self):
        result=self.request('GET','/v1/snapshot');self.revision=result['revision'];self.cache(result);return result
    def push(self,payload):
        if self.revision is None:raise AccountError('서버 목록을 먼저 불러오세요. 다른 계정의 로컬 목록을 바로 덮어쓰지 않습니다.')
        result=self.request('PUT','/v1/snapshot',{'revision':self.revision,'payload':payload});self.revision=result['revision'];self.cache({'revision':self.revision,'payload':payload});return result
    def cache(self,result):
        if self.user:
            path=self.state/'accounts'/self.user['id'];path.mkdir(parents=True,exist_ok=True);temp=path/'snapshot.tmp';temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');temp.replace(path/'snapshot.json')
    def config(self):
        result=self.request('GET','/v1/config');self.config_revision=result['revision'];self.menu_labels=result['payload'].get('menu_labels',{});return result
    def set_labels(self,labels):return self.request('PUT','/v1/config',{'revision':self.config_revision,'menu_labels':labels})
    def users(self,search=''):return self.request('GET','/v1/admin/users?q='+quote(search))
    def inspect_user(self,uid):return self.request('GET','/v1/admin/users/'+quote(uid,safe=''))
    def delete_user(self,uid):return self.request('DELETE','/v1/admin/users/'+quote(uid,safe=''))
