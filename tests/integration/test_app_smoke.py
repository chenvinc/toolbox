"""应用启动冒烟测试（offscreen）。

回归守卫：此前 slide_view.py 在 ``_setup_ui`` 中误用裸 ``change_btn``，
导致 ``ToolboxApp`` 启动即 ``NameError`` 崩溃。viewmodel 测试从不构造 View，
因此这个只在运行时才暴露的 bug 一直漏检。

本测试走真实启动路径构造完整 ``ToolboxApp``（等价于 ``app.py`` 的
``ToolboxApp()``），确保四个 View 均能成功构造、关键控件已正确绑定，
填补「View 构造未受测试覆盖」的盲区。
"""
import sys
import unittest

from PySide6.QtWidgets import QApplication

from app import ToolboxApp
from ui.views.slide_view import SlideView
from ui.views.similarity_view import SimilarityView
from ui.views.json_exam_view import JsonExamView
from ui.views.pdf_slide_view import PdfSlideView


class AppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # QApplication 整个进程只能有一个；在构造 ToolboxApp 之前必须先存在，
        # 因为 __init__ 内会调用 QApplication.setWindowIcon / styleHints。
        cls._app = QApplication.instance() or QApplication(sys.argv)
        # 真实启动路径：构造完整应用即会把四个 View 全部建出来。
        cls.window = ToolboxApp()

    def test_app_constructs_all_four_views(self):
        self.assertEqual(len(self.window._tools), 4)
        self.assertIsInstance(self.window._tools[0], SlideView)
        self.assertIsInstance(self.window._tools[1], SimilarityView)
        self.assertIsInstance(self.window._tools[2], JsonExamView)
        self.assertIsInstance(self.window._tools[3], PdfSlideView)

    def test_slide_view_change_btn_bound(self):
        # 直接守卫本次回归：SlideView 必须把「更改」按钮存为 self.change_btn，
        # 否则 _setup_ui 中 addWidget(change_btn) 会 NameError 崩溃。
        slide = self.window._tools[0]
        self.assertTrue(hasattr(slide, "change_btn"))
        self.assertIsNotNone(slide.change_btn)


if __name__ == "__main__":
    unittest.main()
