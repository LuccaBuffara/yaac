"""Lightweight event system for real-time tool call display.

Tools emit events via ContextVar so the display layer can show them
without polling pydantic-ai's internal message state concurrently.
"""

from contextvars import ContextVar
from typing import Callable

type EventHandler = Callable[[str, str, dict | str], None]

_handler: ContextVar[EventHandler | None] = ContextVar("_handler", default=None)


def set_handler(fn: EventHandler) -> object:
    """Register an event handler for the current async context. Returns a reset token."""
    return _handler.set(fn)


def reset_handler(token: object) -> None:
    _handler.reset(token)


def emit_call(tool_name: str, args: dict) -> None:
    h = _handler.get()
    if h:
        h("call", tool_name, args)


def emit_return(tool_name: str, result: str) -> None:
    h = _handler.get()
    if h:
        h("return", tool_name, result)


def emit_diff(path: str, old_string: str, new_string: str) -> None:
    h = _handler.get()
    if h:
        h("diff", path, {"old": old_string, "new": new_string})


def emit_patch(path: str, diff: str) -> None:
    h = _handler.get()
    if h:
        h("patch", path, {"diff": diff})
