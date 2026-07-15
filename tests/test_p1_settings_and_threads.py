"""P1 #4（阈值配置化）与 P1 #5（线程管理）的回归测试（阶段4 迁移版）。

#4 阈值接线：用 SimilarityServiceImpl + 注入的 FakeLoader，分别以「低于真实
    相似度」与「高于真实相似度」的阈值跑同一次查重，断言 duplicate_count 随
    阈值变化 —— 证明阈值已接线、非硬编码 0.8。（纯 core，无需 Qt）

#5 线程管理：验证新架构的异步框架
    - QtTaskRunner.submit 把同步函数放到后台线程执行，结果经 on_result 回传、
      异常经 on_error 回传，且不阻塞调用线程；
    - SimilarityViewModel 经 QtTaskRunner 调用 service，service 抛出的异常被
      on_async_error 桥接为 failed 信号（单向数据流：core → UI）；
    - View/ViewModel 的 cancel_current 在「无任务」时不崩溃。

阈值持久化（P1#4 的另一半）：SimilarityView 通过 QSettings 保存/读取
阈值/题号格式/选项前缀，重置按钮恢复默认值。
"""
import sys
import time
import unittest
from unittest.mock import MagicMock

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


def _pump(until, timeout: float = 3.0, interval: float = 0.01) -> None:
    """轮询条件期间泵送 Qt 事件循环，使跨线程 QueuedConnection 信号得以分发。

    QtTaskRunner 的 worker 通过 Qt 信号回传结果/异常（跨线程 → QueuedConnection），
    只有在事件循环被泵送时才会投递；测试不运行 QApplication 事件循环，故需手动
    processEvents，否则 on_result/on_error/failed 等回调永远不会触发。
    """
    app = QApplication.instance()
    elapsed = 0.0
    while not until() and elapsed < timeout:
        if app is not None:
            app.processEvents()
        time.sleep(interval)
        elapsed += interval

from shared.contracts import (
    EventType, SimilarityMode, SimilarityRequest, SimilarityResult,
)
from core.ports.io import DocumentLoader
from core.services.similarity_service import SimilarityServiceImpl
from core.ports.events import EventEmitter


# ── 无 Qt 的收集型 emitter（core 测试用） ──
class _CollectingEmitter(EventEmitter):
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def on_event(self, handler):
        self._handler = handler


def _qa():
    return ["1. 下列哪个是 Python 关键字？", "A. class", "B. def",
            "C. if", "D. all of the above"]


def _qb():
    # 与 q_a 共享 "def" 选项，但题干与其它选项不同 —— 相似但不相同（0 < s < 1）
    return ["3. Python 中用于定义函数的关键字是？", "A. func", "B. def",
            "C. lambda", "D. function"]


class _FakeLoader(DocumentLoader):
    def __init__(self, mapping):
        self._mapping = mapping

    def load_paragraphs(self, path):
        return self._mapping[path]


class P1ThresholdTests(unittest.TestCase):
    """证明判定阈值是 request.threshold，而非硬编码 0.8。"""

    def _service(self, loader):
        return SimilarityServiceImpl(loader, _CollectingEmitter())

    def test_threshold_is_wired_not_hardcoded(self):
        q_a, q_b = _qa(), _qb()
        # 先用服务算出真实相似度：构造一次查重拿到 score
        loader0 = _FakeLoader({
            "main.docx": list(q_a),
            "sec.docx": list(q_b),
        })
        svc0 = self._service(loader0)
        res0 = svc0.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY, main_path="main.docx",
            secondary_paths=["sec.docx"], threshold=0.0,
        ))
        # threshold=0 必命中，取 detail 的 score 作为真实相似度 s
        s = res0.details[0].sources[0].score
        self.assertGreater(s, 0.0)
        self.assertLess(s, 1.0)

        low = s * 0.5                       # 低于真实相似度 → 应命中
        high = s + (1.0 - s) * 0.5          # 高于真实相似度且 < 1.0 → 应不命中

        loader = _FakeLoader({
            "main.docx": list(q_a),
            "sec.docx": list(q_b),
        })
        svc = self._service(loader)

        low_res = svc.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY, main_path="main.docx",
            secondary_paths=["sec.docx"], threshold=low,
        ))
        high_res = svc.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY, main_path="main.docx",
            secondary_paths=["sec.docx"], threshold=high,
        ))

        self.assertEqual(low_res.duplicate_count, 1,
                         f"阈值 {low:.3f}（< 相似度 {s:.3f}）应命中重复")
        self.assertEqual(high_res.duplicate_count, 0,
                         f"阈值 {high:.3f}（> 相似度 {s:.3f}）不应命中重复")


