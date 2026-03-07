"""Project memory tools for YAAC."""

from __future__ import annotations

from pathlib import Path

from ..tool_events import emit_call, emit_return

_DEFAULT_MEMORY_TEMPLATE = """# Project Memory

## Stable conventions
- 

## Architecture notes
- 

## Workflow preferences
- 

## Open cautions
- 
"""


def _memory_path() -> Path:
    return Path.cwd() / ".yaac" / "memory" / "MEMORY.md"


async def memory_read() -> str:
    """Read the durable project memory file for the current workspace."""
    emit_call("memory_read", {})
    path = _memory_path()
    if not path.exists():
        result = (
            "No project memory file exists yet. "
            f"Expected location: {path}. "
            "Use memory_write to create one."
        )
        emit_return("memory_read", result)
        return result

    try:
        text = path.read_text(encoding="utf-8")
        result = f"Project memory from {path}:\n\n{text}"
    except Exception as e:
        result = f"Error reading project memory: {e}"

    emit_return("memory_read", result)
    return result


async def memory_write(content: str, append: bool = False) -> str:
    """Create or update the durable project memory file for the current workspace."""
    emit_call("memory_write", {"append": append})
    path = _memory_path()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            existing = path.read_text(encoding="utf-8")
            new_text = existing.rstrip() + "\n\n" + content.strip() + "\n"
        else:
            body = content.strip() or _DEFAULT_MEMORY_TEMPLATE.strip()
            new_text = body + "\n"
        path.write_text(new_text, encoding="utf-8")
        result = f"Project memory saved to {path}."
    except Exception as e:
        result = f"Error writing project memory: {e}"

    emit_return("memory_write", result)
    return result
