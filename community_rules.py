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
    if action=='recommend':
        post={'id':str(request_id),'author':text(request.get('author'),80),'account':actor,
            'title':text(request.get('title'),200),'genre':text(request.get('genre'),200),
            'body':text(request.get('body'),5000),'created':date,'updated':date,'votes':[]}
        if request.get('link'):post['link']=url(request['link'])
        data['posts'].append(post)
    elif action=='vote':
        post=next((p for p in data['posts'] if p['id']==str(request.get('id'))),None)
        if not post:raise ValueError('추천을 찾지 못했습니다.')
        votes=post.setdefault('votes',[])
        if actor in votes:votes.remove(actor)
        else:votes.append(actor)
    elif action in ['edit','delete','site_add','site_delete']:
        if actor.casefold()!=admin.casefold():raise PermissionError('수정·삭제와 사이트 관리는 소유자만 가능합니다.')
        if action.startswith('site_'):
            if action=='site_add':
                item={'id':str(request_id),'name':text(request.get('name'),100),'url':url(request.get('url')),
                    'news_url':url(request['news_url']) if request.get('news_url') else '',
                    'created':date,'updated':date}
                data['sites'].append(item)
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
