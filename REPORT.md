# Agentic Qwen vLLM Text-to-SQL Serving Report

## 1. Overview

This project serves `Qwen/Qwen3-30B-A3B-Instruct-2507` with vLLM on an H100 and wraps it with a LangGraph text-to-SQL agent for BIRD-style SQLite databases. The agent receives a natural-language question and a database id, renders schema/context, generates SQL, executes it, verifies the result deterministically, and optionally revises the SQL with an iteration cap.

The main goal was not only to get a working text-to-SQL system, but to make the serving, observability, evaluation, and tuning decisions measurable. The final repo includes the vLLM serving configuration, Grafana dashboard, Langfuse tracing, eval runner, baseline/post-tuning results, and screenshots showing the system under load.

## 2. Serving Configuration

The model was served through vLLM’s OpenAI-compatible server:

```bash
sudo docker run -d --gpus '"device=0"' \
  --name qwen3-vllm \
  --network host \
  --ipc=host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e HF_TOKEN=$HF_TOKEN \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen3-30B-A3B-Instruct-2507 \
  --served-model-name qwen3-sql \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.92 \
  --max-num-seqs 64 \
  --max-num-batched-tokens 16384 \ 
  --enable-prefix-caching \
  --trust-remote-code
```

The important serving flags were chosen for this workload rather than left at defaults:

* `--dtype bfloat16`: uses H100-friendly bfloat16 inference to reduce memory pressure while preserving quality.
* `--max-model-len 4096`: needed because text-to-SQL prompts include schema/context. A smaller 2048 limit caused context-length errors.
* `--gpu-memory-utilization 0.92`: allows vLLM to allocate most of GPU memory to model execution and KV cache while leaving a safety margin.
* `--max-num-seqs 64`: allows many concurrent requests to be scheduled.
* `--max-num-batched-tokens 16384`: increased throughput because the workload has long prompt-prefill and short SQL outputs. Raising this allowed vLLM to batch more schema-heavy prompt tokens per scheduler iteration.
* `--enable-prefix-caching`: useful because many requests share repeated schema/context prefixes.
* `--trust-remote-code`: required for this model family.

The main throughput improvement came from increasing the token batch budget. The SQL agent sends relatively long prompts containing schema and hints, then asks for a short SQL query. That means prefill cost dominates. When `max-num-batched-tokens` was too small, the GPU processed smaller batches and RPS was lower. Increasing it to roughly 16k let vLLM batch more prefill tokens together, improving GPU utilization and request throughput.

The tradeoff is that larger batches can increase memory pressure and sometimes p95/p99 latency. I monitored this through Grafana using latency, throughput, running/waiting request, and KV-cache panels.

## 3. Observability

The repo includes the Grafana dashboard at:

```text
infra/grafana/provisioning/dashboards/serving.json
```

The dashboard includes:

* P95 end-to-end request latency
* P95 time to first token
* generation tokens/sec
* running requests
* waiting requests / queue
* KV-cache usage

These panels answer two questions:

1. Is the system slow?
2. Where is the slowness coming from: prompt prefill, generation, queueing, or KV-cache pressure?

The dashboard visibly reacted during load tests and eval runs. Screenshots saved:

```text
screenshots/grafana_serving.png
screenshots/grafana_eval_run.png
screenshots/grafana_before.png
screenshots/grafana_after.png
```

I also saved a manual query screenshot showing that the vLLM server was live and returning SQL through the agent:

```text
screenshots/vllm_manual_query.png
```

## 4. Agent Design

The agent is implemented in:

```text
agent/graph.py
agent/prompts.py
agent/context.py
agent/schema.py
agent/execution.py
```

The LangGraph flow is:

```text
START
  -> attach_schema
  -> generate_sql
  -> execute
  -> verify
  -> END if verified
  -> revise if verifier finds a clear issue and iteration cap not reached
  -> execute
  -> verify
  -> END
```

The iteration cap is controlled by:

```bash
MAX_ITERATIONS=2
```

The design intentionally avoids using an LLM verifier in the hot path. The first version used more sequential model calls, which hurt latency. I replaced that with a deterministic verifier and only call the LLM again when the SQL has a clear structural problem.

The verifier checks for:

* SQL execution errors
* non-SELECT/write operations
* obvious count/average/sum/percentage/ranking mismatches
* wrong output shape such as returning a count when the question asks for names/entities
* duplicate rows from joins in list-style questions
* zero rows caused by likely bad filters

One example that triggers revise is a query where the first SQL returns duplicate rows from a join. The verifier asks for a corrected query, and the revise node updates the SQL. This is captured in Langfuse.

Screenshots saved:

```text
screenshots/langfuse_trace.png
screenshots/langfuse_tags.png
```

## 5. Prompt and Context Design

The prompt tells the model to return only one SQLite query, use only schema columns, prefer explicit joins, preserve output shape, and handle common aggregation/ranking cases.

The context renderer includes:

* raw SQLite schema rendered from the database
* foreign keys from `PRAGMA foreign_key_list`
* general SQL hints
* lightweight database-level hints

A key lesson was that some hints added after inspecting eval failures were too targeted. For example, extra DB-specific hints improved the original fixed eval but risked overfitting. I therefore separated clean context from tuned context conceptually:

* clean mode: schema + general hints + broad DB hints
* tuned mode: includes extra eval-derived hints

For the final writeup, I treat the fixed eval as a tuned validation result and the smart eval as a harder diagnostic test rather than claiming the tuned score fully generalizes.

## 6. Evaluation

The eval runner is:

```text
evals/run_eval.py
```

