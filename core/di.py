"""依赖注入容器（纯 Python，零 Qt 依赖）。

组装顺序：外部适配器 → 业务服务（注入端口）→ 由调用方注入 TaskRunner / EventEmitter。
生产环境在 ui/app.py 用 Qt 版实现组装；测试环境传入 SyncTaskRunner / CollectingEmitter。
"""
from __future__ import annotations

from typing import Any, Dict

from core.adapters.docx_loader import DocxLoaderAdapter
from core.adapters.docx_exam_writer import DocxExamWriterAdapter
from core.adapters.pdf_slide_converter import PdfSlideConverterAdapter
from core.adapters.pdf_word_converter import PdfWordConverterAdapter
from core.adapters.pptx_writer import PptxWriterAdapter
from core.ports.events import EventEmitter
from core.ports.tasks import TaskRunner
from core.services.json_to_word_service import JsonToWordServiceImpl
from core.services.pdf_slide_service import PdfSlideServiceImpl
from core.services.pdf_word_service import PdfWordServiceImpl
from core.services.slide_builder import ExtractionServiceImpl, PptxServiceImpl
from core.services.similarity_service import SimilarityServiceImpl


class Container:
    """极简服务容器。"""

    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}

    def register(self, key: str, instance: Any) -> None:
        self._services[key] = instance

    def resolve(self, key: str) -> Any:
        return self._services[key]

    @classmethod
    def build(cls, *, task_runner: TaskRunner, event_emitter: EventEmitter) -> "Container":
        """按生产/测试环境组装服务图。

        task_runner / event_emitter 由调用方提供（生产用 Qt 实现，测试用替身）。
        """
        loader = DocxLoaderAdapter()
        writer = PptxWriterAdapter()
        exam_writer = DocxExamWriterAdapter()
        pdf_converter = PdfSlideConverterAdapter()
        word_converter = PdfWordConverterAdapter()
        extraction = ExtractionServiceImpl(loader, event_emitter)
        pptx = PptxServiceImpl(writer, event_emitter)
        similarity = SimilarityServiceImpl(loader, event_emitter)
        exam = JsonToWordServiceImpl(exam_writer, event_emitter)
        pdf_slide = PdfSlideServiceImpl(pdf_converter, event_emitter)
        pdf_word = PdfWordServiceImpl(word_converter, event_emitter)

        c = cls()
        c.register("extraction", extraction)
        c.register("pptx", pptx)
        c.register("similarity", similarity)
        c.register("exam", exam)
        c.register("pdf_slide", pdf_slide)
        c.register("pdf_word", pdf_word)
        c.register("task_runner", task_runner)
        c.register("event_emitter", event_emitter)
        return c
