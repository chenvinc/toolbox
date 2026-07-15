"""事件推送端口（core → UI，零 Qt 依赖）。

core 只调用 emit()，不关心下游是 Qt Signal、CLI 打印还是测试收集器。
具体传输实现（如 Qt Signal 桥接）位于 ui/infra。
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from shared.contracts import DomainEvent


@runtime_checkable
class EventEmitter(Protocol):
    """core 向前端推送事件的端口。"""
    def emit(self, event: DomainEvent) -> None:
        """推送一个领域事件。"""
        ...

    def on_event(self, handler: Callable[[DomainEvent], None]) -> None:
        """订阅事件（由具体实现注册到传输层）。"""
        ...
