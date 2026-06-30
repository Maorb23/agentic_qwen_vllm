# Agentic Qwen vLLM Text-to-SQL Platform

We built an internal-style text-to-SQL platform that serves Qwen with vLLM,
wraps it in a LangGraph agent, evaluates SQL execution accuracy on BIRD-style
SQLite databases, and observes the full stack with Prometheus, Grafana, and
Langfuse.

The project is designed around one practical workflow:

1. An analyst asks a natural-language question.
2. The agent renders the relevant database schema and context hints.
3. Qwen generates SQLite SQL.
4. The system executes the SQL in read-only mode.
5. A deterministic verifier catches clear structural failures.
6. The agent optionally revises the SQL and returns the final rows.

The main service contract is exposed over HTTP at `POST /answer`.

## What We Built

This repository contains four connected layers:

| Layer | Implementation |
|---|---|
| Model serving | vLLM serving `Qwen/Qwen3-30B-A3B-Instruct-2507` through an OpenAI-compatible API |
| Agent | LangGraph text-to-SQL graph with generate, execute, verify, and revise steps |
| Evaluation | Execution-accuracy runner comparing generated SQL against gold SQL on SQLite |
| Observability | Prometheus/Grafana for serving metrics and Langfuse for agent traces |

The project is intentionally backend-focused. There is no frontend; the product
surface is the agent API plus the observability and evaluation artifacts around
it.

## Architecture

```text
question + db_id
      |
      v
render schema + context hints
      |
      v
+----------------+
| generate_sql   |  LLM call
+----------------+
      |
      v
+----------------+
| execute_sql    |  read-only SQLite execution
+----------------+
      |
      v
+----------------+
| verify         |  deterministic structural checks
+----------------+
      |
      +---- ok ----------------> return SQL + rows
      |
      +---- issue found --------> revise_sql -> execute_sql -> verify
```

The verifier is deliberately deterministic. It avoids an extra model call on
every request and only sends clear, recoverable problems into the revision loop:
SQL execution errors, unsafe statements, missing `COUNT`/`AVG`/`ORDER BY` for
obvious intents, zero-row filtered results, and duplicate rows from joins.

The model-visible guidance lives in:

- `agent/prompts.py`
- `agent/context.py`
- rendered schema from `agent/schema.py`

Function docstrings and inline comments are for maintainers. They are not part
of the prompt unless we explicitly pass them to the model.

## Repository Layout

```text
agent/
  context.py       prompt-visible schema and DB hints
  execution.py     read-only SQLite execution helper
  graph.py         LangGraph agent workflow
  prompts.py       generation and revision prompts
  schema.py        SQLite schema rendering
  server.py        FastAPI wrapper around the graph

evals/
  eval_set.jsonl   curated evaluation questions
  run_eval.py      execution-accuracy evaluator

load_test/
  driver.py        async load driver for the agent endpoint
  perf_pool.jsonl  load-test question pool

infra/
  prometheus.yml
  grafana/
    provisioning/
      dashboards/serving.json
      datasources/prometheus.yml

scripts/
  load_data.py     BIRD dev data preparation
  start_vllm.sh    vLLM launch script

results/           eval and load-test outputs
screenshots/       Grafana, Langfuse, and manual run evidence
REPORT.md          technical writeup and measurements
```

## Prerequisites

- H100 80GB for the final Qwen3-30B-A3B serving run
- Docker and Docker Compose
- `uv`
- Python 3.11+
- Git

The agent can be developed against any OpenAI-compatible endpoint. Final
performance and quality numbers should be collected against the Qwen/vLLM
configuration we report.

## Environment

Create a local environment file:

```bash
cp .env.example .env
```

Important variables:

| Variable | Purpose |
|---|---|
| `VLLM_BASE_URL` | OpenAI-compatible model endpoint, usually `http://localhost:8000/v1` |
| `VLLM_MODEL` | Served model name, usually `qwen3-sql` |
| `OPENAI_API_KEY` | API key value required by OpenAI-compatible clients; vLLM can use a dummy value |
| `LANGFUSE_PUBLIC_KEY` | Optional Langfuse tracing key |
| `LANGFUSE_SECRET_KEY` | Optional Langfuse tracing key |
| `LANGFUSE_HOST` | Local Langfuse host, usually `http://localhost:3001` |

## Setup

Install dependencies:

```bash
uv sync
```

Prepare the BIRD data:

```bash
uv run python scripts/load_data.py
```

This creates:

- `data/bird/<db_id>.sqlite`
- `evals/eval_set.jsonl`
- `load_test/perf_pool.jsonl`

Start the observability stack:

```bash
docker compose up -d
```

Useful local services:

| Service | URL |
|---|---|
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3000` |
| Langfuse | `http://localhost:3001` |
| vLLM | `http://localhost:8000` |
| Agent API | `http://localhost:8001` |

Grafana is provisioned with Prometheus as a datasource and the serving dashboard
under `infra/grafana/provisioning/dashboards/serving.json`.

## Running vLLM

The launch script is:

```bash
scripts/start_vllm.sh
```

