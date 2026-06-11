# LLM Inference + Observability Report

## 1. Serving Configuration

The serving layer runs `Qwen/Qwen3-30B-A3B-Instruct-2507` through vLLM’s OpenAI-compatible API on one H100. The model is exposed as `qwen3-sql` and the agent calls it through `http://localhost:8000/v1`.

| Flag | Value | Justification |
|---|---:|---|
| `--model` | `Qwen/Qwen3-30B-A3B-Instruct-2507` | Required model for the assignment; MoE model with Qwen3Moe architecture. |
| `--served-model-name` | `qwen3-sql` | Stable short model name used by the agent and eval runner. |
| `--dtype` | `bfloat16` | H100-friendly precision with good performance and no quantization risk. |
| `--max-model-len` | `4096` | The workload uses roughly 1.5K-3K token prompts with short SQL outputs, so 4096 gives enough context while limiting KV-cache memory. |
| `--gpu-memory-utilization` | `0.90` | Uses most of the H100 memory while leaving safety margin for runtime overhead. |
| `--max-num-seqs` | `16` | Conservative concurrency starting point for stable latency. |
| `--max-num-batched-tokens` | `8192` | Allows batching/chunked prefill without overcommitting memory. |
| `--trust-remote-code` | enabled | Needed for loading the Qwen model implementation correctly. |
| `--network host` | enabled | Keeps vLLM available on `localhost:8000` for Prometheus and the agent. |
| `--ipc host` | enabled | Recommended for high-performance GPU serving containers. |

Manual validation succeeded:
- `/v1/models` returned the served model `qwen3-sql`.
- `/metrics` exposed vLLM Prometheus metrics.
- A manual chat-completions request returned valid SQL: `SELECT COUNT(*) FROM customers;`.

## 2. Baseline Evaluation Results

I implemented the Phase 5 execution-accuracy eval runner and ran it on the 30-question curated eval set.

Baseline result file:

```text
results/eval_baseline.json
