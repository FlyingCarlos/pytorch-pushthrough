from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


class ProgressStore:
    def __init__(self, progress_dir: Path) -> None:
        self.progress_dir = progress_dir
        self.progress_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chapter_id: str) -> Path:
        return self.progress_dir / f"{chapter_id}.json"

    def load(self, chapter_id: str) -> dict[str, Any]:
        path = self._path(chapter_id)
        if not path.exists():
            return {"cells": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, chapter_id: str, progress: dict[str, Any]) -> None:
        self._path(chapter_id).write_text(
            json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def update_source(
        self,
        chapter_id: str,
        cell_id: str,
        exercise_id: str | None,
        source: str,
        descendants: Iterable[tuple[str, str]],
    ) -> tuple[dict[str, Any], bool]:
        progress = self.load(chapter_id)
        cells = progress.setdefault("cells", {})
        record = cells.setdefault(cell_id, {})
        changed = record.get("source") != source
        record["source"] = source
        record["source_hash"] = hashlib.sha256(source.encode()).hexdigest()

        if changed:
            if exercise_id:
                record["status"] = "dirty"
            for downstream_cell_id, downstream_exercise_id in descendants:
                downstream = cells.setdefault(downstream_cell_id, {})
                downstream["exercise_id"] = downstream_exercise_id
                downstream["status"] = "dirty"

        self.save(chapter_id, progress)
        return progress, changed

    def mark(
        self,
        chapter_id: str,
        cell_id: str,
        status: str,
        test_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        progress = self.load(chapter_id)
        record = progress.setdefault("cells", {}).setdefault(cell_id, {})
        record["status"] = status
        if test_result is not None:
            record["test_result"] = test_result
        self.save(chapter_id, progress)
        return progress

    def reset_cell(
        self,
        chapter_id: str,
        cell_id: str,
        descendants: Iterable[tuple[str, str]],
    ) -> dict[str, Any]:
        progress = self.load(chapter_id)
        cells = progress.setdefault("cells", {})
        cells.pop(cell_id, None)
        for downstream_cell_id, downstream_exercise_id in descendants:
            downstream = cells.setdefault(downstream_cell_id, {})
            downstream["exercise_id"] = downstream_exercise_id
            downstream["status"] = "dirty"
            downstream.pop("test_result", None)
        self.save(chapter_id, progress)
        return progress

    def reset_chapter(self, chapter_id: str) -> dict[str, Any]:
        self._path(chapter_id).unlink(missing_ok=True)
        return {"cells": {}}
