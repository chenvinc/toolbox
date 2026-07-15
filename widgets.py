"""自定义 UI 控件 — 动画按钮、进度条、Toast 通知和文件拖放区。"""

import os

from PySide6.QtWidgets import (
    QPushButton, QProgressBar, QFrame, QLabel,
    QVBoxLayout, QFileDialog, QToolTip,
)
from PySide6.QtCore import (
    Qt, Signal, QTimer,
    QPropertyAnimation, QEasingCurve, QVariantAnimation, QPoint,
)

from theme import Theme


class AppButton(QPushButton):
    """统一按钮样式：圆角矩形、可用/不可用、提示原因和主题驱动。"""

    def __init__(self, text, default_height=44, theme=None):
        """初始化按钮，设定默认高度、主题和默认交互状态。"""
        super().__init__(text)
        self._default_height = default_height
        if default_height is not None:
            self.setFixedHeight(default_height)
        self._theme = theme if theme is not None else Theme()
        self._can_click = True
        self._disabled_reason = ""
        self._loading = False
        self._original_text = text
        self._update_cursor()
        self.update_style()

    def set_theme(self, theme):
        self._theme = theme
        self.update_style()

    def set_actionable(self, actionable, reason=""):
        """设置按钮是否可操作，并在不可操作时保存提示原因。"""
        self._can_click = actionable
        self._disabled_reason = reason
        super().setEnabled(actionable)
        self._update_cursor()
        self.update_style()

    def _update_cursor(self):
        self.setCursor(Qt.PointingHandCursor if self._can_click else Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus if self._can_click else Qt.NoFocus)

    def setEnabled(self, enabled):
        self.set_actionable(enabled, "")

    def update_style(self):
        t = self._theme
        if self._can_click and not self._loading:
            bg = t.accent
            hover = t.accent_light
            pressed = t.accent_dark
            fg = "white"
        else:
            bg = t.disabled_btn_bg
            hover = bg
            pressed = bg
            fg = "rgba(255,255,255,0.75)"

        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: none; "
            f"border-radius: 14px; padding: 0 18px; min-height: {self._default_height}px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:pressed {{ background: {pressed}; }}"
        )

    def mousePressEvent(self, event):
        if not self._can_click or self._loading:
            if self._disabled_reason:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    self._disabled_reason,
                    self,
                )
            event.ignore()
            return
        super().mousePressEvent(event)

    def set_loading(self, loading, reason="正在处理中..."):
        self._loading = loading
        if loading:
            self._original_text = self.text()
            self.setText("转换中...")
            self.set_actionable(False, reason)
        else:
            self.setText(self._original_text)
            self.set_actionable(True, "")


class AnimatedButton(AppButton):
    """带有按压高度动画和加载状态的主操作按钮。"""

    def __init__(self, text, default_height=50, theme=None):
        """初始化按钮，设定默认高度和文本。"""
        super().__init__(text, default_height=default_height, theme=theme)

    def mousePressEvent(self, event):
        if not self._can_click or self._loading:
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)
        self._animate_height(int(self._default_height * 0.92), 100)

    def mouseReleaseEvent(self, event):
        if not self._loading:
            super().mouseReleaseEvent(event)
            self._animate_height(self._default_height, 200)

    def _animate_height(self, target, duration):
        """同时动画 minimumHeight 和 maximumHeight 实现高度变化。"""
        self._height_anim = QPropertyAnimation(self, b"minimumHeight")
        self._height_anim.setDuration(duration)
        self._height_anim.setStartValue(self.height())
        self._height_anim.setEndValue(target)
        self._height_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._height_anim.start()
        self._height_anim2 = QPropertyAnimation(self, b"maximumHeight")
        self._height_anim2.setDuration(duration)
        self._height_anim2.setStartValue(self.height())
        self._height_anim2.setEndValue(target)
        self._height_anim2.setEasingCurve(QEasingCurve.OutCubic)
        self._height_anim2.start()

    def set_loading(self, loading, reason="正在处理中..."):
        """切换按钮的加载状态。"""
        super().set_loading(loading, reason)


class AnimatedProgressBar(QProgressBar):
    """带有平滑过渡动画的进度条。"""

    def __init__(self):
        """初始化进度条及其内部的值变化动画。"""
        super().__init__()
        self._anim = QVariantAnimation()
        self._anim.valueChanged.connect(self._on_anim_value)

    def setValueAnimated(self, val):
        """以动画方式过渡到目标进度值。"""
        self._anim.stop()
        self._anim.setDuration(300)
        self._anim.setStartValue(self.value())
        self._anim.setEndValue(val)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def _on_anim_value(self, val):
        """动画值变化回调，将浮点值转为整数后设置到进度条。"""
        self.setValue(int(val))


