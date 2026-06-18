# agent-checkpoint

> Framework-agnostic checkpoint and resume for long-running AI agents on Kubernetes.

---

## The problem

AI agents that process large workloads — summarising hundreds of documents, running
multi-step research pipelines, or calling LLMs in a loop — can take minutes or hours
to complete. When you run these agents on Kubernetes, the runtime environment is
not guaranteed to stay alive for the whole run.

Kubernetes can evict your pod at any time:

- **Node pressure** — the node runs low on memory or disk and evicts lower-priority pods
- **Voluntary disruptions** — a node drain during a cluster upgrade
- **Spot/preemptible instances** — intentionally short-lived nodes to cut cloud costs
- **Manual intervention** — an operator force-deletes a pod to recover a stuck deployment

When any of these happen, your agent loses everything it has computed so far and
restarts from step 1. If each step involves an LLM call at $0.01–$0.10, restarting
a 100-step pipeline wastes real money. If each step takes 5 seconds, restarting a
200-step pipeline wastes 16 minutes.

Most open-source agent frameworks — CrewAI, AutoGen, mofa — treat the entire run
as a single atomic operation with no built-in recovery. LangGraph has a checkpointer,
but it only works inside LangGraph. Temporal and Restate solve this properly but
require rewriting your agent in their SDK. There is no lightweight, drop-in solution
that works with any framework.

**agent-checkpoint fills that gap.**

---

## How it works

The library wraps individual steps of your agent loop in a `checkpoint()` context
manager. Each time a step completes, its result is written to a SQLite database on
a Kubernetes PersistentVolumeClaim. When the pod is killed and Kubernetes restarts
it, the agent reads the database, skips every step that already has a saved result,
and resumes from the exact point of interruption.

```
First run — pod killed at step 3:

  Agent loop
    │
    ├─ step_01 ──► [checkpoint] mark RUNNING ──► execute ──► mark DONE ──► SQLite ✓
    ├─ step_02 ──► [checkpoint] mark RUNNING ──► execute ──► mark DONE ──► SQLite ✓
    ├─ step_03 ──► [checkpoint] mark RUNNING ──► execute ──► ✗ POD KILLED
    │
    └─ steps 04–10: never reached


After Kubernetes restarts the pod — same RUN_ID, same PVC:

  Agent loop
    │
    ├─ step_01 ──► [checkpoint] is_done? YES ──► return cached result  (instant)
    ├─ step_02 ──► [checkpoint] is_done? YES ──► return cached result  (instant)
    ├─ step_03 ──► [checkpoint] is_done? NO  ──► execute ──► mark DONE ──► SQLite ✓
    ├─ step_04 ──► [checkpoint] is_done? NO  ──► execute ──► mark DONE ──► SQLite ✓
    └─ ...
```

The SQLite file lives on a PersistentVolumeClaim so it survives pod restarts. WAL
(Write-Ahead Logging) mode is enabled so reads never block writes. The checkpoint
overhead is under 0.2 ms per step — negligible compared to LLM call latency.

---

## What already exists and why it's not enough

| Solution | Self-hostable | Framework-agnostic | Drop-in (no rewrite) | Open source |
|---|:---:|:---:|:---:|:---:|
| **agent-checkpoint** | ✓ | ✓ | ✓ | ✓ |
| LangGraph SqliteSaver | ✓ | ✗ LangGraph only | ✗ | ✓ |
| Temporal | ✓ | ✗ requires SDK rewrite | ✗ | ✓ |
| Restate | ✓ | ✗ requires SDK rewrite | ✗ | ✓ |
| Google ADK persistence | ✗ GCP-only | ✗ | ✗ | ✗ |
| Agentspan | ✗ SaaS | ✓ | ✓ | ✗ |

---

## Installation

```bash
pip install agent-checkpoint
```

For PostgreSQL support (multi-node / multi-replica setups):

```bash
pip install agent-checkpoint[postgres]
```

SQLite is part of Python's standard library — no extra dependencies for the default backend.

---

## Quick start

```python
from checkpoint import CheckpointStore, checkpoint

# Connect to the store — SQLite file on a PVC in Kubernetes,
# or a local path during development.
store = CheckpointStore("sqlite:///agent_runs.db")

RUN_ID = "my-agent-run-001"

for i, doc in enumerate(documents):
    step = f"step_{i:02d}"

    with checkpoint(RUN_ID, step, store) as ctx:
        if ctx.result is not None:
            # This step was completed in a previous run.
            # ctx.result holds the value we saved last time.
            result = ctx.result
        else:
            # First time we're seeing this step.
            # Do the work, then save the result so it can be skipped next run.
            result     = agent.process(doc)
            ctx.result = result

    results.append(result)
```

