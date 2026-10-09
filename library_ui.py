from pathlib import Path
import json
import shutil

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,
    QFileDialog,QMessageBox,QSplitter,QFormLayout,QSpinBox,QProgressBar)

from core import Control, Cancelled, Work
from library import LibraryArchive, export_mobile, refresh_metadata, size_text, format_time, genres


def combo(items):
    c=QComboBox()
    c.addItems(items)
    return c


def table(headers):
    t=QTableWidget(0,len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.ExtendedSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().hide()
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    return t


class LibraryTask(QThread):
    event=Signal(str,object)
    done=Signal(str,object)

    def __init__(self, operation):
        super().__init__()
        self.operation=operation
        self.control=Control()

    def run(self):
        try:
            result=self.operation(self.control,self.event.emit)
            self.done.emit('success',result)
        except Cancelled:
            self.done.emit('cancelled',None)
        except Exception as exc:
            import traceback,logging
            logging.error(traceback.format_exc())
            self.done.emit('error',str(exc))


class LibraryDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent)
        self.host=parent
        self.root=Path(parent.path.text()).expanduser().resolve()
        self.rows=[]
        self.current_key=''
        self.task=None
        self.cfg=parent.cfg
        self.prefs=self.cfg.setdefault('library_view',{'upload':True,'download':True,'size':True,'timezone':'seoul'})
        self.setWindowTitle('ToonShelf 2.0 · 내 보관함 / 기기용 내보내기')
        self.resize(1320,870)
        self.build()
        self.refresh()

    def build(self):
        layout=QVBoxLayout(self)
        layout.setContentsMargins(24,22,24,20)
        title=QLabel('내 보관함  /  기기로 가져갈 준비')
        title.setObjectName('title')
        layout.addWidget(title)
        subtitle=QLabel('작품별 분류, 회차별 날짜와 용량을 확인하고 읽는 순서대로 내보내세요.')
        subtitle.setObjectName('muted')
        layout.addWidget(subtitle)
        top=QHBoxLayout()
        self.root_combo=QComboBox()
        known=list(dict.fromkeys([str(self.root)]+self.cfg.get('library_roots',[])))
        self.root_combo.addItems(known)
        self.root_combo.currentTextChanged.connect(self.change_root)
        top.addWidget(self.root_combo,1)
        for text,action in [('다른 보관함 등록',self.choose_root),('새로고침',self.refresh),('저장 폴더 열기',self.open_root)]:
            b=QPushButton(text);b.clicked.connect(action);top.addWidget(b)
        layout.addLayout(top)
        self.summary=QLabel()
        self.summary.setObjectName('accent')
        self.summary.setStyleSheet('font-size:16px; padding:12px; background:#1a2928; border-radius:9px;')
        layout.addWidget(self.summary)
        filters=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('다운로드한 작품 검색')
        self.genre=combo(['모든 장르']);self.publisher=combo(['모든 제공처'])
        for widget in [self.search,self.genre,self.publisher]:filters.addWidget(widget)
        self.search.textChanged.connect(self.render_works)
        self.genre.currentTextChanged.connect(self.render_works)
        self.publisher.currentTextChanged.connect(self.render_works)
        self.sort=combo(['작품 이름순','최근 다운로드순','용량 큰 순','용량 작은 순'])
        self.sort.currentIndexChanged.connect(self.render_works)
        filters.addWidget(self.sort)
        layout.addLayout(filters)
        view=QHBoxLayout()
        view.addWidget(QLabel('표시 옵션'))
        self.columns={}
        for key,text in [('upload','업로드일'),('download','다운로드일'),('size','용량')]:
            box=QCheckBox(text);box.setChecked(self.prefs.get(key,True))
            box.toggled.connect(lambda checked,k=key:self.set_column(k,checked))
            self.columns[key]=box;view.addWidget(box)
        self.zone=combo(['한국 시간 (UTC+9)','UTC'])
        self.zone.setCurrentIndex(1 if self.prefs.get('timezone')=='utc' else 0)
        self.zone.currentIndexChanged.connect(self.zone_changed)
        view.addWidget(self.zone);view.addStretch()
        layout.addLayout(view)
        split=QSplitter(Qt.Vertical)
        self.work_table=table(['작품','장르','제공처','회차','이미지','이미지 용량','최근 다운로드','읽는 순서'])
        self.work_table.itemSelectionChanged.connect(self.show_episodes)
        self.work_table.itemDoubleClicked.connect(lambda _:self.edit_properties())
        self.episode_table=table(['순서','회차','업로드일','첫 다운로드','최근 다운로드','이미지','이미지 용량','상태','읽는 순서'])
        split.addWidget(self.work_table);split.addWidget(self.episode_table)
        split.setSizes([300,260])
        layout.addWidget(split,1)
        self.detail=QLabel('작품을 선택하면 내려받은 회차가 표시됩니다.')
        self.detail.setObjectName('muted')
        layout.addWidget(self.detail)
        actions=QHBoxLayout()
        self.property_button=QPushButton('장르·제공처 수정');self.property_button.clicked.connect(self.edit_properties)
        self.verify_button=QPushButton('날짜·읽는 순서 확인');self.verify_button.clicked.connect(self.verify)
        self.export_button=QPushButton('기기용 내보내기  →');self.export_button.setObjectName('primary');self.export_button.clicked.connect(self.export)
        self.stop_button=QPushButton('작업 중단');self.stop_button.clicked.connect(self.stop);self.stop_button.setEnabled(False)
        for b in [self.property_button,self.verify_button,self.export_button,self.stop_button]:actions.addWidget(b)
        layout.addLayout(actions)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.activity=QLabel('준비됨 · 기존 자료는 날짜·읽는 순서를 확인한 뒤 내보내세요.')
        self.activity.setWordWrap(True);self.activity.setObjectName('accent')
        layout.addWidget(self.activity)

    def persist(self):
        self.cfg['library_view']=self.prefs
        self.cfg['library_roots']=list(dict.fromkeys([str(self.root)]+self.cfg.get('library_roots',[])))
        self.host.persist_settings()

    def set_column(self,key,checked):
        self.prefs[key]=checked
        self.apply_columns()
        self.persist()

    def apply_columns(self):
        if not hasattr(self,'episode_table'):return
        for col in [2]:self.episode_table.setColumnHidden(col,not self.prefs.get('upload',True))
        for col in [3,4]:self.episode_table.setColumnHidden(col,not self.prefs.get('download',True))
        self.work_table.setColumnHidden(6,not self.prefs.get('download',True))
        self.work_table.setColumnHidden(5,not self.prefs.get('size',True))
        self.episode_table.setColumnHidden(6,not self.prefs.get('size',True))

    def zone_changed(self,index):
        self.prefs['timezone']='utc' if index else 'seoul'
        self.render_works();self.persist()

    def change_root(self,path):
        if self.task and self.task.isRunning():return
        self.root=Path(path).expanduser().resolve()
        self.refresh();self.persist()

    def choose_root(self):
        if self.task and self.task.isRunning():return
        path=QFileDialog.getExistingDirectory(self,'기존 다운로드 자료가 있는 저장 폴더 선택',str(self.root))
        if path:
            if self.root_combo.findText(path)<0:self.root_combo.addItem(path)
            self.root_combo.setCurrentText(path)

    def open_root(self):
        import os
        if self.root.is_dir():os.startfile(str(self.root))

    def refresh(self):
        if self.task and self.task.isRunning():return
        self.rows=[]
        if (self.root/'.toonshelf.sqlite3').is_file():
            archive=LibraryArchive(self.root)
            try:
                archive.seed_catalog(self.host.works)
                self.rows=archive.works()
            finally:archive.close()
        self.genre.blockSignals(True);self.publisher.blockSignals(True)
        g,p=self.genre.currentText(),self.publisher.currentText()
        self.genre.clear();self.genre.addItems(['모든 장르']+sorted({i for w in self.rows for i in genres(w['genre'])}))
        self.publisher.clear();self.publisher.addItems(['모든 제공처']+sorted({w['publisher'] or '미분류' for w in self.rows}))
        if self.genre.findText(g)>=0:self.genre.setCurrentText(g)
        if self.publisher.findText(p)>=0:self.publisher.setCurrentText(p)
        self.genre.blockSignals(False);self.publisher.blockSignals(False)
        size=sum(w['size'] for w in self.rows)
        probe=self.root
        while not probe.exists() and probe!=probe.parent:probe=probe.parent
        free=shutil.disk_usage(probe).free
        self.summary.setText(f"작품 {len(self.rows):,}개  ·  회차 {sum(w['episodes'] for w in self.rows):,}개  ·  이미지 {sum(w['images'] for w in self.rows):,}장  ·  이미지 용량 {size_text(size)}  ·  여유 {size_text(free)}")
        self.render_works();self.apply_columns()

    def render_works(self):
        if not hasattr(self,'work_table'):return
        query=self.search.text().strip().casefold()
        rows=[w for w in self.rows if query in w['title'].casefold() and
              (self.genre.currentText()=='모든 장르' or self.genre.currentText() in genres(w['genre'])) and
              (self.publisher.currentText()=='모든 제공처' or self.publisher.currentText()==(w['publisher'] or '미분류'))]
        index=self.sort.currentIndex()
        rows.sort(key=(lambda w:w['title']) if index==0 else (lambda w:w['last_downloaded'] or '') if index==1 else (lambda w:w['size']),reverse=index in (1,2))
        self.work_table.blockSignals(True);self.work_table.setRowCount(len(rows))
        for r,w in enumerate(rows):
            values=[w['title'],w['genre'] or '미분류',w['publisher'] or '미분류',w['episodes'],w['images'],size_text(w['size']),
                    format_time(w['last_downloaded'],self.prefs.get('timezone','seoul')),f"누락 {w['missing']}장" if w['missing'] else '확인됨' if w['order_verified'] else '확인 필요']
            for c,v in enumerate(values):
                item=QTableWidgetItem(str(v));item.setData(Qt.UserRole,w['key']);self.work_table.setItem(r,c,item)
        self.work_table.blockSignals(False)
        if rows:self.work_table.selectRow(0)
        else:self.episode_table.setRowCount(0)

    def selected_keys(self):
        return list(dict.fromkeys(self.work_table.item(i.row(),0).data(Qt.UserRole) for i in self.work_table.selectionModel().selectedRows()))

    def show_episodes(self):
        selected=self.selected_keys()
        if not selected:return
        self.current_key=selected[0]
        archive=LibraryArchive(self.root)
        try:episodes=archive.episodes(self.current_key)
        finally:archive.close()
        self.episode_table.setRowCount(len(episodes))
        status={'complete':'완료','partial':'일부 실패','pending':'대기','failed':'실패','interrupted':'중단'}
        for r,e in enumerate(episodes):
            values=[e['sequence'] or '미확인',e['folder'],e['upload_date'] or '미확인',
                    format_time(e['first_downloaded'],self.prefs.get('timezone','seoul')),
                    format_time(e['last_downloaded'],self.prefs.get('timezone','seoul')),e['images'],size_text(e['size']),
                    f"누락 {e['missing']}장" if e['missing'] else status.get(e['status'],e['status']),'확인됨' if e['order_verified'] else '확인 필요']
            for c,v in enumerate(values):
                item=QTableWidgetItem(str(v));item.setData(Qt.UserRole,e['key']);self.episode_table.setItem(r,c,item)
        self.detail.setText(f'선택 작품 {len(selected)}개 · 현재 표시 작품 회차 {len(episodes)}개 · 첫 다운로드일과 최근 실제 저장일을 구분합니다.')

    def edit_properties(self):
        keys=self.selected_keys()
        if len(keys)!=1:
            QMessageBox.information(self,'작품 선택','속성을 바꿀 작품 한 개를 선택하세요.');return
        row=next(w for w in self.rows if w['key']==keys[0])
        d=QDialog(self);d.setWindowTitle('작품 분류 설정');d.resize(460,260)
        form=QFormLayout(d)
        title=QLabel(row['title']);title.setWordWrap(True);form.addRow(title)
        g=QLineEdit(row['genre']);g.setPlaceholderText('판타지, 액션, 무협 · 여러 장르는 쉼표로 구분')
        p=combo(['미분류','네이버','카카오','다음','레진','탑툰','투믹스','코미코','기타']);p.setEditable(True);p.setCurrentText(row['publisher'] or '미분류')
        form.addRow('장르',g);form.addRow('제공처',p)
        form.addRow(QLabel('사용자 분류는 사이트 목록을 다시 읽어도 유지됩니다.'))
        def save():
            genre=', '.join(genres(g.text()))
            publisher='' if p.currentText()=='미분류' else p.currentText().strip()
            archive=LibraryArchive(self.root)
            try:archive.properties(keys[0],genre,publisher);archive.manifest(keys[0])
            finally:archive.close()
            self.host.set_properties(keys[0],genre,publisher)
            self.refresh();d.accept()
        b=QPushButton('분류 저장');b.setObjectName('primary');b.clicked.connect(save);form.addRow(b)
        d.exec()

    def run_task(self,operation,kind):
        if self.task and self.task.isRunning():return
        self.task=LibraryTask(operation)
        self.task.event.connect(self.on_event)
        self.task.done.connect(lambda state,result:self.finished_task(kind,state,result))
        self.task.finished.connect(lambda:(self.set_busy(False),self.refresh()))
        self.set_busy(True);self.task.start()

    def set_busy(self,busy):
        for w in [self.property_button,self.verify_button,self.export_button,self.root_combo]:w.setEnabled(not busy)
        self.stop_button.setEnabled(busy)

    def verify(self):
        keys=self.selected_keys()
        if not keys:
            QMessageBox.information(self,'작품 선택','날짜와 순서를 확인할 작품을 선택하세요.');return
        cfg=self.host.read_cfg()
        self.activity.setText('사이트에서 업로드일과 원본 이미지 순서를 확인하고 있습니다…')
        self.run_task(lambda c,e:refresh_metadata(cfg,self.root,keys,self.host.works,c,e),'verify')

    def export(self):
        keys=self.selected_keys()
        if not keys:
            QMessageBox.information(self,'작품 선택','내보낼 작품을 선택하세요.');return
        d=QDialog(self);d.setWindowTitle('패드·스마트폰용 내보내기');d.resize(620,460)
        form=QFormLayout(d)
        form.addRow(QLabel(f'작품 {len(keys)}개 · 원본은 유지하고 별도 사본을 만듭니다.'))
        episode_keys=list(dict.fromkeys(self.episode_table.item(i.row(),0).data(Qt.UserRole) for i in self.episode_table.selectionModel().selectedRows()))
        only_selected=QCheckBox(f'선택한 회차 {len(episode_keys)}개만 내보내기')
        only_selected.setEnabled(len(keys)==1 and bool(episode_keys))
        form.addRow(only_selected)
        destination=QLineEdit(self.cfg.get('export_dir',''))
        row=QHBoxLayout();row.addWidget(destination)
        pick=QPushButton('폴더 선택')
        def browse():
            path=QFileDialog.getExistingDirectory(d,'기기로 옮길 파일을 저장할 폴더',destination.text())
            if path:destination.setText(path)
        pick.clicked.connect(browse);row.addWidget(pick);form.addRow('내보내기 위치',row)
        fmt=combo(['회차별 CBZ 파일','순서가 고정된 이미지 폴더'])
        fmt.setCurrentIndex(0 if self.cfg.get('export_format','cbz')=='cbz' else 1)
        group=combo(['작품별','장르별 → 작품별','제공처별 → 작품별'])
        group.setCurrentIndex(['work','genre','publisher'].index(self.cfg.get('export_group','work')))
        optimize=QCheckBox('JPEG로 용량 줄이기 · 이미지 품질이 달라질 수 있습니다')
        optimize.setChecked(self.cfg.get('export_optimize',False))
        width=QSpinBox();width.setRange(320,8000);width.setValue(self.cfg.get('export_width',1600))
        quality=QSpinBox();quality.setRange(40,100);quality.setValue(self.cfg.get('export_quality',85))
        form.addRow('형식',fmt);form.addRow('폴더 분류',group);form.addRow(optimize)
        form.addRow('최대 가로 크기(px)',width);form.addRow('JPEG 품질',quality)
        estimate=QLabel('원본 용량 '+size_text(sum(w['size'] for w in self.rows if w['key'] in keys))+' · 변환 후 용량은 완료 시 표시합니다.')
        estimate.setWordWrap(True);form.addRow(estimate)
        note=QLabel('회차는 0001_1화, 이미지는 000001부터 저장합니다.\nCBZ는 CBZ 형식을 지원하는 만화 뷰어로 열 수 있습니다.\n날짜·순서가 미확인인 기존 자료는 먼저 확인 기능을 실행하세요.')
        note.setWordWrap(True);form.addRow(note)
        def start():
            if not destination.text().strip():
                QMessageBox.warning(d,'저장 위치','내보내기 폴더를 선택하세요.');return
            options={'format':'cbz' if fmt.currentIndex()==0 else 'folder','group':['work','genre','publisher'][group.currentIndex()],
                     'optimize':optimize.isChecked(),'width':width.value(),'quality':quality.value()}
            if only_selected.isChecked():options['episode_keys']=episode_keys
            self.cfg.update(export_dir=destination.text().strip(),export_format=options['format'],export_group=options['group'],
                            export_optimize=options['optimize'],export_width=options['width'],export_quality=options['quality'])
            self.persist();d.accept()
            export_destination=destination.text().strip()
            self.activity.setText('읽는 순서와 파일 무결성을 검사하고 기기용 사본을 만들고 있습니다…')
            self.run_task(lambda c,e:export_mobile(self.root,keys,export_destination,options,c,e),'export')
        b=QPushButton('내보내기 시작');b.setObjectName('primary');b.clicked.connect(start);form.addRow(b)
        d.exec()

    def on_event(self,kind,value):
        if kind=='log':self.activity.setText(value)
        elif kind=='export_progress':self.progress.setRange(0,value['total']);self.progress.setValue(value['value'])

    def finished_task(self,kind,state,result):
        if state=='success' and kind=='export':
            self.activity.setText(f"내보내기 완료 · {result['episode_count']}회차 / {result['image_count']}장 · 원본 {size_text(result['source_bytes'])} → 결과 {size_text(result['output_bytes'])}")
            self.last_export=result
            message=f"저장 위치: {result['path']}\n원본: {size_text(result['source_bytes'])}\n내보내기 결과: {size_text(result['output_bytes'])}\n{result['episode_count']}회차 · {result['image_count']}장"
            QMessageBox.information(self,'기기용 내보내기 완료',message)
        elif state=='success':
            self.activity.setText('업로드일과 이미지 순서를 확인했습니다.');self.refresh()
        elif state=='cancelled':self.activity.setText('작업이 중단되었습니다. 내보내던 임시 사본은 정리했습니다.')
        else:
            self.activity.setText(result);QMessageBox.warning(self,'작업 확인',result)

    def stop(self):
        if self.task:self.task.control.stopped.set()

    def closeEvent(self,event):
        if self.task and self.task.isRunning():
            self.task.control.stopped.set();self.activity.setText('작업을 중단하고 있습니다. 잠시 후 닫아주세요.');event.ignore();return
        self.persist();event.accept()
