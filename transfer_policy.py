"""Interruptible image streaming and live daily bandwidth/time rules."""
import json,time,threading,weakref
from pathlib import Path
from urllib.request import build_opener,HTTPCookieProcessor,Request
from urllib.error import HTTPError
from http.cookiejar import CookieJar,Cookie
from automation_store import in_window,local_now

def validate_policy(value):
    from automation_store import minute
    for field in ('limit_mib',):
        if not 0<=value.get(field,0)<=1024:raise ValueError('속도는 0~1024 MB/s 범위로 설정하세요.')
    minute(value.get('start','00:00'));minute(value.get('end','00:00'))
    for rule in value.get('rules',[]):
        minute(rule['start']);minute(rule['end'])
        if not 0<=rule['mib']<=1024:raise ValueError('시간대별 속도를 확인하세요.')
    return value

class SharedBandwidth:
    """A process-wide budget shared by all image download workers."""
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.Lock();self.last=clock();self.tokens=0.;self.rate=0.
    def take(self,amount,rate):
        with self.lock:
            now=self.clock()
            self.tokens=min(65536.,self.tokens+max(0,now-self.last)*self.rate)
            self.last=now;self.rate=rate
            taken=min(amount,self.tokens);self.tokens-=taken
            return taken

_budgets=weakref.WeakValueDictionary()
_budget_lock=threading.Lock()
def shared_budget(cfg,clock):
    # Workers reading the same settings file always share one global limit.
    scope=str(Path(cfg['policy_file']).resolve()).casefold() if cfg.get('policy_file') else None
    if not scope:return SharedBandwidth(clock)
    with _budget_lock:
        budget=_budgets.get(scope)
        if budget is None:budget=SharedBandwidth(clock);_budgets[scope]=budget
        return budget

class TransferPolicy:
    def __init__(self,cfg,clock=time.monotonic,calendar=local_now):
        self.cfg=cfg;self.clock=clock;self.calendar=calendar;self.last_read=-100.;self.value=cfg.get('network_policy',{});self.deadline=clock();self.waiting=False;self.budget=shared_budget(cfg,clock)
    def spec(self):
        if self.clock()-self.last_read>=1:
            self.last_read=self.clock()
            try:
                if self.cfg.get('policy_file'):self.value=validate_policy(json.loads(Path(self.cfg['policy_file']).read_text(encoding='utf-8')).get('network_policy',{}))
            except (OSError,ValueError,TypeError,KeyError):pass
        return self.value
    def managed(self):
        v=self.spec();return bool(v.get('window_enabled') or self.limit())
    def limit(self):
        v=self.spec();limits=[v.get('limit_mib',0)]+[r['mib'] for r in v.get('rules',[]) if in_window(self.calendar(),r['start'],r['end'])]
        return min((n for n in limits if n>0),default=0)*1024**2
    def allowed(self):
        v=self.spec();return not v.get('window_enabled') or in_window(self.calendar(),v.get('start','00:00'),v.get('end','00:00'))
    def gate(self,control,emit):
        while not self.allowed():
            if not self.waiting:emit('log','허용 다운로드 시간까지 대기 중 · 중단 가능');emit('transfer_wait',True);self.waiting=True
            control.delay(.25)
        if self.waiting:emit('log','허용 다운로드 시간 · 진행 재개');emit('transfer_wait',False);self.waiting=False
        control.check()
    def consume(self,size,control,emit):
        self.gate(control,emit);rate=self.limit()
        if not rate:self.deadline=self.clock();return
        remaining=size
        while remaining>0:
            self.gate(control,emit);rate=self.limit()
            if not rate:break
            remaining-=self.budget.take(remaining,rate)
            if remaining>0:control.delay(min(.05,max(.001,remaining/rate)))

def stream_image(url,headers,cookies,policy,control,emit):
    jar=CookieJar()
    for c in cookies:
        domain=c['domain'];jar.set_cookie(Cookie(0,c['name'],c['value'],None,False,domain,domain.startswith('.'),domain.startswith('.'),c.get('path','/'),True,c.get('secure',False),None,True,None,None,{},False))
    opener=build_opener(HTTPCookieProcessor(jar));policy.gate(control,emit)
    try:response=opener.open(Request(url,headers=headers),timeout=30)
    except HTTPError as e:
        if e.code in (401,403):raise PermissionError(f'이미지 서버 접근 제한 ({e.code})') from e
        raise
    with response:
        chunks=[];size=0
        while True:
            policy.gate(control,emit);data=response.read(64*1024)
            if not data:break
            size+=len(data)
            if size>256*1024**2:raise ValueError('이미지 파일이 처리 가능한 크기를 초과했습니다.')
            policy.consume(len(data),control,emit);chunks.append(data)
        return b''.join(chunks)