It executes the agent on a JSONL eval set, runs the produced SQL against the SQLite database, runs the gold SQL, and compares canonicalized result sets. This avoids requiring exact SQL string match. Two different SQL queries can both be correct if they produce the same result.

The saved eval files are:

```text
results/eval_baseline.json
results/eval_after_tuning.json
```

Optional diagnostic files:

```text
results/eval_smart_clean.json
results/eval_smart_clean_failures.json
```
In Eval smart we have harder queries that further test the agent capabilities.

The main reported metric is execution accuracy. I also track per-iteration accuracy to see whether the verify→revise loop earns its cost. In the tuned run, the loop sometimes fixed structural failures, but the gains were not free: each revise adds another LLM call, increasing latency. This is why I kept the iteration cap low.

The baseline was weaker because the agent relied more heavily on initial generation and had fewer prompt/schema/context improvements. After tuning, execution accuracy improved on the fixed eval. However, the harder smart eval exposed remaining weaknesses, especially:

* wrong aggregation grain
* missing `GROUP BY`
* ranking individual rows instead of ranking entities
* percentage/conditional aggregation mistakes
* multi-hop join mistakes
* occasional extra filters not requested by the question

One inspected smart-eval failure asked for the “top 5 lowest enrollment cities.” The gold SQL grouped by city and ordered by `SUM(Enrollment)`. The agent joined the right tables but ranked individual rows and added `DISTINCT`. This showed that the verifier’s duplicate-row logic was too shallow: the correct fix was not `DISTINCT`, but `GROUP BY City ORDER BY SUM(...)`.

That finding led to a planned verifier/prompt improvement: when the question asks for ranked entities over related rows, use `GROUP BY` on the requested entity and order by an aggregate.

## 7. SLO Diagnosis and Iteration Log

The most important iteration was serving throughput.

### Observation

During load testing, RPS was lower than expected and the GPU was not being used efficiently enough for the prompt-heavy workload. The workload consists of long schema/context prompts and short SQL outputs.

### Hypothesis

The vLLM scheduler was constrained by token batch size. Since the workload is prefill-heavy, too small a `max-num-batched-tokens` value prevents vLLM from batching enough prompt tokens per scheduler step.

### Change

I increased:

```bash
--max-num-batched-tokens
```

to around 16k and used:

```bash
--max-num-seqs 64
--max-model-len 4096
--gpu-memory-utilization 0.92
```

### Result

RPS improved under the same offered load. The Grafana dashboard showed the system processing more work per step, and the load-test result confirmed better throughput. The final load-test output was saved under:

```text
results/load_test_rps10_final.json
```

One final load test scheduled 10 RPS for 300 seconds, producing 3000 requests. The script-reported achieved RPS was lower because it divides by total wall-clock time including the drain period. This is why I report both the offered load and the measured wall-clock throughput.

### Quality Iteration

The first quality improvements were prompt/context/verifier changes. Accuracy improved on the fixed eval, but the smart eval later showed possible overfitting from eval-derived DB hints. The honest interpretation is:

* fixed eval result: tuned in-distribution validation score
* smart eval result: harder generalization/stress test
* next step: evaluate a final untouched holdout set

## 8. Known Limitations

The system still has several limitations:

1. It can rank the wrong grain, for example ranking rows instead of grouping by the requested entity.
2. It sometimes adds reasonable-sounding filters not asked by the user.
3. The deterministic verifier catches obvious structural failures but cannot prove semantic correctness.
4. Some DB-specific hints were added after inspecting eval failures, so the tuned fixed-eval score may overstate generalization.
5. The smart eval is harder and lower-scoring, which is useful diagnostically but should be reported separately from the main validation set.
6. The revise loop improves some cases but adds latency, so it should remain capped.

## 9. What I Would Do With More Time

The next improvements would be specific and measurable:

1. Add dynamic sample-value retrieval from SQLite so the agent discovers values like status labels, gender codes, and date formats instead of relying on hand-written hints.
2. Add explicit relationship/path context for multi-hop joins.
3. Improve the verifier to detect wrong aggregation grain, especially ranked entities over related rows.
4. Add a clean/tuned/holdout evaluation split:

   * clean mode without eval-derived hints
   * tuned mode with all hints
   * final holdout never used during prompt development
5. Add failure categorization to the eval runner so every failed SQL is labeled by type: wrong join, wrong filter value, wrong aggregation, wrong output shape, execution error, or ambiguous gold.
6. Tune `max-num-batched-tokens`, `max-num-seqs`, and `max-model-len` systematically while tracking p50/p95/p99 latency, RPS, KV-cache usage, and accuracy.

## 10. Final Repo Checklist

The final repo contains:

```text
REPORT.md
infra/grafana/provisioning/dashboards/serving.json
agent/graph.py
agent/prompts.py
evals/run_eval.py
results/eval_baseline.json
results/eval_after_prompt_adjustments.json
results/eval_smart_initial.json
results/eval_smart_further_improvements.json
screenshots/vllm_manual_query.png
screenshots/grafana_serving.png
screenshots/langfuse_trace.png
screenshots/langfuse_tags.png
screenshots/grafana_eval_run.png
screenshots/grafana_before.png
screenshots/grafana_after.png
```

Overall, the strongest part of the submission is the metric-grounded iteration: I observed low throughput, connected it to vLLM batching behavior for prompt-heavy requests, changed the serving configuration, and saved before/after evidence. On the quality side, the agent improved on the fixed validation set, but the smart eval revealed real remaining weaknesses and possible overfitting, which I report honestly rather than hiding.
