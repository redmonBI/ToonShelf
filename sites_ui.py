import json
import re
import webbrowser
import urllib.request
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from PySide6.QtWidgets import QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QLineEdit,QFormLayout,QDialog,QMessageBox,QAbstractItemView
from control_ui import TaskDialog,button
from sharing import community,REPOSITORY,issue_link
from community_rules import url

def latest_links(address):
    address=url(address)
    req=urllib.request.Request(address,headers={'User-Agent':'ToonShelf/3.0'})
    with urllib.request.urlopen(req,timeout=25) as r:
        raw=r.read(3*1024*1024+1);base=r.url
    if len(raw)>3*1024*1024:raise ValueError('페이지가 너무 큽니다.')
    soup=BeautifulSoup(raw,'html.parser');result=[];seen=set()
    for a in soup.select('a[href]'):
        title=a.get_text(' ',strip=True);link=urljoin(base,a['href'])
        if urlsplit(link).scheme not in ['https','http'] or link in seen:continue
        if re.search(r'\d+\s*화|최신|업데이트|신작|공식|새 주소',title):
            result.append({'title':title[:200],'url':link});seen.add(link)
        if len(result)>=100:break
    return result

class SitesDialog(TaskDialog):
    def __init__(self,parent):
        super().__init__(parent);self.owner=parent;self.setWindowTitle('사이트 공유 · 최신 링크');self.resize(1050,690)
        self.local_file=parent.state_dir/'site_links.json'
        try:self.local=json.loads(self.local_file.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.local=[]
        self.shared=[];self.rows=[]
        lay=QVBoxLayout(self);lay.addWidget(QLabel('SITES  /  연결할 곳과 최신 소식'))
        self.info=QLabel('개인 링크는 이 PC에 저장합니다. 공유 사이트 등록·삭제는 저장소 소유자만 가능합니다.');self.info.setWordWrap(True);lay.addWidget(self.info)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['종류','사이트','주소','최신 소식 주소']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table)
        row=QHBoxLayout()
        for title,fn in [('개인 링크 추가',lambda:self.add(False)),('공유 사이트 등록 · 소유자',lambda:self.add(True)),('삭제',self.delete),('공유 갱신',self.refresh),('사이트 열기',self.open),('웹에서 최신 링크 조회',self.latest)]:row.addWidget(button(title,fn))
        lay.addLayout(row)
        self.news=QTableWidget(0,2);self.news.setHorizontalHeaderLabels(['웹페이지에 표시된 최신 링크','주소']);self.news.horizontalHeader().setStretchLastSection(True);self.news.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.news.cellDoubleClicked.connect(self.open_news);lay.addWidget(self.news)
        lay.addWidget(QLabel('사이트별 본문 구조가 다를 수 있습니다. 이 화면은 링크 조회·공유용이며 다운로드 어댑터를 자동 변경하지 않습니다.'))
        self.show_rows();self.refresh()
    def show_rows(self):
        self.rows=[dict(r,scope='개인') for r in self.local]+[dict(r,scope='공유') for r in self.shared];self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            for c,v in enumerate([r['scope'],r['name'],r['url'],r.get('news_url','')]):self.table.setItem(n,c,QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
    def selected(self):
        n=self.table.currentRow();return self.rows[n] if 0<=n<len(self.rows) else None
    def save(self):self.local_file.write_text(json.dumps(self.local,ensure_ascii=False,indent=2),encoding='utf-8');self.show_rows()
    def refresh(self):self.task(lambda:community(self.owner.cfg.get('community_repo',REPOSITORY)),self.loaded)
    def loaded(self,ok,data):
        if not ok:self.info.setText('공유 링크 확인 실패: '+str(data));return
        self.shared=data.get('sites',[]);self.show_rows();self.info.setText(f'공유 사이트 {len(self.shared)}개 · 사이트 관리는 소유자 전용')
    def add(self,shared):
        d=QDialog(self);d.setWindowTitle('공유 사이트 등록' if shared else '개인 사이트');lay=QFormLayout(d);fields={}
        for k,t in [('name','사이트 이름'),('url','주소'),('news_url','최신 소식 / 주소 안내 페이지 · 선택')]:fields[k]=QLineEdit();lay.addRow(t,fields[k])
        def send():
            try:
                r={k:w.text().strip() for k,w in fields.items()};r['url']=url(r['url'])
                if r['news_url']:r['news_url']=url(r['news_url'])
                if not r['name']:raise ValueError('사이트 이름을 입력하세요.')
                if shared:webbrowser.open(issue_link(self.owner.cfg.get('community_repo',REPOSITORY),dict(r,action='site_add')))
                else:self.local.append(r);self.save()
                d.accept()
            except Exception as e:QMessageBox.warning(d,'입력 확인',str(e))
        lay.addRow(button('등록',send));d.exec()
    def delete(self):
        r=self.selected()
        if not r:return
        if QMessageBox.question(self,'사이트 삭제','선택한 링크를 삭제할까요?')!=QMessageBox.StandardButton.Yes:return
        if r['scope']=='개인':self.local=[p for p in self.local if p!= {k:v for k,v in r.items() if k!='scope'}];self.save()
        else:webbrowser.open(issue_link(self.owner.cfg.get('community_repo',REPOSITORY),{'action':'site_delete','id':r['id']}))
    def open(self):
        if self.selected():webbrowser.open(url(self.selected()['url']))
    def latest(self):
        r=self.selected()
        if r:self.info.setText('웹페이지에서 최신 링크를 확인 중…');self.task(lambda:latest_links(r.get('news_url') or r['url']),self.news_loaded)
    def news_loaded(self,ok,rows):
        if not ok:self.info.setText('최신 링크 조회 실패: '+str(rows));return
        self.news_rows=rows;self.news.setRowCount(len(rows))
        for n,r in enumerate(rows):
            self.news.setItem(n,0,QTableWidgetItem(r['title']));self.news.setItem(n,1,QTableWidgetItem(r['url']))
        self.info.setText(f'최신 링크 {len(rows)}개 · 더블클릭하면 원문을 엽니다.');self.news.resizeColumnsToContents()
    def open_news(self,row,col):
        if hasattr(self,'news_rows'):webbrowser.open(url(self.news_rows[row]['url']))
