"""P2 技术债修复的回归测试：日志替换 / 提取线程 / QSS 抽取等价性。"""

import importlib.util
import os
import pathlib
import re
import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / fn)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    return mod


_w2s = _load("word_2_slide_tool_p2", "word_2_slide_tool.py")
_theme = _load("theme_p2", "theme.py")


def _norm(s):
    """折叠空白，便于比较 QSS 片段的语义等价性（CSS 空白无意义）。"""
    return re.sub(r"\s+", " ", s).strip()


class LoggingTests(unittest.TestCase):
    def test_no_print_calls_remain(self):
        src = (ROOT / "word_2_slide_tool.py").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"(?<![\w.])print\s*\(", src),
            "word_2_slide_tool.py 中仍残留 print( 调用，应改用 logging",
        )

    def test_logger_is_configured(self):
        import logging
        self.assertTrue(hasattr(_w2s, "logger"))
        self.assertIsInstance(_w2s.logger, logging.Logger)


class ExtractWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            QApplication([])

    def test_emits_extracted_on_success(self):
        fake = [["1. 题干", "A. a", "B. b"], ["2. 题干二", "A. a", "B. b"]]
        with patch.object(_w2s, "extract_questions", lambda p, n, o: list(fake)):
            w = _w2s.ExtractWorker("doc.docx", "1.", "A.")
            got = []
            errs = []
            w.extracted.connect(got.append)
            w.error.connect(errs.append)
            w.run()  # 同步调用 run() 以验证逻辑（同线程直连信号）
            self.assertEqual(got, [fake])
            self.assertEqual(errs, [])

    def test_emits_error_on_exception(self):
        def boom(p, n, o):
            raise RuntimeError("boom")

        with patch.object(_w2s, "extract_questions", boom):
            w = _w2s.ExtractWorker("doc.docx", "1.", "A.")
            got = []
            errs = []
            w.extracted.connect(got.append)
            w.error.connect(errs.append)
            w.run()
            self.assertEqual(got, [])
            self.assertEqual(errs, ["boom"])


class QssEquivalenceTests(unittest.TestCase):
    """验证 Theme.qss_* 产出的片段与重构前的逐字内联字符串语义一致。"""

    def _theme_for(self, dark):
        t = _theme.Theme()
        t._is_dark = dark
        t._set_colors()
        return t

    def test_qss_card_matches_inline(self):
        for dark in (False, True):
            t = self._theme_for(dark)
            expected = f"QFrame {{ background: {t.card_bg}; border-radius: 20px; border: none; }}"
            self.assertEqual(_norm(t.qss_card()), _norm(expected), f"card dark={dark}")

    def test_qss_divider_matches_inline(self):
        for dark in (False, True):
            t = self._theme_for(dark)
            expected = f"background: {t.border}; border: none;"
            self.assertEqual(_norm(t.qss_divider()), _norm(expected), f"divider dark={dark}")

    def test_qss_progress_bar_matches_inline(self):
        for dark in (False, True):
            t = self._theme_for(dark)
            expected = (
                f"QProgressBar {{ border: none; background: {t.progress_bg}; "
                f"border-radius: 3px; height: 6px; }}\n"
                f"QProgressBar::chunk {{ background: {t.progress_chunk}; border-radius: 3px; }}"
            )
            self.assertEqual(_norm(t.qss_progress_bar()), _norm(expected), f"progress dark={dark}")

    def test_qss_section_header_matches_inline(self):
        for dark in (False, True):
            t = self._theme_for(dark)
            expected = (
                f"font-size: 15px; font-weight: bold; "
                f"color: {t.card_header_color}; background: transparent; padding: 0;"
            )
            self.assertEqual(_norm(t.qss_section_header()), _norm(expected), f"header dark={dark}")

    def test_theme_qss_file_loads(self):
        self.assertTrue((ROOT / "theme.qss").exists())
        t = self._theme_for(False)
        self.assertTrue(t.qss_card())
        self.assertTrue(t.qss_progress_bar())


if __name__ == "__main__":
    unittest.main()
