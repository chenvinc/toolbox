"""Quiz2Slide 视图 — 仅负责渲染与事件绑定（零业务规则）。

持有 SlideViewModel（胶水层），把用户操作翻译成 Request 交给 ViewModel：
- 「开始转换」→ 校验输入 → vm.extract(ExtractQuestionsRequest) 后台提取题目
- 提取完成（vm.extracted 信号）→ 弹出预览确认对话框
- 用户确认 → vm.generate(GeneratePptxRequest) 后台生成 PPT
进度/结果/失败均通过 vm 信号回流到本视图更新 UI。
"""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog,
    QSizePolicy, QFrame, QScrollArea, QDialog, QDialogButtonBox,
    QTextBrowser, QApplication,
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSettings
from PySide6.QtGui import QPalette, QDoubleValidator

from theme import Theme, _get_system_fonts
from widgets import AppButton, AnimatedButton, AnimatedProgressBar, ToastNotification, DropZone, StepperInput
from shared.contracts import (
    ExtractQuestionsRequest, GeneratePptxRequest, LineSpacingType,
)
from core.adapters.pptx_writer import _resolve_line_spacing
from ui.infra.preview_escape import escape_preview_line, sanitize_font_name
from ui.infra.open_folder import open_folder
from ui.infra.settings_keys import SlideKeys
from ui.viewmodels.slide_viewmodel import SlideViewModel
from ui.views.base_view import BaseView

logger = logging.getLogger(__name__)


