"""Conversation history persistence for Helena Code.

Saves and loads the full message history to .helena/history.json in the
working directory, so conversations persist across sessions.
"""

from dataclasses import replace
from pathlib import Path
from pydantic_ai.messages import ModelMessagesTypeAdapter

HELENA_DIR = ".helena"
HISTORY_FILE = "history.json"

# Tool results larger than this are truncated before being stored/reused as
# context.  Keeps per-turn input costs sane when files/bash output are large.
_MAX_TOOL_RESULT_CHARS = 3_000
_MAX_HISTORY_MESSAGES = 40   # ~20 turns; oldest messages are dropped when exceeded


def _history_path() -> Path:
    return Path.cwd() / HELENA_DIR / HISTORY_FILE


def trim_tool_results(messages: list) -> list:
    """Return a copy of messages with oversized tool results truncated.

    Only ToolReturnPart content is touched; everything else is left intact.
    This is applied when saving and when reloading history so that old large
    results don't keep burning input tokens every turn.
    """
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    out = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            out.append(msg)
            continue
        new_parts = []
        changed = False
        for part in msg.parts:
            if (
                isinstance(part, ToolReturnPart)
                and isinstance(part.content, str)
                and len(part.content) > _MAX_TOOL_RESULT_CHARS
            ):
                truncated = (
                    part.content[:_MAX_TOOL_RESULT_CHARS]
                    + f"\n… [truncated {len(part.content) - _MAX_TOOL_RESULT_CHARS} chars]"
                )
                new_parts.append(replace(part, content=truncated))
                changed = True
            else:
                new_parts.append(part)
        out.append(replace(msg, parts=new_parts) if changed else msg)
    return out


def trim_history(messages: list) -> list:
    """Drop the oldest messages when history exceeds _MAX_HISTORY_MESSAGES.

    Keeps the most recent messages so the agent always has fresh context.
    Combined with trim_tool_results this keeps per-turn costs bounded.
    """
    if len(messages) > _MAX_HISTORY_MESSAGES:
        return messages[-_MAX_HISTORY_MESSAGES:]
    return messages


def load_history() -> list:
    """Load conversation history from .helena/history.json.

    Returns an empty list if no history file exists yet.
    """
    path = _history_path()
    if not path.exists():
        return []
    try:
        messages = ModelMessagesTypeAdapter.validate_json(path.read_bytes())
        return trim_history(trim_tool_results(messages))
    except Exception:
        return []


def save_history(messages: list) -> None:
    """Persist conversation history to .helena/history.json."""
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ModelMessagesTypeAdapter.dump_json(trim_history(trim_tool_results(messages))))


def clear_history() -> None:
    """Delete the history file."""
    path = _history_path()
    if path.exists():
        path.unlink()
