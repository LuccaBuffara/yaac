"""Session-scoped todo persistence for YAAC.

Todos are stored as JSON in .yaac/todos/{session_id}.json so that
concurrent sessions never conflict.  Each write immediately persists
the full state to disk.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..session import get_session_id
from ..tool_events import emit_call, emit_return

_YAAC_DIR = ".yaac"
_TODOS_DIR = "todos"

_VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


def _todos_path() -> Path:
    return Path.cwd() / _YAAC_DIR / _TODOS_DIR / f"{get_session_id()}.json"


def _load_store() -> dict[str, Any]:
    path = _todos_path()
    if not path.exists():
        return {"session_id": get_session_id(), "todos": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"session_id": get_session_id(), "todos": []}


def _save_store(store: dict[str, Any]) -> None:
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _todos_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def _format_todos(todos: list[dict[str, Any]]) -> str:
    if not todos:
        return "No todos for this session."
    lines = []
    for t in todos:
        status = t.get("status", "pending")
        check = "x" if status == "completed" else " "
        marker = {
            "pending": "PENDING",
            "in_progress": "IN_PROGRESS",
            "completed": "COMPLETED",
            "cancelled": "CANCELLED",
        }.get(status, status.upper())
        lines.append(f"- [{check}] ({marker}) [{t['id']}] {t['content']}")
    return "\n".join(lines)


async def todo_read() -> str:
    """Read all todos for the current session.

    Returns:
        Formatted list of current todos or a message if none exist.
    """
    emit_call("todo_read", {})
    store = _load_store()
    result = _format_todos(store["todos"])
    emit_return("todo_read", result)
    return result


async def todo_write(todos: list[dict[str, str]], merge: bool = True) -> str:
    """Create or update todos for the current session.

    Each todo must have 'id', 'content', and 'status' keys.
    Valid statuses: pending, in_progress, completed, cancelled.

    Args:
        todos: List of todo items to write. Each item needs 'id', 'content', 'status'.
        merge: If True, merge into existing todos by id (update matched, append new).
               If False, replace all existing todos with the provided list.

    Returns:
        Updated todo list summary.
    """
    emit_call("todo_write", {"count": len(todos), "merge": merge})

    for t in todos:
        if "id" not in t or "content" not in t or "status" not in t:
            result = "Error: every todo must have 'id', 'content', and 'status' keys."
            emit_return("todo_write", result)
            return result
        if t["status"] not in _VALID_STATUSES:
            result = f"Error: invalid status '{t['status']}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}."
            emit_return("todo_write", result)
            return result

    store = _load_store()

    if not merge:
        store["todos"] = list(todos)
    else:
        existing_by_id = {t["id"]: t for t in store["todos"]}
        for t in todos:
            existing_by_id[t["id"]] = {**existing_by_id.get(t["id"], {}), **t}
        store["todos"] = list(existing_by_id.values())

    _save_store(store)

    all_done = (
        store["todos"]
        and all(t.get("status") in ("completed", "cancelled") for t in store["todos"])
    )

    result = _format_todos(store["todos"])
    if all_done:
        _todos_path().unlink(missing_ok=True)
        result += "\n\nAll tasks done — session todo file cleaned up."

    emit_return("todo_write", result)
    return result
