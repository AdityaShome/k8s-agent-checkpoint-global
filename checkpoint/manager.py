import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .store import CheckpointStore


@dataclass
class StepContext:
    """
    Mutable holder yielded by checkpoint(). Inspect .result to get the
    cached value (non-None = cache hit). Set .result to persist your
    computed value so it can be recalled on the next run.
    """
    result: Any = None


@contextmanager
def checkpoint(
    run_id: str,
    step: str,
    store: CheckpointStore,
    skip_if_done: bool = True,
):
    """
    Context manager that checkpoints a single agent step.

    Usage:
        with checkpoint(run_id, "step_name", store) as ctx:
            if ctx.result is not None:
                result = ctx.result        # cache hit: reuse saved result
            else:
                result = do_work()
                ctx.result = result        # cache miss: compute + persist

    On first run:  marks RUNNING, yields empty StepContext, saves ctx.result
                   as DONE on clean exit, FAILED on exception.
    On resume:     yields StepContext with .result pre-populated from store,
                   skips execution entirely.
    """
    if skip_if_done and store.is_done(run_id, step):
        cached = store.get_result(run_id, step)
        print(f"[checkpoint] ✓ {step} (cached)")
        yield StepContext(result=cached)
        return

    store.mark_running(run_id, step)
    start = time.monotonic()
    ctx = StepContext()

    try:
        yield ctx
    except Exception as e:
        store.mark_failed(run_id, step, str(e))
        print(f"[checkpoint] ✗ {step} failed: {e}")
        raise
    else:
        duration = (time.monotonic() - start) * 1000
        store.mark_done(run_id, step, ctx.result)
        print(f"[checkpoint] ✓ {step} ({duration:.1f}ms)")
