"""Shared by desktop tests and trusted GitHub Action; accepts data, never code."""
import copy
from datetime import datetime, timezone
from urllib.parse import urlsplit
from link_input import normalize_url

def text(value,limit=200):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('필수 항목 또는 길이를 확인하세요.')
    return value.strip()
def url(value):
    return normalize_url(value)
def apply_request(data,request,actor,admin,request_id,date=None):
    data=copy.deepcopy(data);data.setdefault('posts',[]);data.setdefault('sites',[]);data.setdefault('processed',[])
    if str(request_id) in data['processed']:return data
    if not isinstance(request,dict):raise ValueError('잘못된 요청')
    action=request.get('action');actor=text(actor,100)
    date=date or datetime.now(timezone.utc).isoformat(timespec='seconds')
    if action in ('recommend','recommend_list'):
        post={'id':str(request_id),'author':text(request.get('author'),80),'account':actor,
            'title':text(request.get('title'),200),'genre':text(request.get('genre'),200),
            'body':text(request.get('body'),5000),'created':date,'updated':date,'votes':[]}
        if request.get('link'):post['link']=url(request['link'])
        if action=='recommend_list':
            items=request.get('works')
            if not isinstance(items,list) or not 1<=len(items)<=200:raise ValueError('추천 목록은 요청당 1~200개 작품을 포함해야 합니다.')
            cleaned=[];seen=set()
            for item in items:
                if not isinstance(item,dict):raise ValueError('목록 작품 형식을 확인하세요.')
                day=item.get('weekday',-1)
                if type(day) is not int or day not in range(-1,7):raise ValueError('목록의 요일을 확인하세요.')
                link=url(item.get('link'))
                if link in seen:continue
                seen.add(link);cleaned.append(dict(title=text(item.get('title'),200),genre=text(item.get('genre'),200),publisher=text(item['publisher'],100) if item.get('publisher') else '',weekday=day,link=link))
            post.update(kind='work_list',works=cleaned)
        data['posts'].append(post)
    elif action=='vote':
        post=next((p for p in data['posts'] if p['id']==str(request.get('id'))),None)
        if not post:raise ValueError('추천을 찾지 못했습니다.')
        votes=post.setdefault('votes',[])
        if actor in votes:votes.remove(actor)
        else:votes.append(actor)
    elif action in ['edit','delete','site_add','site_edit','site_delete']:
        if action.startswith('site_'):
            if action=='site_add':
                item={'id':str(request_id),'name':text(request.get('name'),100),'url':url(request.get('url')),
                    'news_url':url(request['news_url']) if request.get('news_url') else '',
                    'created':date,'updated':date}
                from site_registry import revise_site
                item=revise_site(item,item['name'],item['url'],item['news_url'],request.get('planned_urls',[]),date)
                data['sites'].append(item)
            elif action=='site_edit':
                from site_registry import revise_site
                item=next((s for s in data['sites'] if s['id']==str(request.get('id'))),None)
                if not item:raise ValueError('사이트를 찾지 못했습니다.')
                revised=revise_site(item,text(request.get('name'),100),request.get('url'),request.get('news_url',''),request.get('planned_urls',[]),date);item.clear();item.update(revised)
            else:data['sites']=[s for s in data['sites'] if s['id']!=str(request.get('id'))]
        else:
            post=next((p for p in data['posts'] if p['id']==str(request.get('id'))),None)
            if not post:raise ValueError('추천을 찾지 못했습니다.')
            if action=='delete':data['posts'].remove(post)
            else:
                for field,limit in [('author',80),('title',200),('genre',200),('body',5000)]:
                    post[field]=text(request.get(field),limit)
                post['updated']=date
                if request.get('link'):post['link']=url(request['link'])
                else:post.pop('link',None)
    else:raise ValueError('지원하지 않는 요청')
    data['processed'].append(str(request_id));data['updated']=date
    return data
