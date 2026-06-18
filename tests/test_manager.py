import pytest
from checkpoint import CheckpointStore, checkpoint


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    s = CheckpointStore(f"sqlite:///{db}")
    yield s
    s.close()


def test_cache_miss_executes_body(store):
    executed = []

    with checkpoint("run1", "step1", store) as ctx:
        assert ctx.result is None  # cache miss
        ctx.result = "computed"
        executed.append(True)

    assert executed == [True]
    assert store.is_done("run1", "step1")
    assert store.get_result("run1", "step1") == "computed"


def test_cache_hit_skips_body(store):
    # First run
    with checkpoint("run1", "step1", store) as ctx:
        ctx.result = {"answer": 42}

    executed = []

    # Second run — should not enter else branch
    with checkpoint("run1", "step1", store) as ctx:
        if ctx.result is not None:
            result = ctx.result
        else:
            executed.append("should_not_run")
            result = "wrong"

    assert executed == []
    assert result == {"answer": 42}


def test_exception_marks_failed(store, capsys):
    with pytest.raises(RuntimeError, match="deliberate failure"):
        with checkpoint("run1", "step1", store) as ctx:
            raise RuntimeError("deliberate failure")

    assert not store.is_done("run1", "step1")
    captured = capsys.readouterr()
    assert "✗" in captured.out
    assert "deliberate failure" in captured.out


def test_failed_step_can_retry(store):
    with pytest.raises(ValueError):
        with checkpoint("run1", "step1", store) as ctx:
            raise ValueError("transient error")

    # Retry: should execute again (not cached)
    with checkpoint("run1", "step1", store) as ctx:
        assert ctx.result is None  # still a miss after failure
        ctx.result = "retry_success"

    assert store.is_done("run1", "step1")
    assert store.get_result("run1", "step1") == "retry_success"


def test_skip_if_done_false_reruns(store):
    with checkpoint("run1", "step1", store) as ctx:
        ctx.result = "first"

    executed = []

    with checkpoint("run1", "step1", store, skip_if_done=False) as ctx:
        executed.append(True)
        ctx.result = "second"

    assert executed == [True]
    assert store.get_result("run1", "step1") == "second"


def test_cached_output_printed(store, capsys):
    with checkpoint("run1", "step1", store) as ctx:
        ctx.result = "x"

    capsys.readouterr()  # clear first run output

    with checkpoint("run1", "step1", store) as ctx:
        pass

    captured = capsys.readouterr()
    assert "cached" in captured.out
    assert "step1" in captured.out


def test_none_result_stored_and_retrieved(store):
    # Storing None explicitly should work (though it can't be
    # distinguished from a cache miss via ctx.result is not None).
    # This tests that the store round-trips correctly.
    with checkpoint("run1", "step1", store) as ctx:
        ctx.result = None  # intentionally None

    assert store.is_done("run1", "step1")
    assert store.get_result("run1", "step1") is None


def test_multiple_steps_independent(store):
    results = {}

    for i in range(5):
        with checkpoint("run1", f"step_{i}", store) as ctx:
            ctx.result = i * 10

    for i in range(5):
        assert store.is_done("run1", f"step_{i}")
        assert store.get_result("run1", f"step_{i}") == i * 10
