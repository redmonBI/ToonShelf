from pathlib import Path
import sys
from PySide6.QtWidgets import QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHBoxLayout,QMessageBox,QAbstractItemView
from control_ui import TaskDialog,button
from update_storage import list_storage,clear_previous,clean_stage,previous_path
from library import size_text

class UpdateStorageDialog(TaskDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.target=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent/'portable_final'/'ToonShelf';self.setWindowTitle('이전 버전 삭제 · 업데이트 저장 공간');self.resize(800,480)
        lay=QVBoxLayout(self);lay.addWidget(QLabel('업데이트는 같은 프로그램 폴더에 적용하고, 이전 복구본은 한 개만 보관합니다.'))
        note=QLabel('개인 설정·이미지·다운로드 폴더는 삭제하지 않습니다. 복구본을 삭제하면 해당 버전으로 복구할 수 없습니다. 미완료 패치는 보존합니다.');note.setWordWrap(True);lay.addWidget(note)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['항목','버전','용량']);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table,1);self.info=QLabel('저장 공간 확인 중…');lay.addWidget(self.info);row=QHBoxLayout();row.addWidget(button('새로고침',self.refresh));row.addWidget(button('선택한 이전 버전·임시 파일 삭제',self.remove));row.addWidget(button('닫기',self.accept));lay.addLayout(row);self.refresh()
    def refresh(self):
        if any(t.isRunning() for t in self.tasks):return
        self.info.setText('업데이트 저장 공간을 확인하는 중…');self.task(lambda:list_storage(self.target),self.loaded)
    def loaded(self,ok,result):
        if not ok:self.info.setText(str(result));return
        self.rows=result;self.table.setRowCount(len(result))
        for i,r in enumerate(result):
            for c,v in enumerate((r['name'],r['version'],size_text(r['size']))):self.table.setItem(i,c,QTableWidgetItem(v))
        self.info.setText(f'정리 가능한 항목 {len(result)}개 · 합계 {size_text(sum(r["size"] for r in result))}')
    def remove(self):
        if any(t.isRunning() for t in self.tasks):return
        selected=[self.rows[i.row()] for i in self.table.selectionModel().selectedRows()] if hasattr(self,'rows') else []
        if not selected:return
        if QMessageBox.question(self,'이전 버전 삭제','선택한 프로그램 복구본·패치 임시 파일을 삭제할까요? 개인 자료는 유지합니다.')!=QMessageBox.Yes:return
        def work():
            for r in selected:
                p=Path(r['path']);clear_previous(self.target) if p==previous_path(self.target) else clean_stage(p,self.target)
            return list_storage(self.target)
        self.info.setText('이전 버전 파일을 정리하는 중…');self.task(work,self.loaded)
