"""Similarity Checker 视图 — 仅负责渲染与事件绑定（零业务规则）。

持有 SimilarityViewModel（胶水层），把用户操作翻译成 SimilarityRequest 交给
ViewModel：选择文件 / 设定阈值 → vm.check(request) 后台查重。
进度/结果/失败均通过 vm 信号回流到本视图更新 UI；报告导出为本视图的
展示层职责（把结果格式化写入 .docx）。
"""
from __future__ import annotations

import logging
import os
import sys

from docx import Document
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QLineEdit, QFrame, QTextBrowser, QButtonGroup, QRadioButton,
    QFileDialog, QApplication, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QPalette

from theme import Theme
from widgets import AppButton, AnimatedButton, AnimatedProgressBar, DropZone, MultiDropZone
from shared.contracts import (
    SimilarityMode, SimilarityRequest, OneToManyResult, ManyToManyResult,
)
from ui.viewmodels.similarity_viewmodel import SimilarityViewModel
from ui.views.base_view import BaseView

logger = logging.getLogger(__name__)


class SimilarityView(BaseView):
    """题目查重视图。"""

    def get_name(self) -> str:
        return "Similarity Checker"

    def get_description(self) -> str:
        return "检测主文档与多个副文档之间的题目重复率，支持精确/模糊匹配，导出查重报告。"

    def __init__(self, view_model: SimilarityViewModel):
        super().__init__()
        self._vm = view_model
        self.theme = Theme()
        self._main_path = ""
        self._secondary_paths: list = []
        self._all_paths: list = []
        self._mode = SimilarityMode.ONE_TO_MANY
        self._last_result = None

        self.settings = QSettings("SimilarityChecker", "SimilarityChecker")

        self._setup_ui()
        self._connect_view_model()
        self._load_settings()
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_theme_changed
        )

    # ── ViewModel 信号绑定（单向数据流：core → UI） ──
    def _connect_view_model(self):
        self._vm.started.connect(self._on_started)
        self._vm.progress.connect(self._on_progress)
        self._vm.completed.connect(self._on_completed)
        self._vm.failed.connect(self._on_failed)

    # ── 命令转发（单向数据流：UI → core） ──
    def _on_check(self):
        self._log_browser.clear()
        self._check_btn.set_loading(True)
        self._export_btn.set_actionable(False, "请先完成检测后导出")
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setValue(0)

        if self._mode == SimilarityMode.ONE_TO_MANY:
            if not self._main_path:
                self._log_browser.setHtml(
                    f"<p style='color:{self.theme.error_color};'>请先选择主文档</p>"
                )
                self._finish_check_ui()
                return
            if not self._secondary_paths:
                self._log_browser.setHtml(
                    f"<p style='color:{self.theme.error_color};'>请先选择至少一个副文档</p>"
                )
                self._finish_check_ui()
                return
            req = SimilarityRequest(
                mode=SimilarityMode.ONE_TO_MANY,
                main_path=self._main_path,
                secondary_paths=list(self._secondary_paths),
                threshold=self._threshold_spin.value(),
                num_pattern=self._num_edit.text().strip() or "1.",
                opt_prefix=self._opt_edit.text().strip() or "A.",
            )
        else:
            if len(self._all_paths) < 2:
                self._log_browser.setHtml(
                    f"<p style='color:{self.theme.error_color};'>请先选择至少 2 份文档</p>"
                )
                self._finish_check_ui()
                return
            req = SimilarityRequest(
                mode=SimilarityMode.MANY_TO_MANY,
                all_paths=list(self._all_paths),
                threshold=self._threshold_spin.value(),
                num_pattern=self._num_edit.text().strip() or "1.",
                opt_prefix=self._opt_edit.text().strip() or "A.",
            )
        self._vm.check(req)  # 后台执行，结果经 vm 信号回流

    # ── ViewModel 回调 ──
    def _on_started(self, mode):
        self._log_browser.clear()
        self._check_btn.set_loading(True)

    def _on_progress(self, message: str, current: int, total: int):
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValueAnimated(current)
        self._log_browser.append(message)

    def _on_completed(self, result):
        self._finish_check_ui()
        if isinstance(result, ManyToManyResult):
            self._display_many_to_many(result)
        else:
            self._display_one_to_many(result)
        self._last_result = result
        if (isinstance(result, OneToManyResult) and result.duplicate_count > 0) or \
           (isinstance(result, ManyToManyResult) and len(result.duplicate_pairs) > 0):
            self._export_btn.set_actionable(True, "")

    def _on_failed(self, message: str):
        self._finish_check_ui()
        self._log_browser.append(f"\n错误：{message}")

    def _finish_check_ui(self):
        self._check_btn.set_loading(False)
        self._progress_bar.setVisible(False)

    # ── 结果展示 ──
    def _display_one_to_many(self, result: OneToManyResult):
        self._log_browser.append("\n──── 检测摘要 ────")
        self._log_browser.append(f"主文档题目数：{result.main_count}")
        self._log_browser.append(f"重复题目数：{result.duplicate_count}")
        rate = result.duplicate_count / max(result.main_count, 1) * 100
        self._log_browser.append(f"重复率：{rate:.1f}%")
        self._log_browser.append("")
        for d in result.details:
            text0 = d.text[0] if d.text else ""
            preview = (text0[:50] + "…") if len(text0) > 50 else text0
            self._log_browser.append(f"第{d.index}题 - {preview}")
            for item in d.sources:
                self._log_browser.append(
                    f"  重复来源：{item.file} (相似度 {item.score:.2f}, {item.reason})"
                )
            self._log_browser.append("")

    def _display_many_to_many(self, result: ManyToManyResult):
        internal = sum(1 for p in result.duplicate_pairs if p.pair_type == "internal")
        cross = sum(1 for p in result.duplicate_pairs if p.pair_type == "cross")
        self._log_browser.append("\n──── 检测摘要 ────")
        self._log_browser.append(
            f"文档数：{result.document_count}，总题目数：{result.total_questions}"
        )
        self._log_browser.append(
            f"重复对总数：{len(result.duplicate_pairs)}"
            f"（文档内 {internal}，跨文档 {cross}）"
        )
        self._log_browser.append("")
        self._log_browser.append("文档题目分布：")
        for fname, count in result.doc_questions.items():
            self._log_browser.append(f"  {fname}：{count} 题")
        self._log_browser.append("")
        for i, pair in enumerate(result.duplicate_pairs, 1):
            tag = "[跨文档]" if pair.pair_type == "cross" else "[文档内]"
            q1_text = pair.q1_text[0] if pair.q1_text else ""
            preview = (q1_text[:40] + "…") if len(q1_text) > 40 else q1_text
            self._log_browser.append(
                f"{i}. {tag} {pair.q1_file}-第{pair.q1_index}题 "
                f"⇄ {pair.q2_file}-第{pair.q2_index}题 "
                f"({pair.score:.2f}, {pair.reason})"
            )
            self._log_browser.append(f"   {preview}")
            self._log_browser.append("")

    # ── 报告导出（展示层职责） ──
    def _on_export(self):
        if self._last_result is None:
            return
        start_dir = os.path.dirname(self._main_path or (self._all_paths[0] if self._all_paths else ""))
        default_name = os.path.join(start_dir, "查重报告.docx")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出查重报告", default_name, "Word 文档 (*.docx)"
        )
        if not path:
            return
        if isinstance(self._last_result, ManyToManyResult):
            self._export_many_to_many(self._last_result, path)
        else:
            self._export_one_to_many(self._last_result, path)
        self._open_folder(path)

    def _export_one_to_many(self, result: OneToManyResult, path: str):
        doc = Document()
        doc.add_heading("题目查重报告（1对多模式）", 0)
        doc.add_paragraph(
            f"主文档题目数：{result.main_count}，"
            f"重复题目数：{result.duplicate_count}，"
            f"重复率：{result.duplicate_count / max(result.main_count, 1) * 100:.1f}%"
        )
        for d in result.details:
            doc.add_heading(f"第 {d.index} 题", 2)
            for line in d.text:
                doc.add_paragraph(line, style="List Bullet")
            doc.add_paragraph(
                "重复来源：" + "; ".join(
                    f"{item.file} ({item.score:.2f}, {item.reason})"
                    for item in d.sources
                )
            )
        doc.save(path)

    def _export_many_to_many(self, result: ManyToManyResult, path: str):
        doc = Document()
        internal = sum(1 for p in result.duplicate_pairs if p.pair_type == "internal")
        cross = sum(1 for p in result.duplicate_pairs if p.pair_type == "cross")
        doc.add_heading("题目查重报告（多对多模式）", 0)
        doc.add_paragraph(
            f"文档数：{result.document_count}，"
            f"总题目数：{result.total_questions}，"
            f"重复对总数：{len(result.duplicate_pairs)}"
            f"（文档内 {internal}，跨文档 {cross}）"
        )
        doc.add_heading("文档题目分布", 2)
        for fname, count in result.doc_questions.items():
            doc.add_paragraph(f"{fname}：{count} 题", style="List Bullet")
        doc.add_heading("重复详情", 2)
        for i, pair in enumerate(result.duplicate_pairs, 1):
            tag = "跨文档" if pair.pair_type == "cross" else "文档内"
            doc.add_heading(
                f"{i}. [{tag}] {pair.q1_file}-第{pair.q1_index}题 "
                f"⇄ {pair.q2_file}-第{pair.q2_index}题 "
                f"({pair.score:.2f}, {pair.reason})",
                3,
            )
            doc.add_paragraph(f"题目 1（{pair.q1_file} 第{pair.q1_index}题）：")
            for line in pair.q1_text:
                doc.add_paragraph(line, style="List Bullet")
            doc.add_paragraph(f"题目 2（{pair.q2_file} 第{pair.q2_index}题）：")
            for line in pair.q2_text:
                doc.add_paragraph(line, style="List Bullet")
            doc.add_paragraph("")
        doc.save(path)

    # ── UI 构建 ──
    def _setup_ui(self):
        t = self.theme
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        self._section_labels = []
        card = QFrame()
        self._main_card = card
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(16)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_label = QLabel("查重模式：")
        mode_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {t.card_header_color}; "
            "background: transparent; padding: 0;"
        )
        mode_row.addWidget(mode_label)
        self._mode_group = QButtonGroup(self)
        self._radio_1toN = QRadioButton("1对多")
        self._radio_NtoN = QRadioButton("多对多")
        self._radio_1toN.setChecked(True)
        self._mode_group.addButton(self._radio_1toN, 0)
        self._mode_group.addButton(self._radio_NtoN, 1)
        self._mode_group.buttonClicked.connect(self._on_mode_changed)
        mode_row.addWidget(self._radio_1toN)
        mode_row.addWidget(self._radio_NtoN)
        mode_row.addStretch()
        card_layout.addLayout(mode_row)

        self._one_to_many_widgets = []
        lbl_main = self._section_label("📄 主文档（选择题库）", card_layout)
        self._one_to_many_widgets.append(lbl_main)
        self._main_drop_zone = DropZone("点击或拖拽 .docx 文件", "Word 文档 (*.docx)", theme=t)
        self._main_drop_zone.file_selected.connect(self._on_main_file)
        self._one_to_many_widgets.append(self._main_drop_zone)
        card_layout.addWidget(self._main_drop_zone)

        self._divider = QFrame()
        self._divider.setFixedHeight(1)
        self._one_to_many_widgets.append(self._divider)
        card_layout.addWidget(self._divider)

        lbl_sec = self._section_label("📑 副文档（对比库，可多选）", card_layout)
        self._one_to_many_widgets.append(lbl_sec)
        self._secondary_drop_zone = MultiDropZone(
            "点击或拖拽 .docx 文件（可多选）", "Word 文档 (*.docx)", theme=t
        )
        self._secondary_drop_zone.files_selected.connect(self._on_secondary_files)
        self._one_to_many_widgets.append(self._secondary_drop_zone)
        card_layout.addWidget(self._secondary_drop_zone)

        self._many_to_many_widgets = []
        lbl_all = self._section_label("📚 所有文档（可多选，至少2份）", card_layout)
        self._many_to_many_widgets.append(lbl_all)
        self._all_drop_zone = MultiDropZone(
            "点击或拖拽 .docx 文件（可多选）", "Word 文档 (*.docx)", theme=t
        )
        self._all_drop_zone.files_selected.connect(self._on_all_files)
        self._many_to_many_widgets.append(self._all_drop_zone)
        card_layout.addWidget(self._all_drop_zone)
        for w in self._many_to_many_widgets:
            w.setVisible(False)

        settings_row = QHBoxLayout()
        settings_row.setSpacing(8)
        th_label = QLabel("相似度阈值")
        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.5, 1.0)
        self._threshold_spin.setSingleStep(0.01)
        self._threshold_spin.setDecimals(2)
        self._threshold_spin.setValue(float(self.settings.value("threshold", 0.8)))
        num_label = QLabel("题号格式")
        self._num_edit = QLineEdit()
        self._num_edit.setPlaceholderText("如 1.")
        opt_label = QLabel("选项前缀")
        self._opt_edit = QLineEdit()
        self._opt_edit.setPlaceholderText("如 A.")
        self._reset_btn = QPushButton("重置")
        self._reset_btn.clicked.connect(self._on_reset_settings)
        settings_row.addWidget(th_label)
        settings_row.addWidget(self._threshold_spin)
        settings_row.addWidget(num_label)
        settings_row.addWidget(self._num_edit)
        settings_row.addWidget(opt_label)
        settings_row.addWidget(self._opt_edit)
        settings_row.addWidget(self._reset_btn)
        settings_row.addStretch()
        card_layout.addLayout(settings_row)

        self._threshold_spin.valueChanged.connect(self._save_settings)
        self._num_edit.textChanged.connect(self._save_settings)
        self._opt_edit.textChanged.connect(self._save_settings)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self._check_btn = AnimatedButton("开始检测", default_height=44, theme=self.theme)
        self._check_btn.clicked.connect(self._on_check)
        self._export_btn = AppButton("导出报告", default_height=44, theme=self.theme)
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.set_actionable(False, "请先完成检测后导出")
        btn_row.addWidget(self._check_btn)
        btn_row.addWidget(self._export_btn)
        card_layout.addLayout(btn_row)

        card_layout.addSpacing(8)

        self._progress_bar = AnimatedProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        card_layout.addWidget(self._progress_bar)

        self._log_browser = QTextBrowser()
        self._log_browser.setOpenExternalLinks(False)
        self._log_browser.setMinimumHeight(180)
        self._log_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout.addWidget(self._log_browser)

        root.addWidget(card)
        self._restyle_all()

    def _section_label(self, text, layout):
        label = QLabel(text)
        self._section_labels.append(label)
        layout.addWidget(label)
        return label

    def _on_mode_changed(self, button):
        if button == self._radio_1toN:
            self._mode = SimilarityMode.ONE_TO_MANY
            for w in self._one_to_many_widgets:
                w.setVisible(True)
            for w in self._many_to_many_widgets:
                w.setVisible(False)
        else:
            self._mode = SimilarityMode.MANY_TO_MANY
            for w in self._one_to_many_widgets:
                w.setVisible(False)
            for w in self._many_to_many_widgets:
                w.setVisible(True)
        self._log_browser.clear()

    def _on_main_file(self, path):
        self._main_path = path
        self._log_browser.clear()

    def _on_secondary_files(self, paths):
        self._secondary_paths = paths
        self._log_browser.clear()

    def _on_all_files(self, paths):
        self._all_paths = paths
        self._log_browser.clear()

    # ── QSettings 持久化（P1 #4） ──
    def _load_settings(self):
        # 加载期间屏蔽 textChanged/valueChanged，避免部分字段尚未载入时就触发
        # _save_settings 把“半载状态”（如仍为默认的 opt_edit）写回，覆盖已存值。
        self._num_edit.blockSignals(True)
        self._opt_edit.blockSignals(True)
        self._threshold_spin.blockSignals(True)
        self._num_edit.setText(self.settings.value("num_pattern", "1."))
        self._opt_edit.setText(self.settings.value("opt_prefix", "A."))
        self._threshold_spin.setValue(float(self.settings.value("threshold", 0.8)))
        self._num_edit.blockSignals(False)
        self._opt_edit.blockSignals(False)
        self._threshold_spin.blockSignals(False)

    def _save_settings(self):
        self.settings.setValue("threshold", self._threshold_spin.value())
        self.settings.setValue("num_pattern", self._num_edit.text())
        self.settings.setValue("opt_prefix", self._opt_edit.text())

    def _on_reset_settings(self):
        self._threshold_spin.setValue(0.8)
        self._num_edit.setText("1.")
        self._opt_edit.setText("A.")
        self._save_settings()

    def _on_theme_changed(self):
        self.theme.refresh()
        self._restyle_all()

    def _open_folder(self, path):
        folder = os.path.dirname(path) or "."
        try:
            if sys.platform == "darwin":
                os.system(f"open '{folder}'")
            elif sys.platform == "win32":
                os.system(f"explorer '{folder}'")
            else:
                os.system(f"xdg-open '{folder}'")
        except Exception:  # pragma: no cover - 系统调用
            pass

    def _restyle_all(self):
        t = self.theme
        pal = self.palette()
        pal.setColor(QPalette.Window, t.window_solid_bg)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self._main_card.setStyleSheet(t.qss_card())
        for dz in (self._main_drop_zone, self._secondary_drop_zone, self._all_drop_zone):
            dz._theme = t
            dz._apply_style()

        radio_style = (
            f"QRadioButton {{ color: {t.text_primary}; font-size: 14px; "
            f"background: transparent; spacing: 6px; padding: 4px 12px; }}"
            f"QRadioButton::indicator {{ width: 16px; height: 16px; }}"
        )
        self._radio_1toN.setStyleSheet(radio_style)
        self._radio_NtoN.setStyleSheet(radio_style)

        header_s = t.qss_section_header()
        for lbl in self._section_labels:
            lbl.setStyleSheet(header_s)

        self._divider.setStyleSheet(t.qss_divider())
        self._check_btn.set_theme(t)
        self._export_btn.set_theme(t)
        self._progress_bar.setStyleSheet(t.qss_progress_bar())

        self._log_browser.setStyleSheet(
            f"QTextBrowser {{ background: {t.input_bg}; color: {t.text_primary}; "
            f"border: none; border-radius: 8px; padding: 12px; font-size: 13px; }}"
        )
        input_s = (
            f"QLineEdit, QDoubleSpinBox {{ padding: 4px 8px; border: none; "
            f"border-radius: 8px; font-size: 14px; background: {t.input_bg}; "
            f"color: {t.text_primary}; }}"
        )
        self._threshold_spin.setStyleSheet(input_s)
        self._num_edit.setStyleSheet(input_s)
        self._opt_edit.setStyleSheet(input_s)
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ padding: 4px 12px; border: none; border-radius: 8px; "
            f"font-size: 14px; background: {t.input_bg}; color: {t.text_primary}; }}"
        )

    def stop_worker(self):
        """供主窗口 closeEvent 调用，取消正在运行的后台任务。"""
        self._vm.cancel_current()
