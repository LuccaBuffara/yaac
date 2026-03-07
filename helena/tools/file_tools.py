"""File operation tools for Helena Code."""

import asyncio
import os
import re
import tempfile
from pathlib import Path

from ..tool_events import emit_call, emit_return, emit_patch
from ..lsp.client import SEVERITY


async def _lsp_diagnostics_suffix(path: str) -> str:
    """Return a formatted diagnostics block to append to a tool result, or '' if unavailable."""
    try:
        from ..lsp.manager import get_client
        client = await get_client(str(Path(path).expanduser().resolve()))
        if client is None:
            return ""
        diags = await client.get_diagnostics(path)
        if not diags:
            return "\n\nLSP: no diagnostics — file looks clean."
        lines = []
        for d in diags:
            sev = SEVERITY.get(d.get("severity", 1), "ERROR")
            start = d.get("range", {}).get("start", {})
            ln = start.get("line", 0) + 1
            col = start.get("character", 0) + 1
            msg = d.get("message", "")
            source = d.get("source", "")
            prefix = f"[{source}] " if source else ""
            lines.append(f"  {sev} {ln}:{col}  {prefix}{msg}")
        return "\n\nLSP diagnostics:\n" + "\n".join(lines)
    except Exception:
        return ""


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
    if result.startswith("Successfully"):
        result += await _lsp_diagnostics_suffix(path)
    emit_return("write_file", result)
    return result


async def update_file(path: str, diff: str) -> str:
    """Apply a unified diff (@@ hunks) to a file. Token-efficient alternative to
    edit_file for multi-location changes — only changed lines + context needed.
    --- / +++ headers are optional.

    Args:
        path: Path to the file.
        diff: Unified diff string (one or more @@ hunks).

    Returns:
        Success or error message.
    """
    emit_call("update_file", {"path": path})
    result = await asyncio.to_thread(_update_file_sync, path, diff)
    if result.startswith("Successfully"):
        emit_patch(path, diff)
        result += await _lsp_diagnostics_suffix(path)
    emit_return("update_file", result)
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


def _update_file_sync(path: str, diff: str) -> str:
    import subprocess

    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        return f"Error: File not found: {path}"

    # Ensure the diff has the --- / +++ header lines that `patch` requires to
    # recognise unified format.  We use placeholder names; the actual target
    # file is passed as a positional argument so patch ignores the header paths.
    stripped = diff.lstrip()
    if not stripped.startswith("---"):
        diff = f"--- a\n+++ b\n{stripped}"

    patch_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False, encoding="utf-8"
        ) as f:
            f.write(diff)
            patch_path = f.name

        result = subprocess.run(
            ["patch", "--forward", str(file_path), patch_path],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Successfully patched {file_path}"
        # patch writes useful detail to stdout on failure
        detail = (result.stdout or result.stderr or "").strip()
        return f"Error applying patch: {detail}"
    except FileNotFoundError:
        # `patch` not available — fall back to pure-Python hunk applier
        return _apply_hunks_python(file_path, diff)
    except Exception as exc:
        return f"Error applying patch: {exc}"
    finally:
        if patch_path:
            try:
                os.unlink(patch_path)
            except Exception:
                pass


def _apply_hunks_python(file_path: Path, diff: str) -> str:
    """Pure-Python fallback unified-diff applier (no subprocess required)."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        return f"Error reading file: {exc}"

    hunk_header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    diff_lines = diff.splitlines()

    # Collect hunks: list of (old_start_0idx, old_lines, new_lines)
    hunks: list[tuple[int, list[str], list[str]]] = []
    i = 0
    while i < len(diff_lines):
        m = hunk_header.match(diff_lines[i])
        if not m:
            i += 1
            continue
        old_start = int(m.group(1)) - 1  # convert to 0-indexed
        i += 1
        old_part: list[str] = []
        new_part: list[str] = []
        while i < len(diff_lines) and not hunk_header.match(diff_lines[i]):
            hl = diff_lines[i]
            if hl.startswith("-"):
                old_part.append(hl[1:])
            elif hl.startswith("+"):
                new_part.append(hl[1:])
            elif hl.startswith(" "):
                old_part.append(hl[1:])
                new_part.append(hl[1:])
            # skip "\ No newline at end of file" and header lines
            i += 1
        hunks.append((old_start, old_part, new_part))

    if not hunks:
        return "Error: No valid @@ hunks found in diff."

    # Apply in reverse so earlier line-number changes don't shift later hunks
    for old_start, old_part, new_part in reversed(hunks):
        def _ensure_nl(s: str) -> str:
            return s if s.endswith("\n") else s + "\n"

        old_with_nl = [_ensure_nl(l) for l in old_part]
        new_with_nl = [_ensure_nl(l) for l in new_part]
        end = old_start + len(old_with_nl)
        if lines[old_start:end] != old_with_nl:
            return (
                f"Error: Hunk at line {old_start + 1} does not match file contents. "
                "Make sure context lines are correct."
            )
        lines[old_start:end] = new_with_nl

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return f"Successfully patched {file_path}"
    except Exception as exc:
        return f"Error writing patched file: {exc}"


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
