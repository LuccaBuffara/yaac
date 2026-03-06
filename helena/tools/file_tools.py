"""File operation tools for Helena Code."""

import asyncio
from pathlib import Path

from ..tool_events import emit_call, emit_return


async def read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
    """Read a file from the filesystem.

    Args:
        path: Absolute or relative path to the file.
        offset: Line number to start reading from (1-indexed).
        limit: Maximum number of lines to read.

    Returns:
        File contents with line numbers in cat -n format.
    """
    emit_call("read_file", {"path": path, "offset": offset, "limit": limit})
    result = await asyncio.to_thread(_read_file_sync, path, offset, limit)
    emit_return("read_file", result)
    return result


async def write_file(path: str, content: str) -> str:
    """Write content to a file, creating it if it doesn't exist.

    Args:
        path: Absolute or relative path to the file.
        content: Content to write to the file.

    Returns:
        Success or error message.
    """
    emit_call("write_file", {"path": path, "content": content[:80] + "..." if len(content) > 80 else content})
    result = await asyncio.to_thread(_write_file_sync, path, content)
    emit_return("write_file", result)
    return result


async def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Edit a file by replacing an exact string match.

    The old_string must match exactly (including whitespace/indentation).
    For new files, use write_file instead.

    Args:
        path: Absolute or relative path to the file.
        old_string: The exact string to find and replace.
        new_string: The string to replace it with.

    Returns:
        Success or error message.
    """
    emit_call("edit_file", {"path": path})
    result = await asyncio.to_thread(_edit_file_sync, path, old_string, new_string)
    emit_return("edit_file", result)
    return result


async def list_directory(path: str = ".") -> str:
    """List the contents of a directory.

    Args:
        path: Path to the directory. Defaults to current directory.

    Returns:
        Directory listing with file sizes and types.
    """
    emit_call("list_directory", {"path": path})
    result = await asyncio.to_thread(_list_directory_sync, path)
    emit_return("list_directory", result)
    return result


# --- sync implementations ---------------------------------------------------

def _read_file_sync(path: str, offset: int, limit: int) -> str:
    file_path = Path(path).expanduser().resolve()

    if not file_path.exists():
        return f"Error: File not found: {path}"
    if not file_path.is_file():
        return f"Error: Path is not a file: {path}"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        start = max(0, offset - 1)
        end = start + limit
        selected = lines[start:end]

        numbered = [f"{i:6d}\t{line}" for i, line in enumerate(selected, start=start + 1)]
        result = "".join(numbered)
        if end < len(lines):
            result += f"\n... ({len(lines) - end} more lines, use offset/limit to read more)"

        return result or "(empty file)"
    except Exception as e:
        return f"Error reading file: {e}"


def _write_file_sync(path: str, content: str) -> str:
    file_path = Path(path).expanduser().resolve()
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} characters to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


def _edit_file_sync(path: str, old_string: str, new_string: str) -> str:
    file_path = Path(path).expanduser().resolve()

    if not file_path.exists():
        return f"Error: File not found: {path}"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return f"Error: String not found in {path}. Make sure the string matches exactly."
        if count > 1:
            return f"Error: Found {count} matches in {path}. Provide more context to make it unique."

        new_content = content.replace(old_string, new_string, 1)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"Successfully edited {file_path}"
    except Exception as e:
        return f"Error editing file: {e}"


def _list_directory_sync(path: str) -> str:
    dir_path = Path(path).expanduser().resolve()

    if not dir_path.exists():
        return f"Error: Directory not found: {path}"
    if not dir_path.is_dir():
        return f"Error: Path is not a directory: {path}"

    try:
        entries = sorted(dir_path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        if not entries:
            return f"{dir_path}/ (empty)"

        lines = [f"{dir_path}/"]
        for entry in entries:
            if entry.is_dir():
                lines.append(f"  {entry.name}/")
            else:
                size_str = _format_size(entry.stat().st_size)
                lines.append(f"  {entry.name} ({size_str})")

        return "\n".join(lines)
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error listing directory: {e}"


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
