"""PdfWordViewModel 集成测试（ViewModel 接线，无真实文件 IO）。

用 SyncTaskRunner + CollectingEmitter + Fake 适配器，验证：
  - UI 命令（convert）→ core service → 事件 → Qt 信号 的单向数据流
  - 后台异常经 on_async_error 转发为 failed 信号
"""
import sys
import unittest

from PySide6.QtWidgets import QApplication

from core.services.pdf_word_service import PdfWordServiceImpl
from shared.contracts import ConvertPdfToWordRequest, ConvertPdfToWordResult
from ui.viewmodels.pdf_word_viewmodel import PdfWordViewModel


class CollectingEmitter:
    def __init__(self):
        self.events = []
        self._handlers = []

    def emit(self, event):
        self.events.append(event)
        for h in self._handlers:
            h(event)

    def on_event(self, handler):
        self._handlers.append(handler)


class SyncTaskRunner:
    def submit(self, func, *, args=(), kwargs=None, on_progress=None,
               on_result=None, on_error=None):
        try:
            result = func(*args, **(kwargs or {}))
            if on_result:
                on_result(result)
            return None
        except Exception as exc:
            if on_error:
                on_error(exc)
            return None


class FakePdfWordConverter:
    def convert(self, request, on_progress):
        for i in range(2):
            on_progress(i + 1, 2)
        return ConvertPdfToWordResult(
            output_path=request.output_path, page_count=2,
            paragraph_count=5, run_count=10, empty_pages=[],
        )


class PdfWordViewModelTests(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self.emitter = CollectingEmitter()
        self.runner = SyncTaskRunner()
        svc = PdfWordServiceImpl(FakePdfWordConverter(), self.emitter)
        self.vm = PdfWordViewModel(svc, self.runner, self.emitter)
        self.progress = []
        self.vm.progress.connect(lambda m, c, t: self.progress.append((m, c, t)))
        self.completed = []
        self.vm.completed.connect(lambda r: self.completed.append(r))
        self.failed = []
        self.vm.failed.connect(lambda m: self.failed.append(m))

    def _req(self, **overrides):
        base = dict(
            pdf_path="in.pdf", template_path="", output_path="out.docx"
        )
        base.update(overrides)
        return ConvertPdfToWordRequest(**base)

    def test_convert_forwards_progress_and_completed(self):
        self.vm.convert(self._req())
        self.assertTrue(self.progress, "应收到进度信号")
        self.assertEqual(len(self.completed), 1)
        self.assertEqual(self.completed[0].page_count, 2)
        self.assertEqual(self.failed, [])

    def test_progress_signal_carries_page_info(self):
        self.vm.convert(self._req())
        page_progress = [p for p in self.progress if p[2] == 2]
        self.assertEqual([p[1] for p in page_progress][:2], [1, 2])

    def test_error_forwards_to_failed_signal(self):
        # 同路径 → OutputOverwriteError → on_async_error → failed
        self.vm.convert(self._req(template_path="same.docx", output_path="same.docx"))
        self.assertEqual(len(self.failed), 1)
        self.assertIn("相同", str(self.failed[0]))
        self.assertEqual(self.completed, [])


if __name__ == "__main__":
    unittest.main()
