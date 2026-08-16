"""自定义 UI 控件 — 动画按钮、进度条、Toast 通知和文件拖放区。"""

from __future__ import annotations

import os
import re

from PySide6.QtWidgets import (
    QPushButton, QProgressBar, QFrame, QLabel,
    QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy, QFileDialog, QToolTip,
    QDoubleSpinBox, QSpinBox, QLineEdit, QDialog, QPlainTextEdit,
)
from PySide6.QtCore import (
    Qt, Signal, QTimer, QEvent,
    QPropertyAnimation, QEasingCurve, QVariantAnimation, QPoint,
)
from PySide6.QtGui import QMouseEvent, QDragEnterEvent, QDragLeaveEvent, QDropEvent

from theme import Theme


class AppButton(QPushButton):
    """统一按钮样式：圆角矩形、可用/不可用、提示原因和主题驱动。"""

    def __init__(self, text: str, default_height: int = 44, theme: Theme | None = None,
                 loading_text: str = "转换中...", variant: str = "primary") -> None:
        """初始化按钮，设定默认高度、主题和默认交互状态。

        loading_text：进入加载态时显示的文案，默认“转换中...”（Word→PPT 场景）。
        调用方应按业务语义传入，如查重场景传“检测中...”。
        variant：按钮规范变体，"primary" 主按钮（蓝底白字，核心执行操作）；
        "secondary" 次级按钮（白底蓝边框蓝字，辅助操作）。
        """
        super().__init__(text)
        self._default_height = default_height
        if default_height is not None:
            self.setFixedHeight(default_height)
        self._theme = theme if theme is not None else Theme()
        self._variant = variant
        self._can_click = True
        self._disabled_reason = ""
        self._loading = False
        self._original_text = text
        self._loading_text = loading_text
        # 样式依赖的属性已就绪，此后 changeEvent 才可安全同步
        self._style_ready = True
        self._update_cursor()
        self.update_style()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update_style()

    def set_actionable(self, actionable: bool, reason: str = "") -> None:
        """设置按钮是否可操作，并在不可操作时给出提示原因。

        reason 会同步为 tooltip：Qt **不向 disabled 控件派发鼠标事件**，
        因此点击弹提示的老做法在真正禁用时永远不会触发；而 ToolTip 事件
        仍会派发给 disabled 控件，悬停提示才是禁用原因唯一可靠的呈现方式。
        """
        self._disabled_reason = "" if actionable else reason
        if self.isEnabled() == actionable:
            # enabled 未变化时 Qt 不会发 EnabledChange，需手动同步（如仅更新 reason）
            self._sync_enabled_state()
        else:
            self.setEnabled(actionable)  # 经 changeEvent 统一同步

    def _sync_enabled_state(self) -> None:
        """把 Qt 原生 enabled 状态同步到内部视觉状态（光标 / 样式 / 禁用原因提示）。

        设计约定：``setEnabled(False)`` 只翻转可用态、**不改动** ``_disabled_reason``；
        reason 的生命周期完全由 ``set_actionable`` 管理（仅在 ``set_actionable(False, reason)``
        时写入、在重新 ``set_actionable(True)`` 或 enabled 变回 True 时清空）。这样外部直接
        ``setEnabled(False)`` 不会意外清空上一次留下的禁用原因，行为可预期。
        """
        self._can_click = self.isEnabled()
        if self._can_click:
            # 已可用则不存在“禁用原因”
            self._disabled_reason = ""
        self.setToolTip(self._disabled_reason)
        self._update_cursor()
        self.update_style()

    def changeEvent(self, event: QEvent) -> None:
        """响应 Qt 原生 enabled 变化，保持视觉状态与 enabled 一致。

        取代此前对 ``setEnabled`` 的重写——那会把调用方的禁用原因静默清空，
        且违反 Qt API 契约（``setEnabled`` 非虚函数语义被改写）。改用本钩子
        被动同步后，任何调用方（含 Qt 内部、QWidget 级联禁用）都能正确生效。
        """
        if event.type() == QEvent.Type.EnabledChange and getattr(self, "_style_ready", False):
            self._sync_enabled_state()
        super().changeEvent(event)

    def _update_cursor(self) -> None:
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._can_click else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self._can_click else Qt.FocusPolicy.NoFocus)

    def update_style(self) -> None:
        t = self._theme
        if self._can_click and not self._loading:
            if self._variant == "secondary":
                bg = t.secondary_bg
                fg = t.accent
                border = f"1px solid {t.accent}"
                hover = t.hover_blue
                pressed = t.hover_blue
            else:
                bg = t.accent
                fg = "white"
                border = "none"
                hover = t.accent_light
                pressed = t.accent_dark
        else:
            bg = t.disabled_btn_bg
            fg = "#bfbfbf"
            border = "none"
            hover = bg
            pressed = bg

        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: {border}; "
            f"border-radius: {t.radius}px; padding: 0 18px; "
            f"min-height: {self._default_height}px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:pressed {{ background: {pressed}; }}"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
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

    def set_loading(self, loading: bool, reason: str = "正在处理中...") -> None:
        # 幂等保护：仅在“非加载态 → 加载态”的首次跃迁时保存原始文案，
        # 避免重复 set_loading(True)（如 _on_check 与 _on_started 各调一次）
        # 把已切换为加载文案的文本误存为 _original_text，导致恢复时回不到初始文案。
        if loading and not self._loading:
            self._original_text = self.text()
        self._loading = loading
        if loading:
            self.setText(self._loading_text)
            self.set_actionable(False, reason)
        else:
            self.setText(self._original_text)
            self.set_actionable(True, "")


