"""Share work metadata, never paths, credentials, settings or download history."""
import json
from collections_store import work_key
from link_input import normalize_url

def list_requests(entries,collections,author,note=''):
    if not isinstance(author,str) or not author.strip() or len(author)>80:raise ValueError('추천인 이름을 80자 이내로 입력하세요.')
    if len(note)>5000:raise ValueError('추천 내용은 5,000자 이내로 입력하세요.')
    meta={e['key']:e for e in collections};works={}
    for entry in entries:
        w=entry['work'];key=work_key(w);m=meta.get(key,{})
        item=dict(title=str(w['title'])[:200],genre=str(m.get('genre') or w.get('genre') or '미분류')[:200],publisher=str(m.get('publisher') or w.get('publisher') or '')[:100],link=normalize_url(w['url']),weekday=next((d for d in (m.get('weekday',-1),entry.get('weekday',-1),w.get('weekday',-1)) if isinstance(d,int) and d in range(7)),-1))
        works[key]=item
    if not works:raise ValueError('내 웹툰 목록에 작품을 먼저 추가하세요.')
    ordered=sorted(works.values(),key=lambda w:(w['weekday'] if w['weekday']>=0 else 7,w['title']))
    groups=[];current=[]
    for work in ordered:
        if current and (len(current)>=200 or len(json.dumps(current+[work],ensure_ascii=False,indent=2))+len(note)>46000):groups.append(current);current=[]
        current.append(work)
    if current:groups.append(current)
    return [dict(action='recommend_list',author=author.strip(),title='내 웹툰 목록'+(f' · {i+1}/{len(groups)}' if len(groups)>1 else ''),genre='작품 리스트',body=note.strip() or '함께 읽고 싶은 내 웹툰 목록을 공유합니다.',works=group) for i,group in enumerate(groups)]

def launch_request(repo,payload):
    import webbrowser
    from sharing import issue_link,repository
    from urllib.parse import urlencode
    from PySide6.QtWidgets import QApplication
    repo=repository(repo);link=issue_link(repo,payload)
    if len(link)>7000:
        QApplication.clipboard().setText('```json\n'+json.dumps(payload,ensure_ascii=False,indent=2)+'\n```')
        webbrowser.open(f'https://github.com/{repo}/issues/new?'+urlencode({'title':'[ToonShelf] '+payload['action']}))
        return '목록을 클립보드에 준비했습니다. GitHub 본문에 붙여넣고 Submit new issue를 누르세요.'
    webbrowser.open(link)
    return 'GitHub의 Submit new issue를 눌러 등록하세요. 자동 처리 후 친구 추천을 새로고침하세요.'