That's it. No changes to the agent framework, no new infrastructure, no SDK rewrite.
Add the `with checkpoint(...)` block around each step and you get fault-tolerant
resumption for free.

---

## The context manager in detail

```python
with checkpoint(run_id, step_name, store) as ctx:
    ...
```

**On the first run (cache miss):**
1. Marks the step as `RUNNING` in the database.
2. Yields a `StepContext` with `ctx.result = None`.
3. Your code runs inside the `with` block and sets `ctx.result = <your value>`.
4. On clean exit: marks the step as `DONE` and saves `ctx.result` to the database.
5. On exception: marks the step as `FAILED` and re-raises — the step will be
   retried on the next run.

**On resume (cache hit):**
1. Detects `is_done(run_id, step)` is True.
2. Loads the saved result from the database.
3. Yields a `StepContext` with `ctx.result` pre-populated.
4. Your code reads `ctx.result` and skips the expensive work.
5. Returns immediately — no database write needed.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `run_id` | `str` | required | Unique identifier for this agent run. Use the same ID on resume. |
| `step` | `str` | required | Unique name for this step within the run. |
| `store` | `CheckpointStore` | required | The store instance to read/write from. |
| `skip_if_done` | `bool` | `True` | Set to `False` to force re-execution even if the step is cached. |

---

## Store backends

### SQLite (default)

```python
store = CheckpointStore("sqlite:///relative/path/agent.db")
store = CheckpointStore("sqlite:////absolute/path/agent.db")   # four slashes
```

- Zero dependencies — SQLite ships with Python.
- WAL mode enabled automatically for safe concurrent reads/writes.
- Best for single-pod agents. The `.db` file must be on a PVC to survive restarts.

### PostgreSQL

```python
store = CheckpointStore("postgresql://user:password@hostname:5432/dbname")
```

- Requires `pip install agent-checkpoint[postgres]`.
- Best for multi-replica agents or when you want a centralised store.
- Use a connection pooler (PgBouncer) for high-throughput workloads.

---

## Store API

```python
store.is_done(run_id, step)             # → bool
store.get_result(run_id, step)          # → Any | None
store.get_run_summary(run_id)           # → {"completed": int, "failed": int,
                                        #    "running": int, "total": int}
store.list_completed_steps(run_id)      # → list[str]
store.clear_run(run_id)                 # delete all records for a run (start over)
store.mark_running(run_id, step)        # low-level: mark step as in-progress
store.mark_done(run_id, step, result)   # low-level: mark step as complete
store.mark_failed(run_id, step, error)  # low-level: mark step as failed
```

---

## Framework compatibility

The `checkpoint()` context manager is completely framework-agnostic. It wraps a
Python code block — it doesn't care what runs inside.

| Framework | Integration pattern |
|---|---|
| Plain Python loop | Wrap each loop iteration directly |
| CrewAI | Wrap each `crew.kickoff()` call — see `examples/crewai_example.py` |
| AutoGen | Wrap each agent message round-trip |
| LangChain | Wrap each `chain.invoke()` call |
| LangGraph | Use alongside or instead of `SqliteSaver` |
| mofa | Wrap each dataflow node execution |

---

## Kubernetes deployment

### How the persistence works

```
Pod (agent-checkpoint-demo)
  │
  ├── /data/checkpoints/          ← PersistentVolumeClaim mounted here
  │       └── demo_run.db         ← SQLite file, survives pod restarts
  │
  └── examples/demo_agent.py      ← reads CHECKPOINT_DB env var → opens SQLite
```

The agent reads `CHECKPOINT_DB` from the environment. In the Kubernetes manifests,
this is set to `sqlite:////data/checkpoints/demo_run.db` via a ConfigMap. The PVC
is mounted at `/data/checkpoints`. When Kubernetes kills and restarts the pod, the
new pod mounts the same PVC and finds the database with all previously completed steps.

### Deployment vs Job

Use a **Deployment** (`k8s/deployment.yaml`) for agents that should always be
running — chat agents, monitoring loops, or any agent you want Kubernetes to
restart automatically after completion.

Use a **Job** (`k8s/job.yaml`) for batch agents with a finite task — process
these 500 documents, then stop. The `backoffLimit: 10` setting means Kubernetes
will retry the pod up to 10 times on failure, resuming from the last checkpoint
each time.

### Graceful shutdown

The manifests set `terminationGracePeriodSeconds: 30` and a `preStop` sleep of 5
seconds. This gives the agent time to finish writing the current checkpoint before
the container receives `SIGTERM`. The SQLite WAL mode ensures the write is atomic —
a checkpoint is either fully written or not written at all, never half-written.

---

## Kubernetes demo (live)

### Prerequisites

```bash
docker --version    # Docker must be running
kind --version      # KIND — Kubernetes IN Docker
kubectl version --client
```

