import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from sharing import VERSION

root=Path(__file__).resolve().parent;release=root/('portable_final' if '--final' in sys.argv else 'portable')/'ToonShelf'
state=release/'state';state.mkdir(exist_ok=True)
# Export only clean defaults, never credentials, downloaded works or personal paths.
(state/'settings.json').write_text(json.dumps({'site_url':'https://blacktoon423.com','community_repo':'redmonBI/ToonShelf',
 'retry_once':False,'hidden_genres':[],'catalog_sort':0},ensure_ascii=False,indent=2),encoding='utf-8')
(release/'README.md').write_text((root/'README.md').read_text(encoding='utf-8'),encoding='utf-8')
(release/'RELEASE_NOTES.md').write_text((root/'RELEASE_NOTES.md').read_text(encoding='utf-8'),encoding='utf-8')
target=root/f'ToonShelf_{VERSION}_Windows.zip'
with ZipFile(target,'w',ZIP_DEFLATED,compresslevel=6) as z:
    for p in release.rglob('*'):
        if p.is_file() and (p.name=='ToonShelf.exe' or '_internal' in p.relative_to(release).parts or
           p.name in ['README.md','RELEASE_NOTES.md'] or p==state/'settings.json'):
            z.write(p,Path('ToonShelf')/p.relative_to(release))
    for p in root.glob('*.py'):
        if not p.name.startswith(('capture_','validate_','diagnose_')):z.write(p,Path('ToonShelf')/'Source'/p.name)
    for name in ['requirements.txt','ToonShelf.spec','install.bat','run.bat']:z.write(root/name,Path('ToonShelf')/'Source'/name)
with ZipFile(target) as z:assert z.testzip() is None
sha=hashlib.sha256(target.read_bytes()).hexdigest()
(root/'SHA256SUMS.txt').write_text(sha+'  '+target.name+'\n',encoding='utf-8')
print(str(target),target.stat().st_size,sha,flush=True)
