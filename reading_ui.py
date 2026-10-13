from collections import OrderedDict
from pathlib import Path
from bisect import bisect_right
from math import sqrt
from PySide6.QtCore import Qt, QTimer, QSize, QRect, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QImageReader, QImage, QPainter, QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QComboBox,QScrollArea,QGridLayout,QStackedWidget,QSlider,QProgressBar,QDialog,QMessageBox,QFrame,QTabBar,QCheckBox)
from library_ui import LibraryTask
from library import size_text
from reading import shelf_index,chapter_images,prepare_opencomic,opencomic
from pagination import Pagination
from themes import colors

def btn(text,fn):
    b=QPushButton(text);b.clicked.connect(fn);return b

class DecodeSignals(QObject):
    ready=Signal(int,int,QImage,str)

class Decode(QRunnable):
    def __init__(self,gen,index,path,width):
        super().__init__();self.signals=DecodeSignals();self.args=(gen,index,path,width)
    def run(self):
        gen,index,path,width=self.args
        try:
            r=QImageReader(path);s=r.size()
            if not s.isValid():raise ValueError('이미지를 읽을 수 없습니다.')
            scale=min(1,width/s.width(),12000/s.height(),sqrt(8_000_000/(s.width()*s.height())));r.setScaledSize(QSize(max(1,int(s.width()*scale)),max(1,int(s.height()*scale))))
            r.setAutoTransform(True);im=r.read()
            if im.isNull():raise ValueError(r.errorString())
            self.signals.ready.emit(gen,index,im,'')
        except Exception as exc:self.signals.ready.emit(gen,index,QImage(),str(exc))

