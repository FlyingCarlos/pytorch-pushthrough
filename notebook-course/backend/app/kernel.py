from __future__ import annotations

import asyncio
import contextlib
import queue
import re
import time
from typing import Any

from jupyter_client import AsyncKernelManager


# Jupyter formats tracebacks for terminal clients and therefore includes ANSI
# colour/cursor sequences. The browser output component renders plain text, so
# normalize terminal-oriented text at the protocol boundary.
_ANSI_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)
_ANSI_CSI_RE = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]")
_ANSI_ESCAPE_RE = re.compile(r"\x1b[@-_]")
_NON_TEXT_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean_notebook_text(value: Any) -> str:
    """Remove terminal control codes while preserving tabs and line breaks."""
    text = value if isinstance(value, str) else str(value)
    text = _ANSI_OSC_RE.sub("", text)
    text = _ANSI_CSI_RE.sub("", text)
    text = _ANSI_ESCAPE_RE.sub("", text)
    return _NON_TEXT_CONTROL_RE.sub("", text)


class ChapterKernel:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.manager: AsyncKernelManager | None = None
        self.client: Any = None
        self.lock = asyncio.Lock()

    async def start(self, initialization_codes: list[str]) -> None:
        if self.manager and await self.manager.is_alive():
            return
        self.manager = AsyncKernelManager(kernel_name="python3")
        await self.manager.start_kernel(cwd=self.cwd)
        self.client = self.manager.client()
        self.client.start_channels()
        await self.client.wait_for_ready(timeout=30)
        for code in initialization_codes:
            result = await self.execute(code, timeout=60)
            if result["error"]:
                raise RuntimeError(f"Failed to initialize chapter kernel: {result['error']}")

    async def execute(self, code: str, timeout: float = 30) -> dict[str, Any]:
        if not self.client:
            raise RuntimeError("Kernel is not running")
        async with self.lock:
            msg_id = self.client.execute(code, allow_stdin=False, stop_on_error=True)
            outputs: list[dict[str, Any]] = []
            error: dict[str, Any] | None = None
            deadline = time.monotonic() + timeout

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if self.manager:
                        await self.manager.interrupt_kernel()
                    error = {
                        "ename": "TimeoutError",
                        "evalue": f"Cell execution exceeded {timeout:g} seconds",
                        "traceback": [],
                    }
                    break
                try:
                    message = await self.client.get_iopub_msg(timeout=min(1, remaining))
                except queue.Empty:
                    continue
                if message.get("parent_header", {}).get("msg_id") != msg_id:
                    continue

                msg_type = message["header"]["msg_type"]
                content = message["content"]
                if msg_type == "status" and content.get("execution_state") == "idle":
                    break
                if msg_type == "stream":
                    outputs.append(
                        {
                            "output_type": "stream",
                            "name": content["name"],
                            "text": clean_notebook_text(content["text"]),
                        }
                    )
                elif msg_type in {"display_data", "execute_result"}:
                    data = content.get("data", {})
                    if isinstance(data, dict) and isinstance(data.get("text/plain"), str):
                        data = {
                            **data,
                            "text/plain": clean_notebook_text(data["text/plain"]),
                        }
                    outputs.append(
                        {
                            "output_type": msg_type,
                            "data": data,
                            "metadata": content.get("metadata", {}),
                        }
                    )
                elif msg_type == "error":
                    error = {
                        "ename": clean_notebook_text(content.get("ename", "Error")),
                        "evalue": clean_notebook_text(content.get("evalue", "")),
                        "traceback": [
                            clean_notebook_text(line)
                            for line in content.get("traceback", [])
                        ],
                    }
                    outputs.append({"output_type": "error", **error})

            return {"outputs": outputs, "error": error}

    async def shutdown(self) -> None:
        if self.client:
            self.client.stop_channels()
        if self.manager:
            with contextlib.suppress(Exception):
                await self.manager.shutdown_kernel(now=True)
        self.manager = None
        self.client = None


class KernelRegistry:
    def __init__(self) -> None:
        self.kernels: dict[str, ChapterKernel] = {}

    async def get(
        self, chapter_id: str, cwd: str, initialization_codes: list[str]
    ) -> ChapterKernel:
        kernel = self.kernels.get(chapter_id)
        if kernel is None:
            kernel = ChapterKernel(cwd)
            self.kernels[chapter_id] = kernel
        await kernel.start(initialization_codes)
        return kernel

    async def restart(self, chapter_id: str) -> None:
        kernel = self.kernels.pop(chapter_id, None)
        if kernel:
            await kernel.shutdown()

    async def shutdown_all(self) -> None:
        await asyncio.gather(*(kernel.shutdown() for kernel in self.kernels.values()))
        self.kernels.clear()
