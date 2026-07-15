import os
import sys
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QStackedWidget,
    QHBoxLayout, QListWidgetItem, QFrame, QVBoxLayout,
    QLabel, QWidget
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPalette, QIcon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from word_2_slide_tool import Quiz2SlideTool
from similarity_checker import SimilarityCheckerTool
from base_tool import BaseTool
from theme import Theme


class ToolboxApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.theme = Theme()
        QApplication.setWindowIcon(QIcon("./assets/images/logo.png"))
        self.setWindowTitle("ALL IN ONE TOOLBOX")
        self.resize(960, 660)
        self.setMinimumSize(800, 550)

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
        self.nav_list.setSpacing(4)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        sidebar_layout.addWidget(self.nav_list)

        sidebar_layout.addStretch()

        self.stack = QStackedWidget()

        root.addWidget(self.sidebar)
        root.addWidget(self.stack, 1)

        self._register_tools()
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
            "padding: 20px 0; background: transparent; border: none;"
        )

        self.nav_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            f"QListWidget::item {{ padding: 12px 20px; font-size: 14px; "
            f"color: {t.nav_text}; border: none; border-radius: 6px; "
            f"margin: 2px 8px; }}"
            f"QListWidget::item:selected {{ background: {t.nav_selected_bg}; "
            f"color: {t.nav_selected_text}; font-weight: bold; }}"
            f"QListWidget::item:hover:!selected {{ background: {t.nav_hover_bg}; }}"
        )

        self.stack.setStyleSheet(
            "QStackedWidget { background: transparent; border: none; border-radius: 12px; }"
        )

    def _register_tools(self):
        """注册工具箱中的所有工具。"""
        self._add_tool(Quiz2SlideTool())
        self._add_tool(SimilarityCheckerTool())

    def _add_tool(self, tool):
        """将工具添加到导航栏和堆栈中。"""
        self._tools.append(tool)

        item = QListWidgetItem(tool.get_name())
        item.setToolTip(tool.get_description())
        self.nav_list.addItem(item)

        self.stack.addWidget(tool)

    def _on_nav_changed(self, index):
        """导航栏切换时激活对应工具。"""
        if 0 <= index < len(self._tools):
            self.stack.setCurrentIndex(index)
            self._tools[index].on_activate()

    def closeEvent(self, event):
        """窗口关闭时统一停止所有工具的后台线程，避免孤儿线程/资源泄漏。"""
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
