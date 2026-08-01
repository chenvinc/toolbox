"""Word → Slide 视图模型（胶水层，仅做命令转发与事件→信号桥接）。

业务规则一律在 core/services 内；本类不解析题目、不生成 PPT，
只负责：把 UI 的 Request 转发给 service，并把 core 推送的 DomainEvent
翻译成 Qt 信号供 View 绑定。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal

from core.ports.events import EventEmitter
from core.ports.services import ExtractionService, PptxService
from core.ports.tasks import TaskRunner
from shared.contracts import (
    DomainEvent, EventType,
    ExtractQuestionsRequest, GeneratePptxRequest,
    ExtractQuestionsResult, GeneratePptxResult,
)
from ui.infra.qt_task_runner import async_task
from ui.viewmodels.base_viewmodel import BaseViewModel


class SlideViewModel(BaseViewModel):
    """Quiz2Slide 对应的视图模型。"""

    # ── UI 可绑定的信号 ──
    extracted = Signal(object)       # ExtractQuestionsResult
    extract_failed = Signal(object)   # str(消息) 或 异常对象（见 on_async_error）
    pptx_progress = Signal(str, int, int)
    pptx_completed = Signal(object)  # GeneratePptxResult
    pptx_failed = Signal(object)     # str(消息) 或 异常对象（见 on_async_error）

    # 关心的领域事件。CHECK_* 属 SimilarityChecker 工具（见 contracts.py 注释），
    # 本工具只关心 EXTRACT_*/PPTX_*，不再监听 CHECK_FAILED（历史耦合已解耦，
    # 见 docs/architecture.md §8 问题 #3）。
    _WATCHED = frozenset({
        EventType.EXTRACT_COMPLETED,
        EventType.EXTRACT_FAILED,
        EventType.PPTX_PROGRESS,
        EventType.PPTX_COMPLETED,
        EventType.PPTX_FAILED,
    })

    def __init__(
        self,
        extraction: ExtractionService,
        pptx: PptxService,
        task_runner: TaskRunner,
        event_emitter: EventEmitter,
    ) -> None:
        super().__init__(event_emitter, task_runner)
        self._extraction = extraction
        self._pptx = pptx

    # ── 后台异常回调（由 @async_task 触发） ──
    def on_async_error(self, exc: Exception) -> None:
        # 透传异常对象（而非字符串），与 JsonExamViewModel 保持一致，
        # 使视图可按异常类型分流；领域失败事件仍走 _dispatch 发 message 字符串。
        self.pptx_failed.emit(exc)

    # ── 事件 → 信号桥接（单向数据流：core → UI） ──
    def _dispatch(self, event: DomainEvent) -> None:
        etype = event.type
        if etype == EventType.EXTRACT_COMPLETED:
            self.extracted.emit(event.result)
        elif etype == EventType.PPTX_PROGRESS:
            self.pptx_progress.emit(event.message, event.current, event.total)
        elif etype == EventType.PPTX_COMPLETED:
            self.pptx_completed.emit(event.result)
        elif etype == EventType.EXTRACT_FAILED:
            self.extract_failed.emit(event.message)
        elif etype == EventType.PPTX_FAILED:
            self.pptx_failed.emit(event.message)

    # ── 命令转发（单向数据流：UI → core） ──
    @async_task
    def extract(self, request: ExtractQuestionsRequest) -> Any:
        return self._extraction.extract(request)

    @async_task
    def generate(self, request: GeneratePptxRequest) -> Any:
        return self._pptx.generate(request)
