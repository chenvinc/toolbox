"""PdfWordServiceImpl 单元测试（无 Qt、无真实文件 IO）。

用 FakePdfWordConverter + CollectingEmitter 注入端口，验证：
  - 路径校验（输出 == 模板 / 输出 == 源 PDF 均拒绝）
  - 进度/完成事件推送顺序与内容
  - DI 容器装配
"""
import unittest

from core.di import Container
from core.services.pdf_word_service import PdfWordServiceImpl
from shared.contracts import (
    ConvertPdfToWordRequest, ConvertPdfToWordResult, EventType,
)
from shared.errors import OutputOverwriteError


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
    """实现 PdfWordConverter 端口：模拟 3 页 PDF，逐页回调进度。"""

    def __init__(self, pages=3):
        self._pages = pages
        self.calls = []

    def convert(self, request, on_progress):
        self.calls.append(request)
        for i in range(self._pages):
            on_progress(i + 1, self._pages)
        return ConvertPdfToWordResult(
            output_path=request.output_path,
            page_count=self._pages,
            paragraph_count=12,
            run_count=30,
            empty_pages=[1],
        )


def _req(**overrides):
    base = dict(
        pdf_path="in.pdf", template_path="", output_path="out.docx"
    )
    base.update(overrides)
    return ConvertPdfToWordRequest(**base)


class PdfWordServiceTests(unittest.TestCase):
    def setUp(self):
        self.emitter = CollectingEmitter()
        self.converter = FakePdfWordConverter()
        self.svc = PdfWordServiceImpl(self.converter, self.emitter)

    def test_convert_returns_result_and_calls_converter(self):
        res = self.svc.convert(_req())
        self.assertEqual(res.page_count, 3)
        self.assertEqual(res.paragraph_count, 12)
        self.assertEqual(res.run_count, 30)
        self.assertEqual(res.empty_pages, [1])
        self.assertEqual(len(self.converter.calls), 1)

    def test_convert_emits_progress_and_completed_events(self):
        self.svc.convert(_req())
        types = [e.type for e in self.emitter.events]
        # 准备中 + 3 页进度 + 转换完成 + 完成事件
        self.assertEqual(types.count(EventType.WORD_PROGRESS), 5)
        self.assertEqual(types[-1], EventType.WORD_COMPLETED)
        completed = self.emitter.events[-1]
        self.assertEqual(completed.result.page_count, 3)

    def test_progress_events_carry_page_numbers(self):
        self.svc.convert(_req())
        page_events = [
            e for e in self.emitter.events
            if e.type == EventType.WORD_PROGRESS and e.total == 3
        ]
        self.assertEqual([e.current for e in page_events][:3], [1, 2, 3])

    def test_output_same_as_template_raises(self):
        with self.assertRaises(OutputOverwriteError):
            self.svc.convert(_req(template_path="same.docx", output_path="same.docx"))
        self.assertEqual(self.converter.calls, [])

    def test_output_same_as_pdf_raises(self):
        with self.assertRaises(OutputOverwriteError):
            self.svc.convert(_req(pdf_path="same.docx", output_path="same.docx"))
        self.assertEqual(self.converter.calls, [])

    def test_container_builds_pdf_word_service(self):
        c = Container.build(
            task_runner=SyncTaskRunner(), event_emitter=CollectingEmitter()
        )
        self.assertIsInstance(c.resolve("pdf_word"), PdfWordServiceImpl)


if __name__ == "__main__":
    unittest.main()
