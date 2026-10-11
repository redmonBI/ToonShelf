"""Match public catalog metadata without changing private file or schedule records."""
import re,unicodedata
from datetime import datetime,timezone,date
from urllib.parse import urlsplit,urlunsplit
from collections_store import work_dict,work_key,as_work

FIELDS=('title','genre','publisher','thumbnail','weekday','weekdays','latest','updated_date','metadata_checked','metadata_url','metadata_match')

def title_key(value):
    return re.sub(r'[^\w]','',unicodedata.normalize('NFKC',str(value)).casefold())

def extract_date(value):
    match=re.search(r'(20\d{2})[-./](\d{1,2})[-./](\d{1,2})',str(value))
    if not match:return ''
    try:return date(*map(int,match.groups())).isoformat()
    except ValueError:return ''

def work_days(work):
    days=work.get('weekdays',[])
    result={d for d in days if type(d) is int and d in range(7)} if isinstance(days,list) else set()
    if type(work.get('weekday')) is int and work['weekday'] in range(7):result.add(work['weekday'])
    return sorted(result)

class CatalogIndex:
    def __init__(self,catalog):
        self.paths={};self.names={}
        for work in catalog:
            value=work_dict(work);self.paths.setdefault(work_key(value),[]).append(value);self.names.setdefault(title_key(value.get('title','')),[]).append(value)

def match_catalog(work,catalog):
    value=work_dict(work);index=catalog if isinstance(catalog,CatalogIndex) else CatalogIndex(catalog)
    path=work_key(value);direct=index.paths.get(path,[])
    if len(direct)==1:return direct[0],'주소 일치'
    name=title_key(value.get('title',''));matches=index.names.get(name,[]) if name else []
    if len(matches)>1 and value.get('publisher'):
        matches=[w for w in matches if w.get('publisher')==value['publisher']]
    return (matches[0],'작품명 일치') if len(matches)==1 else (None,'중복 작품명' if matches else '사이트에서 찾지 못함')

def merged_work(original,matched,reason):
    value=work_dict(original)
    for field in FIELDS:
        if field in matched and matched[field] not in ('',None,-1,[]):value[field]=matched[field]
    value['metadata_url']=matched['url'];value['metadata_match']=reason
    value['weekdays']=work_days(value)
    return value

def enrich_work(value,metadata=None,automatic=None):
    value=dict(value);m=metadata or {};a=automatic or {}
    for field in FIELDS:
        remote=m.get('work',{}).get(field)
        if remote not in (None,'',-1,[]):value[field]=remote
    value['genre']=m.get('genre') or value.get('genre','')
    value['publisher']=m.get('publisher') or value.get('publisher','')
    override=m.get('weekday',-1)
    if override not in range(7):override=a.get('weekday',-1)
    days=[override] if override in range(7) else work_days(value)
    value['weekdays']=days;value['weekday']=days[0] if days else -1
    return value

def lookup_metadata(cfg,tracked,control,emit):
    from core import Browser,Cancelled
    checked=datetime.now(timezone.utc).isoformat();updates=[];unmatched=[];errors=[]
    with Browser(dict(cfg,_download_job=False),control,emit) as browser:
        catalog=browser.catalog()
        index=CatalogIndex(catalog)
        for i,original in enumerate(tracked):
            control.check();match,reason=match_catalog(original,index)
            if match is None:unmatched.append(dict(title=work_dict(original)['title'],reason=reason));continue
            matched=dict(match,metadata_checked=checked)
            try:
                episodes=browser.episodes(as_work(match))
                dates=[extract_date(e.date) for e in episodes];dates=[d for d in dates if d]
                if dates:matched['updated_date']=max(dates)
            except Cancelled:raise
            except Exception as exc:errors.append(work_dict(original)['title']+' · '+str(exc))
            updates.append(merged_work(original,matched,reason))
            emit('log',f"작품 정보 매칭 {i+1}/{len(tracked)} · {work_dict(original)['title']}")
            control.delay(.25)
    return dict(catalog=[work_dict(w) for w in catalog],updates=updates,unmatched=unmatched,errors=errors)
