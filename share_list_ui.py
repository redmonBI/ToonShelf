from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPlainTextEdit,QTableWidget,QTableWidgetItem,QPushButton,QHeaderView,QAbstractItemView
from collections_store import DAYS
from list_sharing import list_requests,launch_request
from sharing import REPOSITORY

class ShareListDialog(QDialog):
    def __init__(self,host,parent=None):
        super().__init__(parent or host);self.host=host;self.requests=[];self.index=0;self.setWindowTitle('내 웹툰 목록 전체 공유');self.resize(900,690);lay=QVBoxLayout(self)
        title=QLabel('친구에게 나의 다음 이야기를');title.setStyleSheet('font-size:24px;font-weight:700');lay.addWidget(title)
        hint=QLabel('내 웹툰 목록 전체를 추천 리스트로 공유합니다. 작품명·장르·제공처·요일·링크만 포함하며, 저장 위치·다운로드 이력·설정·로그인 정보는 포함하지 않습니다.');hint.setWordWrap(True);lay.addWidget(hint)
        self.author=QLineEdit(host.cfg.get('community_author',''));self.author.setPlaceholderText('추천인 이름 · 필수');self.author.setMaxLength(80);lay.addWidget(self.author)
        self.note=QPlainTextEdit();self.note.setPlaceholderText('함께 읽고 싶은 이유 · 선택');self.note.setMaximumHeight(100);lay.addWidget(self.note)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['작품명','장르','제공처','요일','작품 링크']);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table,1)
        self.entries=host.auto_store.entries();self.metadata=host.collection_store.entries()
        try:self.preview=list_requests(self.entries,self.metadata,'미리보기')
        except ValueError:self.preview=[]
        works=[w for p in self.preview for w in p['works']];self.table.setRowCount(len(works))
        for i,w in enumerate(works):
            for c,v in enumerate([w['title'],w['genre'],w['publisher'],DAYS[w['weekday']] if w['weekday']>=0 else '미지정',w['link']]):self.table.setItem(i,c,QTableWidgetItem(v))
        self.info=QLabel(f'공유할 작품 {len(works)}개 · 실제 등록 전에 내용을 확인하세요.');self.info.setWordWrap(True);lay.addWidget(self.info)
        row=QHBoxLayout();close=QPushButton('닫기');close.clicked.connect(self.reject);row.addWidget(close);row.addStretch();self.send=QPushButton('전체 목록 GitHub에 등록');self.send.setObjectName('primary');self.send.setEnabled(bool(works));self.send.clicked.connect(self.submit);row.addWidget(self.send);lay.addLayout(row)
    def submit(self):
        try:
            if not self.requests:
                self.requests=list_requests(self.entries,self.metadata,self.author.text(),self.note.toPlainText());self.author.setEnabled(False);self.note.setEnabled(False)
            text=launch_request(self.host.cfg.get('community_repo',REPOSITORY),self.requests[self.index]);self.host.cfg['community_author']=self.author.text().strip();self.host.persist_settings();self.index+=1
            self.info.setText(f'등록 화면 {self.index}/{len(self.requests)}을 열었습니다. '+text)
            self.send.setText('다음 목록 등록 화면' if self.index<len(self.requests) else '등록 화면 모두 열림');self.send.setEnabled(self.index<len(self.requests))
        except Exception as exc:self.info.setText(str(exc))
