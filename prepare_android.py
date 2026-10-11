"""Prepare a reproducible Android source archive; never include signing material."""
from pathlib import Path
import shutil, subprocess, zipfile

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'android_app'
PUBLIC = ROOT / 'mobile'
WEB = APP / 'www'
WEB.mkdir(exist_ok=True)
for path in PUBLIC.rglob('*'):
    rel = path.relative_to(PUBLIC)
    if path.is_file() and not any(p in {'node_modules', 'tests', '__pycache__'} for p in rel.parts) and path.suffix.lower() in {'.html', '.js', '.css', '.png', '.svg', '.webmanifest', '.json'} and path.name not in {'package.json', 'package-lock.json'}:
        dest = WEB / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
subprocess.run(['npx.cmd', 'cap', 'sync', 'android'], cwd=APP, check=True)
with zipfile.ZipFile(ROOT / 'ToonShelf_Android_Source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in APP.rglob('*'):
        rel = path.relative_to(APP)
        if not path.is_file() or any(p in {'node_modules', '.gradle', 'build', '.idea'} for p in rel.parts):
            continue
        if path.name == 'local.properties' or path.suffix.lower() in {'.jks', '.keystore', '.apk', '.aab'}:
            continue
        archive.write(path, 'android_app/' + rel.as_posix())
print('Android source prepared:', (ROOT / 'ToonShelf_Android_Source.zip').stat().st_size)
