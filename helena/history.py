"""Conversation history persistence for Helena Code.

Saves and loads the full message history to .helena/history.json in the
working directory, so conversations persist across sessions.
"""

from pathlib import Path
from pydantic_ai.messages import ModelMessagesTypeAdapter

HELENA_DIR = ".helena"
HISTORY_FILE = "history.json"


def _history_path() -> Path:
    return Path.cwd() / HELENA_DIR / HISTORY_FILE


def load_history() -> list:
    """Load conversation history from .helena/history.json.

    Returns an empty list if no history file exists yet.
    """
    path = _history_path()
    if not path.exists():
        return []
    try:
        return ModelMessagesTypeAdapter.validate_json(path.read_bytes())
    except Exception:
        return []


def save_history(messages: list) -> None:
    """Persist conversation history to .helena/history.json."""
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ModelMessagesTypeAdapter.dump_json(messages))


def clear_history() -> None:
    """Delete the history file."""
    path = _history_path()
    if path.exists():
        path.unlink()
