"""Shared application palettes; original comic pixels are never recolored."""
from PySide6.QtGui import QColor, QPalette

THEMES={
 'white':('화이트',dict(bg='#f5f5f7',panel='#ffffff',side='#eceef2',text='#1d1d1f',muted='#596579',border='#c7cdd7',accent='#0070df',hover='#e5efff',selected='#d9e9ff',on='#ffffff')),
 'dark':('다크',dict(bg='#14171e',panel='#202630',side='#10141b',text='#f2f5fa',muted='#b0bfd2',border='#526075',accent='#6bb6ff',hover='#303b4e',selected='#294565',on='#102033')),
 'rainbow':('레인보우',dict(bg='#f7f4ff',panel='#ffffff',side='#ede7fa',text='#251b3d',muted='#655177',border='#cdbbdf',accent='#7440c2',hover='#efe2ff',selected='#ead9ff',on='#ffffff')),
 'gray':('회색',dict(bg='#e4e6e9',panel='#f3f4f6',side='#d4d8df',text='#202832',muted='#4b5767',border='#aab2bf',accent='#42566f',hover='#d7dfe9',selected='#c8d4e5',on='#ffffff')),
 'emphasis':('강조형',dict(bg='#090d12',panel='#121c29',side='#05080d',text='#ffffff',muted='#cad4e2',border='#7d94b2',accent='#ffe045',hover='#263b54',selected='#354767',on='#171700')),
}

def key(value):return value if value in THEMES else 'white'
def colors(value):return THEMES[key(value)][1]

