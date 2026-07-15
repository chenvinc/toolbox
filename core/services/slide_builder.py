"""Word → Slide 业务服务实现（零 Qt 依赖）。

服务通过注入的端口（DocumentLoader / PptxWriter / EventEmitter）完成工作，
自身不 import 任何 GUI 库，也不直接依赖 python-docx / python-pptx
（那些依赖被限制在 core/adapters 内）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    EventType, ExtractCompletedEvent, ExtractQuestionsRequest,
    ExtractQuestionsResult, GeneratePptxRequest, GeneratePptxResult,
    ProgressEvent, PptxCompletedEvent,
)
from shared.errors import OutputOverwriteError
from core.ports.events import EventEmitter
from core.ports.io import DocumentLoader, PptxWriter
from core.services._question_parser import parse_questions
from core.adapters.pptx_writer import _resolve_line_spacing, _same_path

if TYPE_CHECKING:
    pass


class ExtractionServiceImpl:
    """题目提取服务：加载段落 → 解析题目 → 推送完成事件。"""

    def __init__(self, loader: DocumentLoader, emitter: EventEmitter) -> None:
        self._loader = loader
        self._emitter = emitter

    def extract(self, request: ExtractQuestionsRequest) -> ExtractQuestionsResult:
        paragraphs = self._loader.load_paragraphs(request.doc_path)
        questions = parse_questions(paragraphs, request.num_pattern, request.opt_prefix)
        result = ExtractQuestionsResult(questions=questions)
        self._emitter.emit(ExtractCompletedEvent(result=result))
        return result


class PptxServiceImpl:
    """PPT 生成服务：校验路径 → 生成 → 推送进度/完成事件。"""

    def __init__(self, writer: PptxWriter, emitter: EventEmitter) -> None:
        self._writer = writer
        self._emitter = emitter

    def generate(self, request: GeneratePptxRequest) -> GeneratePptxResult:
        if _same_path(request.template_path, request.output_path):
            raise OutputOverwriteError(
                f"输出路径不能与模板路径相同，否则会覆盖并损坏模板文件：{request.output_path}"
            )

        total = len(request.questions)
        self._emitter.emit(
            ProgressEvent(
                type=EventType.PPTX_PROGRESS,
                message="准备中...",
                current=0,
                total=total,
            )
        )

        line_spacing = _resolve_line_spacing(
            request.line_spacing_type.value, request.line_spacing_value
        )

        def _on_progress(cur: int, tot: int) -> None:
            self._emitter.emit(
                ProgressEvent(
                    type=EventType.PPTX_PROGRESS,
                    message=f"正在处理第 {cur}/{tot} 道题",
                    current=cur,
                    total=tot,
                )
            )

        pages = self._writer.build(
            template_path=request.template_path,
            questions=request.questions,
            font_name=request.font_name,
            font_size=request.font_size,
            output_path=request.output_path,
            line_spacing=line_spacing,
            first_line_indent=request.first_line_indent,
            on_progress=_on_progress,
        )

        result = GeneratePptxResult(output_path=request.output_path, page_count=pages)
        self._emitter.emit(
            ProgressEvent(type=EventType.PPTX_PROGRESS, message="生成完成", current=total, total=total)
        )
        self._emitter.emit(PptxCompletedEvent(result=result))
        return result
