#!/usr/bin/env python3
"""
Demo agent for agent-checkpoint conference talk.
Simulates processing 10 documents with 3-second delays per step.

  First run:   python demo_agent.py
  Kill signal: kubectl delete pod -l app=agent-checkpoint-demo --force
  Resume:      python demo_agent.py   (resumes from last checkpoint)
"""

import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from checkpoint import CheckpointStore, checkpoint

DB_PATH = os.getenv("CHECKPOINT_DB", "sqlite:///demo_run.db")
RUN_ID  = os.getenv("RUN_ID",         "demo-run-001")

DOCUMENTS = [f"document_{i:02d}.txt" for i in range(1, 11)]


def process_document(doc: str) -> dict:
    """Simulate an expensive LLM call (3-second sleep stands in for real work)."""
    time.sleep(3)
    return {
        "doc":     doc,
        "tokens":  1234,
        "summary": f"Summary of {doc}",
    }


def main():
    store   = CheckpointStore(DB_PATH)
    summary = store.get_run_summary(RUN_ID)

    print()
    if summary["completed"] > 0:
        print(f"[agent-checkpoint] Resuming run '{RUN_ID}'")
        print(f"[agent-checkpoint] Steps already done: {summary['completed']}/10")
        print(f"[agent-checkpoint] Skipping to step {summary['completed'] + 1}")
    else:
        print(f"[agent-checkpoint] Starting new run '{RUN_ID}'")
    print()

    results = []

    for i, doc in enumerate(DOCUMENTS):
        step = f"process_{i+1:02d}"

        with checkpoint(RUN_ID, step, store) as ctx:
            if ctx.result is not None:
                result = ctx.result
                print(f"  [{i+1:2d}/10] {doc} — skipped (cached)")
            else:
                print(f"  [{i+1:2d}/10] {doc} — processing...", end="", flush=True)
                result    = process_document(doc)
                ctx.result = result
                print(" done ✓")

        results.append(result)

    print()
    print(f"[agent-checkpoint] All 10 steps complete.")
    print(f"[agent-checkpoint] Run '{RUN_ID}' finished successfully.")
    print()


if __name__ == "__main__":
    main()
