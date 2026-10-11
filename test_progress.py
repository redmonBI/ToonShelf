import json,os,tempfile,threading,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget,QScrollArea,QTabWidget,QTableWidget
from PySide6.QtGui import QPalette,QColor
from core import Control,Cancelled
from transfer_policy import TransferPolicy
from download_metrics import DownloadMetrics
from progress_ui import progress_percent,finite,Sparkline,QueueDashboard
import themes

class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_fraction_is_bounded_and_unknown_is_indeterminate(self):
        self.assertIsNone(progress_percent({'status':'running','progress':{'image_progress':{'index':2,'total':3}}}))
        self.assertEqual(progress_percent({'status':'running','progress':{'transfer_progress':{'completed':999,'total':10}}}),99)
        self.assertEqual(progress_percent({'status':'complete'}),100)
        self.assertEqual(progress_percent({'status':'running','progress':{'transfer_progress':{'completed':-1,'total':10}}}),0)
    def test_invalid_graph_samples_are_safe(self):
        graph=Sparkline();graph.resize(300,100)
        for value in (float('nan'),float('inf'),-3,None,'invalid',1048576):graph.add(value)
        self.assertTrue(all(v>=0 for v in graph.samples));self.assertEqual(finite(float('nan')),0)
        graph.grab();graph.close()
    def test_metrics_handle_nonfinite_counts(self):
        meter=DownloadMetrics();meter.record({'bytes':float('inf'),'completed':-4,'total':None});snap=meter.snapshot()
        self.assertEqual(snap['bytes'],0);self.assertIsNone(snap['percent']);self.assertEqual(snap['speed'],0)
    def test_palettes_cover_existing_scroll_viewports_and_disabled_text(self):
        widget=QWidget();scroll=QScrollArea(widget);table=QTableWidget(widget);tabs=QTabWidget(widget)
        for name in themes.THEMES:
            themes.apply(self.app,name);c=themes.colors(name)
            self.assertEqual(scroll.viewport().palette().color(QPalette.Window),QColor(c['bg']))
            self.assertEqual(table.palette().color(QPalette.Disabled,QPalette.Text),QColor(c['muted']))
            self.assertIn('QTabBar::tab:selected',self.app.styleSheet())
        widget.close();themes.apply(self.app,'white')
    def test_parallel_workers_share_one_aggregate_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json';path.write_text(json.dumps({'network_policy':{'limit_mib':1}}))
            cfg={'policy_file':str(path)};policies=[TransferPolicy(cfg),TransferPolicy(cfg)]
            self.assertIs(policies[0].budget,policies[1].budget)
            barrier=threading.Barrier(3);errors=[]
            def run(policy):
                try:
                    barrier.wait()
                    for _ in range(4):policy.consume(65536,Control(),lambda *args:None)
                except Exception as exc:errors.append(exc)
            workers=[threading.Thread(target=run,args=(p,)) for p in policies]
            for worker in workers:worker.start()
            start=time.monotonic();barrier.wait()
            for worker in workers:worker.join(5)
            elapsed=time.monotonic()-start
            self.assertFalse(errors);self.assertTrue(all(not w.is_alive() for w in workers));self.assertGreaterEqual(elapsed,.44);self.assertLess(elapsed,3)
    def test_limit_wait_can_be_stopped(self):
        control=Control();control.stopped.set();policy=TransferPolicy({'network_policy':{'limit_mib':1}})
        with self.assertRaises(Cancelled):policy.consume(65536,control,lambda *args:None)
    def test_large_queue_is_paged_and_buttons_target_correct_work(self):
        from unittest.mock import Mock
        host=QWidget();host.cfg={'theme':'dark'};host.queue_metrics={};host.change_queue=Mock();host.run_queue=Mock();host.pause=Mock()
        rows=[{'id':i,'work':{'title':f'Work {i}'},'status':'running' if i==50 else 'pending','priority':0,'cfg':{'output_dir':'example'},'progress':{'transfer_progress':{'completed':4,'total':8}}} for i in range(60)]
        host.queue=Mock();host.queue.rows.return_value=rows;dialog=QueueDashboard(host)
        self.assertEqual(len(dialog.cards),25);self.assertIn(50,dialog.cards);self.assertEqual(dialog.cards[50].bar.value(),50)
        dialog.cards[50].buttons['held'].click();host.change_queue.assert_called_once_with(50,'held')
        dialog.next.click();self.assertEqual(dialog.page,1);self.assertEqual(len(dialog.cards),25)
        dialog.next.click();self.assertEqual(len(dialog.cards),10);self.assertFalse(dialog.next.isEnabled());dialog.reject();host.close()

if __name__=='__main__':unittest.main()