class P1ThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication(sys.argv)
        else:
            cls._app = QApplication.instance()

    def test_qt_task_runner_runs_off_thread(self):
        from ui.infra.qt_task_runner import QtTaskRunner
        import threading

        runner = QtTaskRunner()
        caller_thread = threading.current_thread().name
        seen = {}
        captured = {}

        def work():
            seen["thread"] = threading.current_thread().name
            return 42

        handle = runner.submit(
            work, on_result=lambda r: captured.update(result=r),
            on_error=lambda e: captured.update(error=e),
        )
        _pump(lambda: "result" in captured)
        handle.join()  # 确保线程终止后再让句柄释放

        self.assertEqual(captured.get("result"), 42)
        self.assertNotEqual(seen.get("thread"), caller_thread)

    def test_qt_task_runner_forwards_error(self):
        from ui.infra.qt_task_runner import QtTaskRunner
        import time

        runner = QtTaskRunner()
        captured = {}

        def boom():
            raise RuntimeError("boom")

        handle = runner.submit(boom, on_error=lambda e: captured.update(error=e))
        _pump(lambda: "error" in captured)
        handle.join()  # 确保后台线程终止后再释放句柄，避免 SIGABRT
        self.assertEqual(str(captured.get("error")), "boom")

    def test_viewmodel_forwards_service_error_to_failed(self):
        from core.di import Container
        from ui.infra.qt_task_runner import QtTaskRunner
        from ui.infra.qt_event_emitter import QtEventEmitter
        from ui.viewmodels.similarity_viewmodel import SimilarityViewModel
        import time

        runner = QtTaskRunner()
        emitter = QtEventEmitter()
        container = Container.build(task_runner=runner, event_emitter=emitter)
        vm = SimilarityViewModel(container.resolve("similarity"), runner, emitter)

        failed = []
        vm.failed.connect(lambda m: failed.append(m))

        # 主文档解析不到题目 → 服务抛 NoQuestionsExtracted → 桥接为 failed
        req = SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY, main_path="__missing__.docx",
            secondary_paths=["__missing__.docx"], threshold=0.8,
        )
        handle = vm.check(req)
        _pump(lambda: bool(failed))
        handle.join()  # 确保后台线程终止，避免句柄释放时线程仍在运行
        self.assertTrue(failed, "service 异常应桥接为 failed 信号")

    def test_cancel_current_when_no_task_is_noop(self):
        from core.di import Container
        from ui.infra.qt_task_runner import QtTaskRunner
        from ui.infra.qt_event_emitter import QtEventEmitter
        from ui.viewmodels.similarity_viewmodel import SimilarityViewModel

        runner = QtTaskRunner()
        emitter = QtEventEmitter()
        container = Container.build(task_runner=runner, event_emitter=emitter)
        vm = SimilarityViewModel(container.resolve("similarity"), runner, emitter)
        # 无任务时取消不应崩溃
        vm.cancel_current()


