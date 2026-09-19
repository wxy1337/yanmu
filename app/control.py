from __future__ import annotations

from contextvars import ContextVar
from threading import Event


class JobCancelled(Exception):
    pass


cancel_event: ContextVar[Event | None] = ContextVar("cancel_event", default=None)


def check_cancelled() -> None:
    event = cancel_event.get()
    if event is not None and event.is_set():
        raise JobCancelled("任务已取消，已完成的步骤可以在重试时复用。")


def interruptible_wait(seconds: float) -> None:
    event = cancel_event.get()
    (event or Event()).wait(seconds)
    check_cancelled()
