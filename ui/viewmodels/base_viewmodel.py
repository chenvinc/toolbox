"""视图模型基类（胶水层公共能力）。

抽取四个视图模型（Slide / Similarity / JsonExam / PdfSlide）共享的「胶水层骨架」：
- 持有 task_runner 与 event_emitter，并在构造时订阅领域事件；
- cancel_current() 取消最近一次后台任务；
- _on_event() 模板方法：内置「只处理本 VM 关心的 EventType」防护
  （所有 ViewModel 共用同一个 QtEventEmitter，避免事件串台），
  再把关心的事件分发给子类实现的 _dispatch()。

子类约定：
- 声明类属性 ``_WATCHED: frozenset[EventType]``，列出本 VM 关心的事件类型；
- 实现 ``_dispatch(event)``，将关心的 DomainEvent 桥接到各自 Qt 信号；
- 实现 ``on_async_error(exc)``，由 @async_task 在后台异常时回调，emit 对应 failed 信号；
- 构造时先 ``super().__init__(event_emitter, task_runner)``，再保存业务 service。
"""
from __future__ import annotations

from typing import FrozenSet

from PySide6.QtCore import QObject

from core.ports.events import EventEmitter
from core.ports.tasks import TaskRunner
from shared.contracts import DomainEvent, EventType


class BaseViewModel(QObject):
    """所有视图模型的基类（模板方法：事件分发 + 任务取消）。"""

    # 子类覆盖：本 VM 关心的事件类型集合。
    # 内置防护——所有 VM 共用同一 QtEventEmitter，只处理关心事件，
    # 否则会误吞其它工具的领域事件（见 docs/architecture.md §8 问题 #3）。
    _WATCHED: FrozenSet[EventType] = frozenset()

    def __init__(self, event_emitter: EventEmitter, task_runner: TaskRunner) -> None:
        super().__init__()
        self._emitter = event_emitter
        self._task_runner = task_runner
        # 订阅领域事件；由基类统一桥接到 _on_event（含 _WATCHED 过滤）
        self._emitter.on_event(self._on_event)

    # ── 任务取消：供窗口关闭时清理线程（四个 VM 原样复制，统一于此） ──
    def cancel_current(self) -> None:
        """取消最近一次后台任务（供窗口关闭时清理线程）。"""
        handle = getattr(self, "_current_task", None)
        if handle is not None:
            handle.cancel()

    # ── 事件 → 信号桥接（模板方法 + 内置串台防护） ──
    def _on_event(self, event: DomainEvent) -> None:
        # 所有 VM 共用同一 QtEventEmitter：仅处理本 VM 关心的事件，
        # 否则会误吞其它工具的事件（见 docs/architecture.md §8 问题 #3）。
        if event.type not in self._WATCHED:
            return
        self._dispatch(event)

    def _dispatch(self, event: DomainEvent) -> None:
        """子类实现：将关心的 DomainEvent 桥接到各自 Qt 信号。"""
        raise NotImplementedError

    def on_async_error(self, exc: Exception) -> None:
        """子类实现：后台异常（@async_task 触发）转发为对应 failed 信号。"""
        raise NotImplementedError
