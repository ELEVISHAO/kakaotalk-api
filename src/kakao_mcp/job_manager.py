"""Serial job queue for KakaoTalk UI automation."""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, Optional


class JobWaitTimeout(Exception):
    """Raised when a job does not start within the wait timeout."""


class _JobItem:
    __slots__ = ("future", "fn", "args", "kwargs", "started", "cancelled")

    def __init__(self, future: Future, fn: Callable[..., Any], args: tuple, kwargs: dict):
        self.future = future
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.started = threading.Event()
        self.cancelled = False


class JobManager:
    """Single-worker queue so only one Win32 UI automation job runs at a time."""

    def __init__(self, wait_timeout_sec: float = 60.0, exec_timeout_sec: float = 300.0):
        self.wait_timeout_sec = wait_timeout_sec
        self.exec_timeout_sec = exec_timeout_sec
        self._q: queue.Queue[Optional[_JobItem]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="kakao-ui-worker", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=timeout)

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        wait_timeout_sec: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        if self._thread is None or not self._thread.is_alive():
            self.start()

        fut: Future = Future()
        item = _JobItem(fut, fn, args, kwargs)
        self._q.put(item)

        wait = self.wait_timeout_sec if wait_timeout_sec is None else wait_timeout_sec
        if not item.started.wait(timeout=wait):
            item.cancelled = True
            raise JobWaitTimeout("automation queue wait timed out")

        return fut.result(timeout=self.exec_timeout_sec)

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            if item.cancelled:
                continue
            item.started.set()
            if item.cancelled:
                continue
            if not item.future.set_running_or_notify_cancel():
                continue
            try:
                item.future.set_result(item.fn(*item.args, **item.kwargs))
            except Exception as e:
                item.future.set_exception(e)


_manager: Optional[JobManager] = None
_manager_lock = threading.Lock()


def get_job_manager(
    wait_timeout_sec: float = 60.0,
    exec_timeout_sec: float = 300.0,
) -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager(wait_timeout_sec, exec_timeout_sec)
            _manager.start()
        return _manager


def reset_job_manager_for_tests() -> None:
    """Stop and clear the singleton (tests only)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.stop()
            _manager = None