Install KIND and kubectl if needed:
```bash
# KIND
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.23.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/kubectl
```

### Setup (one time)

```bash
make demo
```

This will:
1. Create a KIND cluster named `agent-checkpoint`
2. Apply the PVC, ConfigMap, and PDB manifests
3. Build the `agent-checkpoint-demo:latest` Docker image
4. Load the image into the KIND cluster (no registry needed)
5. Deploy the agent and wait for the pod to be ready

### Running the demo

**Reset before each run** (clears the checkpoint database):
```bash
make demo-reset
```

**Terminal 1** — watch the agent process documents:
```bash
make demo-run
```

You will see output like:
```
[agent-checkpoint] Starting new run 'demo-run-001'

  [ 1/10] document_01.txt — processing... done ✓
[checkpoint] ✓ process_01 (3000.1ms)
  [ 2/10] document_02.txt — processing... done ✓
[checkpoint] ✓ process_02 (3000.1ms)
  [ 3/10] document_03.txt — processing...
```

**Terminal 2** — kill the pod mid-run (around step 4–5):
```bash
make demo-kill
```

**Back in Terminal 1** — watch it resume:
```bash
make demo-run
```

You will see:
```
[agent-checkpoint] Resuming run 'demo-run-001'
[agent-checkpoint] Steps already done: 4/10
[agent-checkpoint] Skipping to step 5

[checkpoint] ✓ process_01 (cached)
  [ 1/10] document_01.txt — skipped (cached)
[checkpoint] ✓ process_02 (cached)
  [ 2/10] document_02.txt — skipped (cached)
...
  [ 5/10] document_05.txt — processing... done ✓
```

Steps 1–4 complete instantly. Step 5 onward resumes normally.

### Teardown

```bash
make demo-clean
```

---

## Benchmark results

Measured on a laptop with SQLite WAL mode, ~1 KB JSON payload, 1000 iterations:

| Operation | mean | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| write (`mark_done`) | 0.11 ms | 0.06 ms | 0.10 ms | 0.15 ms | 12.64 ms |
| read (`get_result`) | 0.01 ms | 0.01 ms | 0.01 ms | 0.01 ms | 0.06 ms |

SQLite file size: ~1.2 MB per 1000 checkpoints at ~1 KB each.

A typical LLM call takes 500–5000 ms. The checkpoint overhead of 0.11 ms is
less than 0.02% of that — it is immeasurable in practice.

Run `make bench` to reproduce these numbers on your own machine.

---

## Project structure

```
agent-checkpoint/
├── checkpoint/
│   ├── __init__.py       exports: checkpoint, CheckpointStore, StepContext, StepStatus
│   ├── manager.py        the checkpoint() context manager
│   ├── store.py          SQLite and PostgreSQL backends
│   └── models.py         StepRecord, RunRecord, StepStatus dataclasses
├── examples/
│   ├── demo_agent.py     10-step demo agent for the live conference demo
│   ├── crewai_example.py drop-in usage with CrewAI (commented stub)
│   └── custom_loop.py    plain Python agent loop example
├── k8s/
│   ├── deployment.yaml   agent Deployment with PVC + graceful shutdown
│   ├── job.yaml          alternative: Kubernetes Job for batch agents
│   ├── pvc.yaml          PersistentVolumeClaim for the SQLite file
│   ├── pdb.yaml          PodDisruptionBudget
│   └── configmap.yaml    CHECKPOINT_DB and RUN_ID environment config
├── helm/
│   └── agent-checkpoint/ Helm chart (deployment, pvc, pdb templates)
├── benchmarks/
│   └── overhead.py       measures checkpoint latency in ms
├── tests/
│   ├── test_store.py     store backend tests
│   ├── test_manager.py   context manager tests
│   └── test_resume.py    interruption and resume scenario tests
├── Dockerfile
├── Makefile
└── pyproject.toml
```

---

## Development

```bash
# Install with dev dependencies
make install

# Run tests
make test

# Run benchmark
make bench
```

Tests use a temporary SQLite database per test (via `tmp_path` fixture) and cover:
- Store round-trips (read/write/clear)
- Cache hit and miss behaviour
- Exception handling and retry after failure
- Multi-step isolation between different run IDs
- Interruption at various points in a run and correct resume

---

## Contributing

1. Fork the repo and create a feature branch.
2. `make install` to set up the environment.
3. `make test` — all 28 tests must pass, no new failures.
4. `make bench` — checkpoint write overhead must stay below 5 ms mean.
5. Open a pull request with a description of what changed and why.

Bug reports and feature requests are welcome via GitHub Issues.

---

*Built for the Open Source Summit + Embedded Linux Conference Europe 2026.*
