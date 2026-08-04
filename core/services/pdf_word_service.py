"""PDF → Word 转换业务服务实现（零 Qt 依赖）。

服务通过注入的端口（PdfWordConverter / EventEmitter）完成工作，
自身不 import 任何 GUI 库，也不直接依赖 pymupdf / python-docx
（那些依赖被限制在 core/adapters 内）。

职责：
- 校验输出路径不得与模板/源 PDF 相同（保护源文件）；
- 委托适配器执行转换；
- 沿事件端口推送 WORD_PROGRESS / WORD_COMPLETED（core → UI 单向通道）。
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from core.adapters.pptx_writer import _same_path
from core.ports.events import EventEmitter
from core.ports.io import PdfWordConverter
from shared.contracts import (
    ConvertPdfToWordRequest, ConvertPdfToWordResult, EventType,
    WordCompletedEvent, ProgressEvent,
)
from shared.errors import OutputOverwriteError


class PdfWordServiceImpl:
    """PDF → Word 转换服务：校验路径 → 转换 → 推送进度/完成事件。"""

    def __init__(self, converter: PdfWordConverter, emitter: EventEmitter) -> None:
        self._converter = converter
        self._emitter = emitter

    def convert(self, request: ConvertPdfToWordRequest) -> ConvertPdfToWordResult:
        logger.info("开始转换 PDF：%s → %s", request.pdf_path, request.output_path)
        # 输出不得与模板相同（仅当提供了模板时校验），否则会覆盖并损坏模板。
        if request.template_path and _same_path(request.template_path, request.output_path):
            raise OutputOverwriteError(
                f"输出路径不能与模板路径相同，否则会覆盖并损坏模板文件：{request.output_path}"
            )
        if _same_path(request.pdf_path, request.output_path):
            raise OutputOverwriteError(
                f"输出路径不能与源 PDF 路径相同：{request.output_path}"
            )

        self._emitter.emit(
            ProgressEvent(
                type=EventType.WORD_PROGRESS, message="准备中...", current=0, total=0
            )
        )

        def _on_progress(cur: int, tot: int) -> None:
            self._emitter.emit(
                ProgressEvent(
                    type=EventType.WORD_PROGRESS,
                    message=f"正在转换第 {cur}/{tot} 页",
                    current=cur,
                    total=tot,
                )
            )

        result = self._converter.convert(request, _on_progress)

        self._emitter.emit(
            ProgressEvent(
                type=EventType.WORD_PROGRESS,
                message="转换完成",
                current=result.page_count,
                total=result.page_count,
            )
        )
        self._emitter.emit(WordCompletedEvent(result=result))
        return result
