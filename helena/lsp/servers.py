"""LSP server definitions for Helena Code."""

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerDef:
    id: str
    command: list[str]
    extensions: list[str]
    root_markers: list[str]


SERVERS: list[ServerDef] = [
    ServerDef(
        id="pyright",
        command=["pyright-langserver", "--stdio"],
        extensions=[".py"],
        root_markers=["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", ".git"],
    ),
    ServerDef(
        id="typescript",
        command=["typescript-language-server", "--stdio"],
        extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"],
        root_markers=["package.json", "tsconfig.json", ".git"],
    ),
    ServerDef(
        id="rust-analyzer",
        command=["rust-analyzer"],
        extensions=[".rs"],
        root_markers=["Cargo.toml"],
    ),
    ServerDef(
        id="gopls",
        command=["gopls"],
        extensions=[".go"],
        root_markers=["go.mod", ".git"],
    ),
    ServerDef(
        id="clangd",
        command=["clangd"],
        extensions=[".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"],
        root_markers=["compile_commands.json", "CMakeLists.txt", ".git"],
    ),
]


def find_root(path: str, markers: list[str]) -> str:
    """Walk up from path looking for the first directory that contains a marker file.
    Falls back to the file's own directory if no marker is found.
    """
    start = Path(path).parent if Path(path).is_file() else Path(path)
    p = start
    while True:
        for m in markers:
            if (p / m).exists():
                return str(p)
        parent = p.parent
        if parent == p:
            break
        p = parent
    return str(start)


def available_servers() -> list[ServerDef]:
    """Return only servers whose binary exists on PATH."""
    return [s for s in SERVERS if shutil.which(s.command[0]) is not None]


def server_for_file(path: str) -> ServerDef | None:
    """Return the first available server that handles the given file's extension."""
    ext = Path(path).suffix.lower()
    for s in available_servers():
        if ext in s.extensions:
            return s
    return None
