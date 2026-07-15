"""core/services 单元测试（无 Qt、无 python-docx/pptx，全部依赖经 mock 注入）。

验证：
  - ExtractionServiceImpl：解析题目 + 推送 EXTRACT_COMPLETED 事件
  - PptxServiceImpl：生成结果 + 进度/完成事件 + 同路径拒绝（OutputOverwriteError）
  - Container：build 组装出正确的服务实例
"""
import unittest

from shared.contracts import (
    EventType, ExtractQuestionsRequest, GeneratePptxRequest,
)
from shared.errors import OutputOverwriteError
from core.services.slide_builder import ExtractionServiceImpl, PptxServiceImpl
from core.di import Container


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
        self.calls.append((template_path, len(questions), font_name, output_path))
        total = len(questions)
        for i in range(total):
            if on_progress:
                on_progress(i + 1, total)
        return total * 2


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


PARAGRAPHS = [
    "1. 题目一",
    "A. 选项一",
    "B. 选项二",
    "2. 题目二",
    "A. a",
    "B. b",
]


class ExtractionServiceTests(unittest.TestCase):
    def test_extract_returns_questions_and_emits_event(self):
        loader = FakeDocumentLoader(PARAGRAPHS)
        emitter = CollectingEmitter()
        svc = ExtractionServiceImpl(loader, emitter)

        res = svc.extract(ExtractQuestionsRequest(doc_path="x.docx"))

        self.assertEqual(len(res.questions), 2)
        self.assertEqual(res.questions[0][0], "1. 题目一")
        self.assertEqual(loader.calls, ["x.docx"])
        self.assertTrue(
            any(e.type == EventType.EXTRACT_COMPLETED for e in emitter.events)
        )


class PptxServiceTests(unittest.TestCase):
    def test_generate_returns_result_and_emits_progress_completed(self):
        writer = FakePptxWriter()
        emitter = CollectingEmitter()
        svc = PptxServiceImpl(writer, emitter)
        req = GeneratePptxRequest(
            template_path="t.pptx",
            questions=[["1. x", "A. a"], ["2. y", "A. b"]],
            font_name="Arial", font_size=18, output_path="o.pptx",
        )

        res = svc.generate(req)

        self.assertEqual(res.page_count, 4)
        self.assertEqual(res.output_path, "o.pptx")
        types = [e.type for e in emitter.events]
        self.assertIn(EventType.PPTX_PROGRESS, types)
        self.assertIn(EventType.PPTX_COMPLETED, types)
        self.assertEqual(writer.calls[0][1], 2)

    def test_generate_same_path_raises_output_overwrite_error(self):
        writer = FakePptxWriter()
        emitter = CollectingEmitter()
        svc = PptxServiceImpl(writer, emitter)
        req = GeneratePptxRequest(
            template_path="same.pptx",
            questions=[["1. x", "A. a"]],
            font_name="Arial", font_size=18, output_path="same.pptx",
        )
        with self.assertRaises(OutputOverwriteError):
            svc.generate(req)
        # 不应调用真正的写操作
        self.assertEqual(writer.calls, [])


class ContainerTests(unittest.TestCase):
    def test_build_resolves_services(self):
        c = Container.build(task_runner=SyncTaskRunner(), event_emitter=CollectingEmitter())
        self.assertIsInstance(c.resolve("extraction"), ExtractionServiceImpl)
        self.assertIsInstance(c.resolve("pptx"), PptxServiceImpl)
        self.assertIsNotNone(c.resolve("task_runner"))
        self.assertIsNotNone(c.resolve("event_emitter"))


if __name__ == "__main__":
    unittest.main()
