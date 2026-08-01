"""TaskRunner 的 Qt 实现 + @async_task 装饰器。

把同步 service 方法放到 QThread 后台执行，通过回调（普通 Callable）回传结果，
保持 core 端口契约（core/ports/tasks.py）零 Qt 依赖。
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal

from core.ports.tasks import TaskHandle, TaskRunner


class _Worker(QThread):
    result_ready = Signal(object)
    error_ready = Signal(object)
    progress_ready = Signal(str, int, int)

    def __init__(self, func: Callable, args: tuple, kwargs: dict) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._func(*self._args, **self._kwargs)
            self.result_ready.emit(result)
        except Exception as exc:  # 后台异常经信号传回 UI 线程
            self.error_ready.emit(exc)


class QtTaskHandle(TaskHandle):
    """包装 QThread 以满足 TaskHandle 端口（cancel / join / is_running）。"""

    def __init__(self, worker: _Worker) -> None:
        self._worker = worker

    def cancel(self) -> None:
        """请求线程退出并阻塞直到其完全终止，避免对象销毁时线程仍在运行。"""
        try:
            self._worker.quit()
            self._worker.wait()
        except RuntimeError:
            # worker 的 C++ 对象已被 deleteLater 销毁（线程已结束）
            pass

    def join(self) -> None:
        """阻塞直到后台线程执行完毕（对象销毁前必须确保线程已终止）。"""
        try:
            self._worker.wait()
        except RuntimeError:
            # worker 的 C++ 对象已被 deleteLater 销毁（线程已结束）
            pass

    def is_running(self) -> bool:
        try:
            return self._worker.isRunning()
        except RuntimeError:
            return False


class QtTaskRunner(TaskRunner):
    """基于 QThread 的 TaskRunner 实现。"""

    def __init__(self) -> None:
        # 持有活动 worker 的强引用，避免任务执行期间 worker 被提前回收
        # （裸 QThread 在后台线程仍运行时被析构会触发 SIGABRT）。
        self._active: set = set()

    def submit(
        self,
        func: Callable[..., Any],
        *,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        on_progress: Optional[Callable[[str, int, int], None]] = None,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> TaskHandle:
        worker = _Worker(func, args, kwargs or {})
        if on_progress is not None:
            worker.progress_ready.connect(
                lambda m, c, t: on_progress(m, c, t)
            )
        if on_result is not None:
            worker.result_ready.connect(lambda r: on_result(r))
        if on_error is not None:
            worker.error_ready.connect(lambda e: on_error(e))
        # 线程结束后自清理 C++ 对象（需事件循环；无事件循环时由 GC 兜底）。
        # 配合 _active 强引用，保证任务执行期间 worker 不会被提前析构。
        worker.finished.connect(lambda: self._active.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self._active.add(worker)
        worker.start()
        return QtTaskHandle(worker)


def async_task(method: Callable) -> Callable:
    """装饰 ViewModel 方法：调用时经 ``self._task_runner`` 后台执行原方法。

    后台任务抛出的异常回调到 ``self.on_async_error(exc)``（若 ViewModel 定义）。
    进度/结果通过事件端口（EventEmitter）推送给 UI，而非此装饰器直接处理。

    ``_task_runner`` 必须由 ``BaseViewModel.__init__`` 注入；若子类忘记调用
    ``super().__init__(task_runner=...)``，装饰器在调用时抛出 RuntimeError。
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        # 不再用 getattr 静默回退：task_runner 必须由 BaseViewModel 构造注入。
        # 若子类忘记调用 super().__init__()，这里给出明确、可操作的报错。
        try:
            runner = self._task_runner
        except AttributeError:
            raise RuntimeError(
                f"@async_task used on {type(self).__name__}.{method.__name__}, "
                f"but _task_runner was not injected. "
                f"Did you forget to call super().__init__(task_runner=...)?"
            ) from None

        def _run():
            return method(self, *args, **kwargs)

        def _err(exc: Exception):
            hook = getattr(self, "on_async_error", None)
            if callable(hook):
                hook(exc)

        handle = runner.submit(_run, on_error=_err)
        # 记录最近一次任务句柄，供 stop_worker / 取消使用
        self._current_task = handle
        return handle

    return wrapper
