"""Workspace instruction and memory file discovery for YAAC.

Supports Claude-style project instructions and durable project memory:
- `AGENTS.md` files discovered from the workspace root up to the filesystem root
- `MEMORY.md` discovered in the workspace or `.yaac/memory/MEMORY.md`

The discovered content is injected into the agent's system prompt so it is
available across sessions without relying on transient conversation history.
"""

from __future__ import annotations

from pathlib import Path

_MAX_FILE_CHARS = 12_000


def _truncate(text: str, limit: int = _MAX_FILE_CHARS) -> str:
    if len(text) <= limit:
        return text
    remaining = len(text) - limit
    return text[:limit].rstrip() + f"\n\n[truncated {remaining} chars]"


def _read_if_exists(path: Path) -> str | None:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        return None
    return None


def discover_agents_files(start_dir: Path | None = None) -> list[Path]:
    """Return AGENTS.md files from filesystem root to the current workspace.

    This mirrors Claude-style hierarchical instruction loading where closer
    files override or add to broader parent-level instructions.
    """
    current = (start_dir or Path.cwd()).resolve()
    found: list[Path] = []

    for directory in reversed([current, *current.parents]):
        candidate = directory / "AGENTS.md"
        if candidate.is_file():
            found.append(candidate)

    return found


def discover_memory_file(start_dir: Path | None = None) -> Path | None:
    """Return the preferred project memory file if one exists."""
    current = (start_dir or Path.cwd()).resolve()
    candidates = [
        current / "MEMORY.md",
        current / ".yaac" / "memory" / "MEMORY.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_context_prompt(start_dir: Path | None = None) -> str:
    """Build system-prompt additions from AGENTS.md and MEMORY.md files."""
    current = (start_dir or Path.cwd()).resolve()
    sections: list[str] = []

    agents_files = discover_agents_files(current)
    if agents_files:
        rendered = []
        for path in agents_files:
            text = _read_if_exists(path)
            if not text:
                continue
            rendered.append(
                f"<agents_file path=\"{path}\">\n{_truncate(text.strip())}\n</agents_file>"
            )
        if rendered:
            sections.append(
                "## Workspace Instructions (AGENTS.md)\n\n"
                "Apply these instruction files in order from broadest parent directory to the current workspace.\n"
                "More local files are more specific and should take precedence when instructions conflict.\n\n"
                + "\n\n".join(rendered)
            )

    memory_file = discover_memory_file(current)
    if memory_file:
        text = _read_if_exists(memory_file)
        if text:
            sections.append(
                "## Project Memory\n\n"
                "This is durable project memory that should inform decisions across sessions.\n\n"
                f"<project_memory path=\"{memory_file}\">\n{_truncate(text.strip())}\n</project_memory>"
            )

    if not sections:
        return ""

    return "\n\n" + "\n\n".join(sections)