class ComicCanvas(QWidget):
    def __init__(self,scroll):
        super().__init__();self.scroll=scroll;self.items=[];self.offsets=[0];self.width_read=850
        self.cache=OrderedDict();self.pending={};self.errors={};self.generation=0;self.cache_bytes=0
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(2)
        self.setMinimumHeight(1)
    def configure(self,items,width):
        self.generation+=1;self.items=items;self.width_read=width;self.cache.clear();self.cache_bytes=0;self.errors={}
        self.offsets=[0]
        for item in items:self.offsets.append(self.offsets[-1]+max(1,round(width*item['height']/item['width'])))
        if self.offsets[-1]>16_000_000:
            self.items=[{'path':'','width':800,'height':160,'error':'한 회차 표시 길이가 너무 깁니다. 읽기 폭을 줄이거나 OpenComic으로 열어주세요.'}];self.offsets=[0,160]
        self.setMinimumHeight(self.offsets[-1] or 1);self.resize(max(width,self.scroll.viewport().width()),self.minimumHeight());self.update();self.ensure_visible()
    def ensure_visible(self):
        top=self.scroll.verticalScrollBar().value();bottom=top+self.scroll.viewport().height()+500
        start=max(0,bisect_right(self.offsets,max(0,top-500))-1);wanted=range(start,min(len(self.items),bisect_right(self.offsets,bottom)))
        for i in wanted:
            if len(self.pending)>=16:break
            key=(self.generation,i)
            if i in self.cache or key in self.pending or i in self.errors or self.items[i]['error']:continue
            job=Decode(self.generation,i,self.items[i]['path'],self.width_read);self.pending[key]=job
            job.signals.ready.connect(self.decoded);self.pool.start(job)
    def decoded(self,gen,index,image,error):
        self.pending.pop((gen,index),None)
        if gen!=self.generation:
            self.ensure_visible();return
        if error:self.errors[index]=error
        else:
            self.cache[index]=image;self.cache_bytes+=image.sizeInBytes()
            while self.cache_bytes>48*1024**2 and len(self.cache)>1:
                _,im=self.cache.popitem(last=False);self.cache_bytes-=im.sizeInBytes()
        self.update()
    def paintEvent(self,event):
        painter=QPainter(self);background=getattr(self,'background',None) or self.palette().window().color();painter.fillRect(event.rect(),background);painter.setRenderHint(QPainter.SmoothPixmapTransform)
        start=max(0,bisect_right(self.offsets,event.rect().top())-1)
        for i in range(start,len(self.items)):
            if self.offsets[i]>event.rect().bottom():break
            rect=QRect((self.width()-self.width_read)//2,self.offsets[i],self.width_read,self.offsets[i+1]-self.offsets[i])
            if i in self.cache:
                self.cache.move_to_end(i);painter.drawImage(rect,self.cache[i])
            else:
                painter.setPen(QColor('#202020') if background.lightness()>150 else QColor('#f4f4f4'));message=self.items[i]['error'] or self.errors.get(i) or f'이미지 {i+1} 불러오는 중…'
                painter.drawText(rect,Qt.AlignCenter,message)
        painter.end()

class OfflineLibrary(QWidget):
    def __init__(self,host):
        super().__init__();self.host=host;self.rows=[];self.task=None;self.work=None;self.chapter=0;self.page=0;self.images=[];self.mirrors=[];self.mirror_work=None;self.popup=None;self.closed=False
        lay=QVBoxLayout(self);self.main_layout=lay;lay.setContentsMargins(28,24,28,24)
        self.header=QWidget();header=QHBoxLayout(self.header);title=QLabel('내 작품 라이브러리');title.setStyleSheet('font-size:28px;font-weight:700');header.addWidget(title);header.addStretch()
        header.addWidget(btn('새로고침',self.refresh));header.addWidget(btn('뷰어 설정',host.reader_settings));header.addWidget(btn('다운로드 화면',host.show_catalog));lay.addWidget(self.header)
        self.status=QLabel('보관함을 불러오는 중…');lay.addWidget(self.status)
        self.loading=QProgressBar();self.loading.setRange(0,0);self.loading.setFixedHeight(8);lay.addWidget(self.loading)
        self.stack=QStackedWidget();lay.addWidget(self.stack,1)
        shelf=QWidget();sl=QVBoxLayout(shelf);tools=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('보유 작품 검색');self.search.textChanged.connect(self.filter)
        self.genre=QComboBox();self.genre.addItem('모든 장르');self.genre.currentTextChanged.connect(self.filter)
        self.sort=QComboBox();self.sort.addItems(['최근 다운로드순','작품 이름순','용량 큰 순']);self.sort.currentIndexChanged.connect(self.filter)
        tools.addWidget(self.search,1);tools.addWidget(self.genre);tools.addWidget(self.sort);sl.addLayout(tools)
        from notifications_ui import CollectionFilters
        self.collection_filters=CollectionFilters(self.filter);sl.addWidget(self.collection_filters)
        daytools=QHBoxLayout();self.today=QCheckBox('오늘 요일 자동 검색');self.today.toggled.connect(self.today_changed);daytools.addWidget(self.today);daytools.addWidget(btn('사이트 정보 검색·매칭',self.find_weekdays));daytools.addWidget(btn('검색 중단',self.cancel_lookup));daytools.addWidget(btn('스마트폰·패드 앱',self.mobile_app));daytools.addStretch();sl.addLayout(daytools)
        ordertools=QHBoxLayout();ordertools.addWidget(btn('폴더 이동용 순서 기록 저장',self.publish_orders));ordertools.addWidget(btn('사이트 읽는 순서 다시 맞추기',self.verify_orders));ordertools.addStretch();sl.addLayout(ordertools)
        self.scope_tabs=QTabBar();self.scope_tabs.setExpanding(False)
        for name in ['전체','내 웹툰 · 최근 회차','전회차 보관','일부 회차','다운로드 전']:self.scope_tabs.addTab(name)
        self.scope_tabs.currentChanged.connect(self.filter);sl.addWidget(self.scope_tabs)
        scope_hint=QLabel('전회차 보관은 마지막 회차 확인 기준입니다. 요일을 찾지 못한 작품은 미지정으로 표시됩니다.');scope_hint.setObjectName('muted');sl.addWidget(scope_hint)
        self.shelf_scroll=QScrollArea();self.shelf_scroll.setWidgetResizable(True);self.grid_widget=QWidget();self.grid=QGridLayout(self.grid_widget);self.grid.setAlignment(Qt.AlignTop);self.shelf_scroll.setWidget(self.grid_widget);sl.addWidget(self.shelf_scroll,1)
        self.pager=Pagination();self.pager.requested.connect(self.go_page);sl.addWidget(self.pager);self.stack.addWidget(shelf)
        reader=QWidget();rl=QVBoxLayout(reader);self.reader_layout=rl;self.reader_bar=QWidget();bar=QHBoxLayout(self.reader_bar);bar.addWidget(btn('‹ 라이브러리',self.back));self.prev=btn('이전 화',lambda:self.move(-1));bar.addWidget(self.prev)
        self.chapters=QComboBox();self.chapters.currentIndexChanged.connect(self.select_chapter);bar.addWidget(self.chapters,1)
        self.next=btn('다음 화',lambda:self.move(1));bar.addWidget(self.next);bar.addWidget(btn('슬림 보기',lambda:self.set_slim(True)));bar.addWidget(btn('OpenComic으로 열기',self.external));rl.addWidget(self.reader_bar)
        self.slim_bar=QWidget();self.slim_bar.setObjectName('readerSlim');self.slim_bar.setFixedHeight(32);slim=QHBoxLayout(self.slim_bar);slim.setContentsMargins(4,0,4,0);slim.setSpacing(3)
        self.slim_bar.setStyleSheet('#readerSlim QPushButton {border:0;padding:1px 6px;min-height:22px;max-height:24px;} #readerSlim QComboBox {padding:0px 20px 0px 5px;min-height:24px;max-height:24px;}')
        slim.addWidget(btn('목록',self.back));self.slim_title=QLabel();self.slim_title.setMaximumWidth(240);slim.addWidget(self.slim_title)
        self.slim_prev=btn('이전',lambda:self.move(-1));slim.addWidget(self.slim_prev);self.slim_chapters=QComboBox();self.slim_chapters.setMaximumWidth(190);self.slim_chapters.currentIndexChanged.connect(self.chapters.setCurrentIndex);self.chapters.currentIndexChanged.connect(self.slim_chapters.setCurrentIndex);slim.addWidget(self.slim_chapters);self.slim_next=btn('다음',lambda:self.move(1));slim.addWidget(self.slim_next);slim.addStretch()
        self.slim_position=QLabel('0%');slim.addWidget(self.slim_position);slim.addWidget(btn('설정',host.reader_settings));slim.addWidget(btn('기본 보기',self.show_tools));slim.addWidget(btn('전체 화면',self.toggle_fullscreen));rl.addWidget(self.slim_bar)
        self.reader_footer=QWidget();widthbar=QHBoxLayout(self.reader_footer);widthbar.addWidget(QLabel('읽기 폭'));self.width_slider=QSlider(Qt.Horizontal);self.width_slider.setRange(400,1600);self.width_slider.setValue(host.cfg.get('reader_width',850));widthbar.addWidget(self.width_slider);self.width_slider.valueChanged.connect(self.resize_reading)
        self.position=QLabel();widthbar.addWidget(self.position)
        self.read_scroll=QScrollArea();self.read_scroll.setWidgetResizable(True);self.canvas=ComicCanvas(self.read_scroll);self.read_scroll.setWidget(self.canvas);rl.addWidget(self.read_scroll,1);rl.addWidget(self.reader_footer);self.stack.addWidget(reader)
        self.quick=QWidget(self.read_scroll.viewport());quick=QHBoxLayout(self.quick);quick.setContentsMargins(4,4,4,4)
        quick.addWidget(btn('‹ 목록',self.back));quick.addWidget(btn('도구 표시',self.show_tools));quick.addWidget(btn('⚙',host.settings));self.quick.adjustSize();self.quick.hide()
        self.read_scroll.verticalScrollBar().valueChanged.connect(self.scrolled)
        self.read_scroll.verticalScrollBar().rangeChanged.connect(self.restore_scroll)
        self.restore_fraction=None
        self.resize_timer=QTimer(self);self.resize_timer.setSingleShot(True);self.resize_timer.timeout.connect(self.apply_width)
        self.progress_timer=QTimer(self);self.progress_timer.setSingleShot(True);self.progress_timer.timeout.connect(self.save_position)
        for key,fn in [('Alt+Left',lambda:self.move(-1)),('Alt+Right',lambda:self.move(1)),('Escape',self.escape),('F9',self.toggle_focus),('F11',self.toggle_fullscreen)]:
            shortcut=QShortcut(QKeySequence(key),self);shortcut.activated.connect(fn)
        self.apply_preferences(False)
        self.today_timer=QTimer(self);self.today_timer.timeout.connect(self.refresh_today);self.today_timer.start(60000)
        saved=self.host.cfg.get('library_filters',{});self.restoring_filters=True
        self.scope_tabs.setCurrentIndex(min(4,max(0,int(saved.get('scope',0)))));self.collection_filters.day.set_days(saved.get('days',saved.get('day')));self.today.setChecked(bool(saved.get('today',False)));self.restoring_filters=False

    def toggle_focus(self):self.host.set_view_preference('reader_focus',not self.host.cfg.get('reader_focus',False))
    def show_tools(self):
        self.host.cfg.update(reader_focus=False,reader_slim=False,reader_hide_top=False,reader_hide_bottom=False);self.host.persist_settings();self.host.apply_view_preferences()
    def set_slim(self,value):
        if value:self.host.cfg['reader_focus']=False
        self.host.set_view_preference('reader_slim',bool(value))
    def toggle_fullscreen(self):
        if self.stack.currentIndex()!=1:return
        if self.host.isFullScreen():self.host.showNormal();self.reader_fullscreen=False
        else:self.host.showFullScreen();self.reader_fullscreen=True;self.set_slim(True)
    def escape(self):
        if self.host.isFullScreen() and getattr(self,'reader_fullscreen',False):self.host.showNormal();self.reader_fullscreen=False
        elif self.stack.currentIndex()==1 and any(self.host.cfg.get(k) for k in ('reader_focus','reader_slim','reader_hide_top','reader_hide_bottom')):self.show_tools()
        else:self.back()
    def apply_preferences(self,reading):
        if self.closed:return
        focus=reading and self.host.cfg.get('reader_focus',False)
        slim=reading and self.host.cfg.get('reader_slim',False) and not focus
        compact=focus or slim
        top=reading and (compact or self.host.cfg.get('reader_hide_top',False));bottom=reading and (compact or self.host.cfg.get('reader_hide_bottom',False))
        layout_state=(focus,slim,top,bottom)
        if self.images and getattr(self,'layout_state',None)!=layout_state:
            bar=self.read_scroll.verticalScrollBar();self.resize_fraction=bar.value()/max(1,bar.maximum());self.resize_timer.start(180)
        self.layout_state=layout_state
        self.header.setVisible(not top);self.status.setVisible(not top);self.reader_bar.setVisible(not top);self.reader_footer.setVisible(not bottom)
        self.slim_bar.setVisible(bool(slim));self.read_scroll.setFrameShape(QFrame.NoFrame if compact else QFrame.StyledPanel)
        self.main_layout.setContentsMargins(*( (0,0,0,0) if compact else (28,24,28,24)))
        self.reader_layout.setContentsMargins(*( (0,0,0,0) if compact else (9,9,9,9)))
        self.main_layout.setSpacing(0 if compact else 6);self.reader_layout.setSpacing(0 if compact else 6)
        value=self.host.cfg.get('reader_background','');color=QColor(value) if value else None
        self.canvas.background=color if color and color.isValid() else None
        self.canvas.update();self.quick.setVisible(bool(reading and (top or bottom) and not slim));self.quick.raise_();self.position_quick()
    def position_quick(self):
        self.quick.adjustSize();self.quick.move(max(0,self.read_scroll.viewport().width()-self.quick.width()-14),8)
    def run(self,operation,done):
        if self.task and self.task.isRunning():return False
        self.loading.show();self.status.setText('불러오는 중…');self.prev.setEnabled(False);self.next.setEnabled(False);self.chapters.setEnabled(False)
        self.slim_prev.setEnabled(False);self.slim_next.setEnabled(False);self.slim_chapters.setEnabled(False)
        self.task=LibraryTask(operation);self.task.event.connect(lambda k,v:self.status.setText(str(v)) if k=='log' else None)
        def result(state,value):
            if self.closed:return
            if state=='success':done(value)
            elif state=='error':
                self.status.setText('확인 필요 · '+str(value));self.slim_title.setText('확인 필요 · '+str(value));self.slim_title.setToolTip(str(value))
        self.task.done.connect(result);self.task.finished.connect(self.ready);self.task.start();return True
    def ready(self):
        if self.closed:return
        self.loading.hide();self.chapters.setEnabled(True);self.prev.setEnabled(bool(self.work) and self.chapter>0);self.next.setEnabled(bool(self.work) and self.chapter<len(self.work['chapters'])-1)
        self.slim_chapters.setEnabled(True);self.slim_prev.setEnabled(self.prev.isEnabled());self.slim_next.setEnabled(self.next.isEnabled())
        if getattr(self,'pending_catalog_refresh',False):self.pending_catalog_refresh=False;self.refresh()
    def refresh(self):
        if self.task and self.task.isRunning():return
        self.mirrors=[];self.mirror_work=None
        self.root=Path(self.host.path.text()).expanduser().resolve();catalog=list(self.host.works)
        self.run(lambda c,e:shelf_index(self.root,catalog,c,e),self.loaded)
    def loaded(self,rows):
        from shelf_collections import enrich_shelf
        self.rows=rows;source=enrich_shelf(rows,self.host.collection_store.entries(),self.host.auto_store.entries(),self.host.works);self.genre.blockSignals(True);self.genre.clear();self.genre.addItems(['모든 장르']+sorted({g for w in source for g in w['genre'].replace(',',' ').split()}));self.genre.blockSignals(False)
        self.status.setText(f"{len(source)}개 작품 · {sum(w['episodes'] for w in rows)}회차 · {size_text(sum(w['size'] for w in rows))}"+(' · '+self.match_report if getattr(self,'match_report','') else ''));self.filter()
    def today_changed(self,value):
        self.collection_filters.day.setEnabled(not value);self.refresh_today();self.filter()
    def refresh_today(self):
        if self.today.isChecked():
            from automation_store import local_now
            self.collection_filters.day.setCurrentIndex(self.collection_filters.day.findData(local_now().weekday()))
    def find_weekdays(self):
        from work_metadata import lookup_metadata
        from collections_store import work_key,as_work
        cfg=dict(self.host.read_cfg(),_download_job=False)
        tracked={work_key(w):w for w in self.rows};tracked.update({e['key']:e['work'] for e in self.host.auto_store.entries()})
        def operation(control,emit):
            value=lookup_metadata(cfg,list(tracked.values()),control,emit)
            if (self.root/'.toonshelf.sqlite3').is_file():
                from library import LibraryArchive
                archive=LibraryArchive(self.root)
                try:archive.seed_catalog([as_work(w) for w in value['updates']])
                finally:archive.close()
            return value
        def found(value):
            self.host.set_catalog(value['catalog']);self.host.auto_store.apply_metadata(value['updates']);self.host.collection_store.apply_metadata(value['updates']);self.pending_catalog_refresh=True
            self.match_report=f"정보 매칭 {len(value['updates'])}개 · 미매칭 {len(value['unmatched'])}개 · 날짜 조회 오류 {len(value['errors'])}개"
        self.run(operation,found)
    def cancel_lookup(self):
        if self.task and self.task.isRunning():self.task.control.stopped.set();self.status.setText('검색을 중단하는 중…')
    def mobile_app(self):
        from mobile_ui import MobileDialog
        MobileDialog(self.host).exec()
    def publish_orders(self):
        from library import publish_recorded_orders
        def done(value):
            self.status.setText(f"순서 기록 저장 {value['written']}회차 · 사이트 재확인 필요 {len(value['ambiguous'])}회차")
            QMessageBox.information(self,'폴더 이동 준비',self.status.text()+'\n작품 폴더를 옮길 때 _reading_order.json도 함께 복사하세요. 원본 파일명과 이미지는 유지됩니다.')
        self.run(lambda c,e:publish_recorded_orders(self.root,c,e),done)
    def verify_orders(self):
        from library_ui import LibraryDialog
        LibraryDialog(self.host).exec()
    def filter(self):
        if getattr(self,'restoring_filters',False):return
        self.page=0;self.render()
        value=dict(scope=self.scope_tabs.currentIndex(),days=self.collection_filters.day.currentData(),today=self.today.isChecked())
        if self.host.cfg.get('library_filters')!=value:self.host.cfg['library_filters']=value;self.host.persist_settings()
    def turn_page(self,step):
        self.go_page(self.page+step)
    def go_page(self,index):
        count=max(1,(len(self.filtered())+11)//12);self.page=max(0,min(count-1,index));self.render();self.shelf_scroll.verticalScrollBar().setValue(0)
    def filtered(self):
        from shelf_collections import enrich_shelf
        from work_metadata import CatalogIndex
        if getattr(self,'catalog_source',None) is not self.host.works:self.catalog_source=self.host.works;self.catalog_index=CatalogIndex(self.host.works)
        source=enrich_shelf(self.rows,self.host.collection_store.entries(),self.host.auto_store.entries(),self.catalog_index)
        scope=['','recent','full','partial','pending'][self.scope_tabs.currentIndex()]
        rows=[w for w in source if (not scope or w['storage_scope']==scope or scope=='pending' and not w['has_download']) and self.search.text().casefold() in w['title'].casefold() and (self.genre.currentIndex()==0 or self.genre.currentText() in w['genre'].replace(',',' ').split())]
        i=self.sort.currentIndex();rows.sort(key=lambda w:w['title'] if i==1 else w['size'] if i==2 else w['last_downloaded'] or '',reverse=i!=1)
        return self.collection_filters.apply(rows,self.host.collection_store) if hasattr(self.host,'collection_store') else rows
    def render(self):
        while self.grid.count():
            item=self.grid.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        rows=self.filtered();self.page=min(self.page,max(0,(len(rows)-1)//12));self.pager.update_pages(self.page,max(1,(len(rows)+11)//12))
        for n,w in enumerate(rows[self.page*12:self.page*12+12]):
            card=QFrame();card.setObjectName('libraryCard');cl=QVBoxLayout(card);cl.setContentsMargins(18,18,18,18)
            art=QLabel();art.setAlignment(Qt.AlignCenter);art.setFixedHeight(150)
            if w.get('thumbnail_image') is not None:
                from PySide6.QtGui import QPixmap
                art.setPixmap(QPixmap.fromImage(w['thumbnail_image']).scaled(300,150,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            else:art.setText('표지 없음')
            cl.addWidget(art);title=QLabel(w['title']);title.setWordWrap(True);title.setStyleSheet('font-size:16px;font-weight:700');cl.addWidget(title)
            meta=QLabel((w['genre'] or '미분류')+' · '+(w['publisher'] or '미분류'));meta.setObjectName('muted');cl.addWidget(meta)
            from collections_store import DAYS
            day=' · '.join(DAYS[d] for d in w['weekdays']) or '요일 미지정'
            cl.addWidget(QLabel(w['storage_label']+' · '+day));cl.addWidget(QLabel('최근 업로드 '+(w.get('updated_date') or '미확인')));cl.addWidget(QLabel(f"{w['episodes']}회차 · 기록 용량 {size_text(w['size'])}"));cl.addWidget(btn('계속 읽기  →' if w['has_download'] else '최신 회차 받기',lambda checked=False,w=w:self.open_work(w) if w['has_download'] else self.download_work(w)))
            if hasattr(self.host,'collection_store'):
                row=QHBoxLayout();row.addWidget(btn('★ 즐겨찾기' if (self.host.collection_store.get(w) or {}).get('favorite') else '☆ 즐겨찾기',lambda checked=False,w=w:self.host.toggle_favorite(w)));row.addWidget(btn('요일 · 분류',lambda checked=False,w=w:self.host.work_settings(w)));cl.addLayout(row)
            card.setMinimumWidth(180)
            self.grid.addWidget(card,n//3,n%3)
        if not rows:self.grid.addWidget(QLabel('조건에 맞는 작품이 없습니다. 내 웹툰 목록에 작품을 추가하거나 검색 조건을 변경하세요.'),0,0)
    def download_work(self,work):
        from collections_store import as_work,work_key
        from urllib.parse import urlsplit,urlunsplit
        automatic=next((e for e in self.host.auto_store.entries() if e['key']==work_key(work)),{})
        cfg=dict(self.host.read_cfg(),latest_count=automatic.get('tail',10),start_episode=1,end_episode=0)
        value=dict(work);base=urlsplit(cfg['site_url']);old=urlsplit(value.get('metadata_url') or value['url']);value['url']=urlunsplit((base.scheme,base.netloc,old.path,old.query,''))
        self.host.enqueue_works([as_work(value)],cfg);self.status.setText('다운로드 대기열에 추가했습니다.')
    def open_work(self,work):
        if self.task and self.task.isRunning():return
        if not work.get('chapters'):self.status.setText('다운로드된 회차가 없습니다. 최신 회차 받기를 사용하세요.');return
        self.save_position();self.images=[];self.work=work;self.chapters.blockSignals(True);self.chapters.clear();self.chapters.addItems([e['folder'] for e in work['chapters']]);self.chapters.blockSignals(False)
        self.slim_title.setText(self.slim_title.fontMetrics().elidedText(work['title'],Qt.ElideRight,230));self.slim_title.setToolTip(work['title']);self.slim_chapters.blockSignals(True);self.slim_chapters.clear();self.slim_chapters.addItems([e['folder'] for e in work['chapters']]);self.slim_chapters.blockSignals(False)
        saved=self.host.cfg.get('reading_positions',{}).get(work['key'],{});self.chapter=next((i for i,e in enumerate(work['chapters']) if e['key']==saved.get('chapter')),0)
        self.chapters.blockSignals(True);self.chapters.setCurrentIndex(self.chapter);self.chapters.blockSignals(False);self.stack.setCurrentIndex(1)
        self.slim_chapters.setCurrentIndex(self.chapter)
        if self.host.cfg.get('reader_mode','embedded')=='opencomic':self.external()
        else:self.load_chapter()
        if hasattr(self.host,'apply_view_preferences'):self.host.apply_view_preferences()
    def select_chapter(self,index):
        if index<0 or not self.work or (self.task and self.task.isRunning()):return
        self.save_position();self.chapter=index
        if self.host.cfg.get('reader_mode','embedded')=='opencomic':self.external()
        else:self.load_chapter()
    def move(self,step):
        if self.task and self.task.isRunning():return
        if self.work and 0<=self.chapter+step<len(self.work['chapters']):self.chapters.setCurrentIndex(self.chapter+step)
    def load_chapter(self):
        chapter=self.work['chapters'][self.chapter]
        pos=self.host.cfg.get('reading_positions',{}).get(self.work['key'],{});fraction=pos.get('offsets',{}).get(chapter['key'],pos.get('fraction',0) if pos.get('chapter')==chapter['key'] else 0)
        self.images=[];self.restore_fraction=fraction;self.canvas.configure([],850)
        def loaded(images):
            self.images=images;self.apply_width();self.status.setText(self.work['title']+' · '+chapter['folder']+f' · {len(images)}장'+(' · 다운로드 기록 순서 · 사이트 미확인' if not chapter.get('order_verified') else ' · 사이트 순서'))
            QTimer.singleShot(0,self.restore_scroll)
        self.run(lambda c,e:chapter_images(self.root,chapter,c),loaded)
    def resize_reading(self):self.resize_timer.start(180)
    def apply_width(self):
        if self.closed:return
        bar=self.read_scroll.verticalScrollBar();fraction=getattr(self,'resize_fraction',None)
        if fraction is None:fraction=self.restore_fraction if self.restore_fraction is not None else bar.value()/max(1,bar.maximum())
        self.resize_fraction=None;self.restore_fraction=fraction; width=min(self.width_slider.value(),max(320,self.read_scroll.viewport().width()-20))
        self.canvas.configure(self.images,width);bar.setValue(int(fraction*bar.maximum()));self.host.cfg['reader_width']=self.width_slider.value()
        QTimer.singleShot(0,self.restore_scroll)
    def restore_scroll(self,*args):
        bar=self.read_scroll.verticalScrollBar()
        if self.restore_fraction is not None and self.images and bar.maximum()>0:
            fraction=self.restore_fraction;self.restore_fraction=None;bar.setValue(int(fraction*bar.maximum()))
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'resize_timer') and not self.closed:self.resize_timer.start(180)
        if hasattr(self,'quick'):QTimer.singleShot(0,self.position_quick)
    def scrolled(self):
        if self.closed:return
        self.canvas.ensure_visible();bar=self.read_scroll.verticalScrollBar();self.position.setText(f'{round(bar.value()/max(1,bar.maximum())*100)}%');self.slim_position.setText(self.position.text());self.progress_timer.start(500)
    def save_position(self):
        if self.closed or not self.work or not self.images or self.restore_fraction is not None:return
        bar=self.read_scroll.verticalScrollBar();key=self.work['chapters'][self.chapter]['key'];fraction=bar.value()/max(1,bar.maximum())
        positions=self.host.cfg.setdefault('reading_positions',{});pos=positions.setdefault(self.work['key'],{});pos.setdefault('offsets',{})[key]=fraction;pos.update(chapter=key,fraction=fraction);self.host.persist_settings()
    def back(self):
        self.save_position();self.stack.setCurrentIndex(0)
        if getattr(self,'reader_fullscreen',False):self.host.showNormal();self.reader_fullscreen=False
        if hasattr(self.host,'apply_view_preferences'):self.host.apply_view_preferences()
    def external(self):
        if not self.work:return
        exe=self.host.opencomic_path()
        if not exe:
            self.status.setText('뷰어 설정에서 OpenComic 실행 파일을 선택하세요.');self.host.reader_settings();return
        work=self.work;chapter=self.chapter
        def prepared(paths):
            self.mirrors=paths;self.mirror_work=(str(self.root),work['key'])
            try:opencomic(exe,paths[chapter]);self.status.setText(work['title']+' · OpenComic에서 읽는 중');self.external_controls()
            except Exception as exc:QMessageBox.warning(self,'뷰어 확인',str(exc))
        if self.mirror_work==(str(self.root),work['key']) and chapter<len(self.mirrors) and Path(self.mirrors[chapter]).is_dir():prepared(self.mirrors)
        else:self.run(lambda c,e:prepare_opencomic(self.root,work,c,e),prepared)
    def external_controls(self):
        if self.popup is None:
            self.popup=QDialog(self);self.popup.setWindowTitle('OpenComic · 회차 이동');p=QHBoxLayout(self.popup)
            p.addWidget(btn('이전 화',lambda:self.external_move(-1)));p.addWidget(btn('현재 화 다시 열기',self.external));p.addWidget(btn('다음 화',lambda:self.external_move(1)))
        self.popup.show()
    def external_move(self,step):
        if self.task and self.task.isRunning():return
        if not self.work or not 0<=self.chapter+step<len(self.work['chapters']):return
        self.save_position();self.images=[];self.chapter+=step
        self.chapters.blockSignals(True);self.chapters.setCurrentIndex(self.chapter);self.chapters.blockSignals(False)
        self.external()
    def shutdown(self):
        self.save_position();self.closed=True;self.progress_timer.stop();self.resize_timer.stop();self.today_timer.stop()
        if self.task and self.task.isRunning():self.task.control.stopped.set();return False
        self.canvas.generation+=1;self.canvas.items=[];self.canvas.pool.clear();self.canvas.pool.waitForDone(1000)
        complete=self.canvas.pool.activeThreadCount()==0
        if complete:self.canvas.cache.clear();self.canvas.cache_bytes=0;self.canvas.pending.clear()
        return complete