class AnimatedButton(AppButton):
    """带有按压高度动画和加载状态的主操作按钮。"""

    def __init__(self, text: str, default_height: int = 50, theme: Theme | None = None,
                 loading_text: str = "转换中...", variant: str = "primary") -> None:
        """初始化按钮，设定默认高度和文本。

        loading_text 透传至 AppButton，决定加载态显示的文案。
        variant 透传至 AppButton，决定主/次按钮规范。
        """
        super().__init__(text, default_height=default_height, theme=theme,
                         loading_text=loading_text, variant=variant)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._can_click or self._loading:
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)
        self._animate_height(int(self._default_height * 0.92), 100)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._loading:
            super().mouseReleaseEvent(event)
            self._animate_height(self._default_height, 200)

    def _animate_height(self, target: int, duration: int) -> None:
        """同时动画 minimumHeight 和 maximumHeight 实现高度变化。"""
        self._height_anim = QPropertyAnimation(self, b"minimumHeight")
        self._height_anim.setDuration(duration)
        self._height_anim.setStartValue(self.height())
        self._height_anim.setEndValue(target)
        self._height_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._height_anim.start()
        self._height_anim2 = QPropertyAnimation(self, b"maximumHeight")
        self._height_anim2.setDuration(duration)
        self._height_anim2.setStartValue(self.height())
        self._height_anim2.setEndValue(target)
        self._height_anim2.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._height_anim2.start()

    def set_loading(self, loading: bool, reason: str = "正在处理中...") -> None:
        """切换按钮的加载状态。"""
        super().set_loading(loading, reason)


class AnimatedProgressBar(QProgressBar):
    """带有平滑过渡动画的进度条。"""

    def __init__(self) -> None:
        """初始化进度条及其内部的值变化动画。"""
        super().__init__()
        self._anim = QVariantAnimation()
        self._anim.valueChanged.connect(self._on_anim_value)

    def setValueAnimated(self, val: int) -> None:
        """以动画方式过渡到目标进度值。"""
        self._anim.stop()
        self._anim.setDuration(300)
        self._anim.setStartValue(self.value())
        self._anim.setEndValue(val)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def _on_anim_value(self, val: float) -> None:
        """动画值变化回调，将浮点值转为整数后设置到进度条。"""
        self.setValue(int(val))


