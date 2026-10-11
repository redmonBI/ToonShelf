"""Persistent current, planned and previous addresses for named sites."""
import json,uuid
from pathlib import Path
from datetime import datetime,timezone
from community_rules import url

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def revise_site(old,name,address,news='',planned=(),date=None):
    date=date or now();address=url(address);news=url(news) if news else ''
    name=str(name).strip()
    if not name or len(name)>100:raise ValueError('사이트 이름을 입력하세요.')
    history=list(old.get('history',[]))
    prior=old.get('url')
    if prior and not history:history.append({'url':url(prior),'date':old.get('updated',old.get('created',date))})
    if not history or history[-1]['url']!=address:history.append({'url':address,'date':date})
    planned=list(dict.fromkeys(url(x) for x in planned if str(x).strip()))
    return dict(old,name=name,url=address,news_url=news,planned_urls=planned,history=history,created=old.get('created',date),updated=date)

class SiteRegistry:
    def __init__(self,state):self.state=Path(state)
    def read(self,name):
        try:return json.loads((self.state/name).read_text(encoding='utf-8'))
        except (OSError,ValueError):return []
    def write(self,name,rows):
        self.state.mkdir(parents=True,exist_ok=True);p=self.state/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
    def local(self):return self.read('site_links.json')
    def rows(self):return [dict(r,scope='개인') for r in self.local()]+[dict(r,scope='공유') for r in self.read('shared_sites.json')]
    def cache_shared(self,rows):self.write('shared_sites.json',rows)
    def update(self,old,name,address,news='',planned=()):
        rows=self.local();value=revise_site(old,name,address,news,planned);value.setdefault('id',uuid.uuid4().hex)
        for i,r in enumerate(rows):
            if old and (r.get('id')==old.get('id') if old.get('id') else r.get('name')==old.get('name') and r.get('url')==old.get('url')):rows[i]=value;break
        else:rows.append(value)
        self.write('site_links.json',rows);return value
