"""Pdf2Slide 视图 — 仅负责渲染与事件绑定（零业务规则）。

持有 PdfSlideViewModel（胶水层），把用户操作翻译成 Request 交给 ViewModel：
- 「开始转换」→ 校验输入 → vm.convert(ConvertPdfRequest) 后台转换
进度/结果/失败均通过 vm 信号回流到本视图更新 UI。

转换语义（见 core/adapters/pdf_slide_converter.py）：
以 PPT 模板的母版/版式为底，把 PDF 每页文字还原成可编辑文本框
（保留字体/字号/颜色/粗斜体/坐标），不生成图片、不覆盖模板背景。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFileDialog,
    QSizePolicy, QFrame, QScrollArea, QApplication,
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSettings
from PySide6.QtGui import QPalette, QShowEvent

from widgets import AppButton, AnimatedButton, AnimatedProgressBar, ToastNotification, DropZone
from shared.contracts import ConvertPdfRequest, ConvertPdfResult
from ui.viewmodels.pdf_slide_viewmodel import PdfSlideViewModel
from ui.views.base_view import BaseView
from ui.infra.open_folder import open_folder
from ui.infra.settings_keys import PdfSlideKeys
from ui.infra.safe_settings import read_str

logger = logging.getLogger(__name__)


class PdfSlideView(BaseView):
    """PDF 文档 → 可编辑文字 PowerPoint 幻灯片 的视图。"""

    def get_name(self) -> str:
        return "Pdf2Slide"

    def get_nav_title(self) -> str:
        return "📄 PDF转PPT"

    def get_description(self) -> str:
        return "将 PDF 逐页转换为保留可编辑文字的 PowerPoint 幻灯片（套用模板母版背景）。"

    def __init__(self, view_model: PdfSlideViewModel) -> None:
        super().__init__()
        self.toast: ToastNotification
        self._vm = view_model
        self.setWindowTitle("Pdf2Slide")

        self._pdf_path = ""
        self._tpl_path = ""
        self._out_path = "output.pptx"

        self.settings = QSettings("Pdf2Slide", "Pdf2Slide")

        self._setup_ui()
        self._connect_view_model()
        self._load_settings()
        self.theme.theme_changed.connect(self._on_theme_changed)

    # ── UI 构建 ──
    def _setup_ui(self) -> None:
        t = self.theme

        root = QVBoxLayout(self)
        root.setContentsMargins(self.theme.page_pad_x, self.theme.page_pad_y, self.theme.page_pad_x, self.theme.page_pad_y)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll = scroll

        content = QFrame()
        content.setStyleSheet("background: transparent; border: none;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(self.theme.spacing)

        # ── 模块一：导入 PDF 文档 ──
        card1, l1 = self._make_module_card("导入 PDF 文档")
        self.pdf_drop_zone = DropZone(
            "点击或拖拽 .pdf 文件", "PDF 文档 (*.pdf)", theme=t, variant="primary"
        )
        self.pdf_drop_zone.file_selected.connect(self._on_pdf_file)
        self.pdf_drop_zone.file_cleared.connect(self._on_pdf_cleared)
        self.pdf_drop_zone.invalid_file.connect(
            lambda p: self.toast.show_message(
                f"文件格式不支持：{os.path.basename(p)}", success=False)
        )
        l1.addWidget(self.pdf_drop_zone)
        self._pdf_hint = QLabel(
            "转换将逐页保留 PDF 中的可编辑文字（字体 / 字号 / 颜色 / 粗斜体 / 坐标），"
            "纯图片页（如封面）不含文字属正常现象。"
        )
        self._pdf_hint.setWordWrap(True)
        self._field_labels.append(self._pdf_hint)
        l1.addWidget(self._pdf_hint)
        content_layout.addWidget(card1)

        # ── 模块二：套用 PPT 模板 ──
        card2, l2 = self._make_module_card("套用 PPT 模板")
        self.ppt_drop_zone = DropZone("点击或拖拽 .pptx 模板", "PPT 模板 (*.pptx)", theme=t)
        self.ppt_drop_zone.file_selected.connect(self._on_tpl_file)
        self.ppt_drop_zone.file_cleared.connect(self._on_tpl_cleared)
        self.ppt_drop_zone.invalid_file.connect(
            lambda p: self.toast.show_message(
                f"文件格式不支持：{os.path.basename(p)}", success=False)
        )
        l2.addWidget(self.ppt_drop_zone)
        self._tpl_hint = QLabel(
            "每页以模板第 1 页的版式为底子，自动继承母版 / 主题 / 图片背景。"
        )
        self._tpl_hint.setWordWrap(True)
        self._field_labels.append(self._tpl_hint)
        l2.addWidget(self._tpl_hint)
        content_layout.addWidget(card2)

        # ── 模块三：输出路径设置 ──
        card3, l3 = self._make_module_card("输出路径设置")
        save_row = QHBoxLayout()
        save_row.setSpacing(self.theme.control_spacing)
        self.out_path_label = QLabel()
        self.out_path_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._save_to_label = QLabel("保存到:")
        change_btn = AppButton("更改", default_height=32, theme=self.theme, variant="secondary")
        change_btn.setFixedWidth(80)
        change_btn.clicked.connect(lambda: self._on_browse_save())
        open_btn = AppButton("打开文件夹", default_height=32, theme=self.theme, variant="secondary")
        open_btn.setFixedWidth(104)
        open_btn.clicked.connect(self._open_output_folder)
        self._open_out_btn = open_btn
        self._change_btn = change_btn
        save_row.addWidget(self._save_to_label)
        save_row.addWidget(self.out_path_label)
        save_row.addStretch(1)
        save_row.addWidget(change_btn)
        save_row.addWidget(open_btn)
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
        self.progress_label.setTextFormat(Qt.TextFormat.RichText)
        self.progress_label.linkActivated.connect(self._open_output_folder)
        root.addWidget(self.progress_label)

        self.toast = ToastNotification(self, theme=self.theme)
        self._update_convert_state()
        self._restyle_all()

    # ── ViewModel 信号绑定（单向数据流：core → UI） ──
    def _connect_view_model(self) -> None:
        self._vm.progress.connect(self._on_progress)
        self._vm.completed.connect(self._on_completed)
        self._vm.failed.connect(self._on_failed)

    # ── 命令转发（单向数据流：UI → core） ──
    def on_convert(self) -> None:
        self._clear_error()
        self._save_settings()
        if not self._validate():
            return
        self._set_loading(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("准备中...")
        req = ConvertPdfRequest(
            pdf_path=self._pdf_path,
            template_path=self._tpl_path,
            output_path=self._out_path,
        )
        self._vm.convert(req)  # 后台执行，结果经 vm 信号回流

    # ── ViewModel 回调 ──
    def _on_progress(self, message: str, current: int, total: int) -> None:
        self.progress_label.setText(message)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValueAnimated(current)

    def _on_completed(self, result: ConvertPdfResult) -> None:
        self._set_loading(False)
        self._update_convert_state()
        self.progress_bar.setVisible(False)
        self.toast.show_message(
            f"转换成功，共 {result.page_count} 页 / {result.textbox_count} 个文本框",
            success=True,
        )
        summary = f"转换成功：{result.page_count} 页"
        if result.empty_pages:
            pages = "、".join(str(p) for p in result.empty_pages[:8])
            more = " 等" if len(result.empty_pages) > 8 else ""
            summary += f"（第 {pages}{more} 页为纯图片页，无可提取文字）"
        folder = os.path.dirname(self._out_path) or "."
        self.progress_label.setText(
            f"{summary}  <a href=\"folder:{folder}\" "
            f"style=\"color: {self.theme.accent}; text-decoration: underline;\">打开文件夹</a>"
        )
        self.progress_label.setVisible(True)
        logger.info("PDF 转换完成: %s", self._out_path)

    def _on_failed(self, message: object) -> None:
        self._set_loading(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        msg = message if isinstance(message, str) else str(message)
        self.toast.show_message(msg, success=False)
        logger.error("PDF 转换失败: %s", msg)

    # ── UI 辅助 ──
    def _set_loading(self, loading: bool) -> None:
        self.progress_bar.setVisible(loading)
        self.convert_btn.set_loading(loading)
        if loading:
            self.progress_label.setVisible(True)

    def _on_pdf_file(self, path: str) -> None:
        self._pdf_path = path
        out_dir = os.path.dirname(path)
        base = os.path.splitext(os.path.basename(path))[0]
        self._set_out_path(os.path.join(out_dir, base + ".pptx"))
        self._update_convert_state()

    def _on_pdf_cleared(self) -> None:
        self._pdf_path = ""
        self._set_out_path("output.pptx")
        self._update_convert_state()

    def _on_tpl_file(self, path: str) -> None:
        self._tpl_path = path
        self._update_convert_state()

    def _on_tpl_cleared(self) -> None:
        self._tpl_path = ""
        self._update_convert_state()

    def _update_convert_state(self) -> None:
        """依据是否已选 PDF 与 PPT 模板，启用/置灰「开始转换」与「打开文件夹」。"""
        if self.convert_btn._loading:
            return
        has_pdf = bool(self._pdf_path)
        has_tpl = bool(self._tpl_path)
        if not has_pdf and not has_tpl:
            self.convert_btn.set_actionable(False, "请先选择 PDF 文档与 PPT 模板")
        elif not has_pdf:
            self.convert_btn.set_actionable(False, "请先选择 PDF 文档")
        elif not has_tpl:
            self.convert_btn.set_actionable(False, "请先选择 PPT 模板")
        else:
            self.convert_btn.set_actionable(True, "")
        self._open_out_btn.set_actionable(has_pdf, "请先选择 PDF 文档")

    def _on_browse_save(self) -> None:
        start_dir = os.path.dirname(self._out_path) if self._out_path else ""
        path, _ = QFileDialog.getSaveFileName(
            self, "保存为", start_dir or "output.pptx", "PPTX 文件 (*.pptx)"
        )
        if path:
            self._set_out_path(path)

    def _set_out_path(self, path: str) -> None:
        self._out_path = path
        metrics = self.out_path_label.fontMetrics()
        elided = metrics.elidedText(path, Qt.TextElideMode.ElideMiddle, 200)
        self.out_path_label.setText(elided)
        self.out_path_label.setToolTip(path)

    def _validate(self) -> bool:
        errors = []
        if not self._pdf_path:
            errors.append("请选择 PDF 文件")
        if not self._tpl_path:
            errors.append("请选择 PPT 模板")
        if errors:
            self._show_error("；".join(errors))
            return False
        return True

    def _clear_error(self) -> None:
        self.error_label.setText("")

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)

    def _on_theme_changed(self) -> None:
        self._restyle_all()

    # ── QSettings 持久化（记住上次使用的模板路径） ──
    def _load_settings(self) -> None:
        # 加载期间不触发保存回写，避免半载状态覆盖已存值（见开发指南 Q2）。
        tpl = read_str(self.settings, PdfSlideKeys.TEMPLATE_PATH, "")
        if tpl and os.path.exists(tpl):
            self.ppt_drop_zone.blockSignals(True)
            if self.ppt_drop_zone.set_file(tpl):
                self._tpl_path = tpl
            self.ppt_drop_zone.blockSignals(False)
            self._update_convert_state()

    def _save_settings(self) -> None:
        self.settings.setValue(PdfSlideKeys.TEMPLATE_PATH, self._tpl_path)

    def _open_output_folder(self) -> None:
        if not self._out_path:
            return
        folder_path = os.path.dirname(self._out_path)
        open_folder(folder_path)

    # ── 主题热切换重绘（复用 Theme 片段，禁止硬编码颜色） ──
    def _restyle_all(self) -> None:
        t = self.theme
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, t.window_solid_bg)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

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
        self._change_btn.set_theme(t)
        self._scroll.setStyleSheet(t.qss_scrollbar())

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not hasattr(self, "_faded_in"):
            self._faded_in = True
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity")
            anim.setDuration(250)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()

    def stop_worker(self) -> None:
        """供主窗口 closeEvent 调用，取消正在运行的后台任务。"""
        self._vm.cancel_current()
