"""全局样式管理 — 主题配色与系统字体发现。"""

import string
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication

# 与 theme.qss 保持一致的兜底模板（当主题文件缺失时使用，确保不崩溃）
_EMBEDDED_QSS = """\
# card
QFrame { background: $card_bg; border-radius: $radius; border: none; }

# divider
background: $border; border: none;

# progress_bar
QProgressBar { border: none; background: $progress_bg; border-radius: $radius; height: 6px; }
QProgressBar::chunk { background: $progress_chunk; border-radius: $radius; }

# section_header
font-size: ${font_module_title}px; font-weight: bold; color: $card_header_color; background: transparent; padding: 0;

# scrollbar
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { width: 6px; background: transparent; }
QScrollBar::handle:vertical { background: $scrollbar_handle; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

_QSS_PATH = Path(__file__).with_name("theme.qss")

# 全局唯一的 Theme 实例（单例）。所有 `Theme()` / `get_theme()` 调用返回同一对象，
# 避免 ≥5 处各自创建实例、各自刷新导致的冗余与潜在不一致。
_INSTANCE: "Theme | None" = None


def get_theme() -> "Theme":
    """返回全局唯一的 Theme 单例（推荐用法，语义清晰于 `Theme()`）。"""
    return Theme()


def _get_system_fonts() -> list[str]:
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


class Theme(QObject):
    """管理应用程序的深色/浅色主题配色方案（全局单例）。

    检测系统配色自动切换，提供各组件的颜色属性供样式表使用。
    进程内只有一个实例：`Theme()` 与 `get_theme()` 等价；`refresh()` 后会通过
    `theme_changed` 信号广播，供各视图统一重绘（集中刷新，避免多点重复接线）。
    """

    theme_changed = Signal()

    def __new__(cls) -> "Theme":
        global _INSTANCE
        if _INSTANCE is None:
            _INSTANCE = super().__new__(cls)
        return _INSTANCE

    def __init__(self) -> None:
        # 单例守卫：__new__ 返回同一实例后，__init__ 仍会被重复调用，需跳过重复初始化
        if getattr(self, "_initialized", False):
            return
        super().__init__()
        self._initialized = True
        self._is_dark = False
        self.refresh()
        self._set_tokens()

    def _set_tokens(self) -> None:
        """跨深浅色统一的几何与排版令牌，作为设计规范的单一来源。

        这些值与主题无关（浅色/深色共用），初始化时设定一次，后续
        主题刷新不会改变。QSS 片段与所有控件样式统一从此处取值，
        确保全局圆角/间距/字号严格一致。
        """
        self.radius = 6
        self.spacing = 16
        self.control_spacing = 8
        self.page_pad_x = 24
        self.page_pad_y = 20
        self.font_family = "Microsoft YaHei"
        self.font_page_title = 14
        self.font_module_title = 13
        self.font_body = 12
        self.font_hint = 12

    def refresh(self) -> None:
        """检测系统当前配色方案（深色/浅色）并更新主题颜色。

        更新后通过 `theme_changed` 广播，供订阅者统一重绘（集中刷新）。
        """
        app = QApplication.instance()
        if isinstance(app, QGuiApplication):
            scheme = app.styleHints().colorScheme()
            self._is_dark = (scheme == Qt.ColorScheme.Dark)
        self._set_colors()
        self.theme_changed.emit()

    def _set_colors(self) -> None:
        """根据 _is_dark 标志设置深色或浅色模式下的全部颜色属性。

        色彩严格遵循全局 UI 双模式规范（同一套设计令牌，浅/深一一对应）：
        - 浅色：主色 #1677ff、辅助浅底 #f5f7fa、禁用灰 #d9d9d9、危险 #f53f3f、文本 #333/#666/#999
        - 深色：主色 #3b93ff、页面/侧栏 #1e1e2e、卡片 #2d2d3f、边框 #3f3f56、悬浮 #383852、
                禁用 #555566、危险 #ff5555、文本 #f5f5f7/#d0d0e0/#9999b3
        支持系统配色自动切换（colorSchemeChanged），切换前后视觉层级完全对等、无样式混乱。
        """
        if self._is_dark:
            # 深色模式：严格对齐补充双模式规范（同一套设计令牌，深浅一一对应）
            # 主色 #3b93ff / 页面·侧栏 #1e1e2e / 卡片 #2d2d3f / 边框 #3f3f56
            # 悬浮 #383852 / 禁用 #555566 / 危险 #ff5555
            # 文本 #f5f5f7 · #d0d0e0 · #9999b3
            self.accent = "#3b93ff"
            self.accent_light = "#4096ff"
            self.accent_dark = "#0958d9"
            self.change_btn_color = "#3b93ff"
            self.danger = "#ff5555"
            self.error_color = "#ff5555"
            self.text_primary = "#f5f5f7"
            self.text_secondary = "#d0d0e0"
            self.text_placeholder = "#9999b3"
            self.window_bg = QColor(30, 30, 46, 255)
            self.window_solid_bg = QColor(30, 30, 46)
            self.stack_bg = "#1e1e2e"
            self.sidebar_bg = "#1e1e2e"
            self.sidebar_border = "#3f3f56"
            self.card_bg = "#2d2d3f"
            self.input_bg = "#1f1f1f"
            self.hover_bg = "#2d2d3f"
            self.hover_blue = "#383852"
            self.secondary_bg = "#353549"
            self.border = "#3f3f56"
            self.dashed_border = "#434343"
            self.progress_bg = "#303030"
            self.progress_chunk = "#3b93ff"
            self.disabled_btn_bg = "#555566"
            self.drop_text = "#a0a0a0"
            self.drop_file_text = "#3b93ff"
            self.card_header_color = "#f5f5f7"
            self.nav_text = "#b0b0b0"
            self.nav_selected_bg = "#383852"
            self.nav_selected_text = "#3b93ff"
            self.nav_hover_bg = "#383852"
            self.shadow_color = QColor(0, 0, 0, 80)
            self.titlebar_text = "#f5f5f7"
            self.titlebar_icon_bg = "rgba(255,255,255,0.12)"
            self.toast_bg = "rgba(0,0,0,0.85)"
            self.toast_text = "#FFFFFF"
            self.scrollbar_handle = "rgba(255,255,255,0.25)"
        else:
            self.accent = "#1677ff"
            self.accent_light = "#4096ff"
            self.accent_dark = "#0958d9"
            self.change_btn_color = "#1677ff"
            self.danger = "#f53f3f"
            self.error_color = "#f53f3f"
            self.text_primary = "#333333"
            self.text_secondary = "#666666"
            self.text_placeholder = "#999999"
            self.window_bg = QColor(255, 255, 255, 255)
            self.window_solid_bg = QColor(255, 255, 255)
            self.stack_bg = "#ffffff"
            self.sidebar_bg = "#f5f7fa"
            self.sidebar_border = "#e8e8e8"
            self.card_bg = "#f5f7fa"
            self.input_bg = "#ffffff"
            self.hover_bg = "#f5f7fa"
            self.hover_blue = "#e6f4ff"
            self.secondary_bg = "#ffffff"
            self.border = "#e8e8e8"
            self.dashed_border = "#d9d9d9"
            self.progress_bg = "#e8e8e8"
            self.progress_chunk = "#1677ff"
            self.disabled_btn_bg = "#d9d9d9"
            self.drop_text = "#999999"
            self.drop_file_text = "#1677ff"
            self.card_header_color = "#333333"
            self.nav_text = "#666666"
            self.nav_selected_bg = "#e6f4ff"
            self.nav_selected_text = "#1677ff"
            self.nav_hover_bg = "#e6f4ff"
            self.shadow_color = QColor(0, 0, 0, 20)
            self.titlebar_text = "#333333"
            self.titlebar_icon_bg = "rgba(255,255,255,0.85)"
            self.toast_bg = "rgba(0,0,0,0.80)"
            self.toast_text = "#FFFFFF"
            self.scrollbar_handle = "rgba(0,0,0,0.20)"

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
        mapping = {}
        for k, v in vars(self).items():
            if isinstance(v, str):
                mapping[k] = v
            elif isinstance(v, (int, float)):
                mapping[k] = str(v)
        # 圆角需带 px 单位才符合 QSS 语法（其余 $var 为颜色或纯数字字号）
        mapping["radius"] = f"{self.radius}px"
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

    def qss_scrollbar(self) -> str:
        """滚动区域样式（四工具共用，原内联重复片段）。

        R-9 将各 View ``_restyle_all`` 中逐字相同的滚动条样式块集中于此，
        与 ``qss_card`` / ``qss_divider`` 等保持一致（热加载、按主题色替换）。
        """
        return self._qss_block("scrollbar")
