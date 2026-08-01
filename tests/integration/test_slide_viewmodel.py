"""SlideViewModel 集成测试（ViewModel 接线，无真实文件 IO）。

用 SyncTaskRunner + CollectingEmitter + Fake 适配器，验证：
  - UI 命令（extract/generate）→ core service → 事件 → Qt 信号 的单向数据流
  - 后台异常经 on_async_error 转发为失败信号
"""
import sys
import unittest

from PySide6.QtWidgets import QApplication

from shared.contracts import (
    EventType, ExtractQuestionsRequest, GeneratePptxRequest,
)
from core.services.slide_builder import ExtractionServiceImpl, PptxServiceImpl
from ui.viewmodels.slide_viewmodel import SlideViewModel


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


class FakeDocumentLoader:
    def __init__(self, paragraphs):
        self._paragraphs = list(paragraphs)
        self.calls = []

    def load_paragraphs(self, path):
        self.calls.append(path)
        return list(self._paragraphs)


class FakePptxWriter:
    def __init__(self):
        self.calls = []

    def build(self, template_path, questions, font_name, font_size, output_path,
              line_spacing, first_line_indent, on_progress):
        total = len(questions)
        for i in range(total):
            if on_progress:
                on_progress(i + 1, total)
        return total * 2


PARAGRAPHS = ["1. 题目一", "A. 选项一", "B. 选项二"]


class SlideViewModelTests(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self.emitter = CollectingEmitter()
        self.runner = SyncTaskRunner()
        extraction = ExtractionServiceImpl(FakeDocumentLoader(PARAGRAPHS), self.emitter)
        pptx = PptxServiceImpl(FakePptxWriter(), self.emitter)
        self.vm = SlideViewModel(extraction, pptx, self.runner, self.emitter)
        self.extracted = []
        self.vm.extracted.connect(lambda r: self.extracted.append(r))
        self.progress = []
        self.vm.pptx_progress.connect(lambda m, c, t: self.progress.append((m, c, t)))
        self.failed = []
        self.vm.pptx_failed.connect(lambda m: self.failed.append(m))

    def test_extract_forwards_event_to_signal(self):
        self.vm.extract(ExtractQuestionsRequest(doc_path="x.docx"))
        self.assertEqual(len(self.extracted), 1)
        self.assertEqual(self.extracted[0].questions[0][0], "1. 题目一")

    def test_generate_forwards_progress_and_completed(self):
        self.vm.generate(
            GeneratePptxRequest(
                template_path="t.pptx",
                questions=[["1. x", "A. a"]],
                font_name="Arial", font_size=18, output_path="o.pptx",
            )
        )
        self.assertTrue(self.progress, "应收到进度信号")
        self.assertEqual(self.failed, [])

    def test_error_forwards_to_failed_signal(self):
        # 同路径 → OutputOverwriteError → on_async_error → pptx_failed
        self.vm.generate(
            GeneratePptxRequest(
                template_path="same.pptx",
                questions=[["1. x", "A. a"]],
                font_name="Arial", font_size=18, output_path="same.pptx",
            )
        )
        self.assertEqual(len(self.failed), 1)
        self.assertIn("相同", str(self.failed[0]))


if __name__ == "__main__":
    unittest.main()
