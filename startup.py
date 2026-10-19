"""Opt-in Windows startup and deferred startup download choices."""
import subprocess
import sys
from pathlib import Path

NAME='ToonShelf'
KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'

def command():
    args=[sys.executable]
    if not getattr(sys,'frozen',False):args.append(str(Path(__file__).with_name('app.py')))
    return subprocess.list2cmdline(args+['--startup'])

def configure(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,KEY) as key:
        if enabled:winreg.SetValueEx(key,NAME,0,winreg.REG_SZ,command())
        else:
            try:winreg.DeleteValue(key,NAME)
            except FileNotFoundError:pass

def begin(host):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    if host.automation_closed:return
    service=host.accounts_service
    if service.busy() or not service.startup_ready:
        QTimer.singleShot(500,lambda:begin(host));return
    if service.startup_error:
        host.status.setText('시작 다운로드 보류 · '+service.startup_error);return
    mode=host.cfg.get('startup_download','manual')
    if mode=='manual':return
    if mode=='automatic':host.automation_action('enqueue','all');return
    box=QMessageBox(host);box.setWindowTitle('ToonShelf · 시작 다운로드');box.setText(f'내 웹툰 목록 {len(host.auto_store.entries())}개 작품의 최신 회차를 확인하고 다운로드할까요?')
    go=box.addButton('진행',QMessageBox.AcceptRole);box.addButton('보류',QMessageBox.RejectRole)
    box.setDefaultButton(go);box.finished.connect(lambda _:host.automation_action('enqueue','all') if box.clickedButton()==go and not host.automation_closed else None)
    host.startup_prompt=box;box.setAttribute(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.WA_DeleteOnClose);box.open()
