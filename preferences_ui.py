"""One settings center, with persistent appearance and reading preferences."""
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QPushButton,QTabWidget,QWidget,QComboBox,QCheckBox,QColorDialog,QLineEdit,
    QFileDialog,QDoubleSpinBox,QSpinBox,QMessageBox)
import themes

def button(text,callback):
    widget=QPushButton(text);widget.clicked.connect(callback);return widget

class SettingsCenter(QDialog):
    def __init__(self,host,page=0):
        super().__init__(host);self.host=host;self.setWindowTitle('ToonShelf · 설정');self.resize(700,620)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,20)
        title=QLabel('나에게 맞는 ToonShelf');title.setStyleSheet('font-size:24px;font-weight:700');layout.addWidget(title)
        hint=QLabel('화면과 읽기 설정은 즉시 적용되며, 다음 실행에도 유지됩니다.');hint.setWordWrap(True);layout.addWidget(hint)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        screen=self.page('화면');self.theme=QComboBox();self.theme.addItems([x[0] for x in themes.THEMES.values()]);self.theme.setCurrentIndex(list(themes.THEMES).index(themes.key(host.cfg.get('theme'))))
        self.theme.currentIndexChanged.connect(lambda i:host.apply_theme(list(themes.THEMES)[i]));screen.addRow('프로그램 테마',self.theme)
        self.check(screen,'왼쪽 메뉴를 작게 표시','menu_compact',host.set_menu_compact)
        self.check(screen,'오른쪽 저장 규칙 숨기기','rules_hidden',host.set_rules_hidden)
        screen.addRow(QLabel('모든 화면 상단의 ⚙ 설정에서 다시 변경할 수 있습니다.'))
        reader=self.page('읽기');self.mode=QComboBox();self.mode.addItems(['프로그램 안에서 세로로 읽기','OpenComic 별도 창으로 읽기']);self.mode.setCurrentIndex(int(host.cfg.get('reader_mode')=='opencomic'));self.mode.currentIndexChanged.connect(self.change_mode);reader.addRow('기본 뷰어',self.mode)
        self.check(reader,'집중 보기 · 메뉴와 위·아래 도구 숨기기','reader_focus')
        self.check(reader,'읽을 때 상단 도구 숨기기','reader_hide_top')
        self.check(reader,'읽을 때 하단 읽기 폭·진행률 숨기기','reader_hide_bottom')
        self.background_label=QLabel();reader.addRow('이미지 바깥 배경색',self.background_label)
        row=QHBoxLayout()
        for name,color in [('화이트','#ffffff'),('다크','#14171e'),('회색','#808080'),('종이','#f4ecd8')]:
            row.addWidget(button(name,lambda checked=False,c=color:self.set_background(c)))
        reader.addRow(row);row=QHBoxLayout();row.addWidget(button('원하는 색 선택…',self.choose_background));row.addWidget(button('테마 기본색으로 복원',lambda:self.set_background('')));reader.addRow(row);self.update_background()
        self.read_width=QSpinBox();self.read_width.setRange(400,1600);self.read_width.setSuffix(' px');self.read_width.setValue(host.cfg.get('reader_width',850));self.read_width.valueChanged.connect(self.change_width);reader.addRow('최대 읽기 폭',self.read_width)
        self.exe=QLineEdit(host.opencomic_path());self.exe.setReadOnly(True);row=QHBoxLayout();row.addWidget(self.exe);row.addWidget(button('찾기…',self.choose_viewer));reader.addRow('OpenComic 실행 파일',row)
        help_text=QLabel('F9: 집중 보기 켜기·끄기  /  Esc: 도구 다시 표시\nAlt + ← / →: 이전·다음 화\n숨긴 상태에서는 화면 오른쪽 위의 ⚙ 또는 도구 표시를 누르세요.\n배경색은 원본 이미지에 영향을 주지 않습니다.');help_text.setWordWrap(True);reader.addRow(help_text)
        download=self.page('다운로드');row=QHBoxLayout();self.path_label=QLabel(host.path.text());self.path_label.setWordWrap(True);row.addWidget(self.path_label,1);row.addWidget(button('저장 폴더 변경…',self.choose_folder));download.addRow('저장 위치',row)
        from automation_ui import tail_combo
        self.latest=tail_combo(host.latest.currentData());self.latest.currentIndexChanged.connect(lambda i:host.latest.setCurrentIndex(i));download.addRow('일반 다운로드 범위',self.latest)
        download.addRow(button('자동 목록·예약·속도 제한 설정',lambda:self.open_manager(host.automation_dialog)))
        self.delay=QDoubleSpinBox();self.delay.setRange(.1,30);self.delay.setSingleStep(.1);self.delay.setValue(host.cfg['delay']);download.addRow('이미지 요청 간격 (초)',self.delay)
        self.browser=QCheckBox('작업용 브라우저 창 표시');self.browser.setChecked(host.cfg['visible_browser']);download.addRow(self.browser)
        self.selector=QLineEdit(host.cfg['image_selector']);download.addRow('본문 이미지 선택자',self.selector)
        note=QLabel('다운로드 설정은 아래 버튼으로 저장하세요.\n진행 중인 작업에는 현재 작업이 끝난 뒤 적용됩니다.');note.setWordWrap(True);download.addRow(note);self.download_status=QLabel();download.addRow(self.download_status);download.addRow(button('다운로드 설정 저장',self.save_download))
        convenience=self.page('관리·업데이트')
        for text,fn in [('자동 다운로드 목록·예약·보관 정리',host.automation_dialog),('다운로드 대기열 관리',host.queue_dialog),('완료 후 종료·타이머',host.power_dialog),('다운로드 기록·내보내기',host.history),('업데이트 확인·기존 폴더 패치',host.updates_dialog)]:convenience.addRow(button(text,lambda checked=False,fn=fn:self.open_manager(fn)))
        note=QLabel('업데이트 파일을 검사한 뒤 기존 프로그램 폴더에 패치합니다.\n내 설정, 읽던 위치와 다운로드한 작품은 유지됩니다.');note.setWordWrap(True);convenience.addRow(note)
        self.tabs.setCurrentIndex(page);layout.addWidget(button('닫기',self.accept),alignment=Qt.AlignRight)
    def page(self,title):
        widget=QWidget();form=QFormLayout(widget);form.setContentsMargins(16,20,16,16);form.setVerticalSpacing(16);self.tabs.addTab(widget,title);return form
    def open_manager(self,callback):
        # Close this modal first so an update can exit the application cleanly.
        self.accept();QTimer.singleShot(0,callback)
    def check(self,form,title,key,callback=None):
        widget=QCheckBox(title);widget.setChecked(bool(self.host.cfg.get(key,False)));widget.toggled.connect(callback or (lambda value:self.host.set_view_preference(key,value)));form.addRow(widget);setattr(self,key,widget)
    def set_background(self,value):
        self.host.set_view_preference('reader_background',value);self.update_background()
    def update_background(self):
        value=self.host.cfg.get('reader_background','');self.background_label.setText(value.upper() if value else '현재 테마 기본색');self.background_label.setStyleSheet(f'border-left:18px solid {value or themes.colors(self.host.cfg.get("theme"))["bg"]};padding-left:8px')
    def choose_background(self):
        initial=self.host.cfg.get('reader_background') or themes.colors(self.host.cfg.get('theme'))['bg'];color=QColorDialog.getColor(QColor(initial),self,'읽기 배경색 선택')
        if color.isValid():self.set_background(color.name())
    def change_width(self,value):
        self.host.set_view_preference('reader_width',value);pane=getattr(self.host,'offline',None)
        if pane:pane.width_slider.setValue(value)
    def change_mode(self,index):
        if index and not self.host.opencomic_path():
            QMessageBox.information(self,'뷰어 선택','먼저 OpenComic 실행 파일을 선택하세요.');self.mode.blockSignals(True);self.mode.setCurrentIndex(0);self.mode.blockSignals(False);return
        self.host.set_view_preference('reader_mode','opencomic' if index else 'embedded')
    def choose_viewer(self):
        path,_=QFileDialog.getOpenFileName(self,'OpenComic 실행 파일 선택',self.exe.text(),'실행 파일 (*.exe)')
        if path and Path(path).is_file():self.exe.setText(path);self.host.cfg['opencomic_exe']=path;self.host.persist_settings()
    def choose_folder(self):
        self.host.choose_folder();self.path_label.setText(self.host.path.text())
    def save_download(self):
        from bs4 import BeautifulSoup
        try:
            selector=self.selector.text().strip()
            if not selector:raise ValueError('본문 선택자를 입력하세요.')
            BeautifulSoup('', 'html.parser').select(selector)
            self.host.cfg.update(delay=self.delay.value(),visible_browser=self.browser.isChecked(),image_selector=selector);self.host.persist_settings();self.download_status.setText('다운로드 설정을 저장했습니다.')
        except Exception as exc:QMessageBox.warning(self,'설정 확인',str(exc))
