from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class LSPProtocolError(RuntimeError):
    pass


def _langserver_executable() -> str:
    beside_python = Path(sys.executable).with_name("pyright-langserver")
    if beside_python.exists():
        return str(beside_python)
    executable = shutil.which("pyright-langserver")
    if executable:
        return executable
    raise RuntimeError("pyright-langserver is not installed; run `uv sync` in backend")


def _frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


async def _read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if not line:
            raise EOFError("Pyright language server closed its output")
        if line in {b"\r\n", b"\n"}:
            break
        try:
            name, value = line.decode("ascii").split(":", 1)
        except ValueError as exc:
            raise LSPProtocolError(f"Invalid LSP header: {line!r}") from exc
        headers[name.lower()] = value.strip()

    try:
        content_length = int(headers["content-length"])
    except (KeyError, ValueError) as exc:
        raise LSPProtocolError("LSP response is missing Content-Length") from exc
    body = await reader.readexactly(content_length)
    return json.loads(body.decode("utf-8"))


class PyrightSession:
    def __init__(self, chapter_dir: Path, python_path: Path) -> None:
        self.chapter_dir = chapter_dir
        self.python_path = python_path
        self.process: asyncio.subprocess.Process | None = None
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.process and self.process.returncode is None:
            return
        self.process = await asyncio.create_subprocess_exec(
            _langserver_executable(),
            "--stdio",
            cwd=self.chapter_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Pyright language server is not running")
        async with self._write_lock:
            self.process.stdin.write(_frame(message))
            await self.process.stdin.drain()

    async def read(self) -> dict[str, Any]:
        if not self.process or not self.process.stdout:
            raise RuntimeError("Pyright language server is not running")
        return await _read_frame(self.process.stdout)

    async def drain_stderr(self) -> None:
        if not self.process or not self.process.stderr:
            return
        while await self.process.stderr.readline():
            pass

    async def stop(self) -> None:
        process = self.process
        self.process = None
        if not process or process.returncode is not None:
            return
        if process.stdin:
            process.stdin.close()
            with contextlib.suppress(BrokenPipeError):
                await process.stdin.wait_closed()
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except TimeoutError:
                process.kill()
                await process.wait()

    def configuration_result(self, params: dict[str, Any]) -> list[Any]:
        python_settings = {
            "pythonPath": str(self.python_path),
            "analysis": {
                "typeCheckingMode": "basic",
                "diagnosticMode": "openFilesOnly",
                "autoImportCompletions": True,
            },
        }
        analysis_settings = python_settings["analysis"]
        results: list[Any] = []
        for item in params.get("items", []):
            section = item.get("section")
            if section == "python":
                results.append(python_settings)
            elif section == "python.analysis":
                results.append(analysis_settings)
            elif section == "pyright":
                results.append({"disableLanguageServices": False})
            else:
                results.append(None)
        return results


async def bridge_pyright(
    websocket: WebSocket,
    chapter_dir: Path,
) -> None:
    await websocket.accept()
    session = PyrightSession(chapter_dir, Path(sys.executable))
    await session.start()

    await websocket.send_json(
        {
            "jsonrpc": "2.0",
            "method": "pushthrough/config",
            "params": {
                "rootUri": chapter_dir.as_uri(),
                "documentUri": (chapter_dir / ".pushthrough-lsp" / "chapter.py").as_uri(),
            },
        }
    )

    async def browser_to_pyright() -> None:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            if message.get("method") == "initialize":
                params = message.setdefault("params", {})
                params["processId"] = None
                params["rootUri"] = chapter_dir.as_uri()
                params["rootPath"] = str(chapter_dir)
                params["workspaceFolders"] = [
                    {"uri": chapter_dir.as_uri(), "name": chapter_dir.name}
                ]
            await session.send(message)

    async def pyright_to_browser() -> None:
        while True:
            message = await session.read()
            if message.get("method") == "workspace/configuration" and "id" in message:
                await session.send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": session.configuration_result(message.get("params", {})),
                    }
                )
                continue
            await websocket.send_text(json.dumps(message, ensure_ascii=False))

    tasks = {
        asyncio.create_task(browser_to_pyright()),
        asyncio.create_task(pyright_to_browser()),
        asyncio.create_task(session.drain_stderr()),
    }
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled():
                task.result()
    except (WebSocketDisconnect, EOFError, asyncio.CancelledError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await session.stop()
