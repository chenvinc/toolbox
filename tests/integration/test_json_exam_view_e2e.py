"""JsonExamView 集成测试（视图层反馈与错误处理，需 QApplication / offscreen）。

验证 UI 反馈与错误处理符合预期：
  - _on_progress 把步骤文案写入进度标签、进度条按 total 设定范围与当前值
  - _on_completed 在存在失败图片时弹出「失败图片列表」报告弹窗
  - _on_failed 按异常类型分流：
      · DocumentReadError → JSON 解析失败弹窗（展示具体失败位置）
      · OutputWriteError  → 输出目录无权限弹窗（含「选择目录」重试入口）
      · 其余异常          → Toast 友好提示（不弹窗、不暴露堆栈）
UI 风格复用项目全局组件（widgets.ErrorDialog / ToastNotification），与现有工具一致。
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from shared.contracts import GenerateExamResult
from shared.errors import DocumentReadError, OutputWriteError
from ui.viewmodels.json_exam_viewmodel import JsonExamViewModel
from ui.views.json_exam_view import JsonExamView


class FakeErrorDialog:
    """记录 ErrorDialog 实例化参数的替身，避免真实模态弹窗阻塞测试。"""

    instances: list = []

    def __init__(self, *args, **kwargs):
        FakeErrorDialog.instances.append(self)
        self.args = args
        self.kwargs = kwargs
        self.extraClicked = MagicMock()

    def exec(self):
        return 1


class JsonExamViewE2ETests(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        # 用 MagicMock 替代真实 ViewModel，仅验证视图自身渲染/分支逻辑
        self.vm = MagicMock(spec=JsonExamViewModel)
        self.patcher = patch(
            "ui.views.json_exam_view.ErrorDialog", FakeErrorDialog
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        FakeErrorDialog.instances.clear()
        self.view = JsonExamView(self.vm)

    # ── 进度反馈 ──
    def test_progress_shows_step_messages_and_bar(self):
        self.view._on_progress("解析中...", 0, 5)
        QTest.qWait(350)  # 等待进度条动画过渡完成
        self.assertEqual(self.view.progress_label.text(), "解析中...")
        self.assertEqual(self.view.progress_bar.maximum(), 5)
        self.assertEqual(self.view.progress_bar.value(), 0)

        self.view._on_progress("下载图片 2/5", 2, 5)
        QTest.qWait(350)
        self.assertEqual(self.view.progress_label.text(), "下载图片 2/5")
        self.assertEqual(self.view.progress_bar.maximum(), 5)
        self.assertEqual(self.view.progress_bar.value(), 2)

        self.view._on_progress("生成题本...", 3, 5)
        self.assertEqual(self.view.progress_label.text(), "生成题本...")

    # ── 完成 + 部分图片失败报告 ──
    def test_completed_with_failed_images_shows_dialog(self):
        result = GenerateExamResult(
            question_book_path="/tmp/题本.docx",
            analysis_path="/tmp/解析.docx",
            question_count=3,
            failed_images=["https://x/1.png", "https://x/2.png"],
        )
        self.view._on_completed(result)
        self.assertEqual(len(FakeErrorDialog.instances), 1)
        dlg = FakeErrorDialog.instances[-1]
        self.assertEqual(dlg.kwargs["title"], "部分图片下载失败")
        self.assertIn("https://x/1.png", dlg.kwargs["detail"])
        self.assertIn("https://x/2.png", dlg.kwargs["detail"])

    def test_completed_without_failure_no_dialog(self):
        result = GenerateExamResult(
            question_book_path="/tmp/题本.docx",
            analysis_path="/tmp/解析.docx",
            question_count=3,
            failed_images=[],
        )
        self.view._on_completed(result)
        self.assertEqual(len(FakeErrorDialog.instances), 0)

    # ── JSON 解析失败弹窗 ──
    def test_failed_json_parse_shows_dialog(self):
        self.view._on_failed(
            DocumentReadError("JSON 解析失败：file.json（Expecting value: line 3 column 5）")
        )
        self.assertEqual(len(FakeErrorDialog.instances), 1)
        dlg = FakeErrorDialog.instances[-1]
        self.assertEqual(dlg.kwargs["title"], "JSON 解析失败")
        self.assertIn("line 3", dlg.kwargs["message"])
        self.assertIsNone(dlg.kwargs.get("extra_label"))

    # ── 输出目录无权限弹窗（含重新选择入口） ──
    def test_failed_permission_shows_reselect_dialog(self):
        self.view._on_failed(
            OutputWriteError("写入文件失败（无写入权限）", output_dir="/tmp/x")
        )
        self.assertEqual(len(FakeErrorDialog.instances), 1)
        dlg = FakeErrorDialog.instances[-1]
        self.assertEqual(dlg.kwargs["title"], "输出目录无写入权限")
        self.assertEqual(dlg.kwargs["extra_label"], "选择目录")
        # 确认「选择目录」回调已连接到重试逻辑
        dlg.extraClicked.connect.assert_called_once()

    # ── 其余异常：Toast 友好提示，不弹窗 ──
    def test_failed_generic_uses_toast_not_dialog(self):
        self.view._on_failed(RuntimeError("boom"))
        self.assertEqual(len(FakeErrorDialog.instances), 0)


if __name__ == "__main__":
    unittest.main()
