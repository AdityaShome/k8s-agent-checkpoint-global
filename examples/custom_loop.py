#!/usr/bin/env python3
"""
agent-checkpoint with a plain Python agent loop.

No frameworks required. Shows the minimal integration pattern for any
custom agent that processes items in a loop.

Run:
    python custom_loop.py
    python custom_loop.py   # second run completes instantly
"""

import os
import sys
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from checkpoint import CheckpointStore, checkpoint

DB_PATH = os.getenv("CHECKPOINT_DB", "sqlite:///custom_loop.db")
RUN_ID  = os.getenv("RUN_ID",         "custom-loop-001")


def call_llm(prompt: str) -> str:
    """Stub LLM call — replace with openai / anthropic / etc."""
    time.sleep(0.5)
    return f"Response to: {prompt[:40]}... [tokens={random.randint(100, 500)}]"


def main():
    store = CheckpointStore(DB_PATH)

    items = [
        "Summarise the Q3 earnings report",
        "Extract action items from the board meeting notes",
        "Draft a reply to the customer complaint in ticket #4421",
        "Translate the product description into Spanish",
        "Generate 5 subject lines for the newsletter",
    ]

    print(f"\nRun ID: {RUN_ID}")
    summary = store.get_run_summary(RUN_ID)
    if summary["completed"]:
        print(f"Resuming — {summary['completed']}/{len(items)} already done\n")
    else:
        print("Fresh run\n")

    results = []

    for i, item in enumerate(items):
        step = f"item_{i:02d}"

        with checkpoint(RUN_ID, step, store) as ctx:
            if ctx.result is not None:
                result = ctx.result
            else:
                result     = call_llm(item)
                ctx.result = result

        results.append(result)
        print(f"  {i+1}. {item[:50]}")
        print(f"     → {result}\n")

    print(f"Done. {len(results)} items processed.")
    print(f"Run '{RUN_ID}' complete.\n")


if __name__ == "__main__":
    main()