class StepperInput(QWidget):
    """左侧减号 + 中间数值输入框（去掉原生上下箭头）+ 右侧加号 步进控件。

    全项目统一：Quiz2Slide 的「字号」「自定义行距」与 Similarity 的「相似度阈值」
    共用同一组件，外观 1:1 一致。仅做渲染层包装：
    - 中间为 QDoubleSpinBox / QSpinBox：保留其 range/singleStep/decimals/value，
      仅隐藏原生箭头；value() 透传内部控件。
    - 中间为 QLineEdit：用调用方设置的 QDoubleValidator 约束，± 按钮按 step 增减并
      clamp 到 [min, max]，value() 解析文本返回 float（空/非法时回退 default_value）。
    所有圆角/边框/hover/聚焦/配色均来自全局主题令牌，不引入任何自定义样式参数。
    """

    valueChanged = Signal(float)

    def __init__(self, spin: QDoubleSpinBox | QSpinBox | QLineEdit | None = None,
                 theme: Theme | None = None, minus_text: str = "−", plus_text: str = "+",
                 min_val: float | None = None, max_val: float | None = None,
                 step: float = 1.0, decimals: int = 1, default_value: float = 0.0) -> None:
        super().__init__()
        self._theme = theme if theme is not None else Theme()
        self._min_val = min_val
        self._max_val = max_val
        self._step_val = step
        self._decimals = decimals
        self._default_value = default_value

        if spin is None:
            spin = QDoubleSpinBox()
        self._spin = spin
        self._spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # SpinBox 模式下 ± 按钮走 stepUp/stepDown，只会触发内部控件的信号；
        # 若不桥接，外层 valueChanged 永不发射（键盘输入同理），监听方收不到任何回调。
        # 桥接后两种模式（SpinBox / QLineEdit）对外行为一致，调用方无需感知内部实现。
        if isinstance(self._spin, (QDoubleSpinBox, QSpinBox)):
            # 以 self 作为 context 连接：StepperInput 销毁时连接自动断开，
            # 规避 lambda 隐式持有 self 在半销毁态被信号触发的风险
            # （PySide6 的 lambda 连接不随 receiver 销毁自动断开）。
            # PySide6 支持把 QObject 作为 context 传 connect（随接收者销毁自动断开）；
            # mypy 桩只声明 ConnectionType，故忽略。
            self._spin.valueChanged.connect(self._relay_value, self)  # type: ignore[arg-type]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.minus_button = QPushButton(minus_text)
        self.plus_button = QPushButton(plus_text)
        for b in (self.minus_button, self.plus_button):
            b.setFixedSize(28, 36)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.minus_button.clicked.connect(self._step_down)
        self.plus_button.clicked.connect(self._step_up)

        layout.addWidget(self.minus_button)
        layout.addWidget(self._spin, 1)
        layout.addWidget(self.plus_button)

        self.set_theme(self._theme)

    def _relay_value(self, v: float) -> None:
        # QDoubleSpinBox 发射 float、QSpinBox 发射 int，统一转 float 对外，
        # 使 valueChanged 契约（Signal(float)）在两种模式下一致。
        self.valueChanged.emit(float(v))

    # ── 主题 ──
    def set_theme(self, theme: Theme) -> None:
        """重新应用中间输入框与两侧按钮的全局规范样式（含隐藏原生箭头）。"""
        self._theme = theme
        self._spin.setStyleSheet(self._middle_style())
        btn = self._btn_style()
        self.minus_button.setStyleSheet(btn)
        self.plus_button.setStyleSheet(btn)

    def _middle_style(self) -> str:
        t = self._theme
        return (
            "QLineEdit, QDoubleSpinBox, QSpinBox {"
            f" padding: 4px 8px; border: 1px solid transparent; border-radius: {t.radius}px;"
            f" font-size: 13px; background: {t.input_bg}; color: {t.text_primary};"
            "}"
            # 彻底移除原生上下箭头（宽度/高度归零 + 清除箭头图像），消除重复调节控件
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,"
            " QSpinBox::up-button, QSpinBox::down-button {"
            " width: 0px; height: 0px; border: none; background: transparent; image: none; }"
            "QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow,"
            " QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0px; height: 0px; image: none; }"
            f"QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover {{ border-color: {t.accent}; }}"
            f"QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{"
            f" border: 1px solid {t.accent}; background: {t.card_bg}; }}"
        )

    def _btn_style(self) -> str:
        t = self._theme
        return (
            f"QPushButton {{ background: {t.secondary_bg}; color: {t.text_primary};"
            f" border: 1px solid {t.border}; border-radius: {t.radius}px; font-size: 16px; }}"
            f"QPushButton:hover {{ border-color: {t.accent}; color: {t.accent}; }}"
            f"QPushButton:pressed {{ background: {t.hover_blue}; }}"
            f"QPushButton:disabled {{ background: {t.disabled_btn_bg};"
            f" color: {t.text_placeholder}; border: 1px solid {t.border}; }}"
        )

    # ── 取值 ──
    def value(self) -> float:
        """返回当前数值：SpinBox 直接透传，QLineEdit 解析文本并 clamp。"""
        if isinstance(self._spin, (QDoubleSpinBox, QSpinBox)):
            return self._spin.value()
        try:
            val = float(self._spin.text())
        except ValueError:
            return self._default_value
        if self._min_val is not None:
            val = max(self._min_val, val)
        if self._max_val is not None:
            val = min(self._max_val, val)
        return val

    # ── 步进 ──
    def _step_up(self) -> None:
        self._step(1)

    def _step_down(self) -> None:
        self._step(-1)

    def _step(self, direction: int) -> None:
        if isinstance(self._spin, (QDoubleSpinBox, QSpinBox)):
            if direction > 0:
                self._spin.stepUp()
            else:
                self._spin.stepDown()
            return
        # QLineEdit 模式：按 step 增减并 clamp，保证数值范围与步长不变
        try:
            cur = float(self._spin.text()) if self._spin.text().strip() else self._default_value
        except ValueError:
            cur = self._default_value
        new = cur + direction * self._step_val
        if self._min_val is not None:
            new = max(self._min_val, new)
        if self._max_val is not None:
            new = min(self._max_val, new)
        new = round(new, self._decimals)
        self._spin.setText(f"{new:.{self._decimals}f}")
        self.valueChanged.emit(new)


