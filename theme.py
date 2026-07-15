"""全局样式管理 — 主题配色与系统字体发现。"""

import string
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase

# 与 theme.qss 保持一致的兜底模板（当主题文件缺失时使用，确保不崩溃）
_EMBEDDED_QSS = """\
# card
QFrame { background: $card_bg; border-radius: 20px; border: none; }

# divider
background: $border; border: none;

# progress_bar
QProgressBar { border: none; background: $progress_bg; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: $progress_chunk; border-radius: 3px; }

# section_header
font-size: 15px; font-weight: bold; color: $card_header_color; background: transparent; padding: 0;
"""

_QSS_PATH = Path(__file__).with_name("theme.qss")


def _get_system_fonts():
    """获取系统可用字体列表，优先返回平台相关的推荐字体。

    根据操作系统（macOS/其他）预定义一组优先字体，
    将系统中已安装的优先字体排在前面，其余字体按字母排序附在后面。
    """
    all_fonts = QFontDatabase.families()
    preferred = []
    if sys.platform == "darwin":
        pref = ["SF Pro Text", "SF Pro Display", "苹方", "PingFang SC",
                 "Helvetica Neue", "Helvetica", "Arial"]
    else:
        pref = ["Segoe UI", "微软雅黑", "Microsoft YaHei", "Arial"]
    for p in pref:
        if p in all_fonts:
            preferred.append(p)
    rest = sorted(f for f in all_fonts if f not in preferred)
    return preferred + rest


class Theme:
    """管理应用程序的深色/浅色主题配色方案。

    检测系统配色自动切换，提供各组件的颜色属性供样式表使用。
    """

    def __init__(self):
        self._is_dark = False
        self.refresh()

    def refresh(self):
        """检测系统当前配色方案（深色/浅色）并更新主题颜色。"""
        app = QApplication.instance()
        if app:
            scheme = app.styleHints().colorScheme()
            self._is_dark = (scheme == Qt.ColorScheme.Dark)
        self._set_colors()

    def _set_colors(self):
        """根据 _is_dark 标志设置深色或浅色模式下的全部颜色属性。"""
        if self._is_dark:
            self.card_bg = "#1E1E24"
            self.input_bg = "#2C2C32"
            self.text_primary = "#FFFFFF"
            self.text_secondary = "#98989D"
            self.text_placeholder = "#636366"
            self.border = "#3A3A3C"
            self.dashed_border = "#48484A"
            self.hover_bg = "#2C2C36"
            self.progress_bg = "#3A3A3C"
            self.progress_chunk = "#0A84FF"
            self.window_bg = QColor(30, 30, 36, 235)
            self.window_solid_bg = QColor(30, 30, 36)
            self.shadow_color = QColor(0, 0, 0, 80)
            self.titlebar_text = "#FFFFFF"
            self.titlebar_icon_bg = "rgba(255,255,255,0.12)"
            self.change_btn_color = "#0A84FF"
            self.drop_text = "#98989D"
            self.drop_file_text = "#0A84FF"
            self.card_header_color = "#FFFFFF"
            self.error_color = "#FF453A"
            self.accent = "#0A84FF"
            self.accent_dark = "#0066CC"
            self.accent_light = "#409CFF"
            self.sidebar_bg = "#1C1C22"
            self.sidebar_border = "#2C2C32"
            self.nav_text = "#98989D"
            self.nav_selected_bg = "#2C3A5C"
            self.nav_selected_text = "#6BA3FF"
            self.nav_hover_bg = "#2C2C36"
            self.toast_bg = "rgba(50,50,56,0.92)"
            self.toast_text = "#FFFFFF"
            self.scrollbar_handle = "rgba(180,180,180,0.3)"
            self.disabled_btn_bg = "#3A3A3C"
            self.stack_bg = "#1E1E24"
        else:
            self.card_bg = "#FFFFFF"
            self.input_bg = "#F5F5F7"
            self.text_primary = "#1D1D1F"
            self.text_secondary = "#8E8E93"
            self.text_placeholder = "#C0C0C8"
            self.border = "#E5E5EA"
            self.dashed_border = "#C0C0CC"
            self.hover_bg = "#EDF4FF"
            self.progress_bg = "#E5E5EA"
            self.progress_chunk = "#007AFF"
            self.window_bg = QColor(245, 245, 247, 230)
            self.window_solid_bg = QColor(245, 245, 247)
            self.shadow_color = QColor(0, 0, 0, 20)
            self.titlebar_text = "#333333"
            self.titlebar_icon_bg = "rgba(255,255,255,0.85)"
            self.change_btn_color = "#007AFF"
            self.drop_text = "#8E8E93"
            self.drop_file_text = "#007AFF"
            self.card_header_color = "#1D1D1F"
            self.error_color = "#FF3B30"
            self.accent = "#007AFF"
            self.accent_dark = "#0056D6"
            self.accent_light = "#3395FF"
            self.sidebar_bg = "#F0F0F5"
            self.sidebar_border = "#E0E0E6"
            self.nav_text = "#555555"
            self.nav_selected_bg = "#DDE4FF"
            self.nav_selected_text = "#2255CC"
            self.nav_hover_bg = "#EAEAF2"
            self.toast_bg = "rgba(0,0,0,0.80)"
            self.toast_text = "#FFFFFF"
            self.scrollbar_handle = "rgba(128,128,128,0.4)"
            self.disabled_btn_bg = "#C8C8CC"
            self.stack_bg = "#FFFFFF"

    # ── QSS 片段（来自 theme.qss，按主题色替换，支持热加载） ──────────

    def _read_qss(self) -> str:
        """读取 theme.qss 模板源；文件缺失时回退到内置兜底模板。"""
        try:
            return _QSS_PATH.read_text(encoding="utf-8")
        except OSError:
            return _EMBEDDED_QSS

    def _qss_block(self, name: str) -> str:
        """抽取 theme.qss 中以 `# name` 标记的片段，并用当前主题色替换 $var 占位符。

        每次调用都重新读取文件，因此修改 theme.qss 后在下次主题刷新/切换时即生效
        （即“热加载”）；模板使用 string.Template 的 $var 语法，避免与 CSS 的 {} 冲突。
        """
        raw = self._read_qss()
        mapping = {k: v for k, v in vars(self).items() if isinstance(v, str)}
        in_block = False
        lines: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped == f"# {name}":
                in_block = True
                continue
            if in_block:
                if stripped.startswith("# "):
                    break
                if stripped:
                    lines.append(line.rstrip())
        if not lines:
            return ""
        return string.Template("\n".join(lines)).safe_substitute(mapping)

    def qss_card(self) -> str:
        """卡片容器样式（两工具共用，原内联重复片段）。"""
        return self._qss_block("card")

    def qss_divider(self) -> str:
        """分隔线样式（两工具共用，原内联重复片段）。"""
        return self._qss_block("divider")

    def qss_progress_bar(self) -> str:
        """进度条样式（两工具共用，原内联重复片段）。"""
        return self._qss_block("progress_bar")

    def qss_section_header(self) -> str:
        """区块标题样式（两工具共用，原内联重复片段）。"""
        return self._qss_block("section_header")
