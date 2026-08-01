"""JSON→Word 试卷生成视图 — 仅负责渲染与事件绑定（零业务规则）。

持有 JsonExamViewModel（胶水层），把用户操作翻译成 GenerateExamRequest 交给
ViewModel：选择 JSON 文件 + 设定排版 → vm.generate(request) 后台生成。
进度/结果/失败均通过 vm 信号回流到本视图更新 UI。

UI 严格复用项目公共样式（theme.Theme / widgets.py 与现有 SlideView / SimilarityView
的模块卡片、字段标签、组合框、步进控件、行间距控件实现），禁止硬编码任何样式值。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QFileDialog,
    QSizePolicy, QFrame, QScrollArea, QApplication,
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QPalette, QDoubleValidator

from theme import Theme
from widgets import (
    AppButton, AnimatedButton, AnimatedProgressBar, ToastNotification,
    DropZone, StepperInput, ErrorDialog,
)
from shared.contracts import (
    ExamLineSpacingType, GenerateExamRequest,
)
from shared.errors import DocumentReadError, OutputWriteError
from core.services._exam_layout import WORD_FONT_SIZE_NAMES
from ui.viewmodels.json_exam_viewmodel import JsonExamViewModel
from ui.views.base_view import BaseView
from ui.infra.open_folder import open_folder
from ui.infra.settings_keys import JsonExamKeys

logger = logging.getLogger(__name__)

# 字号下拉框可选项来自 core 排版常量（与 core/services/_exam_layout.WORD_FONT_SIZE_NAME_TO_PT 对齐）
FONT_SIZE_CHOICES = WORD_FONT_SIZE_NAMES

# 字体下拉框候选（CJK / Latin 组合名），默认首项与契约默认值一致。
FONT_CHOICES = [
    "宋体/Times New Roman",
    "黑体/Arial",
    "微软雅黑/Microsoft YaHei",
    "仿宋_GB2312",
    "楷体",
    "方正小标宋简体",
    "Times New Roman",
    "Arial",
]


class JsonExamView(BaseView):
    """JSON→Word 试卷生成视图。"""

    def get_name(self) -> str:
        return "JsonExam"

    def get_nav_title(self) -> str:
        return "📝 试卷生成"

    def get_description(self) -> str:
        return "将 JSON 题目数据转换为 Word 题本与解析文档，支持字体/字号/行距/首行缩进排版。"

    def __init__(self, view_model: JsonExamViewModel):
        super().__init__()
        self._vm = view_model
        self.theme = Theme()
        self._json_path = ""
        self._out_dir = ""

        self.settings = QSettings("JsonExam", "JsonExam")

        self._setup_ui()
        self._connect_view_model()
        self._load_settings()
        self.theme.theme_changed.connect(self._on_theme_changed)

    # ── ViewModel 信号绑定（单向数据流：core → UI） ──
    def _connect_view_model(self):
        self._vm.progress.connect(self._on_progress)
        self._vm.completed.connect(self._on_completed)
        self._vm.failed.connect(self._on_failed)

    # ── UI 构建 ──
    def _setup_ui(self):
        t = self.theme
        self._field_labels: list = []
        self._section_labels: list = []
        self._module_cards: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(self.theme.page_pad_x, self.theme.page_pad_y, self.theme.page_pad_x, self.theme.page_pad_y)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll = scroll

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(self.theme.spacing)

        # ── 模块一：导入题目数据 ──
        card1, l1 = self._make_module_card("导入题目数据")
        self.json_drop_zone = DropZone(
            "点击或拖拽 .json 文件", "JSON 文件 (*.json)", theme=t
        )
        self.json_drop_zone.file_selected.connect(self._on_json_file)
        self.json_drop_zone.file_cleared.connect(self._on_json_cleared)
        self.json_drop_zone.invalid_file.connect(
            lambda p: self.toast.show_message(
                f"文件格式不支持：{os.path.basename(p)}", success=False)
        )
        l1.addWidget(self.json_drop_zone)
        content_layout.addWidget(card1)

        # ── 模块二：排版设置 ──
        card2, l2 = self._make_module_card("排版设置")
        font_row = QHBoxLayout()
        font_row.setSpacing(self.theme.control_spacing)
        self.font_name = QComboBox()
        self.font_name.addItems(FONT_CHOICES)
        self.font_name.setCurrentText("宋体/Times New Roman")
        self.font_name.setMinimumWidth(180)
        self.font_name.setFixedHeight(36)
        self.font_name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.font_size = QComboBox()
        self.font_size.addItems(FONT_SIZE_CHOICES)
        self.font_size.setCurrentText("五号")
        self.font_size.setMinimumWidth(100)
        self.font_size.setFixedHeight(36)
        self.font_size.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        font_row.addWidget(self._make_labeled_field("字体", self.font_name))
        font_row.addWidget(self._make_labeled_field("字号", self.font_size))
        font_row.addStretch()
        l2.addLayout(font_row)

        # 行间距模块小标题（严格匹配全局 section_header：13px 加粗 + 主题文本色）
        spacing_title = QLabel("行间距设置")
        self._section_labels.append(spacing_title)
        l2.addWidget(spacing_title)

        spacing_row = QHBoxLayout()
        spacing_row.setSpacing(self.theme.control_spacing)
        self.line_spacing_type = QComboBox()
        # 选项与契约 ExamLineSpacingType 的枚举值逐一对应
        self.line_spacing_type.addItems(["1倍行距", "1.5倍行距", "2倍行距", "自定义"])
        self.line_spacing_type.setCurrentText("1.5倍行距")
        self.line_spacing_type.setMinimumWidth(160)
        self.line_spacing_type.setFixedHeight(36)
        self.line_spacing_type.currentTextChanged.connect(self._on_spacing_changed)
        spacing_row.addWidget(self.line_spacing_type)

        # 自定义行距：仅在下拉选中「自定义」时显示；占位提示「请输入行距倍数」；
        # 用 QLineEdit + 步进控件（左侧− / 中间输入 / 右侧+），与阈值/字号控件 1:1 统一。
        self.line_spacing_value = QLineEdit()
        self.line_spacing_value.setPlaceholderText("请输入行距倍数")
        self.line_spacing_value.setValidator(QDoubleValidator(0.5, 5.0, 1))
        self.line_spacing_value.setText("1.5")
        self.line_spacing_value.setFixedHeight(36)
        self.line_spacing_value_stepper = StepperInput(
            spin=self.line_spacing_value, theme=t,
            min_val=0.5, max_val=5.0, step=0.1, decimals=1, default_value=1.5,
        )
        self.line_spacing_value_stepper.setVisible(False)
        spacing_row.addWidget(self.line_spacing_value_stepper)

        self.first_line_indent = QCheckBox("启用首行缩进（2 字符）")
        self.first_line_indent.setChecked(True)
        self.first_line_indent.setFixedHeight(36)
        spacing_row.addWidget(self.first_line_indent, alignment=Qt.AlignVCenter)
        spacing_row.addStretch()
        l2.addLayout(spacing_row)
        content_layout.addWidget(card2)

        # ── 模块三：输出设置 ──
        card3, l3 = self._make_module_card("输出设置")
        save_row = QHBoxLayout()
        save_row.setSpacing(self.theme.control_spacing)
        self._save_to_label = QLabel("保存到:")
        self.out_dir_label = QLabel("（默认：与输入 JSON 同目录）")
        self.out_dir_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._select_dir_btn = AppButton("选择目录", default_height=32, theme=self.theme, variant="secondary")
        self._select_dir_btn.setFixedWidth(96)
        self._select_dir_btn.clicked.connect(self._on_browse_dir)
        self._open_out_btn = AppButton("打开文件夹", default_height=32, theme=self.theme, variant="secondary")
        self._open_out_btn.setFixedWidth(104)
        self._open_out_btn.clicked.connect(self._open_output_folder)
        self._open_out_btn.set_actionable(False, "请先生成试卷")
        save_row.addWidget(self._save_to_label)
        save_row.addWidget(self.out_dir_label)
        save_row.addStretch(1)
        save_row.addWidget(self._select_dir_btn)
        save_row.addWidget(self._open_out_btn)
        l3.addLayout(save_row)
        content_layout.addWidget(card3)

        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)
        self.generate_btn = AnimatedButton(
            "开始生成", default_height=40, theme=self.theme, loading_text="生成中..."
        )
        self.generate_btn.clicked.connect(self.on_generate)
        btn_row.addWidget(self.generate_btn)
        root.addLayout(btn_row)

        self.progress_bar = AnimatedProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        self.progress_label.setTextFormat(Qt.RichText)
        self.progress_label.linkActivated.connect(self._open_output_folder)
        root.addWidget(self.progress_label)

        self.toast = ToastNotification(self, theme=self.theme)
        self._update_generate_state()
        self._restyle_all()

    def _make_module_card(self, title):
        """创建带加粗小标题的浅灰圆角模块卡片，返回 (卡片, 内容布局)。"""
        card = QFrame()
        card.setObjectName("module_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(self.theme.page_pad_y, self.theme.spacing, self.theme.page_pad_y, self.theme.spacing)
        layout.setSpacing(12)
        header = QLabel(title)
        header.setObjectName("card_title")
        self._section_labels.append(header)
        layout.addWidget(header)
        self._module_cards.append(card)
        return card, layout

    def _make_labeled_field(self, label_text, widget):
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(label_text)
        self._field_labels.append(label)
        layout.addWidget(label)
        layout.addWidget(widget)
        return wrapper

    # ── 命令转发（单向数据流：UI → core） ──
    def on_generate(self):
        self._clear_error()
        self._save_settings()
        if not self._json_path:
            self._show_error("请先选择 JSON 题目文件")
            return
        self._set_loading(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText("准备中...")
        req = GenerateExamRequest(
            input_path=self._json_path,
            output_dir=self._out_dir,
            font_name=self.font_name.currentText(),
            font_size_name=self.font_size.currentText(),
            line_spacing_type=ExamLineSpacingType(self.line_spacing_type.currentText()),
            line_spacing_value=self.line_spacing_value_stepper.value(),
            first_line_indent=self.first_line_indent.isChecked(),
        )
        self._vm.generate(req)  # 后台执行，结果经 vm 信号回流

    # ── ViewModel 回调 ──
    def _on_progress(self, message: str, current: int, total: int):
        self.progress_label.setText(message)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValueAnimated(current)

    def _on_completed(self, result):
        self._set_loading(False)
        self.progress_bar.setVisible(False)
        self.toast.show_message(
            f"生成成功，共 {result.question_count} 道题", success=True
        )
        folder = os.path.dirname(result.question_book_path) or "."
        self.progress_label.setText(
            f"生成成功　题本：{os.path.basename(result.question_book_path)}　"
            f"解析：{os.path.basename(result.analysis_path)}　"
            f"<a href=\"folder:{folder}\" style=\"color: {self.theme.accent}; "
            f"text-decoration: underline;\">打开文件夹</a>"
        )
        self.progress_label.setVisible(True)
        self._open_out_btn.set_actionable(bool(folder), "打开输出文件夹")
        logger.info("试卷生成完成: %s / %s", result.question_book_path, result.analysis_path)

        # 部分图片下载失败：进度栏已警告，此处汇总报告失败列表（弹窗列出 URL）。
        if result.failed_images:
            self.toast.show_message(
                f"生成成功，但 {len(result.failed_images)} 张图片下载失败", success=False
            )
            self._show_error_dialog(
                "部分图片下载失败",
                f"共 {len(result.failed_images)} 张图片下载失败，已以灰色占位框替代。",
                detail="\n".join(result.failed_images),
            )

    def _on_failed(self, exc: object):
        self._set_loading(False)
        self.progress_bar.setVisible(False)
        msg = str(exc)
        # 按异常类型分流到对应的全局错误弹窗（复用项目错误提示组件）
        if isinstance(exc, DocumentReadError):
            self._show_error_dialog(
                "JSON 解析失败",
                f"题目文件解析失败，请检查文件格式：\n{msg}",
            )
            logger.error("JSON 解析失败: %s", msg)
            return
        if isinstance(exc, OutputWriteError):
            self._show_error_dialog(
                "输出目录无写入权限",
                f"无法写入输出文件，请重新选择有写入权限的目录：\n{msg}",
                extra_label="选择目录",
                on_extra=self._reselect_and_retry,
            )
            logger.error("输出目录写入失败: %s", msg)
            return
        # 其他异常：捕获并展示友好信息，不暴露堆栈
        self.toast.show_message(msg or "生成失败，请检查输入或稍后重试", success=False)
        logger.error("试卷生成失败: %s", msg)

    # ── 全局错误弹窗（复用 widgets.ErrorDialog，样式与其他工具一致） ──
    def _show_error_dialog(self, title, message, detail=None, extra_label=None, on_extra=None):
        dlg = ErrorDialog(
            self, self.theme, title=title, message=message,
            detail=detail, extra_label=extra_label,
        )
        if extra_label and on_extra is not None:
            dlg.extraClicked.connect(on_extra)
        dlg.exec()

    def _reselect_and_retry(self):
        """权限错误弹窗中的「选择目录」：重新选目录后自动重试生成。"""
        self._on_browse_dir()
        if self._out_dir:
            self.on_generate()

    # ── UI 辅助 ──
    def _set_loading(self, loading: bool):
        self.progress_bar.setVisible(loading)
        self.generate_btn.set_loading(loading)
        if loading:
            self.progress_label.setVisible(True)

    def _on_json_file(self, path):
        self._json_path = path
        self._update_generate_state()

    def _on_json_cleared(self):
        self._json_path = ""
        self._update_generate_state()

    def _on_spacing_changed(self, text):
        """行间距下拉切换：仅当选中「自定义」时显示自定义数值输入框。

        交互逻辑与视觉样式与 SlideView 的「行间距」控件完全一致。
        """
        self.line_spacing_value_stepper.setVisible(text == "自定义")

    def _on_browse_dir(self):
        start_dir = self._out_dir or (os.path.dirname(self._json_path) if self._json_path else "")
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", start_dir or "")
        if path:
            self._out_dir = path
            self.out_dir_label.setText(path)
            self._save_settings()

    def _update_generate_state(self):
        """依据是否已选 JSON 文件，启用/置灰「开始生成」按钮。"""
        if self.generate_btn._loading:
            return
        if not self._json_path:
            self.generate_btn.set_actionable(False, "请先选择 JSON 题目文件")
        else:
            self.generate_btn.set_actionable(True, "")

    def _open_output_folder(self, link=None):
        folder = self._out_dir or (os.path.dirname(self._json_path) if self._json_path else "")
        if not folder:
            return
        if isinstance(link, str) and link.startswith("folder:"):
            folder = link[7:]
        open_folder(folder)

    def _validate(self):
        if not self._json_path:
            self._show_error("请先选择 JSON 题目文件")
            return False
        return True

    def _clear_error(self):
        self.error_label.setText("")

    def _show_error(self, msg):
        self.error_label.setText(msg)

    # ── QSettings 持久化 ──
    def _load_settings(self):
        # 加载期间屏蔽 change 信号，避免部分字段尚未载入时触发 _save_settings
        # 把“半载状态”写回，覆盖已存值。
        self.font_name.blockSignals(True)
        self.font_size.blockSignals(True)
        self.line_spacing_type.blockSignals(True)
        self.line_spacing_value.blockSignals(True)
        self.first_line_indent.blockSignals(True)

        self.font_name.setCurrentText(self.settings.value(JsonExamKeys.FONT_NAME, "宋体/Times New Roman"))
        self.font_size.setCurrentText(self.settings.value(JsonExamKeys.FONT_SIZE_NAME, "五号"))
        self.line_spacing_type.setCurrentText(self.settings.value(JsonExamKeys.LINE_SPACING_TYPE, "1.5倍行距"))
        self.line_spacing_value.setText(self.settings.value(JsonExamKeys.LINE_SPACING_VALUE, "1.5"))
        # 兼容旧版本以字符串 "true"/"false" 存储的值
        _indent_raw = self.settings.value(JsonExamKeys.FIRST_LINE_INDENT, True)
        self.first_line_indent.setChecked(
            _indent_raw if isinstance(_indent_raw, bool) else str(_indent_raw) == "true"
        )
        self._out_dir = self.settings.value(JsonExamKeys.OUTPUT_DIR, "")

        self.font_name.blockSignals(False)
        self.font_size.blockSignals(False)
        self.line_spacing_type.blockSignals(False)
        self.line_spacing_value.blockSignals(False)
        self.first_line_indent.blockSignals(False)

        # 自定义输入控件可见性需依据加载后的下拉值还原
        self.line_spacing_value_stepper.setVisible(
            self.line_spacing_type.currentText() == "自定义"
        )
        if self._out_dir:
            self.out_dir_label.setText(self._out_dir)

    def _save_settings(self):
        self.settings.setValue(JsonExamKeys.FONT_NAME, self.font_name.currentText())
        self.settings.setValue(JsonExamKeys.FONT_SIZE_NAME, self.font_size.currentText())
        self.settings.setValue(JsonExamKeys.LINE_SPACING_TYPE, self.line_spacing_type.currentText())
        self.settings.setValue(JsonExamKeys.LINE_SPACING_VALUE, self.line_spacing_value.text())
        self.settings.setValue(JsonExamKeys.FIRST_LINE_INDENT, self.first_line_indent.isChecked())
        self.settings.setValue(JsonExamKeys.OUTPUT_DIR, self._out_dir)

    def _on_theme_changed(self):
        self._restyle_all()

    def _restyle_all(self):
        t = self.theme
        pal = self.palette()
        pal.setColor(QPalette.Window, t.window_solid_bg)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        input_s = (
            f"QLineEdit {{ padding: 4px 8px; border: 1px solid transparent; "
            f"border-radius: {t.radius}px; "
            f"font-size: 13px; background: {t.input_bg}; color: {t.text_primary}; }}"
            f"QLineEdit:hover {{ border-color: {t.accent}; }}"
            f"QLineEdit:focus {{ border: 1px solid {t.accent}; background: {t.card_bg}; }}"
        )
        combo_s = (
            f"QComboBox {{ padding: 4px 8px; border: 1px solid transparent; "
            f"border-radius: {t.radius}px; "
            f"font-size: 13px; background: {t.input_bg}; color: {t.text_primary}; }}"
            f"QComboBox:hover {{ border-color: {t.accent}; }}"
            f"QComboBox:focus {{ border: 1px solid {t.accent}; background: {t.card_bg}; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
            f"QComboBox QAbstractItemView {{ border: 1px solid {t.border}; "
            f"border-radius: {t.radius}px; selection-background-color: {t.accent}; padding: 4px; }}"
        )
        check_s = f"QCheckBox {{ color: {t.text_primary}; font-size: 13px; spacing: 6px; }}"

        self.line_spacing_value.setStyleSheet(input_s)
        self.font_name.setStyleSheet(combo_s)
        self.font_size.setStyleSheet(combo_s)
        self.line_spacing_type.setStyleSheet(combo_s)
        self.line_spacing_value_stepper.set_theme(t)
        self.first_line_indent.setStyleSheet(check_s)

        for card in self._module_cards:
            card.setStyleSheet(t.qss_card())

        label_s = f"font-size: 12px; color: {t.text_secondary}; margin-bottom: 2px;"
        for lbl in self._field_labels:
            lbl.setStyleSheet(label_s)
        header_s = t.qss_section_header()
        for lbl in self._section_labels:
            lbl.setStyleSheet(header_s)

        self._save_to_label.setStyleSheet(
            f"color: {t.text_secondary}; font-size: 12px; background: transparent;"
        )
        self.out_dir_label.setStyleSheet(
            f"color: {t.text_secondary}; font-size: 12px; background: transparent;"
        )
        self.error_label.setStyleSheet(f"color: {t.error_color}; font-size: 12px;")
        self.progress_label.setStyleSheet(f"color: {t.text_secondary}; font-size: 12px;")
        self.progress_bar.setStyleSheet(t.qss_progress_bar())
        self.generate_btn.set_theme(t)
        self._select_dir_btn.set_theme(t)
        self._open_out_btn.set_theme(t)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            f"QScrollBar::handle:vertical {{ background: {t.scrollbar_handle}; "
            "border-radius: 3px; min-height: 30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

    def stop_worker(self):
        """供主窗口 closeEvent 调用，取消正在运行的后台任务。"""
        self._vm.cancel_current()
