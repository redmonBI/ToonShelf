"""Runs only from the repository default branch in GitHub Actions."""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from community_rules import apply_request

def api(path,method='GET',payload=None):
    req=urllib.request.Request('https://api.github.com'+path,
        data=json.dumps(payload).encode() if payload is not None else None,method=method,
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','User-Agent':'ToonShelf-community','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(req,timeout=45) as r:
        data=r.read();return json.loads(data) if data else None

def main():
    repo=os.environ['GITHUB_REPOSITORY'];admin=repo.split('/')[0]
    base='/repos/'+repo;requests=[]
    for page in range(1,21):
        rows=api(base+f'/issues?state=open&sort=created&direction=asc&per_page=100&page={page}')
        requests.extend(r for r in rows if not r.get('pull_request') and r['title'].startswith('[ToonShelf]'))
        if len(rows)<100:break
    for issue in requests:
        try:
            body=issue.get('body') or ''
            if len(body)>15000:raise ValueError('Request too large')
            match=re.fullmatch(r'\s*```json\s*\n(.*?)\n```\s*',body,re.S)
            if not match:raise ValueError('Expected a JSON request')
            request=json.loads(match.group(1))
            actor=issue['user']['login']
            for attempt in range(6):
                current=api(base+'/contents/shared/community.json?ref=main')
                data=json.loads(base64.b64decode(current['content']))
                changed=apply_request(data,request,actor,admin,issue['number'])
                if changed==data:break
                content=base64.b64encode(json.dumps(changed,ensure_ascii=False,indent=2).encode()).decode()
                try:
                    api(base+'/contents/shared/community.json','PUT',{'message':f'Process community request #{issue["number"]}',
                        'content':content,'sha':current['sha'],'branch':'main'})
                    break
                except urllib.error.HTTPError as e:
                    if e.code!=409 or attempt==5:raise
                    time.sleep(attempt+1)
            message='처리 완료. ToonShelf에서 공유 목록을 새로고침하세요.'
        except (ValueError,PermissionError) as e:message='요청 거절: '+str(e)
        # Unexpected network errors leave the issue open for the next run.
        api(base+f'/issues/{issue["number"]}/comments','POST',{'body':message})
        api(base+f'/issues/{issue["number"]}','PATCH',{'state':'closed'})

if __name__=='__main__':main()
