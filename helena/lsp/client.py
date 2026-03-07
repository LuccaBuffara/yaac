"""Single LSP server client for Helena Code."""

import asyncio
import os
from pathlib import Path
from urllib.parse import unquote

from .protocol import LSPProtocol

LANGUAGE_IDS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".mts": "typescript",
    ".cts": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "shellscript",
    ".bash": "shellscript",
    ".zsh": "shellscript",
    ".lua": "lua",
    ".r": "r",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".md": "markdown",
    ".zig": "zig",
}

SEVERITY = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}

SYMBOL_KIND = {
    1: "File", 2: "Module", 3: "Namespace", 4: "Package", 5: "Class",
    6: "Method", 7: "Property", 8: "Field", 9: "Constructor", 10: "Enum",
    11: "Interface", 12: "Function", 13: "Variable", 14: "Constant",
    22: "EnumMember", 23: "Struct", 25: "Operator", 26: "TypeParameter",
}


def _file_uri(path: str) -> str:
    return Path(path).as_uri()


def _uri_to_path(uri: str) -> str:
    path = uri.removeprefix("file://")
    return unquote(path)


class LSPClient:
    """Manages a connection to one LSP server process."""

    def __init__(self, server_id: str, command: list[str], root: str, diag_wait_ms: int = 10000):
        self.server_id = server_id
        self._command = command
        self._root = root
        self._server_diag_wait_ms = diag_wait_ms
        self._protocol: LSPProtocol | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._open_files: dict[str, int] = {}   # abs_path -> version
        self._diagnostics: dict[str, list[dict]] = {}
        self._diag_events: dict[str, asyncio.Event] = {}
        self._started = False

    async def start(self) -> bool:
        """Spawn the LSP server and run the initialize handshake. Returns True on success."""
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError):
            return False

        self._protocol = LSPProtocol(self._proc.stdout, self._proc.stdin)
        self._protocol.on("textDocument/publishDiagnostics", self._on_diagnostics)
        # Silence server-side requests we don't need to handle
        self._protocol.on("window/workDoneProgress/create", lambda _: None)
        self._protocol.on("client/registerCapability", lambda _: None)
        self._protocol.start()

        root_uri = _file_uri(self._root)
        result = await self._protocol.request("initialize", {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "workspaceFolders": [{"uri": root_uri, "name": "workspace"}],
            "capabilities": {
                "textDocument": {
                    "synchronization": {
                        "didOpen": True,
                        "didChange": True,
                        "didClose": True,
                    },
                    "publishDiagnostics": {"versionSupport": False},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "definition": {"linkSupport": False},
                    "references": {},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                },
                "workspace": {
                    "symbol": {},
                    "configuration": True,
                },
            },
            "initializationOptions": {},
        }, timeout=20.0)

        if result is None:
            await self.shutdown()
            return False

        self._protocol.notify("initialized", {})
        self._started = True
        return True

    def _on_diagnostics(self, params: dict) -> None:
        uri = params.get("uri", "")
        path = _uri_to_path(uri)
        self._diagnostics[path] = params.get("diagnostics", [])
        event = self._diag_events.get(path)
        if event:
            event.set()

    async def open_file(self, path: str) -> None:
        """Notify the LSP that a file was opened or its contents changed."""
        if not self._started or not self._protocol:
            return
        abs_path = str(Path(path).resolve())
        lang_id = LANGUAGE_IDS.get(Path(path).suffix.lower(), "plaintext")
        try:
            content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        uri = _file_uri(abs_path)
        version = self._open_files.get(abs_path)
        if version is None:
            self._protocol.notify("textDocument/didOpen", {
                "textDocument": {"uri": uri, "languageId": lang_id, "version": 0, "text": content},
            })
            self._open_files[abs_path] = 0
        else:
            next_ver = version + 1
            self._open_files[abs_path] = next_ver
            self._protocol.notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": next_ver},
                "contentChanges": [{"text": content}],
            })
        try:
            await self._protocol._writer.drain()
        except Exception:
            pass

    async def get_diagnostics(self, path: str, wait_ms: int = 8000) -> list[dict]:
        """Open/refresh the file, wait up to wait_ms for diagnostics, and return them."""
        abs_path = str(Path(path).resolve())
        event = asyncio.Event()
        self._diag_events[abs_path] = event
        self._diagnostics.pop(abs_path, None)
        await self.open_file(abs_path)
        try:
            await asyncio.wait_for(event.wait(), timeout=wait_ms / 1000)
        except asyncio.TimeoutError:
            pass
        finally:
            self._diag_events.pop(abs_path, None)
        return self._diagnostics.get(abs_path, [])

    def _pos_params(self, path: str, line: int, character: int) -> dict:
        return {
            "textDocument": {"uri": _file_uri(str(Path(path).resolve()))},
            "position": {"line": line - 1, "character": character - 1},
        }

    async def hover(self, path: str, line: int, character: int) -> str | None:
        if not self._started or not self._protocol:
            return None
        await self.open_file(path)
        result = await self._protocol.request(
            "textDocument/hover", self._pos_params(path, line, character)
        )
        if not result:
            return None
        contents = result.get("contents", "")
        if isinstance(contents, dict):
            return contents.get("value", "")
        if isinstance(contents, list):
            return "\n".join(
                c.get("value", c) if isinstance(c, dict) else str(c) for c in contents
            )
        return str(contents)

    async def definition(self, path: str, line: int, character: int) -> list[dict]:
        if not self._started or not self._protocol:
            return []
        await self.open_file(path)
        result = await self._protocol.request(
            "textDocument/definition", self._pos_params(path, line, character)
        )
        if not result:
            return []
        return result if isinstance(result, list) else [result]

    async def references(self, path: str, line: int, character: int) -> list[dict]:
        if not self._started or not self._protocol:
            return []
        await self.open_file(path)
        params = self._pos_params(path, line, character)
        params["context"] = {"includeDeclaration": True}
        result = await self._protocol.request("textDocument/references", params)
        return result or []

    async def document_symbols(self, path: str) -> list[dict]:
        if not self._started or not self._protocol:
            return []
        await self.open_file(path)
        result = await self._protocol.request("textDocument/documentSymbol", {
            "textDocument": {"uri": _file_uri(str(Path(path).resolve()))},
        })
        return result or []

    async def shutdown(self) -> None:
        if self._protocol:
            try:
                await self._protocol.request("shutdown", None, timeout=3.0)
                self._protocol.notify("exit", None)
            except Exception:
                pass
            await self._protocol.stop()
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._started = False