The reported configuration serves:

```text
Qwen/Qwen3-30B-A3B-Instruct-2507
```

through an OpenAI-compatible endpoint. See `REPORT.md` for the exact serving
flags and the reasoning behind them.

## Running the Agent API

Start the FastAPI wrapper:

```bash
uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001
```

Health check:

```bash
curl http://localhost:8001/health
```

Example request:

```bash
curl -X POST http://localhost:8001/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "List down Ajax'"'"'s superpowers.", "db": "superhero"}'
```

Example response shape:

```json
{
  "sql": "SELECT ...",
  "rows": [["..."]],
  "iterations": 1,
  "ok": true,
  "error": null,
  "history": []
}
```

## Evaluation

We use execution accuracy rather than exact SQL string matching. The evaluator:

1. Reads `evals/eval_set.jsonl`.
2. Calls the agent endpoint for each question.
3. Runs the generated SQL and gold SQL against the same SQLite DB.
4. Canonicalizes row sets.
5. Reports final accuracy and per-iteration accuracy.

Run:

```bash
uv run python evals/run_eval.py \
  --agent-url http://localhost:8001/answer \
  --out results/eval_baseline.json
```

The per-iteration metric tells us whether the revision loop earns its latency
cost. If later iterations do not improve accuracy, the loop is not providing
value for that dataset.

## Load Testing

The load driver sends sampled questions from `load_test/perf_pool.jsonl` to the
agent endpoint at a target request rate:

```bash
uv run python load_test/driver.py \
  --rps 10 \
  --duration 300 \
  --agent-url http://localhost:8001/answer \
  --out results/load_test.json
```

The result file contains:

- offered RPS
- achieved RPS
- request counts by status
- p50/p95/p99/max latency
- raw per-request records

During load tests, Grafana should show serving latency, throughput, queueing,
and KV-cache behavior moving with the offered load.

## Observability

We use two complementary views:

| Tool | What It Tells Us |
|---|---|
| Prometheus + Grafana | vLLM serving health: latency, throughput, queueing, token rates, KV-cache pressure |
| Langfuse | Agent traces: node timing, prompts, responses, metadata, and revision behavior |

The serving dashboard is intended to answer:

- Is latency high?
- Is the bottleneck queueing, prefill, decode, or batching?
- Are we saturating or wasting the GPU?
- Do KV-cache metrics show enough concurrency headroom?

Langfuse traces are used to inspect individual agent runs, especially requests
that revise or respond slowly.

## Current Results

Detailed numbers are in `REPORT.md`. At a high level:

- vLLM is configured for a prompt-heavy workload with short SQL outputs.
- Increasing the token batch budget improved throughput.
- The context hints and deterministic verifier improved the fixed eval result.
- The harder smart-eval analysis exposed remaining semantic weaknesses and some
  risk of overfitting from DB-specific hints.

The important takeaway is that quality and latency are coupled: every revision
can improve a bad SQL query, but it also adds another LLM call. We keep the loop
small and measure whether it is worth the cost.

## Design Choices

### Prompt-visible context instead of hidden comments

The model does not read Python comments or ordinary function docstrings during
runtime. Guidance that should affect generation belongs in prompts, tool
descriptions, or rendered context. That is why domain hints live in
`agent/context.py` and are appended to the schema prompt.

### Deterministic verifier

The verifier does not try to prove semantic equivalence. It catches high-signal
structural problems cheaply and sends only those cases to revision. This keeps
latency predictable while still fixing common failures.

### Execution accuracy

SQL can be written many ways. We care whether the rows match the intended answer,
so the evaluator compares result sets rather than SQL text.

### Read-only execution

Generated SQL runs against SQLite in read-only mode. The verifier also rejects
obvious write/schema operations.

## Development Notes

When working without the H100, point the agent at another OpenAI-compatible
backend through `.env`. This is enough for graph wiring, API testing, tracing,
and evaluator development. Final measurements should still be collected against
the reported Qwen/vLLM deployment.

Useful commands:

```bash
uv run python scripts/load_data.py
docker compose up -d
uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001
uv run python evals/run_eval.py
uv run python load_test/driver.py --rps 10 --duration 300
```

Syntax check:

```bash
python -m compileall agent evals load_test scripts
```

## Artifacts

Project evidence is kept in:

| Path | Purpose |
|---|---|
| `REPORT.md` | Technical writeup, measurements, and analysis |
| `results/eval_baseline.json` | Baseline execution-accuracy results |
| `results/eval_after_tuning.json` | Post-tuning execution-accuracy results |
| `results/load_test*.json` | Load-test outputs |
| `infra/grafana/provisioning/dashboards/serving.json` | Grafana serving dashboard |
| `screenshots/` | Manual query, Grafana, and Langfuse evidence |

## Next Improvements

The next useful improvements are:

- replace static DB hints with retrieval from schema samples and column-value
  profiles
- strengthen verification for grouping, denominators, and requested output shape
- track token-level latency per graph node in the eval output
- add a regression suite for known failure classes
- separate generalizable context from eval-derived tuning hints
