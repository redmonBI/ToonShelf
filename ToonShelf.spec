# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'numpy', 'pandas', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
# Qt uses Windows ICU exports without a version suffix. Other tools on PATH
# can expose a different ICU DLL with the same name; do not bundle that DLL.
import os
windows_icu = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32', 'icuuc.dll')
a.binaries = [entry for entry in a.binaries if os.path.basename(entry[0]).lower() != 'icuuc.dll']
a.binaries.append(('icuuc.dll', windows_icu, 'BINARY'))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ToonShelf',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ToonShelf',
)
