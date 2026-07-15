"""SimilarityViewModel 集成测试（ViewModel 接线，无真实文件 IO）。

用 SyncTaskRunner + CollectingEmitter + Fake 适配器，验证：
  - UI 命令（check）→ core similarity service → 事件 → Qt 信号 的单向数据流
  - 后台异常经 on_async_error 转发为 failed 信号
"""
import sys
import unittest

from PySide6.QtWidgets import QApplication

from shared.contracts import EventType, SimilarityMode, SimilarityRequest
from core.services.similarity_service import SimilarityServiceImpl
from ui.viewmodels.similarity_viewmodel import SimilarityViewModel


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
    def __init__(self, mapping):
        self._mapping = {k: list(v) for k, v in mapping.items()}
        self.calls = []

    def load_paragraphs(self, path):
        self.calls.append(path)
        return list(self._mapping[path])


MAIN_PARA = [
    "1. 下列哪个是 Python 关键字？", "A. class", "B. def",
    "C. if", "D. all of the above",
]
DUP_PARA = list(MAIN_PARA)
OTHER_PARA = [
    "2. 中国的首都是哪里？", "A. 北京", "B. 上海",
    "C. 广州", "D. 深圳",
]


class SimilarityViewModelTests(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self.emitter = CollectingEmitter()
        self.runner = SyncTaskRunner()
        self.loader = FakeDocumentLoader({
            "main.docx": MAIN_PARA,
            "dup.docx": DUP_PARA,
            "other.docx": OTHER_PARA,
        })
        self.svc = SimilarityServiceImpl(self.loader, self.emitter)
        self.vm = SimilarityViewModel(self.svc, self.runner, self.emitter)

        self.started = []
        self.progress = []
        self.completed = []
        self.failed = []
        self.vm.started.connect(lambda m: self.started.append(m))
        self.vm.progress.connect(lambda msg, c, t: self.progress.append((msg, c, t)))
        self.vm.completed.connect(lambda r: self.completed.append(r))
        self.vm.failed.connect(lambda m: self.failed.append(m))

    def test_check_forwards_events_to_signals(self):
        self.vm.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY,
            main_path="main.docx",
            secondary_paths=["dup.docx", "other.docx"],
            threshold=0.8,
        ))
        self.assertEqual(self.started, [SimilarityMode.ONE_TO_MANY])
        self.assertTrue(self.progress, "应收到进度信号")
        self.assertEqual(len(self.completed), 1)
        self.assertEqual(self.failed, [])
        result = self.completed[0]
        self.assertEqual(result.main_count, 1)
        self.assertEqual(result.duplicate_count, 1)

    def test_error_forwards_to_failed_signal(self):
        # 主文档无题目 → NoQuestionsExtracted → on_async_error → failed
        self.loader._mapping = {"main.docx": ["一段没有题号的普通文本"]}
        self.vm.check(SimilarityRequest(
            mode=SimilarityMode.ONE_TO_MANY,
            main_path="main.docx", secondary_paths=[],
            threshold=0.8,
        ))
        self.assertEqual(len(self.failed), 1)
        self.assertIn("未提取到题目", self.failed[0])
        self.assertEqual(self.completed, [])


if __name__ == "__main__":
    unittest.main()
