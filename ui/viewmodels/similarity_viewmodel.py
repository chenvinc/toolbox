"""题目查重视图模型（胶水层，仅做命令转发与事件→信号桥接）。

业务规则一律在 core/services 内；本类不解析题目、不打分，
只负责：把 UI 的 Request 转发给 SimilarityService，并把 core 推送的 DomainEvent
翻译成 Qt 信号供 View 绑定。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from core.ports.events import EventEmitter
from core.ports.services import SimilarityService
from core.ports.tasks import TaskRunner
from shared.contracts import (
    DomainEvent, EventType, SimilarityRequest,
)
from ui.infra.qt_task_runner import async_task


class SimilarityViewModel(QObject):
    """Similarity Checker 对应的视图模型。"""

    # ── UI 可绑定的信号 ──
    started = Signal(object)            # SimilarityMode
    progress = Signal(str, int, int)    # message, current, total
    completed = Signal(object)          # SimilarityResult
    failed = Signal(str)                # error message

    def __init__(
        self,
        similarity: SimilarityService,
        task_runner: TaskRunner,
        event_emitter: EventEmitter,
    ) -> None:
        super().__init__()
        self._similarity = similarity
        self._task_runner = task_runner
        self._emitter = event_emitter
        # 订阅领域事件，统一桥接到 Qt 信号
        event_emitter.on_event(self._on_event)

    # ── 后台异常回调（由 @async_task 触发） ──
    def on_async_error(self, exc: Exception) -> None:
        self.failed.emit(str(exc))

    def cancel_current(self) -> None:
        """取消最近一次后台任务（供窗口关闭时清理线程）。"""
        handle = getattr(self, "_current_task", None)
        if handle is not None:
            handle.cancel()

    # ── 事件 → 信号桥接（单向数据流：core → UI） ──
    def _on_event(self, event: DomainEvent) -> None:
        etype = event.type
        if etype == EventType.CHECK_STARTED:
            self.started.emit(event.mode)
        elif etype == EventType.CHECK_PROGRESS:
            self.progress.emit(event.message, event.current, event.total)
        elif etype == EventType.CHECK_COMPLETED:
            self.completed.emit(event.result)
        elif etype == EventType.CHECK_FAILED:
            self.failed.emit(event.message)

    # ── 命令转发（单向数据流：UI → core） ──
    @async_task
    def check(self, request: SimilarityRequest) -> Any:
        return self._similarity.check(request)
