"""Only program-owned recovery files may be removed; never user media/state."""
import json,shutil,os,stat
from pathlib import Path

MARKER='_toonshelf_backup.json'

def remove_owned_tree(path):
    def writable_retry(function,name,error):
        if not isinstance(error,PermissionError):raise error
        os.chmod(name,os.stat(name).st_mode | stat.S_IWUSR)
        function(name)
    shutil.rmtree(path,onexc=writable_retry)
def assert_tree(path,stage=False):
    path=Path(path)
    for p in (path,*path.rglob('*')):
        if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):raise ValueError('연결된 업데이트 폴더는 정리하지 않습니다.')
        if p.is_dir() and p.name.casefold() in ('state','downloads','accounts'):
            if not (stage and p.relative_to(path).as_posix()=='ready/ToonShelf/state'):raise ValueError('개인 데이터가 있는 폴더는 정리하지 않습니다.')
def backup_owned(path,target):
    from patch_update import allowed,digest
    path=Path(path);assert_tree(path)
    meta=json.loads((path/MARKER).read_text(encoding='utf-8'))
    if meta.get('kind')!='ToonShelf recovery' or meta.get('status') not in ('complete','rolled_back'):raise ValueError('복구 확인이 필요한 이전 버전은 보존합니다.')
    if Path(meta['target']).resolve()!=Path(target).resolve():raise ValueError('다른 설치 폴더의 백업입니다.')
    actual={p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file() and p.name!=MARKER}
    if actual!=set(meta.get('files',{})):raise ValueError('복구본에 추가된 파일이 있어 정리하지 않습니다.')
    for p in path.rglob('*'):
        if p.is_file() and p.name!=MARKER and not allowed(p.relative_to(path).as_posix()):raise ValueError('백업에 사용자 파일이 있어 정리하지 않습니다.')
        if p.is_file() and p.name!=MARKER and digest(p)!=meta['files'][p.relative_to(path).as_posix()]:raise ValueError('변경된 복구본은 정리하지 않습니다.')
    return meta
def stage_owned(path,target):
    from patch_update import allowed
    path=Path(path);assert_tree(path,stage=True)
    data=json.loads((path/'patch.json').read_text(encoding='utf-8'));result=json.loads((path/'result.json').read_text(encoding='utf-8'))
    if Path(data['target']).resolve()!=Path(target).resolve() or result['status'] not in ('complete','rolled_back','prepared'):raise ValueError('미완료 패치는 복구를 위해 보존합니다.')
    from zipfile import ZipFile
    zipped=None
    if (path/'update.zip').exists():
        with ZipFile(path/'update.zip') as z:zipped={i.filename for i in z.infolist() if not i.is_dir()}
    for p in path.rglob('*'):
        if not p.is_file():continue
        name=p.relative_to(path).as_posix()
        if name in ('update.zip','patch.json','result.json'):continue
        if name.startswith('ready/ToonShelf/') and allowed(name[len('ready/ToonShelf/'):]):
            if zipped is not None and name[6:] not in zipped:raise ValueError('패치 폴더에 추가된 파일이 있어 정리하지 않습니다.')
            continue
        if name.startswith('ready/ToonShelf/state/') and name=='ready/ToonShelf/state/settings.json':continue
        if name.startswith('backup/') and allowed(name[7:]):
            if name[7:] not in {e['name'] for e in data.get('files',[])}:raise ValueError('복구본에 추가된 파일이 있어 정리하지 않습니다.')
            continue
        raise ValueError('사용자 파일이 추가된 패치 폴더는 정리하지 않습니다.')
    return result
def previous_path(target):return Path(target).resolve()/'PreviousVersion'
def clear_previous(target):
    path=previous_path(target)
    if path.exists():backup_owned(path,target);remove_owned_tree(path)
def clean_stage(path,target):
    path=Path(path);updates=Path(target).resolve()/'Updates'
    if path.parent.resolve()!=updates or not (path.name=='current' or path.name.startswith('ToonShelf_update_')):raise ValueError('관리되는 패치 폴더만 정리할 수 있습니다.')
    stage_owned(path,target);remove_owned_tree(path)
def list_storage(target):
    target=Path(target).resolve();rows=[];prev=previous_path(target)
    candidates=[prev,*((target/'Updates').glob('ToonShelf_update_*'))]
    current=target/'Updates'/'current'
    if current.exists():candidates.append(current)
    for p in candidates:
        if not p.exists():continue
        try:
            meta=backup_owned(p,target) if p==prev else stage_owned(p,target)
            rows.append(dict(path=str(p),name='이전 버전 복구본' if p==prev else '설치 전 준비 파일' if meta.get('status')=='prepared' else '완료된 패치 임시 파일',version=meta.get('version',''),size=sum(f.stat().st_size for f in p.rglob('*') if f.is_file())))
        except (OSError,ValueError,KeyError):continue
    return rows

def prepare_slot(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);slot=output/'current'
    if slot.exists():clean_stage(slot,output.parent)
    slot.mkdir();return slot

def cleanup_applied_stages(target):
    target=Path(target).resolve();updates=target/'Updates';removed=[]
    candidates=[updates/'current',*updates.glob('ToonShelf_update_*')]
    for path in candidates:
        if not path.exists():continue
        try:
            meta=stage_owned(path,target)
            if meta.get('status')=='complete' and Path(meta.get('backup','')).resolve()==previous_path(target):
                clean_stage(path,target);removed.append(path.name)
        except (OSError,ValueError,KeyError):continue
    return removed
