"""LSP server definitions for Helena Code."""

import os
import sys
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerDef:
    id: str
    command: list[str]
    extensions: list[str]
    root_markers: list[str]
    # How long to wait for the first publishDiagnostics notification (ms).
    diag_wait_ms: int = 10000


def _resolve_pylsp() -> str:
    """Find pylsp: prefer the same venv as the running Python, then PATH."""
    venv_pylsp = str(Path(sys.executable).parent / "pylsp")
    if os.path.isfile(venv_pylsp) and os.access(venv_pylsp, os.X_OK):
        return venv_pylsp
    if shutil.which("pylsp"):
        return "pylsp"
    return venv_pylsp  # will fail gracefully if missing


def _resolve_ts_server() -> str:
    """Find typescript-language-server: on PATH or in common npm-global locations."""
    if shutil.which("typescript-language-server"):
        return "typescript-language-server"
    candidates = [
        os.path.expanduser("~/.npm-global/bin/typescript-language-server"),
        "/usr/local/bin/typescript-language-server",
        "/opt/homebrew/bin/typescript-language-server",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "typescript-language-server"  # fallback, will fail gracefully


SERVERS: list[ServerDef] = [
    ServerDef(
        id="pylsp",
        command=[_resolve_pylsp()],
        extensions=[".py"],
        root_markers=["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", ".git"],
        diag_wait_ms=12000,
    ),
    ServerDef(
        id="pyright",
        command=["pyright-langserver", "--stdio"],
        extensions=[".py"],
        root_markers=["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", ".git"],
    ),
    ServerDef(
        id="typescript",
        command=[_resolve_ts_server(), "--stdio"],
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
    start = Path(path).expanduser().resolve().parent if Path(path).is_file() else Path(path).expanduser().resolve()
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
    """Return only servers whose binary exists on PATH or as an absolute path."""
    result = []
    for s in SERVERS:
        cmd = s.command[0]
        if os.path.isabs(cmd):
            if os.path.isfile(cmd) and os.access(cmd, os.X_OK):
                result.append(s)
        elif shutil.which(cmd) is not None:
            result.append(s)
    return result


def server_for_file(path: str) -> ServerDef | None:
    """Return the first available server that handles the given file's extension."""
    ext = Path(path).suffix.lower()
    for s in available_servers():
        if ext in s.extensions:
            return s
    return None
