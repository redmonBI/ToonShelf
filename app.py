from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from queue_store import QueueStore
from power import PowerPlan
from sharing import VERSION, REPOSITORY
from PySide6.QtGui import QFont, QPixmap, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel,
    QPushButton, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QVBoxLayout,
    QHBoxLayout, QGridLayout, QScrollArea, QFileDialog, QProgressBar, QPlainTextEdit,
    QMessageBox, QDialog, QFormLayout, QComboBox, QStackedWidget)

from core import Browser, Work, Control, Cancelled, download, validate_url
from pagination import Pagination
import themes

APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
STATE = APP_DIR / 'state'
STATE.mkdir(exist_ok=True)
logging.basicConfig(filename=STATE / 'app.log', level=logging.INFO, encoding='utf-8')
DEFAULT = {'site_url': 'https://blacktoon423.com', 'output_dir': str(APP_DIR / 'Downloads'),
           'min_width': 100, 'min_height': 100, 'start_episode': 1, 'end_episode': 0,
           'delay': .25, 'visible_browser': False, 'image_selector': '#toon_content_imgs img',
           'library_roots': [], 'export_format':'cbz', 'export_optimize':False}

STYLE = themes.stylesheet('white')


def label(text, name=None, size=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    if size:
        widget.setStyleSheet(f'font-size:{size}px; font-weight:600;')
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName('primary')
    widget.clicked.connect(callback)
    return widget


class Job(QThread):
    event = Signal(str, object)
    done = Signal(str, object)

    def __init__(self, kind, cfg, works=()):
        super().__init__()
        self.kind, self.cfg, self.works = kind, dict(cfg), list(works)
        self.control = Control()

    def emit(self, kind, payload):
        self.event.emit(kind, payload)

    def run(self):
        try:
            if self.kind == 'download':
                result = download(self.cfg, self.works, self.control, self.emit)
            else:
                with Browser(self.cfg, self.control, self.emit) as browser:
                    if self.kind == 'scan':
                        self.works = browser.catalog()
                        self.emit('catalog', [asdict(w) for w in self.works])
                        targets = self.works[:24]
                    elif self.kind == 'episodes':
                        result = [asdict(e) for e in browser.episodes(self.works[0])]
                        self.done.emit('episodes', result)
                        return
                    else:
                        browser.visit(self.cfg['site_url'], 'a.toon-link img[data-original]')
                        targets = self.works
                    for work in targets:
                        self.control.check()
                        if not work.thumbnail:
                            continue
                        import hashlib
                        cache = STATE / 'covers'
                        cache.mkdir(exist_ok=True)
                        path = cache / (hashlib.sha256(work.thumbnail.encode()).hexdigest() + '.img')
                        try:
                            if not path.exists():
                                data = browser.fetch(work.thumbnail, self.cfg['site_url'])
                                from PIL import Image
                                from io import BytesIO
                                with Image.open(BytesIO(data)) as image:
                                    image.verify()
                                path.write_bytes(data)
                            self.emit('cover', {'url': work.url, 'path': str(path)})
                        except Cancelled:
                            raise
                        except Exception as exc:
                            self.emit('log', f'표지 로딩: {exc}')
                    result = len(self.works)
            self.done.emit(self.kind, result)
        except Cancelled:
            self.done.emit('cancelled', None)
        except Exception as exc:
            logging.error(traceback.format_exc())
            self.done.emit('error', str(exc))


class Card(QFrame):
    def __init__(self, work, selected, change, detail):
        super().__init__()
        self.setObjectName('card')
        self.setMinimumWidth(165)
        self.setMaximumWidth(270)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        self.cover = QLabel()
        self.cover.setFixedHeight(172)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setObjectName('coverPlaceholder')
        self.cover.setText('TS')
        layout.addWidget(self.cover)
        self.check = QCheckBox(work.title if len(work.title) <= 17 else work.title[:16] + '…')
        self.check.setToolTip(work.title)
        self.check.setChecked(selected)
        self.check.toggled.connect(lambda checked: change(work.url, checked))
        layout.addWidget(self.check)
        meta = label(' · '.join(filter(None,[work.publisher,work.genre,work.latest])) or '회차 목록을 확인하세요', 'muted')
        meta.setWordWrap(True)
        meta.setMaximumHeight(44)
        layout.addWidget(meta)
        b = button('회차 살펴보기  →', lambda: detail(work))
        b.setStyleSheet('padding:6px; font-size:10px;')
        layout.addWidget(b)
        if work.cover:
            self.set_cover(work.cover)

    def set_cover(self, path):
        cover_path = Path(path)
        if not cover_path.is_absolute():
            cover_path = APP_DIR / cover_path
        pix = QPixmap(str(cover_path))
        if not pix.isNull():
            self.cover.setPixmap(pix.scaled(235, 172, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, 235, 172))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = DEFAULT.copy()
        config = STATE / 'settings.json'
        if config.exists():
            try:
                self.cfg.update(json.loads(config.read_text(encoding='utf-8')))
            except (ValueError, OSError):
                pass
        self.overrides={}
        self.state_dir=STATE
        self.queue=QueueStore(STATE/'queue.sqlite3')
        from automation_store import AutoStore
        self.auto_store=AutoStore(STATE/'automation.sqlite3');self.auto_job=None;self.auto_notice='';self.auto_last_check=0;self.automation_closed=False
        self.queue_job=None;self.queue_jobs={};self.queue_metrics={};self.queue_reasons={};self.queue_running=False;self.queue_reason=None;self.batch_ids=set()
        from collections_store import CollectionStore
        self.collection_store=CollectionStore(STATE/'collections.sqlite3');self.notification_job=None
        self.power=PowerPlan(STATE/'power_history.jsonl')
        self.community_cache={}
        self.update_job=None;self.update_rows=[];self.latest_release=None
        if (STATE/'properties.json').exists():
            try:self.overrides=json.loads((STATE/'properties.json').read_text(encoding='utf-8'))
            except (ValueError,OSError):pass
        self.works, self.selected, self.cards = [], set(), {}
        self.page_index = 0
        self.job = None
        self.download_bytes = 0
        self.cover_timer = QTimer(self)
        self.cover_timer.setSingleShot(True)
        self.cover_timer.timeout.connect(self.load_visible_covers)
        self.setWindowTitle(f'ToonShelf {VERSION} · 대기열 · 커뮤니티')
        self.resize(1450, 960)
        self.setMinimumSize(1180, 780)
        self.build()
        self.apply_theme(self.cfg.get('theme','white'),persist=False)
        cached = STATE / 'catalog.json'
        if cached.exists():
            try:
                self.set_catalog(json.loads(cached.read_text(encoding='utf-8')))
                self.status.setText('저장된 목록 · 최신 목록을 불러와 확인하세요')
            except (OSError, ValueError, TypeError):
                pass
        self.queue_timer=QTimer(self);self.queue_timer.timeout.connect(self.queue_tick);self.queue_timer.start(1000)
        self.disk_timer=QTimer(self);self.disk_timer.timeout.connect(self.update_disk);self.disk_timer.start(10000)
        self.update_timer=QTimer(self);self.update_timer.timeout.connect(self.check_updates);self.update_timer.start(6*3600*1000)
        self.automation_timer=QTimer(self);self.automation_timer.timeout.connect(self.automation_tick);self.automation_timer.start(30000)
        self.notification_timer=QTimer(self);self.notification_timer.timeout.connect(self.check_episode_updates);self.notification_timer.start(30*60*1000)
        from app_services import AccountCoordinator
        self.accounts_service=AccountCoordinator(self,STATE)
        if not os.environ.get('TOONSHELF_TESTING') and not any(a.startswith('--') for a in sys.argv[1:]):QTimer.singleShot(2500,self.check_updates)

    def build(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell=QVBoxLayout(root);shell.setContentsMargins(0,0,0,0);shell.setSpacing(0)
        self.app_toolbar=QWidget();toolbar=QHBoxLayout(self.app_toolbar);toolbar.setContentsMargins(12,7,12,7)
        self.menu_toggle=button('☰ 메뉴 접기',self.toggle_menu);toolbar.addWidget(self.menu_toggle)
        toolbar.addStretch()
        self.compact_download=button('선택 작품 다운로드 ↓',self.start_download,True);toolbar.addWidget(self.compact_download)
        self.rules_toggle=button('저장 규칙 숨기기',self.toggle_rules);toolbar.addWidget(self.rules_toggle)
        toolbar.addWidget(button('⚙ 설정',self.settings));shell.addWidget(self.app_toolbar)
        self.account_button=button('계정 · 로그인',self.accounts);toolbar.addWidget(self.account_button)
        self.notification_button=button('새 회차 0',self.notifications);toolbar.addWidget(self.notification_button)
        outer = QHBoxLayout();shell.addLayout(outer,1)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        self.sidebar=sidebar;self.sidebar_buttons=[];self.sidebar_labels=[]
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(186)
        side = QVBoxLayout(sidebar)
        self.sidebar_layout=side
        side.setContentsMargins(19, 30, 19, 24)
        self.brand=label('◈  ToonShelf', 'accent', 21);side.addWidget(self.brand)
        subtitle=label('나만의 작품 아카이브','muted');side.addWidget(subtitle);self.sidebar_labels.append(subtitle)
        side.addSpacing(38)
        nav = button('▦   사이트 작품 목록', self.show_catalog)
        nav.setObjectName('activeNav')
        self.catalog_nav=nav
        self.sidebar_buttons.append((nav,nav.text()))
        side.addWidget(nav)
        for text, action in [('▣   다운로드 작품', self.show_offline), ('↗   보관함·내보내기', self.history), ('≡   다운로드 대기열', self.queue_dialog),
                             ('↻   자동 다운로드', self.automation_dialog),('◷   종료 예약', self.power_dialog), ('♡   친구 추천', self.community_dialog),
                             ('↗   사이트·최신 링크', self.sites_dialog), ('⚙   세부 설정', self.settings), ('↗   저장 폴더', self.open_folder)]:
            b = button(text, action)
            b.setObjectName('nav')
            if action==self.show_offline:self.library_nav=b
            side.addWidget(b)
            self.sidebar_buttons.append((b,text));b.setToolTip(text.strip());b.setAccessibleName(text.strip())
        side.addStretch()
        version_label=label('TOONSHELF  /  '+VERSION,'muted');side.addWidget(version_label);self.sidebar_labels.append(version_label)
        note = label('원본을 보존하고\n회차별로 정리합니다.', 'muted')
        note.setWordWrap(True)
        side.addWidget(note)
        self.sidebar_labels.append(note)
        outer.addWidget(sidebar)
        center = QWidget()
        main = QVBoxLayout(center)
        main.setContentsMargins(28, 27, 24, 24)
        main.setSpacing(16)
        topline = QHBoxLayout()
        topline.addWidget(label('LIBRARY  /  작품 관리', 'muted'))
        self.update_button=button('v'+VERSION+' · 업데이트 확인',self.updates_dialog)
        topline.addWidget(self.update_button)
        topline.addStretch()
        self.status = label('사이트 목록을 불러오면 시작할 수 있어요', 'accent')
        topline.addWidget(self.status)
        main.addLayout(topline)
        main.addWidget(label('읽고 싶은 작품, 한곳에.', 'title'))
        main.addWidget(label('작품을 체크하세요. 첫 회차부터 최신 회차까지 차례대로 정리합니다.', 'muted'))
        source = QFrame()
        source.setObjectName('panel')
        sl = QVBoxLayout(source)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.addWidget(label('SOURCE  /  사이트 연결', 'muted'))
        row = QHBoxLayout()
        self.url = QLineEdit(self.cfg['site_url'])
        self.url.setPlaceholderText('사이트 주소 · 도메인이 변경되면 수정하세요')
        row.addWidget(self.url)
        self.scan_button = button('목록 불러오기', self.scan, True)
        row.addWidget(self.scan_button)
        row.addWidget(button('전체 갱신',self.scan))
        sl.addLayout(row)
        main.addWidget(source)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('작품 이름 검색')
        self.search.textChanged.connect(self.filter_changed)
        tools.addWidget(self.search, 1)
        self.select_all = button('현재 목록 선택', self.select_visible)
        tools.addWidget(self.select_all)
        tools.addWidget(button('선택 해제', self.clear_selection))
        main.addLayout(tools)
        taxonomy=QHBoxLayout()
        self.genre_filter=QComboBox();self.genre_filter.addItem('모든 장르')
        self.publisher_filter=QComboBox();self.publisher_filter.addItem('모든 제공처')
        self.genre_filter.currentTextChanged.connect(self.filter_changed)
        self.publisher_filter.currentTextChanged.connect(self.filter_changed)
        taxonomy.addWidget(self.genre_filter);taxonomy.addWidget(self.publisher_filter)
        self.sort_filter=QComboBox();self.sort_filter.addItems(['기본 순서','인기 · 추천 동감순','신작 · 새로 발견순','최신 회차순','작품명순'])
        self.sort_filter.setCurrentIndex(self.cfg.get('catalog_sort',0));self.sort_filter.currentIndexChanged.connect(self.filter_changed)
        taxonomy.addWidget(self.sort_filter);taxonomy.addWidget(button('장르 숨김',self.hide_genres))
        self.show_hidden=QCheckBox('숨긴 장르 보기');self.show_hidden.toggled.connect(self.filter_changed);taxonomy.addWidget(self.show_hidden)
        main.addLayout(taxonomy)
        from notifications_ui import CollectionFilters
        self.collection_filters=CollectionFilters(self.filter_changed);main.addWidget(self.collection_filters)
        counts = QHBoxLayout()
        self.count = label('작품 0개', 'muted')
        counts.addWidget(self.count)
        counts.addStretch()
        self.selected_label = label('0개 선택', 'accent')
        counts.addWidget(self.selected_label)
        main.addLayout(counts)
        scroll = QScrollArea()
        self.catalog_scroll=scroll
        scroll.setWidgetResizable(True)
        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 6, 0)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.grid_widget)
        main.addWidget(scroll, 1)
        self.pager=Pagination();self.pager.requested.connect(self.go_page);main.addWidget(self.pager)
        self.content_stack=QStackedWidget();self.download_page=QWidget();download_layout=QHBoxLayout(self.download_page)
        download_layout.setContentsMargins(0,0,0,0);download_layout.addWidget(center,1)
        self.content_stack.addWidget(self.download_page);outer.addWidget(self.content_stack,1)
        rail = QWidget()
        self.right_rail=rail
        rail.setFixedWidth(307)
        right = QVBoxLayout(rail)
        right.setContentsMargins(0, 27, 22, 24)
        right.setSpacing(15)
        right.addWidget(label('DOWNLOAD STUDIO', 'muted'))
        panel = QFrame()
        panel.setObjectName('panel')
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(17, 18, 17, 18)
        pl.setSpacing(12)
        pl.addWidget(label('저장 규칙', size=17))
        pl.addWidget(label('저장 위치', 'muted'))
        self.path = QLineEdit(self.cfg['output_dir'])
        self.path.setToolTip(self.cfg['output_dir'])
        pl.addWidget(self.path)
        folder_row=QHBoxLayout()
        folder_row.addWidget(button('폴더 변경',self.choose_folder))
        folder_row.addWidget(button('설정 저장',self.save_settings_clicked))
        pl.addLayout(folder_row)
        self.disk_label=label('저장 폴더를 자유롭게 변경할 수 있습니다.','muted')
        self.disk_label.setWordWrap(True);pl.addWidget(self.disk_label)
        self.path.editingFinished.connect(self.save_settings_clicked)
        pl.addWidget(label('최소 이미지 크기 · 가로 × 세로', 'muted'))
        row = QHBoxLayout()
        self.width, self.height = QSpinBox(), QSpinBox()
        for spin, key in [(self.width, 'min_width'), (self.height, 'min_height')]:
            spin.setRange(1, 20000)
            spin.setValue(self.cfg[key])
        row.addWidget(self.width)
        row.addWidget(label('×'))
        row.addWidget(self.height)
        row.addWidget(label('px', 'muted'))
        pl.addLayout(row)
        pl.addWidget(label('회차 범위 · 마지막 0 = 최신까지', 'muted'))
        row = QHBoxLayout()
        self.start, self.end = QSpinBox(), QSpinBox()
        self.start.setRange(0, 100000)
        self.end.setRange(0, 100000)
        self.start.setValue(self.cfg['start_episode'])
        self.end.setValue(self.cfg['end_episode'])
        row.addWidget(self.start)
        row.addWidget(label('~'))
        row.addWidget(self.end)
        pl.addLayout(row)
        from automation_ui import tail_combo
        self.latest=tail_combo(self.cfg.get('latest_count',0));pl.addWidget(self.latest)
        self.latest.currentIndexChanged.connect(self.latest_mode_changed)
        self.start.setEnabled(not self.latest.currentData());self.end.setEnabled(not self.latest.currentData())
        rule = label('최신 범위 선택 시 회차 범위 대신 최신부터 받습니다.\n작품명 / 1화 / 원본파일명', 'accent')
        rule.setWordWrap(True)
        pl.addWidget(rule)
        self.start_button = button('선택 작품 다운로드  ↓', self.start_download, True)
        pl.addWidget(self.start_button)
        right.addWidget(panel)
        progress = QFrame()
        progress.setObjectName('panel')
        pr = QVBoxLayout(progress)
        pr.setContentsMargins(17, 16, 17, 16)
        self.current = label('다운로드 대기 중', size=15)
        self.current.setWordWrap(True)
        pr.addWidget(self.current)
        self.episode_label = label('체크한 작품의 회차를 순서대로 처리합니다.', 'muted')
        self.episode_label.setWordWrap(True)
        pr.addWidget(self.episode_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        pr.addWidget(self.progress)
        self.image_progress = label('이미지 0 / 0', 'muted')
        pr.addWidget(self.image_progress)
        self.stats = label('신규 0   ·   기존 0   ·   실패 0', 'accent')
        pr.addWidget(self.stats)
        from download_metrics import DownloadMetrics
        self.download_meter=DownloadMetrics();self.speed_label=label('속도 — · 남은 시간 계산 중','muted');self.speed_label.setWordWrap(True);pr.addWidget(self.speed_label)
        self.speed_timer=QTimer(self);self.speed_timer.timeout.connect(self.refresh_speed);self.speed_timer.start(1000)
        self.volume = label('저장 용량 0.0 MB', 'muted')
        pr.addWidget(self.volume)
        pr.addWidget(button('전체 작품 진행 그래프',self.download_dashboard))
        self.active_downloads=label('진행 중인 작품 없음','muted');self.active_downloads.setWordWrap(True);pr.addWidget(self.active_downloads)
        row = QHBoxLayout()
        self.pause_button = button('일시정지', self.pause)
        self.stop_button = button('중단', self.stop)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        row.addWidget(self.pause_button)
        row.addWidget(self.stop_button)
        pr.addLayout(row)
        right.addWidget(progress)
        right.addWidget(label('ACTIVITY  /  작업 기록', 'muted'))
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(700)
        right.addWidget(self.logs, 1)
        download_layout.addWidget(rail)
        self.set_menu_compact(bool(self.cfg.get('menu_compact',False)),persist=False)
        self.set_rules_hidden(bool(self.cfg.get('rules_hidden',False)),persist=False)
        self.render()
        self.update_disk()

    def persist_settings(self):
        service=getattr(self,'accounts_service',None)
        if service and service.profile_id:
            from app_services import SYNC_KEYS
            folder=STATE/'accounts'/service.profile_id;folder.mkdir(parents=True,exist_ok=True);(folder/'settings.json').write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2),encoding='utf-8')
            guest_cfg=service.guest[0];value={k:v for k,v in self.cfg.items() if k not in SYNC_KEYS and k!='reading_positions'};value.update({k:v for k,v in guest_cfg.items() if k in SYNC_KEYS or k=='reading_positions'})
        else:value=self.cfg
        target=STATE/'settings.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)

    def latest_mode_changed(self,index):
        self.start.setEnabled(not self.latest.currentData());self.end.setEnabled(not self.latest.currentData())
        self.cfg['latest_count']=self.latest.currentData();self.persist_settings()

    def toggle_menu(self):self.set_menu_compact(not self.cfg.get('menu_compact',False))
    def set_menu_compact(self,compact,persist=True):
        self.cfg['menu_compact']=compact;self.sidebar.setFixedWidth(68 if compact else 186)
        self.sidebar_layout.setContentsMargins(8 if compact else 19,30,8 if compact else 19,24)
        self.brand.setText('◈' if compact else '◈  ToonShelf')
        for widget in self.sidebar_labels:widget.setVisible(not compact)
        for widget,text in self.sidebar_buttons:
            widget.setText(text.strip()[0] if compact else text);widget.setToolTip(text.strip());widget.setAccessibleName(text.strip())
        self.menu_toggle.setText('☰ 메뉴 펼치기' if compact else '☰ 메뉴 접기')
        if hasattr(self,'pager'):self.render()
        if persist:self.persist_settings()

    def toggle_rules(self):self.set_rules_hidden(not self.cfg.get('rules_hidden',False))
    def set_rules_hidden(self,hidden,persist=True):
        self.cfg['rules_hidden']=hidden;self.right_rail.setVisible(not hidden)
        self.rules_toggle.setText('저장 규칙 표시' if hidden else '저장 규칙 숨기기')
        self.compact_download.setVisible(hidden)
        if hasattr(self,'pager'):self.render()
        if persist:self.persist_settings()

    def save_settings_clicked(self):
        try:
            self.read_cfg();self.update_disk();self.status.setText('저장 위치와 설정을 저장했습니다')
        except ValueError as exc:QMessageBox.warning(self,'설정 확인',str(exc))

    def update_disk(self):
        from library import size_text
        import shutil
        try:
            path=Path(self.path.text()).expanduser().resolve()
            probe=path
            while not probe.exists() and probe!=probe.parent:probe=probe.parent
            free=shutil.disk_usage(probe).free
            self.disk_label.setText(f'저장 장치 여유 공간 {size_text(free)}')
            self.path.setToolTip(str(path))
        except (OSError,ValueError):self.disk_label.setText('저장 경로와 드라이브 연결을 확인하세요.')

    def read_cfg(self):
        cfg = self.cfg.copy()
        cfg.update(site_url=validate_url(self.url.text()), output_dir=self.path.text().strip(),
                   min_width=self.width.value(), min_height=self.height.value(),
                   start_episode=self.start.value(), end_episode=self.end.value(),latest_count=self.latest.currentData(),policy_file=self.policy_path())
        if not cfg['output_dir']:
            raise ValueError('저장 폴더를 선택하세요.')
        if not cfg['latest_count'] and cfg['end_episode'] and cfg['end_episode'] < cfg['start_episode']:
            raise ValueError('마지막 회차는 시작 회차 이상이어야 합니다.')
        cfg['output_dir']=str(Path(cfg['output_dir']).expanduser().resolve())
        cfg['library_roots']=list(dict.fromkeys([cfg['output_dir']]+cfg.get('library_roots',[])))
        self.cfg.update(cfg)
        self.url.setText(cfg['site_url'])
        cfg=self.cfg
        self.persist_settings()
        return cfg

    def policy_path(self):
        service=getattr(self,'accounts_service',None)
        return str(STATE/'accounts'/service.profile_id/'settings.json') if service and service.profile_id else str(STATE/'settings.json')

    def launch(self, kind, works=()):
        if self.job and self.job.isRunning():
            return
        try:
            cfg = self.read_cfg()
        except ValueError as exc:
            QMessageBox.warning(self, '설정 확인', str(exc))
            return
        self.job = Job(kind, cfg, works)
        self.job.event.connect(self.on_event)
        self.job.done.connect(self.on_done)
        self.job.finished.connect(self.on_finished)
        self.scan_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(kind == 'download')
        self.stop_button.setEnabled(True)
        self.job.start()

    def on_finished(self):
        self.scan_button.setEnabled(True)
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(bool(self.queue_job))
        self.stop_button.setEnabled(bool(self.queue_job))
        self.pause_button.setText('일시정지')
        if self.job and self.job.kind != 'covers':
            self.cover_timer.start(500)

    def scan(self):
        self.status.setText('사이트에서 작품 목록을 읽고 있습니다…')
        self.launch('scan')

    def set_catalog(self, values,mark_new=False):
        old={w.url:w for w in self.works}
        seen=self.cfg.setdefault('catalog_firstseen',{})
        import time
        for value in values:
            if value['url'] not in seen:seen[value['url']]=time.time() if mark_new and value['url'] not in old else 0
            if not value.get('cover') and value['url'] in old:value['cover']=old[value['url']].cover
        self.works = [Work(**w) for w in values]
        from urllib.parse import urlsplit
        for work in self.works:
            properties=self.overrides.get(urlsplit(work.url).path,{})
            if 'genre' in properties:work.genre=properties['genre']
            if 'publisher' in properties:work.publisher=properties['publisher']
        self.refresh_taxonomy()
        self.selected.intersection_update(w.url for w in self.works)
        self.page_index = 0
        self.render()

    def refresh_taxonomy(self):
        from library import genres
        for widget,choices in [(self.genre_filter,['모든 장르']+sorted({g for w in self.works for g in genres(w.genre)})),
                               (self.publisher_filter,['모든 제공처']+sorted({w.publisher or '미분류' for w in self.works}))]:
            selected=widget.currentText();widget.blockSignals(True);widget.clear();widget.addItems(choices)
            if widget.findText(selected)>=0:widget.setCurrentText(selected)
            widget.blockSignals(False)

    def set_properties(self,key,genre,publisher):
        from urllib.parse import urlsplit
        self.overrides[key]={'genre':genre,'publisher':publisher}
        (STATE/'properties.json').write_text(json.dumps(self.overrides,ensure_ascii=False,indent=2),encoding='utf-8')
        for work in self.works:
            if urlsplit(work.url).path==key:work.genre=genre;work.publisher=publisher
        self.refresh_taxonomy();self.render();self.cache_catalog()

    def cache_catalog(self):
        values = []
        for w in self.works:
            value = asdict(w)
            if w.cover:
                try:
                    value['cover'] = str(Path(w.cover).relative_to(APP_DIR))
                except ValueError:
                    pass
            values.append(value)
        (STATE / 'catalog.json').write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')

    def filtered(self):
        q = self.search.text().strip().casefold()
        from library import genres
        g,p=self.genre_filter.currentText(),self.publisher_filter.currentText()
        hidden=set(self.cfg.get('hidden_genres',[]))
        works=[w for w in self.works if q in w.title.casefold() and (g=='모든 장르' or g in genres(w.genre)) and
                (p=='모든 제공처' or p==(w.publisher or '미분류')) and (self.show_hidden.isChecked() or not hidden.intersection(genres(w.genre)))]
        mode=self.sort_filter.currentIndex()
        votes={}
        for post in self.community_cache.get('posts',[]):votes[post['title']]=votes.get(post['title'],0)+len(post.get('votes',[]))
        seen=self.cfg.get('catalog_firstseen',{})
        if mode==1:works.sort(key=lambda w:votes.get(w.title,0),reverse=True)
        elif mode==2:works.sort(key=lambda w:seen.get(w.url,0),reverse=True)
        elif mode==3:
            import re
            works.sort(key=lambda w:float(re.search(r'\d+(?:\.\d+)?',w.latest).group()) if re.search(r'\d+(?:\.\d+)?',w.latest) else -1,reverse=True)
        elif mode==4:works.sort(key=lambda w:w.title.casefold())
        if hasattr(self,'collection_filters'):works=self.collection_filters.apply(works,self.collection_store)
        return works

    def filter_changed(self):
        if hasattr(self,'sort_filter'):self.cfg['catalog_sort']=self.sort_filter.currentIndex()
        self.page_index = 0
        self.render()
        self.cover_timer.start(600)

    def load_visible_covers(self):
        if self.job and self.job.isRunning():
            return
        missing = [w for w in self.filtered()[self.page_index*24:(self.page_index+1)*24] if not w.cover]
        if missing:
            self.launch('covers', missing)

    def render(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.cards = {}
        works = self.filtered()
        self.page_index=min(self.page_index,max(0,(len(works)-1)//24))
        self.count.setText(f'작품 {len(works):,}개  ·  전체 {len(self.works):,}개')
        self.selected_label.setText(f'{len(self.selected)}개 선택')
        columns=(5 if self.cfg.get('menu_compact') else 4) if self.cfg.get('rules_hidden') else 3
        for i, work in enumerate(works[self.page_index*24:(self.page_index+1)*24]):
            card = Card(work, work.url in self.selected, self.select, self.episodes)
            row=QHBoxLayout();favorite=button('★' if (self.collection_store.get(work) or {}).get('favorite') else '☆',lambda checked=False,w=work:self.toggle_favorite(w));favorite.setToolTip('즐겨찾기 추가 / 해제');row.addWidget(favorite)
            row.addWidget(button('요일 · 분류',lambda checked=False,w=work:self.work_settings(w)));card.layout().addLayout(row)
            self.cards[work.url] = card
            self.grid.addWidget(card, i//columns, i%columns)
        if not works:
            empty = label('아직 작품이 없습니다.\n상단의 ‘목록 불러오기’를 눌러 시작하세요.', 'muted', 16)
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(300)
            self.grid.addWidget(empty, 0, 0, 1, 3)
        self.pager.update_pages(self.page_index,max(1,(len(works)+23)//24))

    def select(self, url, checked):
        self.selected.add(url) if checked else self.selected.discard(url)
        self.selected_label.setText(f'{len(self.selected)}개 선택')

    def select_visible(self):
        self.selected.update(self.cards)
        for card in self.cards.values():
            card.check.setChecked(True)

    def clear_selection(self):
        self.selected.clear()
        for card in self.cards.values():
            card.check.setChecked(False)
        self.selected_label.setText('0개 선택')

    def turn_page(self, delta):
        self.go_page(self.page_index+delta)

    def go_page(self,index):
        maximum = max(0, (len(self.filtered())-1)//24)
        self.page_index = max(0, min(maximum,index))
        self.render()
        self.catalog_scroll.verticalScrollBar().setValue(0)
        missing = [w for w in self.filtered()[self.page_index*24:(self.page_index+1)*24] if not w.cover]
        if missing:
            self.launch('covers', missing)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, '이미지 저장 폴더', self.path.text())
        if path:
            self.path.setText(path)
            self.save_settings_clicked()

    def open_folder(self):
        path = Path(self.path.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path.resolve()))

    def start_download(self):
        works = [w for w in self.works if w.url in self.selected]
        if not works:
            QMessageBox.information(self, '작품 선택', '다운로드할 작품을 체크하세요.')
            return
        # Preserve paths while replacing only the host the user configured.
        from urllib.parse import urlsplit, urlunsplit
        try:
            host = urlsplit(validate_url(self.url.text()))
        except ValueError as exc:
            QMessageBox.warning(self, '주소 확인', str(exc))
            return
        works = [Work(**{**asdict(w),'url':urlunsplit((host.scheme, host.netloc, urlsplit(w.url).path, '', ''))}) for w in works]
        self.download_bytes = 0
        self.progress.setValue(0)
        self.status.setText('다운로드 준비 중')
        if any(a.startswith('--self-test') for a in sys.argv):self.launch('download',works);return
        try:cfg=self.read_cfg()
        except ValueError as exc:QMessageBox.warning(self,'설정 확인',str(exc));return
        ids=self.queue.add(works,cfg);self.batch_ids.update(ids)
        self.status.setText(f'대기열에 {len(ids)}개 작품 추가');self.run_queue()

    def pause(self):
        if self.queue_jobs:
            paused=all(job.control.paused.is_set() for job in self.queue_jobs.values())
            for id,job in self.queue_jobs.items():
                job.control.paused.clear() if paused else job.control.paused.set();self.queue.change(id,'running' if paused else 'paused')
            self.pause_button.setText('일시정지' if paused else '계속 받기')
            return
        if self.job:
            if self.job.control.paused.is_set():
                self.job.control.paused.clear()
                self.pause_button.setText('일시정지')
                self.status.setText('다운로드 진행 중')
            else:
                self.job.control.paused.set()
                self.pause_button.setText('계속 받기')
                self.status.setText('일시정지 · 현재 요청이 끝나면 멈춥니다')

    def stop(self):
        if self.queue_jobs:
            self.queue_running=False
            for id in list(self.queue_jobs):self.change_queue(id,'stopped')
            return
        if self.job:
            self.job.control.stopped.set()
            self.status.setText('중단 요청 · 현재 요청이 끝나면 멈춥니다')

    def episodes(self, work):
        self.status.setText(f'{work.title} · 회차 확인 중')
        self.launch('episodes', [work])

    def on_event(self, kind, value):
        if kind == 'catalog':
            self.set_catalog(value,True)
            self.cache_catalog()
            self.persist_settings()
            self.status.setText(f'{len(value):,}개 작품 발견 · 표지 불러오는 중')
        elif kind == 'cover':
            for w in self.works:
                if w.url == value['url']:
                    w.cover = value['path']
            if value['url'] in self.cards:
                self.cards[value['url']].set_cover(value['path'])
        elif kind == 'log':
            self.logs.appendPlainText(value)
        elif kind == 'transfer_wait':
            self.transfer_waiting=value;self.status.setText('허용 다운로드 시간까지 대기 중 · 중단 가능' if value else '다운로드 진행 중')
        elif kind == 'plan':
            self.progress.setRange(0, max(1, value))
        elif kind == 'current':
            self.current.setText(value['title'])
            self.episode_label.setText(f"{value['episode']}  ·  {value['date']}\n회차 {value['index']+1} / {value['total']}")
            self.status.setText('다운로드 진행 중')
        elif kind == 'image_progress':
            self.image_progress.setText(f"이미지 {value['index']} / {value['total']}")
        elif kind == 'saved':
            self.download_bytes += value['bytes']
            self.volume.setText(f'신규 저장 용량 {self.download_bytes/1024**2:.1f} MB')
        elif kind == 'progress':
            self.progress.setValue(value['value'])
            self.stats.setText(f"신규 {value['saved']} · 기존 {value['skipped']} · 제외 {value['filtered']} · 실패 {value['failed']}")
        elif kind=='transfer_progress':
            self.download_meter.record(value);self.refresh_speed()

    def on_done(self, kind, value):
        if kind == 'error':
            self.status.setText('확인이 필요합니다 · 작업 기록을 확인하세요')
            self.logs.appendPlainText(value)
            QMessageBox.warning(self, '작업 확인', value)
        elif kind == 'cancelled':
            self.status.setText('중단됨 · 다시 시작하면 저장한 파일은 건너뜁니다')
        elif kind == 'episodes':
            self.status.setText(f'회차 {len(value)}개 확인')
            dialog = QDialog(self)
            dialog.setWindowTitle('회차 미리보기 · 다운로드 순서')
            dialog.resize(650, 580)
            layout = QVBoxLayout(dialog)
            layout.addWidget(label(f'총 {len(value):,}개 회차 · 게시 날짜 / 회차 순서', 'accent', 16))
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText('\n'.join(f"{i+1:04d}   {e['folder']}   {e['date']}" for i, e in enumerate(value)))
            layout.addWidget(text)
            layout.addWidget(button('닫기', dialog.accept))
            dialog.exec()
        elif kind == 'download':
            failed = value['failed']
            self.status.setText(f"{'부분 완료 · 실패 항목은 다시 시작해 재시도하세요' if failed else '다운로드 완료'}")
            self.logs.appendPlainText(json.dumps(value, ensure_ascii=False))
        else:
            self.cache_catalog()
            self.status.setText(f'작품 {len(self.works):,}개 · 선택 후 다운로드하세요')

    def settings(self):
        from preferences_ui import SettingsCenter
        SettingsCenter(self).exec()

    def history(self):
        if self.auto_job and self.auto_job.isRunning():QMessageBox.information(self,'작업 진행 중','자동 목록 작업을 마친 뒤 보관함을 여세요.');return
        if self.queue_job or (self.job and self.job.isRunning()):
            QMessageBox.information(self,'작업 진행 중','현재 작업이 끝난 뒤 보관함을 여세요.');return
        try:self.read_cfg()
        except ValueError as exc:QMessageBox.warning(self,'설정 확인',str(exc));return
        from library_ui import LibraryDialog
        LibraryDialog(self).exec()

    def closeEvent(self, event):
        if self.notification_job and self.notification_job.isRunning():self.notification_job.control.stopped.set();self.status.setText('새 회차 확인 정리 중 · 잠시 후 다시 닫아주세요');event.ignore();return
        if self.accounts_service.busy():self.status.setText('계정 동기화가 끝난 뒤 닫아주세요');event.ignore();return
        if self.auto_job and self.auto_job.isRunning():
            self.auto_job.control.stopped.set();self.status.setText('자동 목록 작업 정리 중 · 잠시 후 다시 닫아주세요');event.ignore();return
        if getattr(self,'offline',None) is not None and not self.offline.shutdown():
            self.status.setText('뷰어 작업 정리 중 · 잠시 후 다시 닫아주세요');event.ignore();return
        if self.queue_job:
            self.queue_running=False
            for id in list(self.queue_jobs):self.change_queue(id,'stopped')
            self.status.setText('대기열 기록 저장 중 · 잠시 후 다시 닫아주세요');event.ignore();return
        if self.update_job and self.update_job.isRunning():event.ignore();return
        if self.job and self.job.isRunning():
            self.job.control.stopped.set()
            self.status.setText('작업 종료 중 · 잠시 후 다시 닫아주세요')
            event.ignore()
            return
        try:
            self.read_cfg()
        except ValueError:
            pass
        self.power.cancel()
        self.automation_timer.stop()
        self.notification_timer.stop()
        self.speed_timer.stop();self.cover_timer.stop();self.queue_timer.stop();self.disk_timer.stop();self.update_timer.stop()
        self.accounts_service.stop()
        self.automation_closed=True
        event.accept()

    def queue_dialog(self):
        self.download_dashboard()
    def power_dialog(self):
        from control_ui import PowerDialog
        PowerDialog(self).exec()
    def community_dialog(self):
        from control_ui import CommunityDialog
        CommunityDialog(self).exec()
    def sites_dialog(self):
        from sites_ui import SitesDialog
        SitesDialog(self).exec()
    def updates_dialog(self):
        from control_ui import UpdatesDialog
        UpdatesDialog(self).exec()
    def hide_genres(self):
        from library import genres
        d=QDialog(self);d.setWindowTitle('장르 제외 · 숨김');lay=QVBoxLayout(d);checks=[]
        for genre in sorted({g for w in self.works for g in genres(w.genre)}):
            c=QCheckBox(genre);c.setChecked(genre in self.cfg.get('hidden_genres',[]));lay.addWidget(c);checks.append(c)
        def save():
            self.cfg['hidden_genres']=[c.text() for c in checks if c.isChecked()];self.persist_settings();self.filter_changed();d.accept()
        lay.addWidget(button('숨김 설정 저장',save));d.exec()
    def run_queue(self):
        for r in self.queue.rows():
            if r['status']=='stopped':self.queue.change(r['id'],'pending')
        self.batch_ids.update(r['id'] for r in self.queue.rows() if r['status']=='pending')
        self.queue_running=True;self.queue_tick()
    def change_queue(self,id,action):
        r=next((r for r in self.queue.rows() if r['id']==id),None)
        if not r:return
        if action=='priority':self.queue.change(id,priority=max([v['priority'] for v in self.queue.rows()]+[0])+1);return
        if id in self.queue_jobs:
            if action=='pending':self.queue_jobs[id].control.paused.clear();self.queue.change(id,'running');return
            if action=='paused':self.queue_jobs[id].control.paused.set();self.queue.change(id,'paused');return
            self.queue_reasons[id]=action;self.queue_jobs[id].control.stopped.set();self.queue.change(id,action);return
        if action=='pending':self.queue.change(id,'pending',retry_count=0,error='');self.batch_ids.add(id);self.queue_running=True
        else:self.queue.change(id,action)
    def queue_event(self,kind,value,id=None):
        id=self.active_id if id is None else id
        r=next((r for r in self.queue.rows() if r['id']==id),None)
        if r is None:return
        p=r['progress'];p[kind]=value
        if kind in ['plan','current','image_progress','progress','saved','transfer_progress','transfer_wait']:self.queue.change(id,progress=p)
        meter=self.queue_metrics.get(id)
        if meter and kind=='transfer_progress' and id!=self.active_id:meter.record(value)
        if meter and kind=='transfer_wait':meter.pause(bool(value))
        if id==self.active_id:self.on_event(kind,value)
        elif kind=='log':self.logs.appendPlainText(r['work']['title']+' · '+str(value))
    def queue_done(self,kind,result,id=None):
        id=self.active_id if id is None else id;r=next(r for r in self.queue.rows() if r['id']==id)
        reason=self.queue_reasons.get(id)
        if reason:status=reason;error='사용자 요청';result={}
        elif kind=='download':status='partial' if result['failed'] else 'complete';error='';self.logs.appendPlainText(r['work']['title']+' · 다운로드 처리 완료')
        elif kind=='cancelled':status='stopped';error='중단';result={}
        else:status='failed';error=str(result);result={};self.logs.appendPlainText(error)
        self.queue.change(id,status,result=result,error=error)
        if kind=='download':self.accounts_service.record_download(r,result,status)
        if status in ['partial','failed'] and self.cfg.get('retry_once') and r['retry_count']<1 and '연속 3개' not in error:
            self.queue.change(id,'pending',retry_count=r['retry_count']+1);self.logs.appendPlainText(r['work']['title']+' · 실패 항목 재시도 1회')
    def queue_finished(self,id=None):
        id=self.active_id if id is None else id;self.queue_jobs.pop(id,None);self.queue_reasons.pop(id,None)
        self.queue_job=next(iter(self.queue_jobs.values()),None)
        if self.queue_jobs:self.active_id=next(iter(self.queue_jobs));self.download_meter=self.queue_metrics[self.active_id]
        self.queue_reason=None;self.pause_button.setEnabled(bool(self.queue_jobs));self.stop_button.setEnabled(bool(self.queue_jobs))
        self.queue_tick()
    def queue_tick(self):
        if getattr(self,'accounts_dialog_open',False) or self.accounts_service.busy():return
        if self.queue_running and not (self.auto_job and self.auto_job.isRunning()):
            from urllib.parse import urlsplit
            from download_metrics import DownloadMetrics
            def lease(row):return (str(Path(row['cfg']['output_dir']).resolve()),urlsplit(row['work']['url']).path)
            capacity=max(1,min(4,int(self.cfg.get('download_concurrency',2))))
            rows=self.queue.rows();busy={lease(r) for r in rows if r['id'] in self.queue_jobs}
            candidates=[r for r in rows if r['status']=='pending' and lease(r) not in busy]
            for row in candidates:
                if len(self.queue_jobs)>=capacity:break
                if lease(row) in busy:continue
                busy.add(lease(row));id=row['id'];self.queue_reasons.pop(id,None)
                self.queue.change(row['id'],'running',attempts=row['attempts']+1)
                cfg=dict(row['cfg'],network_policy=self.cfg.get('network_policy',{}),policy_file=self.policy_path())
                job=Job('download',cfg,[Work(**row['work'])]);self.queue_jobs[id]=job;self.queue_metrics[id]=DownloadMetrics()
                job.event.connect(lambda kind,value,id=id:self.queue_event(kind,value,id))
                job.done.connect(lambda kind,value,id=id:self.queue_done(kind,value,id));job.finished.connect(lambda id=id:self.queue_finished(id))
                if self.queue_job is None:self.active_id=id;self.queue_job=job;self.download_meter=self.queue_metrics[id];self.transfer_waiting=False
                self.pause_button.setEnabled(True);self.stop_button.setEnabled(True);job.start()
            if not self.queue_jobs and not any(r['status']=='pending' for r in self.queue.rows()):
                rows=[r for r in self.queue.rows() if r['id'] in self.batch_ids]
                complete=any(r['status'] in ['complete','partial','failed'] for r in rows) and all(r['status'] in ['complete','partial','failed','cancelled'] for r in rows)
                self.queue_running=False
                if complete:self.queue_running=False;self.status.setText('대기열 완료 · 보관함에서 실패 항목 확인')
                else:self.status.setText('대기열 중단·보류 · 재개할 작품을 선택하세요')
                if complete and self.power.due(True):self.execute_power()
                if complete:
                    with self.auto_store.db() as db:db.execute("DELETE FROM settings WHERE key='cleanup_stamp'")
                    self.auto_last_check=0;QTimer.singleShot(1000,self.automation_tick)
        if self.power.spec.get('trigger')!='complete' and self.power.due(False):self.execute_power()
        if self.power.issued:
            import time
            self.status.setText(f'PC 종료까지 {max(0,int(self.power.fire_at-time.time()))}초 · 종료 예약 메뉴에서 취소')
            try:self.power.fire_due()
            except Exception as e:self.power.cancel();QMessageBox.warning(self,'종료 실패',str(e))
    def execute_power(self):
        try:
            if self.queue_jobs:
                self.queue_running=False
                for id in list(self.queue_jobs):self.change_queue(id,'stopped')
            action=self.power.execute()
            if action=='app':
                self.quit_timer=QTimer(self);self.quit_timer.timeout.connect(self.finish_quit);self.quit_timer.start(500)
            elif action:self.status.setText('PC 종료 예약됨 · 60초 안에 종료 예약 메뉴에서 취소 가능')
        except Exception as e:QMessageBox.warning(self,'종료 예약',str(e))
    def finish_quit(self):
        if self.job and self.job.isRunning():self.job.control.stopped.set();return
        if self.update_job and self.update_job.isRunning():return
        if self.queue_job:return
        self.quit_timer.stop();self.close()
    def power_description(self):
        if self.power.issued:return 'PC 종료 대기 중 · 예약 취소 가능'
        if not self.power.armed:return '종료 예약 꺼짐'
        return '예약 켜짐 · '+{'complete':'대기열 완료 후','timer':str(self.power.spec.get('minutes'))+'분 후','at':'지정 시각'}[self.power.spec['trigger']]
    def check_updates(self):
        if self.update_job and self.update_job.isRunning():return
        from control_ui import Task
        from sharing import releases,community,version_tuple
        def check():
            repo=self.cfg.get('community_repo',REPOSITORY)
            return {'releases':releases(repo),'community':community(repo)}
        self.update_job=Task(check);self.update_job.done.connect(self.update_result);self.update_job.start()
    def update_result(self,ok,value):
        if not ok:self.update_button.setText('v'+VERSION+' · 확인 실패 · 다시 확인');return
        from sharing import version_tuple
        self.community_cache=value['community'];self.render()
        rows=[r for r in value['releases'] if not r.get('draft') and not r.get('prerelease')]
        self.update_rows=rows
        newer=[]
        for row in rows:
            try:
                if version_tuple(row['tag_name'])>version_tuple(VERSION):newer.append(row)
            except ValueError:pass
        if newer:
            self.latest_release=max(newer,key=lambda r:version_tuple(r['tag_name']))
            self.update_button.setText('새 업데이트 '+self.latest_release['tag_name']+' · '+self.latest_release.get('published_at','')[:10])
            self.update_button.setToolTip(self.latest_release.get('body') or '')
        else:self.update_button.setText('v'+VERSION+' · 최신 버전')

    def set_page_nav(self,library):
        for widget,active in [(self.catalog_nav,not library),(self.library_nav,library)]:
            widget.setObjectName('activeNav' if active else 'nav');widget.style().unpolish(widget);widget.style().polish(widget)
    def apply_theme(self,value,persist=True):
        value=themes.key(value);self.cfg['theme']=value;themes.apply(QApplication.instance(),value)
        if getattr(self,'offline',None) is not None:self.offline.canvas.update()
        if persist:self.persist_settings()
    def show_catalog(self):
        self.content_stack.setCurrentWidget(self.download_page);self.set_page_nav(False);self.compact_download.setEnabled(True)
        self.apply_view_preferences()
    def show_offline(self):
        if self.auto_job and self.auto_job.isRunning() and getattr(self,'auto_action','')=='cleanup':QMessageBox.information(self,'자동 정리 중','정리가 끝난 뒤 라이브러리를 여세요.');return
        self.compact_download.setEnabled(False)
        from reading_ui import OfflineLibrary
        if getattr(self,'offline',None) is None:
            self.offline=OfflineLibrary(self);self.content_stack.addWidget(self.offline)
        self.content_stack.setCurrentWidget(self.offline)
        self.apply_view_preferences()
        self.set_page_nav(True)
        if not self.offline.rows or self.offline.root!=Path(self.path.text()).expanduser().resolve():self.offline.refresh()
    def opencomic_path(self):
        configured=self.cfg.get('opencomic_exe','')
        bundled=APP_DIR/'Vendor'/'OpenComic'/'OpenComic.exe'
        return configured if configured and Path(configured).is_file() else str(bundled) if bundled.is_file() else ''
    def reader_settings(self):
        from preferences_ui import SettingsCenter
        SettingsCenter(self,1).exec()

    def refresh_speed(self):
        if self.automation_closed:return
        from download_metrics import duration
        from library import size_text
        active=self.queue_job or (self.job if self.job and self.job.kind=='download' else None)
        self.download_meter.pause(bool(active and (active.control.paused.is_set() or getattr(self,'transfer_waiting',False))))
        value=self.download_meter.snapshot()
        if active:self.speed_label.setText('허용 다운로드 시간까지 대기' if getattr(self,'transfer_waiting',False) else '일시정지 · 예상 시간 대기' if value['paused'] else f"실효 속도 {size_text(value['speed'])}/초\n현재 작품 예상 남은 시간 {duration(value['remaining'])}")
        else:self.speed_label.setText('속도 — · 다운로드 대기 중')
        if not self.queue_jobs:self.active_downloads.setText('진행 중인 작품 없음');return
        rows={r['id']:r for r in self.queue.rows()}
        lines=[]
        for id,job in self.queue_jobs.items():
            meter=self.queue_metrics.get(id);row=rows.get(id,{})
            if meter:
                meter.pause(job.control.paused.is_set() or bool(row.get('progress',{}).get('transfer_wait')));snapshot=meter.snapshot();percent=snapshot.get('percent');lines.append(row.get('work',{}).get('title','')+f" · {str(percent)+'%' if percent is not None else '준비 중'}")
        self.active_downloads.setText('\n'.join(lines) or '진행 중인 작품 없음')

    def set_view_preference(self,key,value):
        if key=='reader_background':
            if value and not QColor(value).isValid():raise ValueError('배경색을 확인하세요.')
            value=QColor(value).name() if value else ''
        self.cfg[key]=value;self.persist_settings();self.apply_view_preferences()

    def automation_dialog(self):
        from automation_ui import AutomationDialog
        AutomationDialog(self).exec()

    def open_network_settings(self):
        from automation_ui import AutomationDialog
        dialog=AutomationDialog(self);dialog.tabs.setCurrentIndex(2);dialog.exec()

    def download_dashboard(self):
        from progress_ui import QueueDashboard
        QueueDashboard(self).exec()

    def enqueue_works(self,works,cfg=None):
        cfg=cfg or self.read_cfg();ids=self.queue.add(works,cfg);self.batch_ids.update(ids);self.queue_running=True;self.queue_tick();return ids

    def toggle_favorite(self,work):
        current=self.collection_store.get(work) or {};self.collection_store.update(work,favorite=not current.get('favorite'));self.render()
        pane=getattr(self,'offline',None)
        if pane:pane.render()

    def work_settings(self,work):
        from notifications_ui import WorkSettingsDialog
        dialog=WorkSettingsDialog(self,work)
        if dialog.exec():self.render();self.refresh_taxonomy()
        pane=getattr(self,'offline',None)
        if pane:pane.render()

    def notifications(self):
        from notifications_ui import NotificationsDialog
        NotificationsDialog(self).exec()

    def refresh_notifications(self):
        self.notification_button.setText('새 회차 '+str(self.collection_store.unread_count()))

    def check_episode_updates(self):
        if self.automation_closed or not self.cfg.get('notifications_enabled') or (self.notification_job and self.notification_job.isRunning()):return
        if self.auto_job and self.auto_job.isRunning():return
        from collections_store import check_updates
        from library_ui import LibraryTask
        try:cfg=self.read_cfg()
        except ValueError:return
        store=self.collection_store;automatic=self.auto_store
        self.notification_job=LibraryTask(lambda c,e:check_updates(store,automatic,cfg,c,e))
        def done(state,value):
            self.refresh_notifications()
            if state=='success' and value['added']:self.status.setText(f"새 회차 {value['added']}개 · 알림에서 확인하세요")
        self.notification_job.done.connect(done);self.notification_job.start()

    def accounts(self):
        from account_ui import AccountDialog
        if self.accounts_service.busy():self.status.setText('계정 동기화 중 · 잠시 후 다시 열어주세요');return
        AccountDialog(self).exec()

    def account_snapshot(self):return self.accounts_service.snapshot()
    def account_apply(self,payload):self.accounts_service.apply(payload)
    def account_signed_out(self):self.accounts_service.signed_out()
    def account_can_switch(self):self.accounts_service.assert_switchable()
    def account_import_local(self):self.accounts_service.import_local()
    def account_set_device(self,label):self.accounts_service.set_device(label)
    def account_import_works(self,works):
        from collections_store import as_work
        known={w.url for w in self.works}
        for value in works:
            work=as_work(value);self.collection_store.update(work)
            if work.url not in known:self.works.append(work);known.add(work.url)
        self.render();self.refresh_taxonomy();self.status.setText('조회 작품을 목록에 추가했습니다. 체크 후 다운로드할 수 있습니다.')
    def account_apply_labels(self,labels):
        keys=['catalog','library','archive','downloads','automatic','power','community','sites','settings','folder']
        original=getattr(self,'original_sidebar_names',None)
        if original is None:self.original_sidebar_names=[text for _,text in self.sidebar_buttons];original=self.original_sidebar_names
        self.sidebar_buttons=[(widget,(original[i].strip()[0]+'   '+labels[keys[i]]) if i<len(keys) and keys[i] in labels else original[i]) for i,(widget,_) in enumerate(self.sidebar_buttons)]
        self.set_menu_compact(self.cfg.get('menu_compact',False),False)

    def cleanup_busy(self):
        pane=getattr(self,'offline',None)
        if self.queue_job or (self.job and self.job.isRunning()) or (pane and pane.stack.currentIndex()==1):return True
        return any(w.__class__.__name__=='LibraryDialog' and w.isVisible() for w in QApplication.topLevelWidgets())

    def automation_action(self,action,scope='selected'):
        if self.auto_job and self.auto_job.isRunning():return
        if action=='cleanup' and self.cleanup_busy():self.auto_notice='뷰어·다운로드·내보내기 사용 중 · 자동 정리 보류';return
        try:cfg=self.read_cfg()
        except ValueError as e:self.auto_notice=str(e);return
        from library_ui import LibraryTask
        from automation_store import enqueue_occurrences,local_now
        from retention import plan_cleanup,apply_cleanup
        from core import Work
        store=self.auto_store;queue=self.queue;root=Path(cfg['output_dir']);entries=store.chosen(scope)
        self.auto_action=action
        def operation(control,emit):
            if action=='due':return ('queue',enqueue_occurrences(store,queue,cfg))
            if action=='enqueue':
                ids=[];slot='manual:'+local_now().isoformat()
                for item in store.payload(cfg,scope,slot):control.check();ids+=queue.add([Work(**item['work'])],item['cfg'])
                store.log(f'수동 업데이트 · {len(ids)}개 대기열 등록');return ('queue',ids)
            plan=plan_cleanup(root,entries)
            if action=='preview':return ('preview',plan)
            # External readers may keep image files open even after leaving the library.
            if os.name=='nt':
                import subprocess
                active=subprocess.run(['powershell','-NoProfile','-Command','@(Get-Process OpenComic -ErrorAction SilentlyContinue).Count'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
                if active.returncode or active.stdout.strip()!='0':return ('held','OpenComic 사용 중 · 정리 보류')
            result=apply_cleanup(root,plan,control,emit) if plan else dict(deleted=0,bytes=0,errors=[])
            from library import size_text
            text=f"자동 정리 · 이미지 {result['deleted']}개 · {size_text(result['bytes'])} · 보존/오류 {len(result['errors'])}건"
            store.log(text+('\n'+'\n'.join(result['errors'][:20]) if result['errors'] else ''))
            with store.db() as db:db.execute("INSERT OR REPLACE INTO settings VALUES('cleanup_stamp',?)",(local_now().strftime('%Y-%m-%d %H'),))
            return ('cleaned',text)
        self.auto_job=LibraryTask(operation);self.auto_job.event.connect(lambda k,v:self.logs.appendPlainText(str(v)) if k=='log' else None)
        def done(state,result):
            if state!='success':
                self.auto_notice='자동 목록 처리 '+('중단' if state=='cancelled' else '실패 · '+str(result));store.log(self.auto_notice,'failed');return
            kind,data=result
            if kind=='queue':
                self.batch_ids.update(data)
                if data:self.queue_running=True
                self.auto_notice=f'자동 목록 · {len(data)}개 작품 대기열 등록'
            elif kind=='preview':
                from library import size_text
                parent=QApplication.activeModalWidget() or self
                dialog=QDialog(parent);dialog.setWindowTitle('자동 정리 대상 · 미리보기');dialog.resize(750,500);layout=QVBoxLayout(dialog)
                layout.addWidget(QLabel(f"{len(data)}회차 · 기록 용량 {size_text(sum(e['bytes'] for e in data))} · 이 화면에서는 삭제하지 않습니다."))
                box=QPlainTextEdit();box.setReadOnly(True);box.setPlainText('\n'.join(e['title']+' / '+e['episode']+' / '+size_text(e['bytes']) for e in data) or '정리할 회차가 없습니다.');layout.addWidget(box);layout.addWidget(button('닫기',dialog.accept));dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.show();self.auto_preview=dialog
            else:self.auto_notice=str(data)
            self.logs.appendPlainText(self.auto_notice)
        self.auto_job.done.connect(done);self.auto_job.finished.connect(self.queue_tick);self.auto_job.start()

    def automation_tick(self):
        import time
        from automation_store import local_now,minute
        if self.automation_closed or getattr(self,'accounts_dialog_open',False) or self.accounts_service.busy():return
        if self.power.issued:return
        if time.monotonic()-self.auto_last_check<30 or (self.auto_job and self.auto_job.isRunning()):return
        if self.update_job and self.update_job.isRunning():return
        if any(w.__class__.__name__=='UpdatesDialog' and w.isVisible() for w in QApplication.topLevelWidgets()):return
        self.auto_last_check=time.monotonic();schedule=self.auto_store.schedule()
        # Prepared occurrences are recovered even after an interrupted registration.
        with self.auto_store.db() as db:
            prepared=db.execute("SELECT 1 FROM runs WHERE status='prepared' LIMIT 1").fetchone();stamp=db.execute("SELECT value FROM settings WHERE key='cleanup_stamp'").fetchone()
        now=local_now()
        target=now.replace(hour=minute(schedule['time'])//60,minute=minute(schedule['time'])%60,second=0,microsecond=0)
        with self.auto_store.db() as db:claimed=db.execute('SELECT 1 FROM runs WHERE slot=?',(target.isoformat(),)).fetchone()
        if prepared or (not claimed and schedule['enabled'] and now.weekday() in schedule['days'] and now>=target and schedule.get('activated','')<=target.isoformat()):
            self.automation_action('due',schedule['scope']);return
        if schedule.get('cleanup') and not self.cleanup_busy() and (not stamp or stamp[0]!=now.strftime('%Y-%m-%d %H')):
            self.automation_action('cleanup',schedule['scope'])

    def apply_view_preferences(self):
        pane=getattr(self,'offline',None)
        reading=bool(pane and self.content_stack.currentWidget()==pane and pane.stack.currentIndex()==1 and self.cfg.get('reader_mode','embedded')=='embedded')
        focused=reading and self.cfg.get('reader_focus',False)
        self.app_toolbar.setVisible(not focused);self.sidebar.setVisible(not focused)
        if pane:pane.apply_preferences(reading)


def main():
    if '--apply-update' in sys.argv:
        from patch_update import run_helper
        index=sys.argv.index('--apply-update')
        return run_helper(sys.argv[index+1]) if len(sys.argv)>index+1 else 1
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    if '--capture' in sys.argv:
        target = APP_DIR / 'preview.png'
        QTimer.singleShot(900, lambda: (window.grab().save(str(target)), app.quit()))
    if ('--self-test' in sys.argv or '--self-test-403' in sys.argv) and window.works:
        def begin_test():
            window.path.setText(str(APP_DIR / 'validation_downloads'))
            regression = '--self-test-403' in sys.argv
            window.start.setValue(23 if regression else 1)
            window.end.setValue(24 if regression else 1)
            work = next((w for w in window.works if '/18684.html' in w.url), window.works[0]) if regression else window.works[0]
            window.selected.add(work.url)
            window.render()
            window.start_download()
            def complete(kind, value):
                if kind == 'download':
                    window.cover_timer.stop()
                    window.grab().save(str(APP_DIR / 'download_preview.png'))
                    (STATE / 'packaged_validation.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
                    QTimer.singleShot(100, app.quit)
            window.job.done.connect(complete)
        QTimer.singleShot(200, begin_test)
        QTimer.singleShot(90000, app.quit)
    if '--self-test-mobile' in sys.argv:
        def begin_mobile_test():
            from library_ui import LibraryDialog,LibraryTask
            from library import export_mobile,size_text
            window.path.setText(str(APP_DIR/'validation_downloads'))
            dialog=LibraryDialog(window)
            window.mobile_dialog=dialog
            dialog.show()
            def continue_mobile_test():
                if dialog.task and dialog.task.isRunning():
                    QTimer.singleShot(50,continue_mobile_test);return
                finish_mobile_test(dialog)
            QTimer.singleShot(50,continue_mobile_test)
        def finish_mobile_test(dialog):
            from library_ui import LibraryTask
            from library import export_mobile,size_text
            if not dialog.rows:
                (STATE/'packaged_v2_error.txt').write_text('검증 자료가 없습니다.',encoding='utf-8')
                app.quit();return
            key=dialog.rows[0]['key']
            dialog.set_column('upload',False)
            assert dialog.episode_table.isColumnHidden(2)
            dialog.set_column('upload',True)
            options={'format':'cbz','group':'publisher','optimize':True,'width':1200,'quality':85}
            task=LibraryTask(lambda c,e:export_mobile(APP_DIR/'validation_downloads',[key],APP_DIR/'validation_exports',options,c,e))
            window.mobile_job=task
            task.event.connect(dialog.on_event)
            def complete(state,result):
                if state=='success':
                    dialog.activity.setText(f"내보내기 완료 · {result['image_count']}장 · 원본 {size_text(result['source_bytes'])} → 결과 {size_text(result['output_bytes'])}")
                    report={'result':result,'works':dialog.work_table.rowCount(),'episodes':dialog.episode_table.rowCount(),
                            'upload_date':dialog.episode_table.item(0,2).text(),
                            'download_date':dialog.episode_table.item(0,3).text(),
                            'size':dialog.episode_table.item(0,6).text(),'columns_verified':True}
                    (STATE/'packaged_v2_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                    dialog.grab().save(str(APP_DIR/'library_preview_v2.png'))
                else:
                    (STATE/'packaged_v2_error.txt').write_text(str(result),encoding='utf-8')
                QTimer.singleShot(100,app.quit)
            task.done.connect(complete);task.start()
        QTimer.singleShot(200,begin_mobile_test)
        QTimer.singleShot(90000,app.quit)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