class ToastNotification(QFrame):
    """从窗口顶部滑入的短暂提示消息框（设计为全局固定风格，不随主题变化）。"""

    def __init__(self, parent: QWidget, theme: Theme | None = None) -> None:
        """初始化 Toast 组件，预设显示和隐藏的位移动画。"""
        super().__init__(parent)
        self._theme = theme
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_label_style()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._apply_frame_style(True)
        self._show_anim = QPropertyAnimation(self, b"pos")
        self._show_anim.setDuration(200)
        self._show_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hide_anim = QPropertyAnimation(self, b"pos")
        self._hide_anim.setDuration(200)
        self._hide_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._hide_anim.finished.connect(self.hide)
        self.hide()

    def _apply_label_style(self) -> None:
        if self._theme:
            color = self._theme.toast_text
        else:
            color = "white"
        self._label.setStyleSheet(
            f"color: {color}; font-size: 13px; padding: 14px 18px; "
            "background: transparent;"
        )

    def _apply_frame_style(self, success: bool = True) -> None:
        if self._theme:
            bg = self._theme.danger if not success else self._theme.toast_bg
            radius = self._theme.radius
        else:
            bg = "rgba(0,0,0,0.80)"
            radius = 12
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border-radius: {radius}px; }}"
        )

    def show_message(self, text: str, success: bool = True, duration: int = 3000) -> None:
        """显示一条 Toast 消息。

        消息从窗口顶部滑入，停留指定时间后自动滑出隐藏。
        """
        prefix = "✅ " if success else "❌ "
        self._label.setText(prefix + text)
        self._apply_frame_style(success)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.setFixedWidth(min(self.width() + 20, parent.width() - 40))
            x = (parent.width() - self.width()) // 2
        else:
            x = 0
        self.move(x, -self.height())
        self.show()
        self.raise_()
        self._show_anim.stop()
        self._show_anim.setStartValue(QPoint(x, -self.height()))
        self._show_anim.setEndValue(QPoint(x, 16))
        self._show_anim.start()
        QTimer.singleShot(duration, self._start_hide)

    def _start_hide(self) -> None:
        """启动隐藏动画，将 Toast 从窗口顶部滑出。"""
        x = self.x()
        self._hide_anim.stop()
        self._hide_anim.setStartValue(QPoint(x, 16))
        self._hide_anim.setEndValue(QPoint(x, -self.height()))
        self._hide_anim.start()


