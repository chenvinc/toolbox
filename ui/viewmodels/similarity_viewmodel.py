"""题目查重视图模型（胶水层，仅做命令转发与事件→信号桥接）。

业务规则一律在 core/services 内；本类不解析题目、不打分，
只负责：把 UI 的 Request 转发给 SimilarityService，并把 core 推送的 DomainEvent
翻译成 Qt 信号供 View 绑定。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal

from core.ports.events import EventEmitter
from core.ports.services import SimilarityService
from core.ports.tasks import TaskRunner
from shared.contracts import (
    CheckCompletedEvent, CheckStartedEvent, DomainEvent, EventType,
    FailedEvent, ProgressEvent, SimilarityRequest,
)
from ui.infra.qt_task_runner import async_task
from ui.viewmodels.base_viewmodel import BaseViewModel


class SimilarityViewModel(BaseViewModel):
    """Similarity Checker 对应的视图模型。"""

    # ── UI 可绑定的信号 ──
    started = Signal(object)            # SimilarityMode
    progress = Signal(str, int, int)    # message, current, total
    completed = Signal(object)          # SimilarityResult
    failed = Signal(object)             # str(消息) 或 异常对象（见 on_async_error）

    _WATCHED = frozenset({
        EventType.CHECK_STARTED,
        EventType.CHECK_PROGRESS,
        EventType.CHECK_COMPLETED,
        EventType.CHECK_FAILED,
    })

    def __init__(
        self,
        similarity: SimilarityService,
        task_runner: TaskRunner,
        event_emitter: EventEmitter,
    ) -> None:
        super().__init__(event_emitter, task_runner)
        self._similarity = similarity

    # ── 后台异常回调（由 @async_task 触发） ──
    def on_async_error(self, exc: Exception) -> None:
        # 透传异常对象（而非字符串），与 JsonExamViewModel 保持一致，
        # 使视图可按异常类型分流。
        self.failed.emit(exc)

    # ── 事件 → 信号桥接（单向数据流：core → UI） ──
    def _dispatch(self, event: DomainEvent) -> None:
        # isinstance 窄化（而非按 event.type 比较）：让 mypy 能推出具体事件类，
        # 避免对 DomainEvent Union 做属性访问报 union-attr。
        # 各分支仅处理本 VM _WATCHED 的事件（_on_event 已过滤）。
        if isinstance(event, CheckStartedEvent):
            self.started.emit(event.mode)
        elif isinstance(event, ProgressEvent):  # CHECK_PROGRESS
            self.progress.emit(event.message, event.current, event.total)
        elif isinstance(event, CheckCompletedEvent):
            self.completed.emit(event.result)
        elif isinstance(event, FailedEvent):  # CHECK_FAILED
            self.failed.emit(event.message)

    # ── 命令转发（单向数据流：UI → core） ──
    @async_task
    def check(self, request: SimilarityRequest) -> Any:
        return self._similarity.check(request)
