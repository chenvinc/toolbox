"""JsonExamViewModel 集成测试（ViewModel 接线，需 QApplication / offscreen）。

用 SyncTaskRunner + CollectingEmitter + FakeExamDocxWriter（注入真实服务），验证：
  - UI 命令（generate）→ core service → 事件 → Qt 信号 的单向数据流
  - 后台异常经 on_async_error 转发为 failed 信号
"""
import json
import os
import sys
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from shared.contracts import ExamLineSpacingType, GenerateExamRequest, GenerateExamResult
from core.ports.io import ExamDocxWriter
from core.services.json_to_word_service import JsonToWordServiceImpl
from ui.viewmodels.json_exam_viewmodel import JsonExamViewModel


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


SAMPLE_JSON = {
    "pageTitle": "VM 测试试卷",
    "questions": [
        {
            "questionNumber": "1.",
            "questionType": "单选题",
            "questionStem": "题干",
            "options": {"A": {"text": "甲"}, "B": {"text": "乙"}},
            "correctAnswer": "A",
            "correctRate": "50 %",
            "solution": {"analysis": "解析"},
        }
    ],
}


class FakeExamDocxWriter(ExamDocxWriter):
    def __init__(self, fail=False):
        self.fail = fail

    def build(self, request, questions, on_progress, image_cache=None):
        if self.fail:
            raise RuntimeError("boom")
        if on_progress:
            on_progress(1, 2)
            on_progress(2, 2)
        return GenerateExamResult(
            question_book_path="/tmp/题本.docx",
            analysis_path="/tmp/解析.docx",
            question_count=len(questions),
        )


class JsonExamViewModelTests(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._dir = tempfile.mkdtemp()
        self._json_path = os.path.join(self._dir, "exam.json")
        with open(self._json_path, "w", encoding="utf-8") as fh:
            json.dump(SAMPLE_JSON, fh, ensure_ascii=False)

        self.emitter = CollectingEmitter()
        self.runner = SyncTaskRunner()
        self.writer = FakeExamDocxWriter()
        # 把 FakeExamDocxWriter 注入真实服务（与 SimilarityViewModel 测试同构）
        self.svc = JsonToWordServiceImpl(self.writer, self.emitter)
        self.vm = JsonExamViewModel(self.svc, self.runner, self.emitter)
        self.progress_seen = []
        self.completed_result = None
        self.failed_msg = None
        self.vm.progress.connect(lambda m, c, t: self.progress_seen.append((m, c, t)))
        self.vm.completed.connect(lambda r: setattr(self, "completed_result", r))
        self.vm.failed.connect(lambda m: setattr(self, "failed_msg", m))

    def test_generate_success_signals(self):
        req = GenerateExamRequest(
            input_path=self._json_path,
            line_spacing_type=ExamLineSpacingType.CUSTOM,
            line_spacing_value=1.8,
        )
        self.vm.generate(req)
        self.assertIsNotNone(self.completed_result)
        self.assertIsNone(self.failed_msg)
        self.assertTrue(len(self.progress_seen) >= 2)
        self.assertEqual(self.completed_result.question_count, 1)  # SAMPLE_JSON 含 1 题

    def test_generate_failure_forwards_failed(self):
        self.writer.fail = True  # 让 writer.build 抛异常，经由服务 → on_async_error
        req = GenerateExamRequest(input_path=self._json_path)
        self.vm.generate(req)
        self.assertIsNone(self.completed_result)
        # failed 信号透传异常对象（保留类型），视图据此分类处理
        self.assertIsInstance(self.failed_msg, RuntimeError)
        self.assertEqual(str(self.failed_msg), "boom")


if __name__ == "__main__":
    unittest.main()
