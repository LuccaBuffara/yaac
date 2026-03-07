"""JSON-RPC 2.0 message framing for LSP over asyncio subprocess stdio."""

import asyncio
import json
from typing import Any, Callable


class LSPProtocol:
    """Handles JSON-RPC 2.0 framing with an LSP server over subprocess stdin/stdout."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[str, list[Callable]] = {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.get_event_loop().create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                msg = await self._recv()
                if msg is None:
                    break
                self._dispatch(msg)
            except asyncio.CancelledError:
                raise
            except Exception:
                break
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()

    def _dispatch(self, msg: dict) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            fut = self._pending.pop(msg["id"], None)
            if fut and not fut.done():
                if "error" in msg:
                    e = msg["error"]
                    fut.set_exception(RuntimeError(f"LSP {e.get('code')}: {e.get('message')}"))
                else:
                    fut.set_result(msg.get("result"))
        elif "method" in msg:
            for h in self._handlers.get(msg["method"], []):
                try:
                    h(msg.get("params", {}))
                except Exception:
                    pass

    async def _recv(self) -> dict | None:
        headers: dict[str, str] = {}
        while True:
            line = await self._reader.readline()
            if not line:
                return None
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                break
            if ":" in text:
                k, _, v = text.partition(":")
                headers[k.strip().lower()] = v.strip()
        length = int(headers.get("content-length", 0))
        if not length:
            return None
        try:
            body = await self._reader.readexactly(length)
        except (asyncio.IncompleteReadError, Exception):
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _write(self, msg: dict) -> None:
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        self._writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)

    def on(self, method: str, handler: Callable) -> None:
        self._handlers.setdefault(method, []).append(handler)

    async def request(self, method: str, params: Any, timeout: float = 10.0) -> Any:
        req_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        try:
            await self._writer.drain()
        except Exception:
            pass
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            self._pending.pop(req_id, None)
            if not fut.done():
                fut.cancel()
            return None

    def notify(self, method: str, params: Any) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
