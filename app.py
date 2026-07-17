"""应用入口 — 组装前后端并启动工具箱。

按架构分层：
- core/di.Container 组装业务服务（外部适配器 → 服务，零 Qt）
- ui/infra 提供 Qt 版 TaskRunner / EventEmitter（UI 层）
- ui/viewmodels 是胶水层（持有 service，发射信号）
- ui/views 仅负责渲染与事件绑定

本文件属于 UI 层，负责生产环境的依赖装配，不编写任何业务规则。
"""
import os
import sys
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QStackedWidget,
    QHBoxLayout, QListWidgetItem, QFrame, QVBoxLayout,
    QLabel, QWidget,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPalette, QIcon, QFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.di import Container
from ui.infra.qt_task_runner import QtTaskRunner
from ui.infra.qt_event_emitter import QtEventEmitter
from ui.viewmodels.slide_viewmodel import SlideViewModel
from ui.viewmodels.similarity_viewmodel import SimilarityViewModel
from ui.viewmodels.json_exam_viewmodel import JsonExamViewModel
from ui.views.slide_view import SlideView
from ui.views.similarity_view import SimilarityView
from ui.views.json_exam_view import JsonExamView
from theme import Theme


class ToolboxApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.theme = Theme()
        self._apply_global_font()
        QApplication.setWindowIcon(QIcon("./assets/images/logo.png"))

    def _apply_global_font(self):
        """全局统一字体：微软雅黑（含跨平台回退），基准 12px。"""
        font = QFont()
        font.setFamilies([
            "Microsoft YaHei", "PingFang SC", "Microsoft YaHei UI",
            "SimHei", "Heiti SC", "sans-serif",
        ])
        font.setPointSize(12)
        app = QApplication.instance()
        if app is not None:
            app.setFont(font)
        self.setWindowTitle("ALL IN ONE TOOLBOX")
        self.resize(960, 660)
        self.setMinimumSize(800, 550)

        # ── 依赖装配：core 服务图 + UI 层 TaskRunner / EventEmitter ──
        self._task_runner = QtTaskRunner()
        self._event_emitter = QtEventEmitter()
        container = Container.build(
            task_runner=self._task_runner,
            event_emitter=self._event_emitter,
        )
        slide_vm = SlideViewModel(
            container.resolve("extraction"),
            container.resolve("pptx"),
            self._task_runner,
            self._event_emitter,
        )
        sim_vm = SimilarityViewModel(
            container.resolve("similarity"),
            self._task_runner,
            self._event_emitter,
        )
        exam_vm = JsonExamViewModel(
            container.resolve("exam"),
            self._task_runner,
            self._event_emitter,
        )

        self._tools = []

        central = QWidget()
        central.setAutoFillBackground(True)
        self.setCentralWidget(central)
        self.setAutoFillBackground(True)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(200)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.sidebar_title = QLabel("\u5de5\u5177\u7bb1")
        self.sidebar_title.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.sidebar_title)

        self.nav_list = QListWidget()
        self.nav_list.setIconSize(QSize(24, 24))
        self.nav_list.setSpacing(2)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        sidebar_layout.addWidget(self.nav_list)

        sidebar_layout.addStretch()

        self.stack = QStackedWidget()

        root.addWidget(self.sidebar)
        root.addWidget(self.stack, 1)

        self._register_tools(slide_vm, sim_vm, exam_vm)
        self.nav_list.setCurrentRow(0)
        self._restyle_all()
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_theme_changed
        )
        self._on_theme_changed()

    def _on_theme_changed(self):
        self.theme.refresh()
        self._restyle_all()

    def _restyle_all(self):
        t = self.theme
        pal = self.palette()
        pal.setColor(QPalette.Window, t.window_solid_bg)
        self.setPalette(pal)

        self.centralWidget().setStyleSheet(
            f"QWidget {{ background: {t.window_solid_bg.name()}; }}"
        )

        self.sidebar.setStyleSheet(
            f"QFrame {{ background: {t.sidebar_bg}; "
            f"border-right: 1px solid {t.sidebar_border}; }}"
        )

        self.sidebar_title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {t.text_primary}; "
            f"padding: 24px 0 16px; background: transparent; "
            f"border: none; border-bottom: 1px solid {t.sidebar_border};"
        )

        self.nav_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            f"QListWidget::item {{ padding: 12px 16px; font-size: 13px; spacing: 4px; "
            f"color: {t.nav_text}; border: none; border-left: 3px solid transparent; "
            f"border-radius: 6px; margin: 4px 10px; }}"
            f"QListWidget::item:selected {{ background: {t.nav_selected_bg}; "
            f"color: {t.nav_selected_text}; font-weight: bold; "
            f"border-left: 3px solid {t.accent}; }}"
            f"QListWidget::item:hover:!selected {{ background: "
            f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.hover_blue}, "
            f"stop:1 rgba(0,0,0,0)); }}"
        )

        self.stack.setStyleSheet(
            "QStackedWidget { background: transparent; border: none; border-radius: 12px; }"
        )

    def _register_tools(self, slide_vm, sim_vm, exam_vm):
        """注册工具箱中的所有视图（持有对应 ViewModel）。"""
        self._add_tool(SlideView(slide_vm))
        self._add_tool(SimilarityView(sim_vm))
        self._add_tool(JsonExamView(exam_vm))

    def _add_tool(self, tool):
        """将视图添加到导航栏和堆栈中。"""
        self._tools.append(tool)

        item = QListWidgetItem(tool.get_nav_title())
        item.setToolTip(f"{tool.get_name()}\n{tool.get_description()}")
        self.nav_list.addItem(item)

        self.stack.addWidget(tool)

    def _on_nav_changed(self, index):
        """导航栏切换时激活对应视图。"""
        if 0 <= index < len(self._tools):
            self.stack.setCurrentIndex(index)
            self._tools[index].on_activate()

    def closeEvent(self, event):
        """窗口关闭时统一取消所有视图的后台任务，避免孤儿线程/资源泄漏。"""
        for tool in self._tools:
            stop = getattr(tool, 'stop_worker', None)
            if callable(stop):
                stop()
        super().closeEvent(event)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    window = ToolboxApp()
    window.show()
    sys.exit(app.exec())
