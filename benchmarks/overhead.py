#!/usr/bin/env python3
"""
Measures the per-operation overhead of agent-checkpoint (SQLite backend).

Runs 1000 write operations and 1000 read operations with a ~1 KB JSON payload,
then prints a summary table with mean, p50, p95, and p99 latencies.

Target: write < 5 ms mean, < 20 ms p99.

Usage:
    python benchmarks/overhead.py
    python benchmarks/overhead.py --iterations 5000
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from checkpoint import CheckpointStore


PAYLOAD = {
    "doc": "document_01.txt",
    "tokens": 1234,
    "summary": "A" * 900,   # ~1 KB when JSON-encoded
    "metadata": {"model": "gpt-4o", "latency_ms": 342, "finish_reason": "stop"},
}


def percentile(data: list[float], p: float) -> float:
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def run_write_benchmark(store: CheckpointStore, run_id: str, n: int) -> list[float]:
    times = []
    for i in range(n):
        step = f"bench_step_{i:05d}"
        t0 = time.perf_counter()
        store.mark_running(run_id, step)
        store.mark_done(run_id, step, PAYLOAD)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return times


def run_read_benchmark(store: CheckpointStore, run_id: str, n: int) -> list[float]:
    times = []
    for i in range(n):
        step = f"bench_step_{i:05d}"
        t0 = time.perf_counter()
        _ = store.get_result(run_id, step)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return times


def print_table(label: str, times: list[float]):
    mean  = statistics.mean(times)
    p50   = percentile(times, 50)
    p95   = percentile(times, 95)
    p99   = percentile(times, 99)
    worst = max(times)
    print(f"  {label:<20} mean={mean:6.2f}ms  p50={p50:6.2f}ms  p95={p95:6.2f}ms  p99={p99:6.2f}ms  max={worst:7.2f}ms")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()

    n = args.iterations

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "bench.db")
        store   = CheckpointStore(f"sqlite:///{db_path}")
        run_id  = "bench-run"

        print(f"\nagent-checkpoint overhead benchmark")
        print(f"Backend : SQLite (WAL mode)")
        print(f"Payload : ~{len(json.dumps(PAYLOAD))} bytes JSON")
        print(f"N       : {n} operations each\n")

        print("Warming up (100 ops)...")
        warm_run = "warm"
        for i in range(100):
            store.mark_running(warm_run, f"w_{i}")
            store.mark_done(warm_run, f"w_{i}", PAYLOAD)
        store.clear_run(warm_run)
        print("Done.\n")

        print("Running write benchmark...")
        write_times = run_write_benchmark(store, run_id, n)

        print("Running read benchmark...")
        read_times  = run_read_benchmark(store, run_id, n)

        db_size_kb = os.path.getsize(db_path) / 1024

        print(f"\n{'─' * 80}")
        print(f"  {'Operation':<20} {'mean':>10}   {'p50':>10}   {'p95':>10}   {'p99':>10}   {'max':>10}")
        print(f"{'─' * 80}")
        print_table("write (mark_done)", write_times)
        print_table("read  (get_result)", read_times)
        print(f"{'─' * 80}")
        print(f"  SQLite file size after {n} checkpoints: {db_size_kb:.1f} KB")
        print()

        # Emit pass/fail against targets
        w_mean = statistics.mean(write_times)
        w_p99  = percentile(write_times, 99)
        ok = True
        if w_mean > 5:
            print(f"  WARNING: write mean {w_mean:.2f}ms exceeds 5ms target")
            ok = False
        if w_p99 > 20:
            print(f"  WARNING: write p99 {w_p99:.2f}ms exceeds 20ms target")
            ok = False
        if ok:
            print(f"  All targets met (write mean < 5ms, p99 < 20ms) ✓")
        print()

        store.close()


if __name__ == "__main__":
    main()