class ToastNotification(QFrame):
    """从窗口顶部滑入的短暂提示消息框（设计为全局固定风格，不随主题变化）。"""

    def __init__(self, parent, theme=None):
        """初始化 Toast 组件，预设显示和隐藏的位移动画。"""
        super().__init__(parent)
        self._theme = theme
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._apply_label_style()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._apply_frame_style()
        self._show_anim = QPropertyAnimation(self, b"pos")
        self._show_anim.setDuration(200)
        self._show_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hide_anim = QPropertyAnimation(self, b"pos")
        self._hide_anim.setDuration(200)
        self._hide_anim.setEasingCurve(QEasingCurve.InCubic)
        self._hide_anim.finished.connect(self.hide)
        self.hide()

    def _apply_label_style(self):
        if self._theme:
            color = self._theme.toast_text
        else:
            color = "white"
        self._label.setStyleSheet(
            f"color: {color}; font-size: 13px; padding: 14px 18px; "
            "background: transparent;"
        )

    def _apply_frame_style(self):
        if self._theme:
            bg = self._theme.toast_bg
        else:
            bg = "rgba(0,0,0,0.80)"
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border-radius: 12px; }}"
        )

    def show_message(self, text, success=True, duration=3000):
        """显示一条 Toast 消息。

        消息从窗口顶部滑入，停留指定时间后自动滑出隐藏。
        """
        prefix = "✅ " if success else "❌ "
        self._label.setText(prefix + text)
        self.adjustSize()
        self.setFixedWidth(min(self.width() + 20, self.parent().width() - 40))
        x = (self.parent().width() - self.width()) // 2
        self.move(x, -self.height())
        self.show()
        self.raise_()
        self._show_anim.stop()
        self._show_anim.setStartValue(QPoint(x, -self.height()))
        self._show_anim.setEndValue(QPoint(x, 16))
        self._show_anim.start()
        QTimer.singleShot(duration, self._start_hide)

    def _start_hide(self):
        """启动隐藏动画，将 Toast 从窗口顶部滑出。"""
        x = self.x()
        self._hide_anim.stop()
        self._hide_anim.setStartValue(QPoint(x, 16))
        self._hide_anim.setEndValue(QPoint(x, -self.height()))
        self._hide_anim.start()


class DropZone(QFrame):
    """支持点击选择和拖拽放入的文件选择区域。"""

    file_selected = Signal(str)

    def __init__(self, placeholder_text, file_filter="", compact=False, theme=None):
        """初始化文件拖放区域。"""
        super().__init__()
        self._theme = theme
        self.setAcceptDrops(True)
        self._compact = compact
        self._file_filter = file_filter
        self._placeholder = placeholder_text
        layout = QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(14, 0, 14, 0)
            self.setFixedHeight(48)
        else:
            layout.setContentsMargins(24, 20, 24, 20)
            self.setMinimumHeight(72)
        self.label = QLabel(placeholder_text)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style()

    def _apply_style(self):
        """根据当前主题应用正常状态和拖拽状态的样式表，同时更新标签颜色。"""
        t = self._theme
        db = t.dashed_border if t else "#C0C0CC"
        ib = t.input_bg if t else "#F5F5F7"
        self._normal_style = (
            f"QFrame {{ background: {ib}; border: 2px dashed {db}; "
            f"border-radius: 12px; }}"
            f"QFrame:hover {{ border-color: {t.accent if t else '#007AFF'}; "
            f"background: {t.hover_bg if t else '#EDF4FF'}; }}"
        )
        self._drag_style = (
            f"QFrame {{ background: {t.hover_bg if t else '#EDF4FF'}; "
            f"border: 2px solid {t.accent if t else '#007AFF'}; border-radius: 12px; }}"
        )
        self.setStyleSheet(self._normal_style)

        if self.label.text() == self._placeholder:
            text_color = t.drop_text if t else "#8E8E93"
            self.label.setStyleSheet(
                f"color: {text_color}; font-size: 13px; "
                "background: transparent; border: none;"
            )
        else:
            ac = t.drop_file_text if t else "#007AFF"
            self.label.setStyleSheet(
                f"color: {ac}; font-size: 13px; font-weight: bold; "
                "background: transparent; border: none;"
            )

    def mousePressEvent(self, event):
        """左键点击时打开文件选择对话框。"""
        if event.button() == Qt.LeftButton:
            self._open_dialog()

    def dragEnterEvent(self, event):
        """拖拽进入时检查是否包含文件 URL，若是则接受并切换拖拽样式。"""
        if event.mimeData().hasUrls():
            event.accept()
            self.setStyleSheet(self._drag_style)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """拖拽离开时恢复正常样式。"""
        self.setStyleSheet(self._normal_style)

    def dropEvent(self, event):
        """处理文件放下事件，取第一个文件路径并设置。"""
        self.setStyleSheet(self._normal_style)
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.set_file(path)
            self.file_selected.emit(path)

    def set_file(self, path):
        """设置已选文件，更新标签文本为文件名并以主题色高亮显示。"""
        self.label.setText(os.path.basename(path))
        self._apply_style()

    def _open_dialog(self):
        """打开文件选择对话框，选择后设置文件并发射 file_selected 信号。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", self._file_filter
        )
        if path:
            self.set_file(path)
            self.file_selected.emit(path)