class P1SettingsPersistenceTests(unittest.TestCase):
    """SimilarityView 通过 QSettings 持久化阈值/题号格式/选项前缀。"""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication(sys.argv)
        else:
            cls._app = QApplication.instance()
        # 隔离 QSettings：macOS 的 NativeFormat 会忽略 setPath/setDefaultFormat，
        # 且会写入真实用户 plist（~/Library/Preferences/...），污染用户配置并导致
        # 跨运行残留。这里把 similarity_view 模块中的 QSettings 替换为强制
        # IniFormat + 临时目录的子类，确保测试完全隔离。
        import tempfile
        from ui.views import similarity_view
        cls._settings_dir = tempfile.mkdtemp(prefix="simview_settings_")
        real_qsettings = QSettings

        class _IsolatedQSettings(real_qsettings):
            def __init__(self, *args, **kwargs):
                if args or kwargs:
                    org = args[0] if len(args) > 0 else kwargs.get("organization")
                    app = args[1] if len(args) > 1 else kwargs.get("application")
                    super().__init__(
                        real_qsettings.Format.IniFormat,
                        real_qsettings.Scope.UserScope,
                        org, app,
                    )
                else:
                    super().__init__(
                        real_qsettings.Format.IniFormat,
                        real_qsettings.Scope.UserScope,
                    )

        real_qsettings.setPath(
            real_qsettings.Format.IniFormat,
            real_qsettings.Scope.UserScope,
            cls._settings_dir,
        )
        cls._RealQSettings = real_qsettings
        cls._IsolatedQSettings = _IsolatedQSettings
        similarity_view.QSettings = _IsolatedQSettings

    @classmethod
    def tearDownClass(cls):
        import shutil
        from ui.views import similarity_view
        similarity_view.QSettings = cls._RealQSettings
        shutil.rmtree(cls._settings_dir, ignore_errors=True)

    def _make_view(self):
        from core.di import Container
        from ui.infra.qt_task_runner import QtTaskRunner
        from ui.infra.qt_event_emitter import QtEventEmitter
        from ui.viewmodels.similarity_viewmodel import SimilarityViewModel
        from ui.views.similarity_view import SimilarityView

        runner = QtTaskRunner()
        emitter = QtEventEmitter()
        container = Container.build(task_runner=runner, event_emitter=emitter)
        vm = SimilarityViewModel(container.resolve("similarity"), runner, emitter)
        return SimilarityView(vm)

    def _clear_settings(self):
        s = self._make_view().settings
        s.clear()
        s.sync()

    def test_defaults_loaded_when_no_stored_value(self):
        self._clear_settings()
        view = self._make_view()
        try:
            self.assertAlmostEqual(view._threshold_spin.value(), 0.8, places=2)
            self.assertEqual(view._num_edit.text(), "1.")
            self.assertEqual(view._opt_edit.text(), "A.")
        finally:
            view.deleteLater()
            self._clear_settings()

    def test_save_then_read_roundtrip(self):
        self._clear_settings()
        view = self._make_view()
        try:
            view._threshold_spin.setValue(0.95)
            view._num_edit.setText("2.")
            view._opt_edit.setText("B.")
            view._save_settings()

            s = view.settings
            self.assertAlmostEqual(float(s.value("threshold")), 0.95, places=2)
            self.assertEqual(s.value("num_pattern"), "2.")
            self.assertEqual(s.value("opt_prefix"), "B.")
        finally:
            view.deleteLater()
            self._clear_settings()

    def test_reset_restores_defaults(self):
        self._clear_settings()
        view = self._make_view()
        try:
            view._threshold_spin.setValue(0.95)
            view._num_edit.setText("9.")
            view._opt_edit.setText("Z.")
            view._on_reset_settings()
            self.assertAlmostEqual(view._threshold_spin.value(), 0.8, places=2)
            self.assertEqual(view._num_edit.text(), "1.")
            self.assertEqual(view._opt_edit.text(), "A.")
        finally:
            view.deleteLater()
            self._clear_settings()


if __name__ == "__main__":
    unittest.main()