class DropZone(QFrame):
    """支持点击选择、拖拽放入的单文件上传区。

    特性：拖拽悬浮反馈（背景淡蓝 + 边框高亮）、单文件删除按钮、
    长文件名省略 + hover 完整路径提示、按 file_filter 校验格式（不合规发 invalid_file）。
    """

    file_selected = Signal(str)
    file_cleared = Signal()
    invalid_file = Signal(str)

    def __init__(self, placeholder_text: str, file_filter: str = "", compact: bool = False,
                 theme: Theme | None = None, variant: str = "secondary") -> None:
        """初始化单文件拖放区域。

        variant：视觉层级变体。
        - "primary"：主文档上传框，使用主色虚线边框（强调、突出主次）。
        - "secondary"（默认）：中性虚线边框，作为辅助上传框。
        两种变体在 hover / 拖拽时均切换为主色实线边框 + 悬浮底色。
        """
        super().__init__()
        # theme 省略时回退全局单例：签名允许 None，实现就必须真的支持 None
        # （此前样式代码只对部分令牌做了兜底，theme=None 会在 t.radius 处崩溃）。
        self._theme = theme if theme is not None else Theme()
        self.setAcceptDrops(True)
        self._compact = compact
        self._file_filter = file_filter
        self._variant = variant
        self._placeholder = placeholder_text
        self._file_path = ""
        self._allowed_exts = self._parse_exts(file_filter)

        layout = QHBoxLayout(self)
        if compact:
            layout.setContentsMargins(14, 0, 14, 0)
            self.setFixedHeight(48)
        else:
            layout.setContentsMargins(24, 0, 16, 0)
            self.setMinimumHeight(64)
        layout.setSpacing(8)

        self._text_label = QLabel(placeholder_text)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._text_label, 1)

        self._del_btn = QPushButton("✕")
        self._del_btn.setFixedSize(20, 20)
        self._del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_btn.clicked.connect(self.clear)
        self._del_btn.setVisible(False)
        layout.addWidget(self._del_btn)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    @staticmethod
    def _parse_exts(file_filter: str) -> list[str]:
        """从 'Word 文档 (*.docx)' 形式解析出允许的后缀列表（小写）。"""
        if not file_filter:
            return []
        return [e.lower() for e in re.findall(r"\*\.(\w+)", file_filter)]

    def _is_allowed(self, path: str) -> bool:
        if not self._allowed_exts:
            return True
        low = path.lower()
        return any(low.endswith("." + e) for e in self._allowed_exts)

    def _del_btn_style(self) -> str:
        t = self._theme
        return (
            f"QPushButton {{ background: {t.secondary_bg}; color: {t.text_secondary}; "
            f"border: none; border-radius: 10px; font-size: 12px; }}"
            f"QPushButton:hover {{ color: white; background: {t.danger}; }}"
        )

    def _apply_style(self) -> None:
        """根据当前主题与 variant 应用正常/拖拽样式，同时更新标签与删除按钮。"""
        t = self._theme
        if self._variant == "primary":
            # 主文档：主色虚线边框，凸显“主”的地位
            normal_border = f"2px dashed {t.accent}"
        else:
            # 辅助：中性虚线边框，弱化以形成主次对比
            normal_border = f"2px dashed {t.dashed_border}"
        self._normal_style = (
            f"QFrame {{ background: {t.input_bg}; border: {normal_border}; "
            f"border-radius: {t.radius}px; }}"
            f"QFrame:hover {{ border-color: {t.accent}; "
            f"background: {t.hover_blue}; }}"
        )
        self._drag_style = (
            f"QFrame {{ background: {t.hover_blue}; "
            f"border: 2px solid {t.accent}; border-radius: {t.radius}px; }}"
        )
        self.setStyleSheet(self._normal_style)
        self._del_btn.setStyleSheet(self._del_btn_style())

        if self._file_path:
            self._text_label.setStyleSheet(
                f"color: {t.drop_file_text}; font-size: 13px; font-weight: bold; "
                "background: transparent; border: none;"
            )
        else:
            self._text_label.setStyleSheet(
                f"color: {t.drop_text}; font-size: 13px; "
                "background: transparent; border: none;"
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键点击空白处打开文件选择对话框；点击删除按钮不触发。"""
        child = self.childAt(event.pos())
        if isinstance(child, QPushButton):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_dialog()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """拖拽进入时检查是否包含文件 URL，若是则接受并切换拖拽样式。"""
        if event.mimeData().hasUrls():
            event.accept()
            self.setStyleSheet(self._drag_style)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """拖拽离开时恢复正常样式。"""
        self.setStyleSheet(self._normal_style)

    def dropEvent(self, event: QDropEvent) -> None:
        """处理文件放下事件，取第一个文件路径并设置。"""
        self.setStyleSheet(self._normal_style)
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if self.set_file(path):
                self.file_selected.emit(path)

    def set_file(self, path: str) -> bool:
        """校验通过后设置文件，更新标签/工具提示并暴露完整路径。返回是否成功。"""
        if not self._is_allowed(path):
            self.invalid_file.emit(path)
            return False
        self._file_path = path
        base = os.path.basename(path)
        fm = self._text_label.fontMetrics()
        elided = fm.elidedText(base, Qt.TextElideMode.ElideMiddle, 280)
        self._text_label.setText(elided)
        self._text_label.setToolTip(path)
        self._del_btn.setVisible(True)
        self._apply_style()
        return True

    def clear(self) -> None:
        """清空已选文件，恢复占位态，并广播 file_cleared。"""
        if not self._file_path:
            return
        self._file_path = ""
        self._text_label.setText(self._placeholder)
        self._text_label.setToolTip("")
        self._del_btn.setVisible(False)
        self._apply_style()
        self.file_cleared.emit()

    def get_path(self) -> str:
        return self._file_path

    def _open_dialog(self) -> None:
        """打开单文件选择对话框，选择后校验、设置并发射 file_selected。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", self._file_filter
        )
        if path and self.set_file(path):
            self.file_selected.emit(path)


