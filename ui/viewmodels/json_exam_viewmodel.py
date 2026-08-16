"""JSON→Word 试卷视图模型（胶水层，仅做命令转发与事件→信号桥接）。

业务规则一律在 core/services/json_to_word_service.py 内；本类不解析 JSON、
不读写文件，只负责：把 UI 的 GenerateExamRequest 转发给 ExamGeneratorService，
并把 core 推送的 DomainEvent 翻译成 Qt 信号供 View 绑定。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal

from core.ports.events import EventEmitter
from core.ports.services import ExamGeneratorService
from core.ports.tasks import TaskRunner
from shared.contracts import (
    DomainEvent, EventType, ExamCompletedEvent, ExamFailedEvent,
    GenerateExamRequest, ProgressEvent,
)
from ui.infra.qt_task_runner import async_task
from ui.viewmodels.base_viewmodel import BaseViewModel


class JsonExamViewModel(BaseViewModel):
    """JSON→Word 试卷生成对应的视图模型。"""

    # ── UI 可绑定的信号 ──
    progress = Signal(str, int, int)    # message, current, total
    completed = Signal(object)          # GenerateExamResult
    failed = Signal(object)             # 异常对象（保留类型供视图分类处理）

    _WATCHED = frozenset({
        EventType.EXAM_PROGRESS,
        EventType.EXAM_COMPLETED,
        EventType.EXAM_FAILED,
    })

    def __init__(
        self,
        exam: ExamGeneratorService,
        task_runner: TaskRunner,
        event_emitter: EventEmitter,
    ) -> None:
        super().__init__(event_emitter, task_runner)
        self._exam = exam

    # ── 后台异常回调（由 @async_task 触发） ──
    def on_async_error(self, exc: Exception) -> None:
        # 透传异常对象（而非字符串），使视图可按类型分流：JSON 解析错误 /
        # 输出目录权限错误分别弹对应弹窗，其余异常展示友好文案。
        self.failed.emit(exc)

    # ── 事件 → 信号桥接（单向数据流：core → UI） ──
    def _dispatch(self, event: DomainEvent) -> None:
        # isinstance 窄化（而非按 event.type 比较）：让 mypy 能推出具体事件类，
        # 避免对 DomainEvent Union 做属性访问报 union-attr。
        if isinstance(event, ProgressEvent):  # EXAM_PROGRESS
            self.progress.emit(event.message, event.current, event.total)
        elif isinstance(event, ExamCompletedEvent):
            self.completed.emit(event.result)
        elif isinstance(event, ExamFailedEvent):
            self.failed.emit(event.message)

    # ── 命令转发（单向数据流：UI → core） ──
    @async_task
    def generate(self, request: GenerateExamRequest) -> Any:
        return self._exam.generate(request)
