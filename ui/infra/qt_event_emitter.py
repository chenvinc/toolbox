"""EventEmitter 的 Qt 实现：把 core 领域事件桥接为 Qt 信号。

core 服务在不同线程调用 emit()，本对象常驻 UI 线程，Qt 自动以
QueuedConnection 将事件排队到 UI 线程，保证线程安全。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from core.ports.events import EventEmitter
from shared.contracts import DomainEvent


class QtEventEmitter(QObject):
    """将 DomainEvent 通过 Qt 信号转发给订阅者。

    结构上实现 core.ports.events.EventEmitter 端口（emit / on_event）；
    EventEmitter 是 @runtime_checkable Protocol，按结构子类型满足，无需继承
    （继承会因 Protocol 元类与 QObject 元类冲突而报错）。
    """

    _signal = Signal(object)

    def emit(self, event: DomainEvent) -> None:
        self._signal.emit(event)

    def on_event(self, handler: Callable[[DomainEvent], None]) -> None:
        self._signal.connect(handler)
