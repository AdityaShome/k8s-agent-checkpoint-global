"""
Simulates mid-run interruption and resume scenarios.

These tests verify the core correctness guarantee:
  - Steps completed before interruption are not re-executed on resume.
  - Steps that were in-progress (RUNNING) at interruption are re-executed.
  - Steps not yet started are executed normally on resume.
"""
import pytest
from checkpoint import CheckpointStore, checkpoint


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "agent_run.db"
    s = CheckpointStore(f"sqlite:///{db}")
    yield s
    s.close()


def run_agent(store, run_id, documents, interrupt_at=None):
    """
    Helper: simulate an agent processing `documents`.
    If interrupt_at is set, raises KeyboardInterrupt at that step index
    to simulate a pod kill mid-run.
    Returns (results, executed_steps).
    """
    results = {}
    executed = []

    for i, doc in enumerate(documents):
        step = f"step_{i:02d}"

        if interrupt_at is not None and i == interrupt_at:
            raise KeyboardInterrupt(f"Simulated pod kill at step {i}")

        with checkpoint(run_id, step, store) as ctx:
            if ctx.result is not None:
                results[step] = ctx.result
            else:
                executed.append(step)
                ctx.result = {"doc": doc, "index": i}
                results[step] = ctx.result

    return results, executed


def test_full_run_no_interruption(store):
    docs = [f"doc_{i}" for i in range(5)]
    results, executed = run_agent(store, "run1", docs)

    assert len(executed) == 5
    assert all(store.is_done("run1", f"step_{i:02d}") for i in range(5))
    summary = store.get_run_summary("run1")
    assert summary["completed"] == 5


def test_second_run_skips_all(store):
    docs = [f"doc_{i}" for i in range(5)]
    run_agent(store, "run1", docs)

    _, executed_second = run_agent(store, "run1", docs)
    assert executed_second == []  # nothing re-executed


def test_interrupt_mid_run_and_resume(store):
    docs = [f"doc_{i}" for i in range(10)]

    # First run: interrupted at step 5
    with pytest.raises(KeyboardInterrupt):
        run_agent(store, "run1", docs, interrupt_at=5)

    # Steps 0-4 are done, step 5 was never started (interrupt before mark_running)
    for i in range(5):
        assert store.is_done("run1", f"step_{i:02d}"), f"step_{i:02d} should be done"
    assert not store.is_done("run1", "step_05")

    # Second run: steps 0-4 skipped, steps 5-9 executed
    _, executed_second = run_agent(store, "run1", docs)
    assert executed_second == [f"step_{i:02d}" for i in range(5, 10)]

    # All 10 steps now complete
    assert store.get_run_summary("run1")["completed"] == 10


def test_interrupt_during_step_execution(store):
    """
    Simulates a pod kill inside the with block (step is RUNNING, then
    the process dies without clean exit). On next run, RUNNING steps
    are re-executed because is_done() returns False for RUNNING status.
    """
    run_id = "run2"

    # Manually simulate: step_00 done, step_01 running (never finished)
    store.mark_running(run_id, "step_00")
    store.mark_done(run_id, "step_00", {"doc": "doc_0", "index": 0})
    store.mark_running(run_id, "step_01")
    # step_01 stays RUNNING — simulates a killed pod

    docs = [f"doc_{i}" for i in range(5)]
    _, executed = run_agent(store, run_id, docs)

    # step_00 cached, step_01 onward re-executed
    assert "step_00" not in executed
    assert "step_01" in executed
    assert "step_02" in executed


def test_two_concurrent_run_ids_isolated(store):
    docs = [f"doc_{i}" for i in range(3)]

    run_agent(store, "run_a", docs)

    _, executed_b = run_agent(store, "run_b", docs)
    assert len(executed_b) == 3  # run_b never ran before

    _, executed_a_again = run_agent(store, "run_a", docs)
    assert len(executed_a_again) == 0  # run_a already complete


def test_clear_run_forces_full_rerun(store):
    docs = [f"doc_{i}" for i in range(4)]
    run_agent(store, "run1", docs)

    store.clear_run("run1")
    _, executed_after_clear = run_agent(store, "run1", docs)
    assert len(executed_after_clear) == 4


def test_partial_results_preserved_across_resume(store):
    docs = [f"doc_{i}" for i in range(6)]

    with pytest.raises(KeyboardInterrupt):
        run_agent(store, "run1", docs, interrupt_at=3)

    results, _ = run_agent(store, "run1", docs)

    # Results from first run (steps 0-2) must match what was computed
    for i in range(3):
        step = f"step_{i:02d}"
        assert results[step] == {"doc": f"doc_{i}", "index": i}
