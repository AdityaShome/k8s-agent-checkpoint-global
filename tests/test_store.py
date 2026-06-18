import pytest
import tempfile
import os
from checkpoint import CheckpointStore, StepStatus


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    s = CheckpointStore(f"sqlite:///{db}")
    yield s
    s.close()


def test_is_done_false_initially(store):
    assert store.is_done("run1", "step1") is False


def test_mark_running_then_done(store):
    store.mark_running("run1", "step1")
    assert store.is_done("run1", "step1") is False

    store.mark_done("run1", "step1", {"value": 42})
    assert store.is_done("run1", "step1") is True


def test_get_result_roundtrip(store):
    store.mark_running("run1", "step1")
    payload = {"doc": "test.txt", "tokens": 100, "nested": [1, 2, 3]}
    store.mark_done("run1", "step1", payload)

    result = store.get_result("run1", "step1")
    assert result == payload


def test_get_result_none_when_not_done(store):
    assert store.get_result("run1", "missing") is None


def test_mark_failed(store):
    store.mark_running("run1", "step1")
    store.mark_failed("run1", "step1", "something went wrong")
    assert store.is_done("run1", "step1") is False


def test_get_run_summary_empty(store):
    summary = store.get_run_summary("no-such-run")
    assert summary == {"completed": 0, "failed": 0, "running": 0, "total": 0}


def test_get_run_summary_mixed(store):
    for i in range(5):
        store.mark_running("run1", f"step_{i}")
        store.mark_done("run1", f"step_{i}", i)

    store.mark_running("run1", "step_fail")
    store.mark_failed("run1", "step_fail", "err")

    store.mark_running("run1", "step_running")

    summary = store.get_run_summary("run1")
    assert summary["completed"] == 5
    assert summary["failed"] == 1
    assert summary["running"] == 1
    assert summary["total"] == 7


def test_list_completed_steps(store):
    for step in ["a", "b", "c"]:
        store.mark_running("run1", step)
        store.mark_done("run1", step, step)

    store.mark_running("run1", "d")
    store.mark_failed("run1", "d", "error")

    completed = store.list_completed_steps("run1")
    assert set(completed) == {"a", "b", "c"}
    assert "d" not in completed


def test_clear_run(store):
    store.mark_running("run1", "step1")
    store.mark_done("run1", "step1", "x")
    store.clear_run("run1")

    assert store.is_done("run1", "step1") is False
    assert store.get_run_summary("run1")["total"] == 0


def test_different_run_ids_isolated(store):
    store.mark_running("run_a", "step1")
    store.mark_done("run_a", "step1", "result_a")

    assert store.is_done("run_b", "step1") is False
    assert store.get_result("run_b", "step1") is None


def test_non_json_serializable_result(store):
    class Unserializable:
        def __str__(self):
            return "fallback_string"

    store.mark_running("run1", "step1")
    with pytest.warns(UserWarning, match="not JSON-serializable"):
        store.mark_done("run1", "step1", Unserializable())

    result = store.get_result("run1", "step1")
    assert result == "fallback_string"


def test_invalid_url_scheme():
    with pytest.raises(ValueError, match="Unsupported database URL"):
        CheckpointStore("mysql://localhost/db")


def test_mark_running_resets_previous_failure(store):
    store.mark_running("run1", "step1")
    store.mark_failed("run1", "step1", "first failure")

    store.mark_running("run1", "step1")
    store.mark_done("run1", "step1", "recovered")

    assert store.is_done("run1", "step1") is True
    assert store.get_result("run1", "step1") == "recovered"
