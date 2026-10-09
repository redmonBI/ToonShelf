import hashlib
import base64
import json
import re
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlencode,urlsplit
from zipfile import ZipFile

VERSION='3.0.0'
REPOSITORY='redmonBI/ToonShelf'
def repository(value):
    value=value.strip().removeprefix('https://github.com/').rstrip('/')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',value):raise ValueError('GitHub 소유자/저장소 형식으로 입력하세요.')
    return value
def get_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'ToonShelf/'+VERSION,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=25) as r:
        raw=r.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('공유 데이터가 너무 큽니다.')
    return json.loads(raw)
def community(repo=REPOSITORY):
    # Read the current Contents revision rather than the stale raw-file CDN.
    data=get_json(f'https://api.github.com/repos/{repository(repo)}/contents/shared/community.json?ref=main&refresh={time.time_ns()}')
    if data.get('encoding')!='base64':raise ValueError('공유 데이터 형식이 올바르지 않습니다.')
    return json.loads(base64.b64decode(data['content'],validate=False))
def releases(repo=REPOSITORY):
    return get_json(f'https://api.github.com/repos/{repository(repo)}/releases?per_page=30')
def version_tuple(value):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)',value)
    if not match:raise ValueError('정식 버전 형식이 아닙니다.')
    return tuple(map(int,match.groups()))
def issue_link(repo,payload):
    from community_rules import apply_request
    # Validate shape locally; authorization is checked by trusted action again.
    if payload.get('action') in ['recommend','site_add']:
        apply_request({},payload,'preview','preview','preview')
    return f'https://github.com/{repository(repo)}/issues/new?'+urlencode({'title':'[ToonShelf] '+str(payload.get('action')),'body':'```json\n'+json.dumps(payload,ensure_ascii=False,indent=2)+'\n```'})
def prepare_update(release,output,repo=REPOSITORY):
    repo=repository(repo)
    if release.get('draft') or release.get('prerelease'):raise ValueError('정식 업데이트만 설치할 수 있습니다.')
    version=release.get('tag_name','');version_tuple(version)
    assets=release.get('assets',[])
    asset=next((a for a in assets if a.get('name')==f'ToonShelf_{version.lstrip("v")}_Windows.zip'),None)
    checksum=next((a for a in assets if a.get('name')=='SHA256SUMS.txt'),None)
    if not asset or not checksum:raise ValueError('설치 파일 또는 검증 파일이 없습니다.')
    base=f'https://github.com/{repo}/releases/download/{version}/'
    for a in [asset,checksum]:
        if not a['browser_download_url'].startswith(base):raise ValueError('업데이트 출처가 일치하지 않습니다.')
    with urllib.request.urlopen(checksum['browser_download_url'],timeout=30) as r:checksum_data=r.read(65536).decode('utf-8')
    expected=next((line.split()[0] for line in checksum_data.splitlines() if line.split()[-1].lstrip('*')==asset['name']),None)
    if not expected or not re.fullmatch('[0-9a-fA-F]{64}',expected):raise ValueError('SHA-256 검증 정보가 없습니다.')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output).free<asset['size']*5:raise ValueError('업데이트용 여유 공간이 부족합니다.')
    stage=Path(tempfile.mkdtemp(prefix='ToonShelf_update_',dir=output))
    try:
        zip_path=stage/'update.zip';sha=hashlib.sha256();count=0
        with urllib.request.urlopen(asset['browser_download_url'],timeout=60) as r,zip_path.open('wb') as f:
            while chunk:=r.read(1024*1024):
                count+=len(chunk)
                if count>asset['size']:raise ValueError('업데이트 파일 크기가 일치하지 않습니다.')
                sha.update(chunk);f.write(chunk)
        if count!=asset['size'] or sha.hexdigest().lower()!=expected.lower():raise ValueError('업데이트 파일 검증에 실패했습니다.')
        expanded=stage/'ready';expanded.mkdir()
        with ZipFile(zip_path) as z:
            if sum(i.file_size for i in z.infolist())>asset['size']*20:raise ValueError('압축 해제 크기 제한 초과')
            for i in z.infolist():
                dest=(expanded/i.filename).resolve()
                if not dest.is_relative_to(expanded) or i.filename.startswith(('/', '\\')) or ':' in i.filename:
                    raise ValueError('안전하지 않은 압축 경로')
                if ((i.external_attr>>16)&0o170000)==0o120000:raise ValueError('심볼릭 링크는 허용하지 않습니다.')
            z.extractall(expanded)
        exe=expanded/'ToonShelf'/'ToonShelf.exe'
        if not exe.exists():raise ValueError('실행 파일이 없습니다.')
        return {'path':str(exe.parent),'version':version,'sha256':expected}
    except Exception:
        shutil.rmtree(stage);raise
