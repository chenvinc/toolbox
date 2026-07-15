"""依赖注入容器（纯 Python，零 Qt 依赖）。

组装顺序：外部适配器 → 业务服务（注入端口）→ 由调用方注入 TaskRunner / EventEmitter。
生产环境在 ui/app.py 用 Qt 版实现组装；测试环境传入 SyncTaskRunner / CollectingEmitter。
"""
from __future__ import annotations

from typing import Any, Dict

from core.adapters.docx_loader import DocxLoaderAdapter
from core.adapters.pptx_writer import PptxWriterAdapter
from core.ports.events import EventEmitter
from core.ports.tasks import TaskRunner
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
        extraction = ExtractionServiceImpl(loader, event_emitter)
        pptx = PptxServiceImpl(writer, event_emitter)
        similarity = SimilarityServiceImpl(loader, event_emitter)

        c = cls()
        c.register("extraction", extraction)
        c.register("pptx", pptx)
        c.register("similarity", similarity)
        c.register("task_runner", task_runner)
        c.register("event_emitter", event_emitter)
        return c
