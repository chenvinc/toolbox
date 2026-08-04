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
import threading
import faulthandler

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QStackedWidget,
    QHBoxLayout, QListWidgetItem, QFrame, QVBoxLayout,
    QLabel, QWidget,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPalette, QIcon, QFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.infra.qt_task_runner import QtTaskRunner
from ui.infra.qt_event_emitter import QtEventEmitter
from ui.composition import build_view_models
from ui.views.slide_view import SlideView
from ui.views.similarity_view import SimilarityView
from ui.views.json_exam_view import JsonExamView
from ui.views.pdf_slide_view import PdfSlideView
from ui.views.pdf_word_view import PdfWordView
from theme import Theme


class ToolboxApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.theme = Theme()
        self._apply_global_font()  # 仅字体
        QApplication.setWindowIcon(QIcon("./assets/images/logo.png"))
        self.setWindowTitle("ALL IN ONE TOOLBOX")
        self.resize(960, 660)
        self.setMinimumSize(800, 550)

        # ── 依赖装配（DI / VM 构造已抽至 ui/composition.build_view_models） ──
        self._task_runner = QtTaskRunner()
        self._event_emitter = QtEventEmitter()
        slide_vm, sim_vm, exam_vm, pdf_vm, word_vm = build_view_models(
            self._task_runner, self._event_emitter
        )

        # ── 窗口布局（导航 + 堆栈） ──
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

        self._register_tools(slide_vm, sim_vm, exam_vm, pdf_vm, word_vm)
        self.nav_list.setCurrentRow(0)
        self._restyle_all()
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_theme_changed
        )
        self._on_theme_changed()

    def _apply_global_font(self):
        """全局统一字体：微软雅黑（含跨平台回退），基准 12px。

        仅负责字体；依赖装配与窗口布局见 ``__init__`` / ``ui/composition``（N-01 根因）。
        """
        font = QFont()
        font.setFamilies([
            "Microsoft YaHei", "PingFang SC", "Microsoft YaHei UI",
            "SimHei", "Heiti SC", "sans-serif",
        ])
        font.setPointSize(12)
        app = QApplication.instance()
        if app is not None:
            app.setFont(font)

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

    def _register_tools(self, slide_vm, sim_vm, exam_vm, pdf_vm, word_vm):
        """注册工具箱中的所有视图（持有对应 ViewModel）。"""
        self._add_tool(SlideView(slide_vm))
        self._add_tool(SimilarityView(sim_vm))
        self._add_tool(JsonExamView(exam_vm))
        self._add_tool(PdfSlideView(pdf_vm))
        self._add_tool(PdfWordView(word_vm))

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
        shutdown_logging()
        super().closeEvent(event)


# 模块级句柄/守卫：configure_logging 持有 crash.log 文件对象，正常退出由
# shutdown_logging 关闭；_qt_handler_guard 防止 Qt 消息处理器重入死循环。
_qt_handler_guard = threading.local()
_crash_log_fh = None


def configure_logging() -> str:
    """配置根日志：RotatingFileHandler 落盘到用户数据目录 logs/toolbox.log
    （跨平台，不污染项目目录），保留 stderr 便于开发期观测；并安装
    sys.excepthook 把未捕获异常写入日志（A-05 整改：补齐文件 handler + 崩溃兜底）。

    返回日志文件绝对路径，便于自检 / 测试。
    """
    import logging.handlers

    from PySide6.QtCore import QStandardPaths, qInstallMessageHandler, QtMsgType

    _log_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not _log_dir:
        _log_dir = os.path.dirname(os.path.abspath(__file__))
    _log_dir = os.path.join(_log_dir, "logs")
    os.makedirs(_log_dir, exist_ok=True)
    _log_path = os.path.join(_log_dir, "toolbox.log")

    _root = logging.getLogger()
    _root.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    _rfh = logging.handlers.RotatingFileHandler(
        _log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    _rfh.setFormatter(_fmt)
    _root.addHandler(_rfh)
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(_fmt)
    _root.addHandler(_sh)

    def _excepthook(exc_type, exc_value, exc_tb):
        """记录未捕获异常到日志，避免崩溃后无迹可寻。"""
        logging.getLogger("uncaught").critical(
            "未捕获异常", exc_info=(exc_type, exc_value, exc_tb)
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # Qt 内部消息（qWarning/qCritical）转发到 logging，避免 C++ 层报错只在
    # stderr 闪现、打包为 GUI 后被丢弃（R-5 补充：sys.excepthook 仅覆盖主线程）。
    # 加重入保护：若日志轮转/写入过程中再次触发 Qt 消息，直接丢弃，避免
    # 「Qt 警告 → logging → RotatingFileHandler 轮转 → 又触发 Qt 警告」的死循环。
    def _qt_message_handler(mode, context, message):
        if getattr(_qt_handler_guard, "active", False):
            return
        _qt_handler_guard.active = True
        try:
            level = {
                QtMsgType.QtDebugMsg: logging.DEBUG,
                QtMsgType.QtInfoMsg: logging.INFO,
                QtMsgType.QtWarningMsg: logging.WARNING,
                QtMsgType.QtCriticalMsg: logging.ERROR,
                QtMsgType.QtFatalMsg: logging.CRITICAL,
            }.get(mode, logging.WARNING)
            logging.getLogger("qt").log(level, "%s (%s:%d)", message, context.file, context.line)
        finally:
            _qt_handler_guard.active = False

    qInstallMessageHandler(_qt_message_handler)

    # 原生崩溃（segfault 等）最低限度留痕到 crash.log（R-5 补充）。
    # 句柄由模块级 _crash_log_fh 持有，正常退出时由 shutdown_logging() 关闭，
    # 避免未关闭句柄在 Windows 上阻塞日志目录清理/移动；重复调用本函数时先
    # disable + 关闭旧句柄，杜绝「两个句柄指向同一文件」。
    global _crash_log_fh
    if _crash_log_fh is not None:
        faulthandler.disable()
        try:
            _crash_log_fh.close()
        except Exception:
            pass
        _crash_log_fh = None
    _crash_log = os.path.join(_log_dir, "crash.log")
    _crash_log_fh = open(_crash_log, "a", encoding="utf-8")
    faulthandler.enable(file=_crash_log_fh)
    logging.getLogger("toolbox").info("崩溃留痕已启用：%s", _crash_log)

    return _log_path


def shutdown_logging() -> None:
    """正常退出时释放日志资源：先 disable faulthandler（停止写 fd），再关闭
    crash.log 句柄，避免进程退出后仍持有未关闭的文件句柄（Windows 上会阻止
    目录清理/移动）。与 configure_logging 对称。"""
    global _crash_log_fh
    try:
        faulthandler.disable()
    except Exception:
        pass
    if _crash_log_fh is not None:
        try:
            _crash_log_fh.close()
        except Exception:
            pass
        _crash_log_fh = None


if __name__ == "__main__":
    log_path = configure_logging()
    logging.getLogger("toolbox").info("应用启动，日志写入 %s", log_path)
    app = QApplication(sys.argv)
    window = ToolboxApp()
    window.show()
    sys.exit(app.exec())
