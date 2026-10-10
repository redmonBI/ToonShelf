"""Monotonic wall-clock throughput with explicitly estimated remaining time."""
import time
from collections import deque

class DownloadMetrics:
    def __init__(self,clock=time.monotonic):self.clock=clock;self.reset()
    def reset(self):
        self.start=self.clock();self.bytes=0;self.completed=0;self.total=0;self.samples=deque();self.paused_at=None;self.pause_time=0
    def pause(self,value):
        if value and self.paused_at is None:self.paused_at=self.clock()
        elif not value and self.paused_at is not None:
            self.pause_time+=self.clock()-self.paused_at;self.paused_at=None;self.samples.clear()
    def record(self,value):
        self.bytes+=value.get('bytes',0);self.completed=value.get('completed',self.completed);self.total=value.get('total',self.total)
        self.samples.append((self.clock(),self.bytes))
        while len(self.samples)>2 and self.samples[1][0]<self.clock()-15:self.samples.popleft()
    def snapshot(self):
        now=self.paused_at if self.paused_at is not None else self.clock()
        elapsed=max(.001,now-self.start-self.pause_time)
        speed=0
        if self.samples and self.paused_at is None:
            base,amount=self.samples[0]
            speed=max(0,self.bytes-amount)/max(.001,now-base)
            if len(self.samples)==1:speed=self.bytes/elapsed
        remaining=None
        if self.completed>=3 and self.total>=self.completed:remaining=elapsed/self.completed*(self.total-self.completed)
        return {'speed':speed,'remaining':remaining,'paused':self.paused_at is not None,'completed':self.completed,'total':self.total}

def duration(seconds):
    if seconds is None:return '계산 중'
    seconds=max(0,int(seconds));h,r=divmod(seconds,3600);m,s=divmod(r,60)
    return f'{h}시간 {m}분' if h else f'{m}분 {s}초' if m else f'{s}초'
