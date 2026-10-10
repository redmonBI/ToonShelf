"""Fetch the official unchanged portable build for both local and CI packages."""
import hashlib
import shutil
import subprocess
import urllib.request
from pathlib import Path

VERSION='1.6.5'
SHA256='33260a274efbfe0461944f845c987222ce6e8472b0056987fe67eb37621730ea'
root=Path(__file__).resolve().parent
archive=root/'ThirdParty'/'OpenComic-1.6.5.7z';archive.parent.mkdir(exist_ok=True)
url=f'https://github.com/ollm/OpenComic/releases/download/v{VERSION}/OpenComic-Folder-Portable-{VERSION}.7z'
if not archive.is_file():urllib.request.urlretrieve(url,archive)
if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise RuntimeError('OpenComic official archive checksum mismatch')
target=root/'Vendor'/'OpenComic';target.mkdir(parents=True,exist_ok=True)
extractor=shutil.which('7z') or r'C:\Program Files\7-Zip\7z.exe'
subprocess.run([extractor,'x',str(archive),'-o'+str(target),'-y'],check=True,stdout=subprocess.DEVNULL)
if not (target/'OpenComic.exe').is_file():raise RuntimeError('OpenComic.exe is missing')
license_url=f'https://raw.githubusercontent.com/ollm/OpenComic/v{VERSION}/LICENSE'
urllib.request.urlretrieve(license_url,target/'LICENSE_OpenComic.txt')
(target/'SOURCE_AND_NOTICE.txt').write_text(f'OpenComic {VERSION}, official unchanged portable binary by ollm.\nLicense: see LICENSE_OpenComic.txt.\nCorresponding source and build instructions: https://github.com/ollm/OpenComic/tree/v{VERSION}\nSource archive (equivalent access, same version): https://github.com/ollm/OpenComic/archive/refs/tags/v{VERSION}.zip\nOfficial binaries: https://github.com/ollm/OpenComic/releases/tag/v{VERSION}\nOpenComic is an external application; ToonShelf embedded reader is independently implemented.\n',encoding='utf-8')
print('OpenComic verified and bundled',flush=True)
