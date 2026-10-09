import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

class PowerPlan:
    """Never armed implicitly; tests inject a runner and clock."""
    def __init__(self,history,runner=None,clock=time.time):
        self.history=Path(history);self.clock=clock
        self.runner=runner or (lambda args:subprocess.run(args,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        self.armed=False;self.issued=False;self.spec={};self.deadline=None;self.fire_at=None
    def log(self,event):
        self.history.parent.mkdir(parents=True,exist_ok=True)
        with self.history.open('a',encoding='utf-8') as f:
            f.write(json.dumps({'date':datetime.now().astimezone().isoformat(),'event':event,'plan':self.spec},ensure_ascii=False)+'\n')
    def arm(self,spec):
        if self.issued:raise ValueError('먼저 진행 중인 종료 예약을 취소하세요.')
        if spec['action'] not in ['app','pc','force'] or spec['trigger'] not in ['complete','timer','at']:raise ValueError('종료 설정 오류')
        deadline=None
        if spec['trigger']=='timer':
            minutes=int(spec['minutes'])
            if not 1<=minutes<=10080:raise ValueError('타이머는 1~10080분입니다.')
            deadline=self.clock()+minutes*60
        if spec['trigger']=='at':
            deadline=float(spec['timestamp'])
            if deadline<=self.clock():raise ValueError('미래의 종료 시각을 선택하세요.')
        self.spec=dict(spec);self.deadline=deadline
        self.armed=True;self.log('armed')
    def due(self,complete=False):
        return self.armed and (complete if self.spec['trigger']=='complete' else self.clock()>=self.deadline)
    def execute(self):
        if not self.armed:return None
        self.armed=False
        action=self.spec['action']
        if action!='app':
            # Windows /t>0 implies /f. Keep the cancellable countdown in-app
            # so a normal shutdown does not silently become a forced one.
            self.fire_at=self.clock()+60;self.issued=True
        self.log('issued');return action
    def fire_due(self):
        if not self.issued or self.fire_at is None or self.clock()<self.fire_at:return False
        args=['shutdown.exe','/s','/t','0']
        if self.spec['action']=='force':args.append('/f')
        self.runner(args);self.issued=False;self.fire_at=None;self.log('shutdown');return True
    def cancel(self):
        self.armed=False;self.issued=False;self.deadline=None;self.fire_at=None;self.log('cancelled')

