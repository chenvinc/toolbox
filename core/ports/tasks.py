"""异步执行端口（零 Qt 依赖）。

ViewModel 调用 submit() 把同步 service 方法放到后台线程，通过回调
（普通 Callable，非 Qt Signal）回传进度/结果/错误，保持 core 无 Qt。
Qt 版实现（QThread）位于 ui/infra/qt_task_runner.py，由 DI 注入。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol, Tuple, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class TaskHandle(Protocol):
    """后台任务句柄。"""
    def cancel(self) -> None:
        """取消任务（若支持）。"""
        ...

    def is_running(self) -> bool:
        """任务是否仍在运行。"""
        ...


@runtime_checkable
class TaskRunner(Protocol):
    """异步任务运行端口。"""
    def submit(
        self,
        func: Callable[..., T],
        *,
        args: Tuple[Any, ...] = (),
        kwargs: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[str, int, int], None]] = None,
        on_result: Optional[Callable[[T], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> TaskHandle:
        """提交一个同步函数到后台执行。

        Args:
            func: 要执行的同步函数（通常是某个 service 方法）。
            args / kwargs: 传给 func 的位置与关键字参数。
            on_progress: 进度回调 (message, current, total)。
            on_result: 成功回调，参数为 func 的返回值。
            on_error: 异常回调，参数为抛出的 Exception。
        """
        ...