def stylesheet(value):
 c=colors(value)
 def css(s):
  for name,color in c.items():s=s.replace('@'+name+'@',color)
  return s
 result=css('''
 QWidget {background:@bg@;color:@text@;font-family:"Malgun Gothic";font-size:12px;}
 QMainWindow,QDialog,QStackedWidget {background:@bg@;color:@text@;}
 QAbstractScrollArea,QAbstractScrollArea > QWidget#qt_scrollarea_viewport {background:@bg@;color:@text@;}
 QTabWidget::pane {background:@panel@;border:1px solid @border@;border-radius:10px;}
 QTabBar::tab {background:@side@;color:@muted@;padding:10px 14px;border:0;}
 QTabBar::tab:selected {background:@panel@;color:@accent@;border-bottom:2px solid @accent@;}
 QScrollBar:vertical {background:@side@;width:12px;border:0;}
 QScrollBar::handle:vertical {background:@border@;min-height:30px;border-radius:6px;}
 QScrollBar:horizontal {background:@side@;height:12px;border:0;}
 QScrollBar::handle:horizontal {background:@border@;min-width:30px;border-radius:6px;}
 QScrollBar::add-line,QScrollBar::sub-line {height:0;width:0;}
 QTextEdit,QDateTimeEdit,QTimeEdit {background:@panel@;color:@text@;border:1px solid @border@;border-radius:8px;padding:6px;}
 QGroupBox {border:1px solid @border@;border-radius:10px;margin-top:12px;padding-top:14px;}
 QGroupBox::title {color:@muted@;subcontrol-origin:margin;left:12px;}
 QMenu {background:@panel@;color:@text@;border:1px solid @border@;}
 QMenu::item:selected {background:@selected@;color:@text@;}
 QTableView,QListView,QTreeView {background:@panel@;alternate-background-color:@side@;color:@text@;selection-background-color:@selected@;selection-color:@text@;}
 QAbstractItemView::item:selected:!active {background:@selected@;color:@text@;}
 QWidget:disabled {color:@muted@;}
 QLabel {background:transparent;}
 QLabel#muted {color:@muted@;}
 QLabel#accent {color:@accent@;}
 QLabel#title {font-size:26px;font-weight:700;}
 QLabel#coverPlaceholder {background:@side@;color:@muted@;border-radius:8px;font-size:30px;}
 QFrame#sidebar {background:@side@;border-right:1px solid @border@;}
 QFrame#panel,QFrame#card {background:@panel@;border:1px solid @border@;border-radius:14px;}
 QFrame#libraryCard {background:@panel@;border:1px solid @border@;border-radius:18px;}
 QFrame#libraryCard QLabel {border:0;}
 QPushButton {background:@panel@;color:@text@;border:1px solid @border@;border-radius:9px;padding:10px 12px;font-weight:600;}
 QPushButton:hover {background:@hover@;border-color:@accent@;}
 QPushButton:disabled {color:@muted@;background:@side@;}
 QPushButton#primary {background:@accent@;color:@on@;border:1px solid @accent@;}
 QPushButton#primary:hover {border:1px solid @text@;}
 QPushButton#nav {text-align:left;border:0;background:transparent;color:@muted@;padding:12px;}
 QPushButton#activeNav {text-align:left;background:@selected@;color:@accent@;border:1px solid @accent@;padding:12px;}
 QPushButton#pageButton {padding:7px 4px;min-width:22px;border-radius:8px;}
 QPushButton#pageButton:checked {background:@accent@;color:@on@;border:1px solid @accent@;}
 QPushButton#pageStep {padding:7px 6px;}
 QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox {background:@panel@;color:@text@;border:1px solid @border@;border-radius:8px;padding:8px;selection-background-color:@selected@;selection-color:@text@;}
 QComboBox QAbstractItemView {background:@panel@;color:@text@;selection-background-color:@selected@;selection-color:@text@;}
 QCheckBox {background:transparent;spacing:8px;}
 QCheckBox::indicator {width:17px;height:17px;background:@panel@;border:1px solid @border@;border-radius:4px;}
 QCheckBox::indicator:checked {background:@accent@;border:1px solid @accent@;}
 QScrollArea {border:0;background:@bg@;}
 QScrollArea > QWidget {background:@bg@;}
 QProgressBar {background:@side@;color:@text@;border:0;border-radius:5px;height:10px;text-align:center;}
 QProgressBar::chunk {background:@accent@;border-radius:5px;}
 QPlainTextEdit {background:@panel@;color:@muted@;border:1px solid @border@;border-radius:8px;padding:8px;font-size:11px;}
 QToolTip {background:@panel@;color:@text@;border:1px solid @border@;padding:6px;}
 QTableWidget {background:@panel@;alternate-background-color:@side@;gridline-color:@border@;border:1px solid @border@;selection-background-color:@selected@;selection-color:@text@;}
 QHeaderView::section {background:@side@;color:@text@;border:0;padding:9px;}
 QTableWidget::item {padding:7px;}
 QSlider::groove:horizontal {background:@border@;height:5px;border-radius:2px;}
 QSlider::sub-page:horizontal {background:@accent@;}
 QSlider::handle:horizontal {background:@accent@;border:1px solid @border@;width:14px;margin:-5px 0;border-radius:7px;}
 ''')
 if key(value)=='rainbow':
  result+='''QPushButton#primary,QProgressBar::chunk {background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #b32852,stop:0.2 #b04f1b,stop:0.4 #426d21,stop:0.6 #006b8b,stop:0.8 #325cc0,stop:1 #843cb1);color:white;}
  QFrame#sidebar {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffe5ed,stop:0.25 #fff0dc,stop:0.5 #e2f6eb,stop:0.75 #e0edff,stop:1 #eee1ff);border-right:3px solid #9261d4;}'''
 return result

def apply(application,value):
 c=colors(value);p=QPalette()
 for role,color in [(QPalette.Window,c['bg']),(QPalette.WindowText,c['text']),(QPalette.Base,c['panel']),
  (QPalette.AlternateBase,c['side']),(QPalette.Text,c['text']),(QPalette.Button,c['panel']),
  (QPalette.ButtonText,c['text']),(QPalette.Highlight,c['selected']),(QPalette.HighlightedText,c['text']),
  (QPalette.ToolTipBase,c['panel']),(QPalette.ToolTipText,c['text']),(QPalette.PlaceholderText,c['muted'])]:p.setColor(role,QColor(color))
 for role in (QPalette.WindowText,QPalette.Text,QPalette.ButtonText,QPalette.PlaceholderText):
  p.setColor(QPalette.Disabled,role,QColor(c['muted']))
 p.setColor(QPalette.Disabled,QPalette.Highlight,QColor(c['side']))
 p.setColor(QPalette.Disabled,QPalette.HighlightedText,QColor(c['muted']))
 application.setPalette(p);application.setStyleSheet(stylesheet(value))
 # Already created native viewports may retain an explicit old palette.
 for widget in application.allWidgets():
  if not widget.property('preserveReaderPalette'):
   widget.setPalette(p)
  widget.update()
