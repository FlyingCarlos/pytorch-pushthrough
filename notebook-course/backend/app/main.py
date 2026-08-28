from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .course_store import CourseStore
from .kernel import KernelRegistry
from .lsp import bridge_pyright
from .progress import ProgressStore


PROJECT_DIR = Path(__file__).resolve().parents[2]
COURSES_DIR = PROJECT_DIR / "courses"
PROGRESS_DIR = PROJECT_DIR / ".progress"
TEST_SENTINEL = "__PUSHTHROUGH_TEST__"

courses = CourseStore(COURSES_DIR)
progress_store = ProgressStore(PROGRESS_DIR)
kernels = KernelRegistry()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await kernels.shutdown_all()


app = FastAPI(title="Pushthrough", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunCellRequest(BaseModel):
    source: str
    check: bool = False


class RunThroughRequest(BaseModel):
    sources: dict[str, str]


def _load_chapter(chapter_id: str) -> dict[str, Any]:
    try:
        return courses.load(chapter_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _cell(chapter: dict[str, Any], cell_id: str) -> dict[str, Any]:
    try:
        return next(cell for cell in chapter["cells"] if cell["id"] == cell_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=f"Unknown cell: {cell_id}") from exc


def _public_progress(chapter: dict[str, Any], raw_progress: dict[str, Any]) -> dict[str, Any]:
    by_exercise = {
        record.get("exercise_id"): record
        for record in raw_progress.get("cells", {}).values()
        if record.get("exercise_id")
    }
    result: dict[str, Any] = {}
    for cell in chapter["cells"]:
        record = raw_progress.get("cells", {}).get(cell["id"], {})
        if not record and cell.get("exercise_id"):
            record = by_exercise.get(cell["exercise_id"], {})
        result[cell["id"]] = {
            "status": record.get("status", "idle"),
            "test_result": record.get("test_result"),
        }
    return result


def _initialization_codes(chapter: dict[str, Any], raw_progress: dict[str, Any]) -> list[str]:
    codes = [cell["source"] for cell in chapter["cells"] if cell["type"] == "setup"]
    for cell in chapter["cells"]:
        record = raw_progress.get("cells", {}).get(cell["id"], {})
        if record.get("status") == "passed" and record.get("source"):
            codes.append(record["source"])
    return codes


def _test_result(outputs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for output in reversed(outputs):
        if output.get("output_type") != "stream":
            continue
        for line in output.get("text", "").splitlines():
            if line.startswith(TEST_SENTINEL):
                return json.loads(line[len(TEST_SENTINEL) :])
    return None


@app.get("/api/chapters/{chapter_id}")
async def get_chapter(chapter_id: str) -> dict[str, Any]:
    chapter = _load_chapter(chapter_id)
    raw_progress = progress_store.load(chapter_id)
    for cell in chapter["cells"]:
        saved = raw_progress.get("cells", {}).get(cell["id"], {}).get("source")
        if saved is not None:
            cell["source"] = saved
    chapter["progress"] = _public_progress(chapter, raw_progress)
    return chapter


@app.get("/api/chapters")
async def list_chapters() -> dict[str, list[dict[str, Any]]]:
    summaries = []
    for chapter_id in courses.chapter_ids():
        chapter = courses.load(chapter_id)
        raw_progress = progress_store.load(chapter_id)
        public_progress = _public_progress(chapter, raw_progress)
        exercises = [cell for cell in chapter["cells"] if cell.get("exercise_id")]
        passed = sum(
            public_progress[cell["id"]]["status"] == "passed" for cell in exercises
        )
        total = len(exercises)
        summaries.append(
            {
                "id": chapter["id"],
                "title": chapter["title"],
                "description": chapter["description"],
                "duration_minutes": chapter["duration_minutes"],
                "order": chapter["order"],
                "level": chapter["level"],
                "exercise_count": total,
                "passed_count": passed,
                "progress_percent": round(passed / total * 100) if total else 0,
            }
        )
    summaries.sort(key=lambda item: (item["order"], item["title"]))
    return {"chapters": summaries}


@app.post("/api/chapters/{chapter_id}/cells/{cell_id}/run")
async def run_cell(chapter_id: str, cell_id: str, request: RunCellRequest) -> dict[str, Any]:
    chapter = _load_chapter(chapter_id)
    cell = _cell(chapter, cell_id)
    if cell["cell_type"] != "code" or not cell["runnable"]:
        raise HTTPException(status_code=400, detail="This cell cannot be executed by the learner")

    execution_source = request.source if cell["editable"] else cell["source"]
    raw_progress = progress_store.load(chapter_id)
    if cell["editable"]:
        exercise_id = cell.get("exercise_id")
        descendant_exercises = courses.descendants(chapter, exercise_id) if exercise_id else set()
        descendants = [
            (candidate["id"], candidate["exercise_id"])
            for candidate in chapter["cells"]
            if candidate.get("exercise_id") in descendant_exercises
        ]
        raw_progress, _ = progress_store.update_source(
            chapter_id, cell_id, exercise_id, execution_source, descendants
        )
        record = raw_progress["cells"].setdefault(cell_id, {})
        if exercise_id:
            record["exercise_id"] = exercise_id
            progress_store.save(chapter_id, raw_progress)

    kernel = await kernels.get(
        chapter_id,
        str(COURSES_DIR / chapter_id),
        _initialization_codes(chapter, raw_progress),
    )
    execution = await kernel.execute(execution_source)
    if execution["error"]:
        updated = (
            progress_store.mark(chapter_id, cell_id, "failed")
            if cell["editable"]
            else raw_progress
        )
        return {**execution, "test_result": None, "progress": _public_progress(chapter, updated)}

    test_result = None
    if cell["editable"] and request.check and cell.get("test"):
        test_path = courses.tests_path(chapter_id)
        test_code = f"""
import importlib.util as _push_importlib
import json as _push_json
_push_spec = _push_importlib.spec_from_file_location('_pushthrough_tests', {str(test_path)!r})
_push_module = _push_importlib.module_from_spec(_push_spec)
_push_spec.loader.exec_module(_push_module)
_push_result = _push_module.run_test({cell['test']!r}, globals())
print({TEST_SENTINEL!r} + _push_json.dumps(_push_result, ensure_ascii=False))
"""
        test_execution = await kernel.execute(test_code)
        test_result = _test_result(test_execution["outputs"])
        if test_result is None:
            test_result = {
                "passed": False,
                "checks": [],
                "message": "测试运行失败，请检查测试代码。",
            }
        status = "passed" if test_result.get("passed") else "failed"
        updated = progress_store.mark(chapter_id, cell_id, status, test_result)
    else:
        updated = raw_progress

    return {
        **execution,
        "test_result": test_result,
        "progress": _public_progress(chapter, updated),
    }


@app.post("/api/chapters/{chapter_id}/cells/{cell_id}/run-through")
async def run_through_cell(
    chapter_id: str,
    cell_id: str,
    request: RunThroughRequest,
) -> dict[str, Any]:
    chapter = _load_chapter(chapter_id)
    target = _cell(chapter, cell_id)
    if target["cell_type"] != "code" or not target["editable"]:
        raise HTTPException(status_code=400, detail="The target cell cannot be executed")

    target_index = next(
        index for index, candidate in enumerate(chapter["cells"]) if candidate["id"] == cell_id
    )
    runnable_cells = [
        cell
        for index, cell in enumerate(chapter["cells"])
        if index <= target_index and cell["cell_type"] == "code" and cell["editable"]
    ]

    # “运行至此”从一个干净环境开始，避免当前 Cell 意外依赖之后运行过的变量。
    await kernels.restart(chapter_id)
    setup_codes = [cell["source"] for cell in chapter["cells"] if cell["type"] == "setup"]
    kernel = await kernels.get(chapter_id, str(COURSES_DIR / chapter_id), setup_codes)

    executions: list[dict[str, Any]] = []
    stopped_at: str | None = None
    for cell in runnable_cells:
        source = request.sources.get(cell["id"], cell["source"])
        exercise_id = cell.get("exercise_id")
        descendant_exercises = courses.descendants(chapter, exercise_id) if exercise_id else set()
        descendants = [
            (candidate["id"], candidate["exercise_id"])
            for candidate in chapter["cells"]
            if candidate.get("exercise_id") in descendant_exercises
        ]
        progress_store.update_source(
            chapter_id,
            cell["id"],
            exercise_id,
            source,
            descendants,
        )
        execution = await kernel.execute(source)
        executions.append({"cell_id": cell["id"], **execution})
        if execution["error"]:
            progress_store.mark(chapter_id, cell["id"], "failed")
            stopped_at = cell["id"]
            break

    raw_progress = progress_store.load(chapter_id)
    return {
        "executions": executions,
        "stopped_at": stopped_at,
        "progress": _public_progress(chapter, raw_progress),
    }


@app.post("/api/chapters/{chapter_id}/cells/{cell_id}/reset")
async def reset_cell(chapter_id: str, cell_id: str) -> dict[str, Any]:
    chapter = _load_chapter(chapter_id)
    cell = _cell(chapter, cell_id)
    if cell["cell_type"] != "code" or not cell["editable"]:
        raise HTTPException(status_code=400, detail="This cell cannot be restored")

    exercise_id = cell.get("exercise_id")
    descendant_exercises = courses.descendants(chapter, exercise_id) if exercise_id else set()
    descendants = [
        (candidate["id"], candidate["exercise_id"])
        for candidate in chapter["cells"]
        if candidate.get("exercise_id") in descendant_exercises
    ]
    raw_progress = progress_store.reset_cell(chapter_id, cell_id, descendants)
    await kernels.restart(chapter_id)
    return {
        "source": cell["source"],
        "progress": _public_progress(chapter, raw_progress),
    }


@app.post("/api/chapters/{chapter_id}/reset")
async def reset_chapter(chapter_id: str) -> dict[str, Any]:
    chapter = _load_chapter(chapter_id)
    raw_progress = progress_store.reset_chapter(chapter_id)
    await kernels.restart(chapter_id)
    return {
        "sources": {
            cell["id"]: cell["source"]
            for cell in chapter["cells"]
            if cell["cell_type"] == "code" and cell["editable"]
        },
        "progress": _public_progress(chapter, raw_progress),
    }


@app.post("/api/chapters/{chapter_id}/kernel/restart")
async def restart_kernel(chapter_id: str) -> dict[str, str]:
    _load_chapter(chapter_id)
    await kernels.restart(chapter_id)
    return {"status": "restarted"}


@app.websocket("/api/chapters/{chapter_id}/lsp")
async def chapter_lsp(websocket: WebSocket, chapter_id: str) -> None:
    try:
        chapter = courses.load(chapter_id)
    except (FileNotFoundError, ValueError):
        await websocket.close(code=4404, reason=f"Unknown chapter: {chapter_id}")
        return
    chapter_dir = COURSES_DIR / chapter_id
    await bridge_pyright(
        websocket,
        chapter_dir,
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
