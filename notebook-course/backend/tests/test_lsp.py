import asyncio
from pathlib import Path

import pytest

from app.lsp import PyrightSession, _frame


async def _response(session: PyrightSession, request_id: int) -> dict:
    while True:
        message = await asyncio.wait_for(session.read(), timeout=10)
        if message.get("method") == "workspace/configuration":
            await session.send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": session.configuration_result(message.get("params", {})),
                }
            )
        elif message.get("id") == request_id:
            return message


def test_lsp_frame_uses_utf8_byte_length() -> None:
    framed = _frame({"jsonrpc": "2.0", "method": "example", "params": {"text": "中文"}})
    header, body = framed.split(b"\r\n\r\n", 1)
    assert header == f"Content-Length: {len(body)}".encode()


@pytest.mark.asyncio
async def test_pyright_completion_and_hover(tmp_path: Path) -> None:
    source = "import torch\ntor\nvalue = torch.zeros(2)\n"
    document_uri = (tmp_path / "chapter.py").as_uri()
    session = PyrightSession(tmp_path, Path(__file__).parents[1] / ".venv/bin/python")
    await session.start()
    stderr_task = asyncio.create_task(session.drain_stderr())
    try:
        await session.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {
                        "workspace": {"configuration": True},
                        "textDocument": {"completion": {"completionItem": {}}},
                    },
                },
            }
        )
        initialize = await _response(session, 1)
        assert initialize["result"]["capabilities"]["hoverProvider"]
        assert initialize["result"]["capabilities"]["completionProvider"]

        await session.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        await session.send(
            {
                "jsonrpc": "2.0",
                "method": "workspace/didChangeConfiguration",
                "params": {"settings": None},
            }
        )
        await session.send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": document_uri,
                        "languageId": "python",
                        "version": 1,
                        "text": source,
                    }
                },
            }
        )

        await session.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": document_uri},
                    "position": {"line": 1, "character": 3},
                    "context": {"triggerKind": 1},
                },
            }
        )
        completion = await _response(session, 2)
        result = completion["result"]
        items = result if isinstance(result, list) else result["items"]
        assert "torch" in {item["label"] for item in items}

        await session.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": document_uri},
                    "position": {"line": 2, "character": 10},
                },
            }
        )
        hover = await _response(session, 3)
        assert "(module) torch" in str(hover["result"])
    finally:
        await session.stop()
        await asyncio.wait_for(stderr_task, timeout=2)
