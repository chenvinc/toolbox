"""P2 技术债修复的回归测试（阶段4 迁移版）：日志替换 / QSS 抽取等价性。

- 全仓 core/ 与 ui/ 源码不得残留 print( 调用（业务日志统一走 logging）。
- Theme.qss_* 产出的片段与约定字符串语义一致（theme.py 作为 UI 基础库保留）。

原 P2 测试中的 ExtractWorker 断言已由 tests/integration/test_slide_viewmodel.py
（FakeTaskRunner 转发）与 tests/integration/test_slide_e2e.py（真实适配器端到端）
覆盖，此处不再重复。
"""
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

import theme


def _norm(s):
    """折叠空白，便于比较 QSS 片段的语义等价性（CSS 空白无意义）。"""
    return re.sub(r"\s+", " ", s).strip()


def _scan_sources_for_print():
    """返回 core/ 与 ui/ 下所有 .py 源码中残留的 print( 行（忽略测试目录）。"""
    hits = []
    for pkg in ("core", "ui"):
        base = ROOT / pkg
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            # 跳过测试代码本身
            if "tests" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            for m in re.finditer(r"(?<![\w.])print\s*\(", src):
                hits.append(str(path))
    return hits


class LoggingTests(unittest.TestCase):
    def test_no_print_calls_remain_in_core_and_ui(self):
        hits = _scan_sources_for_print()
        self.assertEqual(
            hits, [],
            f"以下源码仍残留 print( 调用，应改用 logging: {hits}"
        )


class QssEquivalenceTests(unittest.TestCase):
    """验证 Theme.qss_* 产出的片段与约定字符串语义一致。"""

    def _theme_for(self, dark):
        t = theme.Theme()
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
