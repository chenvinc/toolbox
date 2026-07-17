"""JsonExamView 交互测试（offscreen，需 QApplication）。

验证新 Tool 的 UI 控件默认状态、行间距自定义切换交互、以及「开始生成」能正确
构造 GenerateExamRequest 并经 ViewModel 完成生成（单向数据流 + 状态可读）。
"""
import os
import sys
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from shared.contracts import ExamLineSpacingType, GenerateExamRequest, GenerateExamResult
from core.ports.io import ExamDocxWriter
from core.services.json_to_word_service import JsonToWordServiceImpl
from ui.viewmodels.json_exam_viewmodel import JsonExamViewModel
from ui.views.json_exam_view import JsonExamView


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


class RecordingExamDocxWriter(ExamDocxWriter):
    def __init__(self):
        self.last_request = None
        self.last_questions = None

    def build(self, request, questions, on_progress, image_cache=None):
        self.last_request = request
        self.last_questions = list(questions)
        if on_progress:
            on_progress(1, 2)
            on_progress(2, 2)
        return GenerateExamResult(
            question_book_path="/tmp/题本.docx",
            analysis_path="/tmp/解析.docx",
            question_count=len(questions),
        )


SAMPLE_JSON = {
    "pageTitle": "交互测试试卷",
    "questions": [
        {
            "questionNumber": "1.",
            "questionType": "单选题",
            "questionStem": "题干内容",
            "options": {"A": {"text": "甲"}, "B": {"text": "乙"}},
            "correctAnswer": "A",
            "correctRate": "50 %",
            "solution": {"analysis": "解析内容"},
        }
    ],
}


class JsonExamViewTests(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._dir = tempfile.mkdtemp()
        self._json_path = os.path.join(self._dir, "exam.json")
        with open(self._json_path, "w", encoding="utf-8") as fh:
            import json
            json.dump(SAMPLE_JSON, fh, ensure_ascii=False)

        self.emitter = CollectingEmitter()
        self.runner = SyncTaskRunner()
        self.writer = RecordingExamDocxWriter()
        # 把 RecordingExamDocxWriter 注入真实服务（与 ViewModel 测试同构）
        self.svc = JsonToWordServiceImpl(self.writer, self.emitter)
        self.vm = JsonExamViewModel(self.svc, self.runner, self.emitter)
        # 隔离 QSettings 持久化：offscreen 下写入用户目录，会跨测试运行污染默认态
        from PySide6.QtCore import QSettings as _QS
        _st = _QS("JsonExam", "JsonExam")
        _st.clear()
        _st.sync()
        self.view = JsonExamView(self.vm)
        self.view.show()  # offscreen 下 show 后 isVisible() 才反映 setVisible 状态

    def test_default_control_states(self):
        self.assertEqual(self.view.font_name.currentText(), "宋体/Times New Roman")
        self.assertEqual(self.view.font_size.currentText(), "五号")
        self.assertEqual(self.view.line_spacing_type.currentText(), "1.5倍行距")
        self.assertFalse(self.view.line_spacing_value_stepper.isVisible())
        self.assertTrue(self.view.first_line_indent.isChecked())
        # 未选文件时，生成按钮应禁用
        self.assertFalse(self.view.generate_btn._can_click)

    def test_line_spacing_custom_toggle(self):
        self.view.line_spacing_type.setCurrentText("自定义")
        self.view._on_spacing_changed("自定义")
        self.assertTrue(self.view.line_spacing_value_stepper.isVisible())

        self.view.line_spacing_type.setCurrentText("2倍行距")
        self.view._on_spacing_changed("2倍行距")
        self.assertFalse(self.view.line_spacing_value_stepper.isVisible())

    def test_generate_builds_request_and_completes(self):
        # 选择 JSON 文件：set_file 仅更新显示，file_selected 才通知 View（与拖拽/选择对话框一致）
        self.view.json_drop_zone.set_file(self._json_path)
        self.view.json_drop_zone.file_selected.emit(self._json_path)
        self.assertTrue(self.view.generate_btn._can_click)

        # 切到自定义行距并设值，验证请求正确携带
        self.view.line_spacing_type.setCurrentText("自定义")
        self.view.line_spacing_value.setText("1.8")

        self.view.on_generate()

        req = self.writer.last_request
        self.assertIsInstance(req, GenerateExamRequest)
        self.assertEqual(req.input_path, self._json_path)
        self.assertEqual(req.font_name, "宋体/Times New Roman")
        self.assertEqual(req.font_size_name, "五号")
        self.assertEqual(req.line_spacing_type, ExamLineSpacingType.CUSTOM)
        self.assertAlmostEqual(req.line_spacing_value, 1.8)
        self.assertTrue(req.first_line_indent)
        # 完成后「打开文件夹」按钮应可用
        self.assertTrue(self.view._open_out_btn._can_click)


if __name__ == "__main__":
    unittest.main()