class MultiDropZone(QFrame):
    """多文件上传区：文件列表展示、单文件删除、批量清空、格式校验、拖拽悬浮反馈。

    每次文件集合变化（新增 / 删除 / 清空）均广播 files_selected(当前完整列表)；
    单个文件格式不合规时广播 invalid_file（由视图层弹轻量 Toast）。

    注意：与 DropZone 的 API 不对称——本类**没有**独立的 ``file_cleared`` 信号，
    清空事件统一通过 ``files_selected([])``（空列表）表达。调用方若需区分
    「用户主动清空」与「程序调用 clear_all()」，应据此约定自行判断，而非期待
    独立信号。此处刻意不为对称性补信号，避免引入冗余 API。
    """

    files_selected = Signal(list)
    invalid_file = Signal(str)

    def __init__(self, placeholder_text: str, file_filter: str = "", compact: bool = False,
                 theme: Theme | None = None, variant: str = "secondary") -> None:
        super().__init__()
        # 同 DropZone：theme 省略时回退全局单例，保证签名与实现一致。
        self._theme = theme if theme is not None else Theme()
        self.setAcceptDrops(True)
        self._compact = compact
        self._file_filter = file_filter
        self._variant = variant
        self._placeholder = placeholder_text
        self._paths: list[str] = []
        self._allowed_exts = self._parse_exts(file_filter)

        layout = QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(14, 10, 14, 10)
            self.setMinimumHeight(56)
        else:
            layout.setContentsMargins(20, 16, 20, 16)
            self.setMinimumHeight(80)
        layout.setSpacing(8)

        self._placeholder_label = QLabel(placeholder_text)
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder_label)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        layout.addWidget(self._list_widget)

        self._clear_btn = AppButton(
            "清空全部", default_height=28, theme=theme, variant="secondary"
        )
        self._clear_btn.setFixedWidth(96)
        self._clear_btn.clicked.connect(self.clear_all)
        layout.addWidget(self._clear_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()
        self._refresh()

    @staticmethod
    def _parse_exts(file_filter: str) -> list[str]:
        if not file_filter:
            return []
        return [e.lower() for e in re.findall(r"\*\.(\w+)", file_filter)]

    def _is_allowed(self, path: str) -> bool:
        if not self._allowed_exts:
            return True
        low = path.lower()
        return any(low.endswith("." + e) for e in self._allowed_exts)

    def _apply_style(self) -> None:
        t = self._theme
        if self._variant == "primary":
            normal_border = f"2px dashed {t.accent}"
        else:
            normal_border = f"2px dashed {t.dashed_border}"
        self._normal_style = (
            f"QFrame {{ background: {t.input_bg}; border: {normal_border}; "
            f"border-radius: {t.radius}px; }}"
            f"QFrame:hover {{ border-color: {t.accent}; background: {t.hover_blue}; }}"
        )
        self._drag_style = (
            f"QFrame {{ background: {t.hover_blue}; border: 2px solid {t.accent}; "
            f"border-radius: {t.radius}px; }}"
        )
        self.setStyleSheet(self._normal_style)
        self._placeholder_label.setStyleSheet(
            f"color: {t.drop_text}; font-size: 13px; "
            "background: transparent; border: none;"
        )

    def _row_style(self) -> str:
        t = self._theme
        return (
            f"QFrame {{ background: {t.secondary_bg}; "
            f"border: none; border-radius: {t.radius}px; padding: 6px 10px; }}"
            f"QLabel {{ color: {t.text_primary}; "
            f"font-size: 13px; background: transparent; border: none; }}"
        )

    def _del_btn_style(self) -> str:
        t = self._theme
        return (
            f"QPushButton {{ background: {t.secondary_bg}; color: {t.text_secondary}; "
            f"border: none; border-radius: 10px; font-size: 12px; }}"
            f"QPushButton:hover {{ color: white; background: {t.danger}; }}"
        )

    def _refresh(self) -> None:
        """重建文件列表行（含省略名 + 完整路径 tooltip + 单删按钮），并按有无文件切换占位/清空。"""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not self._paths:
            self._placeholder_label.setVisible(True)
            self._list_widget.setVisible(False)
            self._clear_btn.setVisible(False)
            return
        self._placeholder_label.setVisible(False)
        self._list_widget.setVisible(True)
        self._clear_btn.setVisible(True)
        row_style = self._row_style()
        del_style = self._del_btn_style()
        for path in self._paths:
            row = QFrame()
            row.setStyleSheet(row_style)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            base = os.path.basename(path)
            fm = row.fontMetrics()
            elided = fm.elidedText(base, Qt.TextElideMode.ElideMiddle, 240)
            name = QLabel(elided)
            name.setToolTip(path)
            name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            rl.addWidget(name, 1)
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(20, 20)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setStyleSheet(del_style)
            del_btn.clicked.connect(lambda _=False, p=path: self._remove_path(p))
            rl.addWidget(del_btn)
            self._list_layout.addWidget(row)

    def _remove_path(self, path: str) -> None:
        if path in self._paths:
            self._paths.remove(path)
            self._refresh()
            self.files_selected.emit(list(self._paths))

    def clear_all(self) -> None:
        if not self._paths:
            return
        self._paths = []
        self._refresh()
        self.files_selected.emit([])

    def get_paths(self) -> list[str]:
        return list(self._paths)

    def _add_files(self, paths: list[str]) -> None:
        changed = False
        for p in paths:
            if not self._is_allowed(p):
                self.invalid_file.emit(p)
            elif p not in self._paths:
                self._paths.append(p)
                changed = True
        if changed:
            self._refresh()
            self.files_selected.emit(list(self._paths))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """点击空白处（非按钮）打开文件选择对话框，便于继续追加文件。"""
        child = self.childAt(event.pos())
        if isinstance(child, QPushButton):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_dialog()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.accept()
            self.setStyleSheet(self._drag_style)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.setStyleSheet(self._normal_style)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setStyleSheet(self._normal_style)
        urls = event.mimeData().urls()
        if urls:
            paths = [url.toLocalFile() for url in urls]
            self._add_files(paths)

    def _open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "", self._file_filter,
        )
        if paths:
            self._add_files(paths)


