from __future__ import annotations

import pytest

from app.kernel import ChapterKernel, clean_notebook_text


def test_clean_notebook_text_removes_ansi_and_preserves_layout() -> None:
    raw = (
        "\x1b[31mValueError\x1b[0m: bad\n"
        "\tline 2\x1b]8;;https://example.com\x07link\x1b]8;;\x07\x00"
    )

    assert clean_notebook_text(raw) == "ValueError: bad\n\tline 2link"


@pytest.mark.asyncio
async def test_kernel_strips_control_codes_from_stream_and_traceback(tmp_path) -> None:
    kernel = ChapterKernel(str(tmp_path))
    await kernel.start([])

    try:
        result = await kernel.execute(
            "print('\\x1b[32mvisible output\\x1b[0m')\n"
            "raise ValueError('\\x1b[31mbad value\\x1b[0m')"
        )
    finally:
        await kernel.shutdown()

    assert result["error"] is not None
    assert result["error"]["ename"] == "ValueError"
    assert result["error"]["evalue"] == "bad value"
    assert "ValueError: bad value" in "\n".join(result["error"]["traceback"])

    rendered_text = "\n".join(
        [
            output.get("text", "")
            + "\n".join(output.get("traceback", []))
            for output in result["outputs"]
        ]
    )
    assert "\x1b" not in rendered_text
    assert "\x9b" not in rendered_text
    assert "visible output" in rendered_text
