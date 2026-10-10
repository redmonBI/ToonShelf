"""Apply a verified release in place from a separate, staged process."""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime,timezone
from pathlib import Path

def allowed(name):
    p=Path(name)
    return (not p.is_absolute() and '..' not in p.parts and ':' not in name and '\\' not in name
            and (name in ('ToonShelf.exe','README.md','RELEASE_NOTES.md') or
                 (len(p.parts)>1 and p.parts[0] in ('_internal','Vendor','Source'))))

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()

def safe_path(root,name):
    if not allowed(name):raise ValueError('패치 파일 경로가 올바르지 않습니다.')
    p=root/Path(name)
    for item in (p,*p.parents):
        if item==root:break
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):
            raise ValueError('연결된 폴더에는 패치를 설치할 수 없습니다.')
    if not p.resolve().is_relative_to(root):raise ValueError('패치 경로가 설치 폴더를 벗어납니다.')
    return p

def prepare_patch(result,target,parent_pid):
    source=Path(result['path']).resolve();target=Path(target).resolve()
    if source==target or source.is_relative_to(target/'_internal'):
        raise ValueError('패치 준비 폴더가 올바르지 않습니다.')
    if not (target/'ToonShelf.exe').is_file():raise ValueError('현재 프로그램의 설치 폴더를 찾지 못했습니다.')
    entries=[]
    for path in sorted(source.rglob('*')):
        name=path.relative_to(source).as_posix()
        if path.is_file() and allowed(name):
            safe_path(source,name);dest=safe_path(target,name);sha=digest(path)
            if dest.is_file() and digest(dest)==sha:continue
            entries.append({'name':name,'sha256':sha,'size':path.stat().st_size})
    if not any(e['name']=='ToonShelf.exe' for e in entries):raise ValueError('패치 실행 파일이 없습니다.')
    required=sum(e['size']+(safe_path(target,e['name']).stat().st_size if safe_path(target,e['name']).is_file() else 0) for e in entries)
    if shutil.disk_usage(target).free<required+32*1024*1024:raise ValueError('패치와 복구본을 저장할 공간이 부족합니다.')
    manifest=source.parent.parent/'patch.json'
    manifest.write_text(json.dumps({'source':str(source),'target':str(target),'parent_pid':parent_pid,
        'version':result['version'],'release_sha256':result['sha256'],'files':entries},ensure_ascii=False,indent=2),encoding='utf-8')
    return str(manifest)

def wait_for_exit(pid):
    if os.name!='nt':raise RuntimeError('Windows 패치 도우미입니다.')
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x100000,False,int(pid))
    if not handle:
        if ctypes.get_last_error()==87:return
        raise OSError('현재 프로그램 종료 상태를 확인할 수 없습니다.')
    try:
        if kernel.WaitForSingleObject(handle,180000)!=0:raise TimeoutError('프로그램 종료를 기다리다가 패치를 중단했습니다.')
    finally:kernel.CloseHandle(handle)

def replace_file(path,temp):
    for attempt in range(31):
        try:os.replace(temp,path);return
        except PermissionError:
            if attempt==30:raise
            time.sleep(.5)

def restart(path):
    return subprocess.Popen([str(path)],cwd=str(path.parent),close_fds=True).pid

def apply_patch(manifest,wait=wait_for_exit,launch=restart):
    manifest=Path(manifest).resolve();data=json.loads(manifest.read_text(encoding='utf-8'))
    source=Path(data['source']).resolve();target=Path(data['target']).resolve();entries=data['files']
    if source.parent.parent!=manifest.parent or source==target:raise ValueError('패치 준비 위치가 올바르지 않습니다.')
    names=[e['name'].casefold() for e in entries]
    if len(names)!=len(set(names)) or 'toonshelf.exe' not in names:raise ValueError('패치 파일 목록이 올바르지 않습니다.')
    for entry in entries:
        src=safe_path(source,entry['name']);safe_path(target,entry['name'])
        if digest(src)!=entry['sha256']:raise ValueError('준비한 패치가 변경되었습니다. 다시 다운로드하세요.')
    wait(data['parent_pid'])
    backup=manifest.parent/'backup';backup.mkdir(exist_ok=False);touched=[]
    status={'version':data['version'],'time':datetime.now(timezone.utc).isoformat(),
            'release_sha256':data['release_sha256'],'backup':str(backup),'status':'applying'}
    log=manifest.parent/'result.json'
    try:
        for entry in entries:
            name=entry['name'];src=safe_path(source,name);dest=safe_path(target,name)
            old=backup/name;existed=dest.exists()
            if existed:
                old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,old)
            dest.parent.mkdir(parents=True,exist_ok=True)
            temp=dest.with_name(dest.name+'.toonshelf-patch-tmp')
            try:
                shutil.copy2(src,temp);replace_file(dest,temp)
            finally:
                if temp.exists():temp.unlink()
            touched.append((name,existed))
        status['status']='complete'
    except Exception as error:
        status.update(status='rolled_back',error=str(error));rollback_errors=[]
        for name,existed in reversed(touched):
            try:
                dest=safe_path(target,name)
                if existed:
                    temp=dest.with_name(dest.name+'.toonshelf-patch-tmp');shutil.copy2(backup/name,temp);replace_file(dest,temp)
                else:dest.unlink(missing_ok=True)
            except Exception as e:rollback_errors.append(str(e))
        if rollback_errors:status.update(status='recovery_required',rollback_errors=rollback_errors)
    log.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    history=target/'state'/'update_history.jsonl';history.parent.mkdir(exist_ok=True)
    with history.open('a',encoding='utf-8') as f:f.write(json.dumps(status,ensure_ascii=False)+'\n')
    if status['status'] in ('complete','rolled_back'):
        status['restart_pid']=launch(target/'ToonShelf.exe')
        log.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if status['status']=='complete' else 1

def run_helper(manifest):
    try:return apply_patch(manifest)
    except Exception as e:
        error='업데이트 처리 중 확인이 필요합니다. Updates 폴더의 결과 기록과 복구본을 확인하세요.\n'+str(e)
        if os.name=='nt':ctypes.windll.user32.MessageBoxW(None,error,'ToonShelf 업데이트',0x10)
        return 1
