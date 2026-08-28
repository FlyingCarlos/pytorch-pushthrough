from pathlib import Path

from app.course_store import CourseStore


COURSES_DIR = Path(__file__).resolve().parents[2] / "courses"


def test_descendants_follow_explicit_dependencies() -> None:
    store = CourseStore(COURSES_DIR)
    chapter = store.load("makemore-bigram")

    assert store.descendants(chapter, "count-matrix") == {
        "count-model",
        "neural-model",
        "training-loop",
        "sampler",
    }


def test_all_dependencies_reference_real_exercises() -> None:
    store = CourseStore(COURSES_DIR)
    chapter = store.load("makemore-bigram")
    graph = store.dependency_graph(chapter)

    assert "vocabulary" in graph
    assert graph["neural-model"] == {"training-loop"}


def test_foundation_course_precedes_makemore_course() -> None:
    store = CourseStore(COURSES_DIR)
    foundation = store.load("tensors-and-matmul")
    makemore = store.load("makemore-bigram")

    assert foundation["order"] == 1
    assert makemore["order"] == 2
    assert store.descendants(foundation, "dot-product") == {
        "manual-matmul",
        "linear-transform",
        "batched-linear",
        "tiny-mlp",
    }


def test_foundation_teaching_examples_are_read_only() -> None:
    store = CourseStore(COURSES_DIR)
    foundation = store.load("tensors-and-matmul")
    examples = [cell for cell in foundation["cells"] if cell["type"] == "example"]

    assert len(examples) == 7
    assert all(cell["cell_type"] == "code" for cell in examples)
    assert all(not cell["editable"] for cell in examples)
    assert all(cell["runnable"] for cell in examples)
    assert all(not cell["hidden"] for cell in examples)


def test_makemore_examples_are_runnable_and_read_only() -> None:
    store = CourseStore(COURSES_DIR)
    chapter = store.load("makemore-bigram")
    examples = [cell for cell in chapter["cells"] if cell["type"] == "example"]

    assert len(examples) == 8
    assert all(cell["cell_type"] == "code" for cell in examples)
    assert all(not cell["editable"] for cell in examples)
    assert all(cell["runnable"] for cell in examples)


def test_makemore_initialization_is_visible_but_locked() -> None:
    store = CourseStore(COURSES_DIR)
    chapter = store.load("makemore-bigram")
    setup = next(cell for cell in chapter["cells"] if cell["id"] == "chapter-setup")
    dataset = next(cell for cell in chapter["cells"] if cell["id"] == "dataset-setup")

    assert "import torch.nn.functional as F" in setup["source"]
    assert setup["title"] == "课程初始化 · 自动执行"
    assert not setup["hidden"]
    assert not setup["editable"]
    assert not setup["runnable"]
    assert dataset["hidden"]
    assert "words =" in dataset["source"]
