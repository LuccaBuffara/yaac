"""Search tools for Helena Code."""

import asyncio
import fnmatch
import os
import re
from pathlib import Path

from ..tool_events import emit_call, emit_return


async def glob_search(pattern: str, directory: str = ".") -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern like '**/*.py' or 'src/**/*.ts'.
        directory: Directory to search in. Defaults to current directory.

    Returns:
        Newline-separated list of matching file paths, sorted by modification time.
    """
    base = Path(directory).expanduser().resolve()

    if not base.exists():
        return f"Error: Directory not found: {directory}"

    emit_call("glob_search", {"pattern": pattern, "directory": directory})
    result = await asyncio.to_thread(_glob_sync, base, pattern)
    emit_return("glob_search", result)
    return result


async def grep_search(
    pattern: str,
    path: str = ".",
    file_pattern: str = "*",
    ignore_case: bool = False,
    max_results: int = 100,
) -> str:
    """Search for a regex pattern in file contents.

    Args:
        pattern: Regular expression pattern to search for.
        path: File or directory to search in.
        file_pattern: Glob pattern to filter files (e.g. '*.py').
        ignore_case: Whether to ignore case in the pattern.
        max_results: Maximum number of matching lines to return.

    Returns:
        Matching lines in 'filepath:linenum:content' format.
    """
    search_path = Path(path).expanduser().resolve()

    if not search_path.exists():
        return f"Error: Path not found: {path}"

    try:
        flags = re.IGNORECASE if ignore_case else 0
        re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    emit_call("grep_search", {"pattern": pattern, "path": path, "file_pattern": file_pattern})
    result = await asyncio.to_thread(_grep_sync, search_path, pattern, file_pattern, ignore_case, max_results)
    emit_return("grep_search", result)
    return result


# --- sync implementations ---------------------------------------------------

def _glob_sync(base: Path, pattern: str) -> str:
    try:
        matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            return f"No files found matching '{pattern}' in {base}"
        lines = [str(p) for p in matches]
        if len(lines) > 100:
            return "\n".join(lines[:100]) + f"\n... ({len(lines) - 100} more results)"
        return "\n".join(lines)
    except Exception as e:
        return f"Error during glob search: {e}"


def _grep_sync(
    search_path: Path,
    pattern: str,
    file_pattern: str,
    ignore_case: bool,
    max_results: int,
) -> str:
    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)
    results = []
    files_to_search: list[Path] = []

    if search_path.is_file():
        files_to_search = [search_path]
    else:
        for root, dirs, files in os.walk(search_path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv")
            ]
            for fname in files:
                if fnmatch.fnmatch(fname, file_pattern):
                    files_to_search.append(Path(root) / fname)

    for file_path in files_to_search:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    if regex.search(line):
                        results.append(f"{file_path}:{lineno}:{line.rstrip()}")
                        if len(results) >= max_results:
                            break
        except (PermissionError, IsADirectoryError):
            continue
        if len(results) >= max_results:
            break

    if not results:
        return f"No matches found for '{pattern}'"

    output = "\n".join(results)
    if len(results) >= max_results:
        output += f"\n\n[Showing first {max_results} results. Narrow your search for more precise results.]"
    return output
