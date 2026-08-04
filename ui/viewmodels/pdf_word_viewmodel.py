"""PDF → Word 视图模型（胶水层，仅做命令转发与事件→信号桥接）。

业务规则一律在 core/services 内；本类不解析 PDF、不生成 Word，
只负责：把 UI 的 ConvertPdfToWordRequest 转发给 service，并把 core 推送的
DomainEvent 翻译成 Qt 信号供 View 绑定。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal

from core.ports.events import EventEmitter
from core.ports.services import PdfWordService
from core.ports.tasks import TaskRunner
from shared.contracts import ConvertPdfToWordRequest, DomainEvent, EventType

from ui.infra.qt_task_runner import async_task
from ui.viewmodels.base_viewmodel import BaseViewModel


class PdfWordViewModel(BaseViewModel):
    """Pdf2Word 对应的视图模型。"""

    # ── UI 可绑定的信号 ──
    progress = Signal(str, int, int)   # message, current, total
    completed = Signal(object)         # ConvertPdfToWordResult
    failed = Signal(object)             # str(消息) 或 异常对象（见 on_async_error）

    _WATCHED = frozenset({
        EventType.WORD_PROGRESS,
        EventType.WORD_COMPLETED,
        EventType.WORD_FAILED,
    })

    def __init__(
        self,
        pdf_word: PdfWordService,
        task_runner: TaskRunner,
        event_emitter: EventEmitter,
    ) -> None:
        super().__init__(event_emitter, task_runner)
        self._pdf_word = pdf_word

    # ── 后台异常回调（由 @async_task 触发，必须定义否则异常被吞） ──
    def on_async_error(self, exc: Exception) -> None:
        # 透传异常对象（而非字符串），与 JsonExamViewModel 保持一致，
        # 使视图可按异常类型分流。
        self.failed.emit(exc)

    # ── 事件 → 信号桥接（单向数据流：core → UI） ──
    def _dispatch(self, event: DomainEvent) -> None:
        etype = event.type
        if etype == EventType.WORD_PROGRESS:
            self.progress.emit(event.message, event.current, event.total)
        elif etype == EventType.WORD_COMPLETED:
            self.completed.emit(event.result)
        elif etype == EventType.WORD_FAILED:
            self.failed.emit(event.message)

    # ── 命令转发（单向数据流：UI → core） ──
    @async_task
    def convert(self, request: ConvertPdfToWordRequest) -> Any:
        return self._pdf_word.convert(request)
