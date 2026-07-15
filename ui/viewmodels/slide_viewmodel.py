"""Word → Slide 视图模型（胶水层，仅做命令转发与事件→信号桥接）。

业务规则一律在 core/services 内；本类不解析题目、不生成 PPT，
只负责：把 UI 的 Request 转发给 service，并把 core 推送的 DomainEvent
翻译成 Qt 信号供 View 绑定。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from core.ports.events import EventEmitter
from core.ports.services import ExtractionService, PptxService
from core.ports.tasks import TaskRunner
from shared.contracts import (
    DomainEvent, EventType,
    ExtractQuestionsRequest, GeneratePptxRequest,
    ExtractQuestionsResult, GeneratePptxResult,
)
from ui.infra.qt_task_runner import async_task


class SlideViewModel(QObject):
    """Quiz2Slide 对应的视图模型。"""

    # ── UI 可绑定的信号 ──
    extracted = Signal(object)       # ExtractQuestionsResult
    extract_failed = Signal(str)
    pptx_progress = Signal(str, int, int)
    pptx_completed = Signal(object)  # GeneratePptxResult
    pptx_failed = Signal(str)

    def __init__(
        self,
        extraction: ExtractionService,
        pptx: PptxService,
        task_runner: TaskRunner,
        event_emitter: EventEmitter,
    ) -> None:
        super().__init__()
        self._extraction = extraction
        self._pptx = pptx
        self._task_runner = task_runner
        self._emitter = event_emitter
        # 订阅领域事件，统一桥接到 Qt 信号
        event_emitter.on_event(self._on_event)

    # ── 后台异常回调（由 @async_task 触发） ──
    def on_async_error(self, exc: Exception) -> None:
        self.pptx_failed.emit(str(exc))

    def cancel_current(self) -> None:
        """取消最近一次后台任务（供窗口关闭时清理线程）。"""
        handle = getattr(self, "_current_task", None)
        if handle is not None:
            handle.cancel()

    # ── 事件 → 信号桥接（单向数据流：core → UI） ──
    def _on_event(self, event: DomainEvent) -> None:
        etype = event.type
        if etype == EventType.EXTRACT_COMPLETED:
            self.extracted.emit(event.result)
        elif etype == EventType.PPTX_PROGRESS:
            self.pptx_progress.emit(event.message, event.current, event.total)
        elif etype == EventType.PPTX_COMPLETED:
            self.pptx_completed.emit(event.result)
        elif etype == EventType.EXTRACT_FAILED:
            self.extract_failed.emit(event.message)
        elif etype in (EventType.PPTX_FAILED, EventType.CHECK_FAILED):
            self.pptx_failed.emit(event.message)

    # ── 命令转发（单向数据流：UI → core） ──
    @async_task
    def extract(self, request: ExtractQuestionsRequest) -> Any:
        return self._extraction.extract(request)

    @async_task
    def generate(self, request: GeneratePptxRequest) -> Any:
        return self._pptx.generate(request)
