"""LSP-powered code intelligence tools for Helena Code."""

from pathlib import Path

from ..tool_events import emit_call, emit_return
from ..lsp.manager import get_client
from ..lsp.client import SEVERITY, SYMBOL_KIND

_OPERATIONS = ("hover", "definition", "references", "document_symbols")


async def lsp_diagnostics(path: str) -> str:
    """Get language server diagnostics (errors, warnings, hints) for a file.

    Always call this after write_file or edit_file to catch type errors,
    undefined references, and other static analysis issues immediately.

    Requires an LSP server installed for the file type:
      Python:          pip install pyright
      TypeScript/JS:   npm i -g typescript-language-server typescript
      Rust:            rustup component add rust-analyzer
      Go:              go install golang.org/x/tools/gopls@latest
      C/C++:           install clangd via your package manager

    Args:
        path: Absolute or relative path to the file.

    Returns:
        Formatted diagnostics (ERROR/WARN/INFO/HINT with line:col), or a
        message indicating the file is clean or no server is available.
    """
    emit_call("lsp_diagnostics", {"path": path})
    abs_path = str(Path(path).expanduser().resolve())

    if not Path(abs_path).exists():
        result = f"Error: File not found: {path}"
        emit_return("lsp_diagnostics", result)
        return result

    client = await get_client(abs_path)
    if client is None:
        ext = Path(path).suffix or path
        result = f"No LSP server available for {ext} files. Install one to enable diagnostics."
        emit_return("lsp_diagnostics", result)
        return result

    diags = await client.get_diagnostics(abs_path)

    if not diags:
        result = "No diagnostics — file looks clean."
        emit_return("lsp_diagnostics", result)
        return result

    lines = []
    for d in diags:
        sev = SEVERITY.get(d.get("severity", 1), "ERROR")
        start = d.get("range", {}).get("start", {})
        ln = start.get("line", 0) + 1
        col = start.get("character", 0) + 1
        msg = d.get("message", "")
        source = d.get("source", "")
        prefix = f"[{source}] " if source else ""
        lines.append(f"{sev} {ln}:{col}  {prefix}{msg}")

    result = "\n".join(lines)
    emit_return("lsp_diagnostics", result)
    return result


async def lsp_query(
    operation: str,
    path: str,
    line: int = 1,
    character: int = 1,
) -> str:
    """Query the LSP server for code intelligence at a specific file location.

    Operations:
      hover            — Type info and documentation for the symbol at line:character.
      definition       — Where the symbol at line:character is defined.
      references       — All usages of the symbol at line:character across the project.
      document_symbols — All symbols (functions, classes, variables) in the file.
                         line and character are ignored for this operation.

    Args:
        operation:  One of: hover, definition, references, document_symbols.
        path:       Absolute or relative path to the file.
        line:       Line number (1-based).
        character:  Character offset (1-based).

    Returns:
        Formatted results from the LSP server.
    """
    if operation not in _OPERATIONS:
        return f"Unknown operation '{operation}'. Choose from: {', '.join(_OPERATIONS)}"

    emit_call("lsp_query", {"operation": operation, "path": path, "line": line, "character": character})
    abs_path = str(Path(path).expanduser().resolve())

    if not Path(abs_path).exists():
        result = f"Error: File not found: {path}"
        emit_return("lsp_query", result)
        return result

    client = await get_client(abs_path)
    if client is None:
        ext = Path(path).suffix or path
        result = f"No LSP server available for {ext} files."
        emit_return("lsp_query", result)
        return result

    if operation == "hover":
        text = await client.hover(abs_path, line, character)
        result = text.strip() if text else "No hover info at this position."

    elif operation == "definition":
        locs = await client.definition(abs_path, line, character)
        result = _fmt_locations(locs) if locs else "No definition found."

    elif operation == "references":
        locs = await client.references(abs_path, line, character)
        result = _fmt_locations(locs) if locs else "No references found."

    elif operation == "document_symbols":
        syms = await client.document_symbols(abs_path)
        result = _fmt_symbols(syms) if syms else "No symbols found."

    emit_return("lsp_query", result)
    return result


def _fmt_locations(locs: list[dict]) -> str:
    lines = []
    for loc in locs:
        uri = loc.get("uri") or loc.get("targetUri", "")
        file_path = uri.removeprefix("file://")
        try:
            from urllib.parse import unquote
            file_path = unquote(file_path)
        except Exception:
            pass
        r = loc.get("range") or loc.get("targetSelectionRange") or loc.get("targetRange") or {}
        start = r.get("start", {})
        ln = start.get("line", 0) + 1
        col = start.get("character", 0) + 1
        lines.append(f"{file_path}:{ln}:{col}")
    return "\n".join(lines)


def _fmt_symbols(syms: list[dict], indent: int = 0) -> str:
    lines = []
    prefix = "  " * indent
    for s in syms:
        kind = SYMBOL_KIND.get(s.get("kind", 0), "Symbol")
        name = s.get("name", "")
        detail = s.get("detail", "")
        r = (
            s.get("selectionRange")
            or s.get("range")
            or s.get("location", {}).get("range", {})
        )
        ln = r.get("start", {}).get("line", 0) + 1
        detail_str = f"  {detail}" if detail else ""
        lines.append(f"{prefix}{kind} {name}{detail_str}  (line {ln})")
        children = s.get("children", [])
        if children:
            lines.append(_fmt_symbols(children, indent + 1))
    return "\n".join(lines)