class ErrorDialog(QDialog):
    """全局错误提示弹窗（复用主题令牌，与其他工具样式一致）。

    用于需要明确告知用户的错误场景：
      - JSON 解析失败（弹窗展示具体失败位置）
      - 输出目录无写入权限（附「选择目录」按钮以便重新选择后重试）
      - 部分图片下载失败（明细列出失败 URL）

    样式与项目公共规范统一：卡片式面板、错误色标题、主题按钮，禁止硬编码样式值。
    """

    extraClicked = Signal()

    def __init__(self, parent: QWidget, theme: Theme, *, title: str, message: str,
                 detail: str | None = None, confirm_label: str = "知道了",
                 extra_label: str | None = None) -> None:
        """初始化错误弹窗。

        Args:
            parent: 父控件（通常为视图自身）。
            theme: 当前主题（Theme 实例），用于配色与控件样式。
            title: 弹窗标题（错误色加粗）。
            message: 主要说明文字（自动换行）。
            detail: 可选的多行明细（如失败图片 URL 列表），以只读文本框展示。
            confirm_label: 确认按钮文案，默认「知道了」。
            extra_label: 可选次级动作按钮文案（如「选择目录」），点击会触发 extraClicked。
        """
        super().__init__(parent)
        self._theme = theme
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setMaximumHeight(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # 标题行：错误色警示符 + 标题
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        dot = QLabel("⚠")
        dot.setStyleSheet(
            f"color: {theme.error_color}; font-size: 18px; background: transparent;"
        )
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {theme.error_color}; font-size: 14px; font-weight: bold; "
            f"background: transparent;"
        )
        title_row.addWidget(dot)
        title_row.addWidget(title_label)
        title_row.addStretch(1)
        root.addLayout(title_row)

        # 主要说明
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setTextFormat(Qt.TextFormat.PlainText)
        msg_label.setStyleSheet(
            f"color: {theme.text_primary}; font-size: 13px; background: transparent;"
        )
        root.addWidget(msg_label)

        # 明细（可选）：只读多行文本框
        if detail:
            detail_box = QPlainTextEdit()
            detail_box.setReadOnly(True)
            detail_box.setPlainText(detail)
            detail_box.setStyleSheet(
                f"QPlainTextEdit {{ background: {theme.input_bg}; "
                f"color: {theme.text_secondary}; border: 1px solid {theme.border}; "
                f"border-radius: {theme.radius}px; font-size: 12px; padding: 6px; }}"
            )
            root.addWidget(detail_box, 1)

        # 按钮行：次级动作（可选）+ 确认
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        if extra_label:
            self._extra_btn = AppButton(
                extra_label, default_height=36, theme=theme, variant="secondary"
            )
            self._extra_btn.clicked.connect(self._on_extra)
            btn_row.addWidget(self._extra_btn)
        self._confirm_btn = AppButton(
            confirm_label, default_height=36, theme=theme, variant="primary"
        )
        self._confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._confirm_btn)
        root.addLayout(btn_row)

    def _on_extra(self) -> None:
        self.extraClicked.emit()
        self.accept()
