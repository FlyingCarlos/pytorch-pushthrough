from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _source_text(value: str | list[str]) -> str:
    return value if isinstance(value, str) else "".join(value)


class CourseStore:
    def __init__(self, courses_dir: Path) -> None:
        self.courses_dir = courses_dir

    def _notebook_path(self, chapter_id: str) -> Path:
        path = self.courses_dir / chapter_id / "chapter.ipynb"
        if not path.is_file():
            raise FileNotFoundError(f"Unknown chapter: {chapter_id}")
        return path

    def tests_path(self, chapter_id: str) -> Path:
        return self._notebook_path(chapter_id).with_name("tests.py")

    def chapter_ids(self) -> list[str]:
        return sorted(
            path.parent.name
            for path in self.courses_dir.glob("*/chapter.ipynb")
            if path.is_file()
        )

    def load(self, chapter_id: str) -> dict[str, Any]:
        notebook = json.loads(self._notebook_path(chapter_id).read_text(encoding="utf-8"))
        chapter_meta = notebook.get("metadata", {}).get("pushthrough", {})
        dependency_mode = chapter_meta.get("dependency_mode", "explicit")
        previous_exercise: str | None = None
        cells: list[dict[str, Any]] = []

        for index, raw_cell in enumerate(notebook.get("cells", [])):
            metadata = raw_cell.get("metadata", {}).get("pushthrough", {})
            cell_type = raw_cell.get("cell_type", "code")
            role = metadata.get("type", "lesson" if cell_type == "markdown" else "example")
            cell_id = raw_cell.get("id") or f"cell-{index + 1}"
            exercise_id = metadata.get("exercise_id")
            depends_on = list(metadata.get("depends_on", []))

            if role in {"exercise", "checkpoint"}:
                exercise_id = exercise_id or cell_id
                if dependency_mode == "sequential" and "depends_on" not in metadata and previous_exercise:
                    depends_on = [previous_exercise]
                previous_exercise = exercise_id

            cells.append(
                {
                    "id": cell_id,
                    "cell_type": cell_type,
                    "type": role,
                    "title": metadata.get("title"),
                    "source": _source_text(raw_cell.get("source", "")),
                    "exercise_id": exercise_id,
                    "depends_on": depends_on,
                    "test": metadata.get("test"),
                    "editable": metadata.get("editable", role in {"exercise", "checkpoint", "finale", "example"}),
                    "runnable": metadata.get("runnable", cell_type == "code" and role != "setup"),
                    "hidden": metadata.get("hidden", role == "setup"),
                }
            )

        chapter = {
            "id": chapter_meta.get("id", chapter_id),
            "title": chapter_meta.get("title", chapter_id),
            "description": chapter_meta.get("description", ""),
            "duration_minutes": chapter_meta.get("duration_minutes"),
            "order": chapter_meta.get("order", 999),
            "level": chapter_meta.get("level", "入门"),
            "cells": cells,
        }
        self._validate(chapter)
        return chapter

    def dependency_graph(self, chapter: dict[str, Any]) -> dict[str, set[str]]:
        dependents: dict[str, set[str]] = {}
        for cell in chapter["cells"]:
            exercise_id = cell.get("exercise_id")
            if not exercise_id:
                continue
            dependents.setdefault(exercise_id, set())
            for dependency in cell["depends_on"]:
                dependents.setdefault(dependency, set()).add(exercise_id)
        return dependents

    def descendants(self, chapter: dict[str, Any], exercise_id: str) -> set[str]:
        dependents = self.dependency_graph(chapter)
        pending = list(dependents.get(exercise_id, set()))
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            pending.extend(dependents.get(current, set()))
        return visited

    @staticmethod
    def _validate(chapter: dict[str, Any]) -> None:
        exercise_ids = {
            cell["exercise_id"] for cell in chapter["cells"] if cell.get("exercise_id")
        }
        for cell in chapter["cells"]:
            missing = set(cell["depends_on"]) - exercise_ids
            if missing:
                raise ValueError(
                    f"Cell {cell['id']} depends on unknown exercises: {sorted(missing)}"
                )