class SlideView(BaseView):
    """Word 题目 → PowerPoint 幻灯片 的视图。"""

    def get_name(self) -> str:
        return "Quiz2Slide"

    def get_nav_title(self) -> str:
        return "📑 题库转PPT"

    def get_description(self) -> str:
        return "将 Word 题目文档转换为可直接使用的 PowerPoint 幻灯片。"

    def __init__(self, view_model: SlideViewModel):
        super().__init__()
        self._vm = view_model
        self.theme = Theme()
        self.setWindowTitle("Quiz2Slide")
        self.resize(700, 700)
        self.setMinimumSize(680, 600)

        self._word_path = ""
        self._ppt_path = ""
        self._out_path = "output.pptx"
        self._extracted: list = []

        self.settings = QSettings("Quiz2Slide", "Quiz2Slide")

        self._setup_ui()
        self._connect_view_model()
        self._load_settings()
        self._center_on_screen()
        self.theme.theme_changed.connect(self._on_theme_changed)

    # ── QtSettings helper（避免与 typing 冲突） ──
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

        # ── 模块一：导入源文档 ──
        card1, l1 = self._make_module_card("导入源文档")
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(self.theme.control_spacing)
        self.question_num_fmt = QLineEdit("1.")
        self.question_num_fmt.setPlaceholderText("如 1.")
        self.question_num_fmt.setFixedHeight(36)
        self.option_prefix = QLineEdit("A.")
        self.option_prefix.setPlaceholderText("如 A.")
        self.option_prefix.setFixedHeight(36)
        fmt_row.addWidget(self._make_labeled_field("题号格式", self.question_num_fmt))
        fmt_row.addWidget(self._make_labeled_field("选项前缀", self.option_prefix))
        l1.addLayout(fmt_row)

        self.word_drop_zone = DropZone("点击或拖拽 .docx 文件", "Word 文档 (*.docx)", theme=t)
        self.word_drop_zone.file_selected.connect(self._on_word_file)
        self.word_drop_zone.file_cleared.connect(self._on_word_cleared)
        self.word_drop_zone.invalid_file.connect(
            lambda p: self.toast.show_message(
                f"文件格式不支持：{os.path.basename(p)}", success=False)
        )
        l1.addWidget(self.word_drop_zone)
        content_layout.addWidget(card1)

        # ── 模块二：幻灯片样式自定义 ──
        card2, l2 = self._make_module_card("幻灯片样式自定义")
        font_row = QHBoxLayout()
        font_row.setSpacing(self.theme.control_spacing)
        system_fonts = _get_system_fonts()
        self.font_name = QComboBox()
        self.font_name.setEditable(True)
        self.font_name.addItems(system_fonts)
        self.font_name.setCurrentText(system_fonts[0] if system_fonts else "Arial")
        self.font_name.setMinimumWidth(160)
        self.font_name.setFixedHeight(36)
        self.font_name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.font_size = QSpinBox()
        self.font_size.setRange(9, 72)
        self.font_size.setValue(18)
        self.font_size.setMinimumWidth(70)
        self.font_size.setFixedHeight(36)
        self.font_size_stepper = StepperInput(spin=self.font_size, theme=t)
        font_row.addWidget(self._make_labeled_field("字体", self.font_name))
        font_row.addWidget(self._make_labeled_field("字号", self.font_size_stepper))
        l2.addLayout(font_row)

        # 行间距模块小标题（严格匹配全局 section_header：13px 加粗 + 主题文本色）
        spacing_title = QLabel("行间距设置")
        self._section_labels.append(spacing_title)
        l2.addWidget(spacing_title)

        spacing_row = QHBoxLayout()
        spacing_row.setSpacing(self.theme.control_spacing)
        self.line_spacing_type = QComboBox()
        self.line_spacing_type.addItems(["1 倍", "1.5 倍", "自定义"])
        self.line_spacing_type.setCurrentText("1 倍")
        self.line_spacing_type.setMinimumWidth(160)
        self.line_spacing_type.setFixedHeight(36)
        self.line_spacing_type.currentTextChanged.connect(self._on_spacing_changed)
        spacing_row.addWidget(self.line_spacing_type)

        # 自定义行距：仅在下拉选中「自定义」时显示；占位提示「请输入行距倍数」；
        # 用 QLineEdit + 步进控件（左侧− / 中间输入 / 右侧+），与阈值输入框 1:1 统一。
        self.line_spacing_value = QLineEdit()
        self.line_spacing_value.setPlaceholderText("请输入行距倍数")
        self.line_spacing_value.setValidator(QDoubleValidator(0.5, 5.0, 1))
        self.line_spacing_value.setText("2.0")
        self.line_spacing_value.setFixedHeight(36)
        self.line_spacing_value_stepper = StepperInput(
            spin=self.line_spacing_value, theme=t,
            min_val=0.5, max_val=5.0, step=0.1, decimals=1, default_value=2.0,
        )
        self.line_spacing_value_stepper.setVisible(False)
        spacing_row.addWidget(self.line_spacing_value_stepper)

        self.first_line_indent = QCheckBox("启用首行缩进")
        self.first_line_indent.setChecked(True)
        self.first_line_indent.setFixedHeight(36)
        spacing_row.addWidget(self.first_line_indent, alignment=Qt.AlignVCenter)
        spacing_row.addStretch()
        l2.addLayout(spacing_row)
        content_layout.addWidget(card2)

        # ── 模块三：套用 PPT 模板 ──
        card3, l3 = self._make_module_card("套用 PPT 模板")
        self.ppt_drop_zone = DropZone("点击或拖拽 .pptx 模板", "PPT 模板 (*.pptx)", theme=t)
        self.ppt_drop_zone.file_selected.connect(self._on_ppt_file)
        self.ppt_drop_zone.file_cleared.connect(self._on_ppt_cleared)
        self.ppt_drop_zone.invalid_file.connect(
            lambda p: self.toast.show_message(
                f"文件格式不支持：{os.path.basename(p)}", success=False)
        )
        l3.addWidget(self.ppt_drop_zone)
        content_layout.addWidget(card3)

        # ── 模块四：输出路径设置 ──
        card4, l4 = self._make_module_card("输出路径设置")
        save_row = QHBoxLayout()
        save_row.setSpacing(self.theme.control_spacing)
        self.out_path_label = QLabel()
        self.out_path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._save_to_label = QLabel("保存到:")
        self.change_btn = AppButton("更改", default_height=32, theme=self.theme, variant="secondary")
        self.change_btn.setFixedWidth(80)
        self.change_btn.clicked.connect(lambda: self._on_browse_save())
        open_btn = AppButton("打开文件夹", default_height=32, theme=self.theme, variant="secondary")
        open_btn.setFixedWidth(104)
        open_btn.clicked.connect(self._open_output_folder)
        self._open_out_btn = open_btn
        save_row.addWidget(self._save_to_label)
        save_row.addWidget(self.out_path_label)
        save_row.addStretch(1)
        save_row.addWidget(change_btn)
        save_row.addWidget(open_btn)
        l4.addLayout(save_row)
        content_layout.addWidget(card4)

        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)
        self.spinner = QLabel()
        self.spinner.setFixedSize(24, 24)
        self.spinner.setVisible(False)
        self.spinner.setStyleSheet("background: transparent; border: none;")
        btn_row.addWidget(self.spinner)
        self.convert_btn = AnimatedButton(
            "开始转换", default_height=40, theme=self.theme, loading_text="转换中..."
        )
        self.convert_btn.clicked.connect(self.on_convert)
        btn_row.addWidget(self.convert_btn)
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
        self._update_convert_state()
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

    # ── ViewModel 信号绑定（单向数据流：core → UI） ──
    def _connect_view_model(self):
        self._vm.extracted.connect(self._on_extracted)
        self._vm.extract_failed.connect(self._on_extract_failed)
        self._vm.pptx_progress.connect(self._on_pptx_progress)
        self._vm.pptx_completed.connect(self._on_pptx_completed)
        self._vm.pptx_failed.connect(self._on_pptx_failed)

    # ── 命令转发（单向数据流：UI → core） ──
    def on_convert(self):
        self._clear_error()
        self._save_settings()
        if not self._validate():
            return
        self._set_loading(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在识别题目...")
        req = ExtractQuestionsRequest(
            doc_path=self._word_path,
            num_pattern=self.question_num_fmt.text().strip() or "1.",
            opt_prefix=self.option_prefix.text().strip() or "A.",
        )
        self._vm.extract(req)  # 后台执行，结果经 vm.extracted 信号回流

    # ── ViewModel 回调 ──
    def _on_extracted(self, result):
        self._set_loading(False)
        self._extracted = result.questions
        if not self._extracted:
            self._show_error("未识别到任何题目")
            return
        self._prompt_and_convert(self._extracted)

    def _on_extract_failed(self, message: object):
        self._set_loading(False)
        msg = message if isinstance(message, str) else str(message)
        self._show_error(f"题目识别失败：{msg}")
        logger.error("题目识别失败: %s", msg)

    def _on_pptx_progress(self, message: str, current: int, total: int):
        self.progress_label.setText(message)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValueAnimated(current)

    def _on_pptx_completed(self, result):
        self._set_loading(False)
        self._update_convert_state()
        self.progress_bar.setVisible(False)
        self.toast.show_message(f"生成成功，共 {result.page_count} 页", success=True)
        folder = os.path.dirname(self._out_path) or "."
        self.progress_label.setText(
            f"生成成功  <a href=\"folder:{folder}\" "
            f"style=\"color: {self.theme.accent}; text-decoration: underline;\">打开文件夹</a>"
        )
        self.progress_label.setVisible(True)
        logger.info("转换完成: %s", self._out_path)

    def _on_pptx_failed(self, message: object):
        self._set_loading(False)
        self.progress_bar.setVisible(False)
        msg = message if isinstance(message, str) else str(message)
        self.toast.show_message(msg, success=False)
        logger.error("转换失败: %s", msg)

    # ── 预览确认对话框（UI 交互，控制权在 UI 层） ──
    def _prompt_and_convert(self, questions):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"识别结果 — 共 {len(questions)} 道题")
        dlg.setMinimumSize(620, 450)
        dlg.setModal(True)

        font_name = self.font_name.currentText()
        font_size = self.font_size.value()
        line_height = _resolve_line_spacing(
            self.line_spacing_type.currentText(), self.line_spacing_value_stepper.value()
        )
        indent_px = round(font_size * 1.333 * 2)
        indent = f"{indent_px}px" if self.first_line_indent.isChecked() else "0"

        css = (
            f"body {{ margin: 24px; font-family: '{sanitize_font_name(font_name)}'; "
            f"font-size: {font_size}pt; line-height: {line_height}; "
            f"color: {self.theme.text_primary}; "
            f"background-color: {self.theme.card_bg}; }}"
            f".q-header {{ font-weight: bold; color: {self.theme.accent}; "
            f"margin-top: 16px; margin-bottom: 6px; text-indent: 0; }}"
            f".q {{ margin-bottom: 2px; text-indent: {indent}; "
            f"word-break: break-all; }}"
        )

        parts = []
        for i, q in enumerate(questions, 1):
            parts.append(f"<div class='q-header'>第 {i} 题</div>")
            for line in q:
                parts.append(f"<div class='q'>{escape_preview_line(line)}</div>")
        html = (
            "<html><head><meta charset='utf-8'>"
            f"<style>{css}</style></head><body>"
            + "\n".join(parts) +
            "</body></html>"
        )

        preview = QTextBrowser()
        preview.setOpenExternalLinks(False)
        preview.setHtml(html)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, dlg
        )
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)

        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.addWidget(preview)
        dlg_layout.addWidget(btn_box)

        if dlg.exec() != QDialog.Accepted:
            return

        req = GeneratePptxRequest(
            template_path=self._ppt_path,
            questions=questions,
            font_name=font_name,
            font_size=font_size,
            output_path=self._out_path,
            line_spacing_type=LineSpacingType(self.line_spacing_type.currentText()),
            line_spacing_value=self.line_spacing_value_stepper.value(),
            first_line_indent=self.first_line_indent.isChecked(),
        )
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("准备中...")
        self._set_loading(True)
        self._vm.generate(req)  # 后台执行，结果经 vm.pptx_* 信号回流

    # ── UI 辅助 ──
    def _set_loading(self, loading: bool):
        self.spinner.setVisible(loading)
        self.progress_bar.setVisible(loading)
        self.convert_btn.set_loading(loading)
        if loading:
            self.progress_label.setVisible(True)

    def _on_word_file(self, path):
        self._word_path = path
        out_dir = os.path.dirname(path)
        self._set_out_path(os.path.join(out_dir, "output.pptx"))
        self._update_convert_state()

    def _on_ppt_file(self, path):
        self._ppt_path = path
        self._update_convert_state()

    def _on_word_cleared(self):
        self._word_path = ""
        self._set_out_path("output.pptx")
        self._update_convert_state()

    def _on_ppt_cleared(self):
        self._ppt_path = ""
        self._update_convert_state()

    def _update_convert_state(self):
        """依据是否已选 Word 文档与 PPT 模板，启用/置灰「开始转换」与「打开文件夹」。"""
        if self.convert_btn._loading:
            return
        has_word = bool(self._word_path)
        has_ppt = bool(self._ppt_path)
        if not has_word and not has_ppt:
            self.convert_btn.set_actionable(False, "请先选择 Word 文档与 PPT 模板")
        elif not has_word:
            self.convert_btn.set_actionable(False, "请先选择 Word 文档")
        elif not has_ppt:
            self.convert_btn.set_actionable(False, "请先选择 PPT 模板")
        else:
            self.convert_btn.set_actionable(True, "")
        self._open_out_btn.set_actionable(has_word, "请先选择 Word 文档")

    def _on_spacing_changed(self, text):
        self.line_spacing_value_stepper.setVisible(text == "自定义")

    def _on_browse_save(self):
        start_dir = os.path.dirname(self._out_path) if self._out_path else ""
        path, _ = QFileDialog.getSaveFileName(
            self, "保存为", start_dir or "output.pptx", "PPTX 文件 (*.pptx)"
        )
        if path:
            self._set_out_path(path)

    def _set_out_path(self, path):
        self._out_path = path
        metrics = self.out_path_label.fontMetrics()
        elided = metrics.elidedText(path, Qt.ElideMiddle, 200)
        self.out_path_label.setText(elided)
        self.out_path_label.setToolTip(path)

    def _validate(self):
        errors = []
        if not self._word_path:
            errors.append("请选择 Word 文件")
        if not self._ppt_path:
            errors.append("请选择 PPT 模板")
        if not self.font_name.currentText().strip():
            errors.append("请选择字体")
        if errors:
            self._show_error("；".join(errors))
            return False
        return True

    def _clear_error(self):
        self.error_label.setText("")

    def _show_error(self, msg):
        self.error_label.setText(msg)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def _on_theme_changed(self):
        self._restyle_all()

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

    # ── QSettings 持久化（阈值/格式/字体） ──
    def _load_settings(self):
        # 加载期间屏蔽 change 信号，避免部分字段尚未载入时触发 _save_settings
        # 把“半载状态”写回，覆盖已存值。
        self.question_num_fmt.blockSignals(True)
        self.option_prefix.blockSignals(True)
        self.font_name.blockSignals(True)
        self.question_num_fmt.setText(self.settings.value(SlideKeys.QUESTION_NUM_FMT, "1."))
        self.option_prefix.setText(self.settings.value(SlideKeys.OPT_PREFIX, "A."))
        self.font_name.setCurrentText(self.settings.value(SlideKeys.FONT_NAME, "微软雅黑"))
        self.question_num_fmt.blockSignals(False)
        self.option_prefix.blockSignals(False)
        self.font_name.blockSignals(False)

    def _save_settings(self):
        self.settings.setValue(SlideKeys.QUESTION_NUM_FMT, self.question_num_fmt.text())
        self.settings.setValue(SlideKeys.OPT_PREFIX, self.option_prefix.text())
        self.settings.setValue(SlideKeys.FONT_NAME, self.font_name.currentText())

    def _open_output_folder(self):
        if not self._out_path:
            return
        folder_path = os.path.dirname(self._out_path)
        open_folder(folder_path)

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

        for w in (self.question_num_fmt, self.option_prefix):
            w.setStyleSheet(input_s)
        self.font_size_stepper.set_theme(t)
        self.font_name.setStyleSheet(combo_s)
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
        self.out_path_label.setStyleSheet(
            f"color: {t.text_secondary}; font-size: 12px; background: transparent;"
        )
        self.error_label.setStyleSheet(f"color: {t.error_color}; font-size: 12px;")
        self.progress_label.setStyleSheet(f"color: {t.text_secondary}; font-size: 12px;")
        self.progress_bar.setStyleSheet(t.qss_progress_bar())
        self.convert_btn.set_theme(t)
        self._open_out_btn.set_theme(t)
        self.change_btn.set_theme(t)
        # 拖放区须在换肤时同步刷新（对齐 SimilarityView），否则暗色模式下不跟随
        for dz in (self.word_drop_zone, self.ppt_drop_zone):
            dz._theme = t
            dz._apply_style()
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            f"QScrollBar::handle:vertical {{ background: {t.scrollbar_handle}; "
            "border-radius: 3px; min-height: 30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, "_faded_in"):
            self._faded_in = True
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity")
            anim.setDuration(250)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()

    def stop_worker(self):
        """供主窗口 closeEvent 调用，取消正在运行的后台任务。"""
        self._vm.cancel_current()
