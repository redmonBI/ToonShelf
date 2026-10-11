"""Private list transfer and install link for the mobile reader."""
import json,webbrowser
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QFileDialog,QMessageBox
MOBILE_URL='https://redmonbi.github.io/ToonShelf/mobile/'

def mobile_snapshot(host):
    from app_services import sanitize_snapshot,portable_work
    from collections_store import work_key
    from shelf_collections import enrich_shelf
    pane=getattr(host,'offline',None);rows=enrich_shelf(getattr(pane,'rows',[]),host.collection_store.entries(),host.auto_store.entries(),host.works)
    works={work_key(w):portable_work(w) for w in rows}
    payload=sanitize_snapshot(dict(lists=host.auto_store.export_data(),favorites=host.collection_store.export_data(),works=list(works.values()),reading=host.cfg.get('reading_positions',{})))
    return dict(format='toonshelf-mobile',version=1,payload=payload)

class MobileDialog(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.setWindowTitle('ToonShelf · 스마트폰·패드 앱');self.resize(560,410);lay=QVBoxLayout(self)
        title=QLabel('어디서든 이어 읽기');title.setStyleSheet('font-size:24px;font-weight:700');lay.addWidget(title)
        note=QLabel('Android의 Chrome에서 아래 주소를 열고 메뉴 → 앱 설치 / 홈 화면에 추가를 선택하세요.\n\n같은 계정으로 목록을 불러오거나 목록 JSON을 가져올 수 있습니다.\n이미지는 PC의 ‘기기용 내보내기’에서 회차별 CBZ로 내보낸 뒤 스마트폰으로 옮겨 ‘파일 가져오기’를 사용하세요.\n\n모바일 앱은 가져온 회차를 오프라인으로 읽습니다. PC 자동 다운로드는 PC 프로그램이 실행 중일 때 진행됩니다.');note.setWordWrap(True);lay.addWidget(note)
        link=QLabel(MOBILE_URL);link.setTextInteractionFlags(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.TextSelectableByMouse);lay.addWidget(link)
        for text,fn in [('모바일 앱 열기',lambda:webbrowser.open(MOBILE_URL)),('목록 JSON 내보내기',self.export),('닫기',self.accept)]:
            b=QPushButton(text);b.clicked.connect(fn);lay.addWidget(b)
    def export(self):
        filename,_=QFileDialog.getSaveFileName(self,'모바일로 옮길 목록 저장','ToonShelf_목록.json','JSON (*.json)')
        if not filename:return
        try:
            payload=mobile_snapshot(self.host);path=Path(filename);temporary=path.with_suffix(path.suffix+'.part');temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
            QMessageBox.information(self,'목록 저장 완료','목록 JSON을 스마트폰으로 옮겨 모바일 앱의 파일 가져오기에서 선택하세요. 이미지·로그인 정보는 포함하지 않았습니다.')
        except Exception as exc:QMessageBox.warning(self,'목록 저장 확인',str(exc))
