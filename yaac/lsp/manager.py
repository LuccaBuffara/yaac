"""Session-level LSP client manager for YAAC.

Maintains one LSPClient per (server_id, root) pair. Clients are started
lazily on first file access and shut down together at session end.
"""

import asyncio
from pathlib import Path

from .client import LSPClient
from .servers import ServerDef, find_root, server_for_file

# (server_id, root) -> LSPClient
_clients: dict[tuple[str, str], LSPClient] = {}
# (server_id, root) -> in-flight start Task
_starting: dict[tuple[str, str], asyncio.Task] = {}


async def _get_or_start(server: ServerDef, root: str) -> LSPClient | None:
    key = (server.id, root)

    if key in _clients:
        return _clients[key]

    if key in _starting:
        return await _starting[key]

    async def _start() -> LSPClient | None:
        client = LSPClient(server.id, server.command, root, diag_wait_ms=server.diag_wait_ms)
        ok = await client.start()
        if ok:
            _clients[key] = client
            return client
        return None

    task = asyncio.get_event_loop().create_task(_start())
    _starting[key] = task
    try:
        return await task
    finally:
        _starting.pop(key, None)


async def get_client(path: str) -> LSPClient | None:
    """Return the LSP client for the given file, starting one if needed.
    Returns None if no server is available or installed for the file type.
    """
    abs_path = str(Path(path).expanduser().resolve())
    server = server_for_file(abs_path)
    if server is None:
        return None
    root = find_root(abs_path, server.root_markers)
    return await _get_or_start(server, root)


async def shutdown_all() -> None:
    """Shut down all active LSP clients. Call when the session ends."""
    for client in list(_clients.values()):
        try:
            await client.shutdown()
        except Exception:
            pass
    _clients.clear()
