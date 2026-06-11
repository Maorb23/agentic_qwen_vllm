"""Eval runner using execution accuracy."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = ROOT / "evals" / "eval_set.jsonl"
DEFAULT_OUT_FILE = ROOT / "results" / "eval_baseline.json"
DB_DIR = ROOT / "data" / "bird"
AGENT_URL_DEFAULT = "http://localhost:8001/answer"
MAX_ITERATIONS = 3


def run_sql(db_id: str, sql: str, timeout: float = 5.0) -> tuple[bool, list[tuple] | None, str | None]:
    """Run sql against db_id in read-only mode."""
    path = DB_DIR / f"{db_id}.sqlite"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return True, rows, None
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


def canonicalize(rows: list[tuple] | None) -> list[tuple] | None:
    """Sort rows; coerce cells to str; None -> ''."""
    if rows is None:
        return None
    return sorted(tuple("" if c is None else str(c) for c in row) for row in rows)


def matches(gold_rows: list[tuple] | None, pred_rows: list[tuple] | None) -> bool:
    if gold_rows is None or pred_rows is None:
        return False
    return canonicalize(gold_rows) == canonicalize(pred_rows)


def _attempt_sqls_from_history(history: list[dict]) -> list[str]:
    sqls: list[str] = []
    for h in history:
        if h.get("node") in {"generate_sql", "revise"} and h.get("sql"):
            sqls.append(h["sql"])
    return sqls


def eval_one(question: dict, agent_url: str) -> dict:
    """Score one question by execution accuracy."""
    db_id = question["db_id"]
    q_text = question["question"]
    gold_sql = question["gold_sql"]

    gold_ok, gold_rows, gold_error = run_sql(db_id, gold_sql)
    if not gold_ok:
        return {
            "question": q_text,
            "db_id": db_id,
            "gold_sql": gold_sql,
            "gold_error": gold_error,
            "agent_error": None,
            "final_sql": "",
            "iterations": 0,
            "correct": False,
            "per_iteration_correct": [],
            "history": [],
        }

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(
                agent_url,
                json={
                    "question": q_text,
                    "db": db_id,
                    "tags": {"phase": "eval_baseline", "db_id": db_id},
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {
            "question": q_text,
            "db_id": db_id,
            "gold_sql": gold_sql,
            "gold_error": None,
            "agent_error": f"{type(e).__name__}: {e}",
            "final_sql": "",
            "iterations": 0,
            "latency_seconds": time.monotonic() - t0,
            "correct": False,
            "per_iteration_correct": [],
            "history": [],
        }

    latency = time.monotonic() - t0
    history = data.get("history", [])
    attempt_sqls = _attempt_sqls_from_history(history)

    if not attempt_sqls and data.get("sql"):
        attempt_sqls = [data["sql"]]

    per_iter: list[bool] = []
    for sql in attempt_sqls:
        pred_ok, pred_rows, _ = run_sql(db_id, sql)
        per_iter.append(pred_ok and matches(gold_rows, pred_rows))

    final_sql = data.get("sql", attempt_sqls[-1] if attempt_sqls else "")
    final_ok, final_rows, final_error = run_sql(db_id, final_sql) if final_sql else (False, None, "no sql")
    correct = final_ok and matches(gold_rows, final_rows)

    return {
        "question": q_text,
        "db_id": db_id,
        "gold_sql": gold_sql,
        "agent_error": data.get("error"),
        "final_sql": final_sql,
        "final_sql_error": final_error,
        "iterations": data.get("iterations", len(attempt_sqls)),
        "latency_seconds": latency,
        "correct": correct,
        "per_iteration_correct": per_iter,
        "history": history,
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate overall and per-iteration execution accuracy."""
    n = len(results)
    if n == 0:
        return {
            "num_questions": 0,
            "overall_execution_accuracy": 0.0,
            "per_iteration_accuracy": {},
            "avg_iterations": 0.0,
            "failed_requests": 0,
        }

    overall = sum(1 for r in results if r.get("correct")) / n
    failed = sum(1 for r in results if r.get("agent_error"))

    per_iteration_accuracy: dict[str, float] = {}
    for k in range(MAX_ITERATIONS):
        correct_k = 0
        for r in results:
            per = r.get("per_iteration_correct", [])
            if not per:
                is_correct = False
            elif k < len(per):
                is_correct = per[k]
            else:
                is_correct = per[-1]
            correct_k += int(is_correct)
        per_iteration_accuracy[f"iter_{k}"] = correct_k / n

    avg_iterations = sum(int(r.get("iterations", 0) or 0) for r in results) / n

    return {
        "num_questions": n,
        "overall_execution_accuracy": overall,
        "per_iteration_accuracy": per_iteration_accuracy,
        "avg_iterations": avg_iterations,
        "failed_requests": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_FILE)
    parser.add_argument("--agent-url", default=AGENT_URL_DEFAULT)
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.eval_set.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(questions)} eval questions from {args.eval_set}")

    results: list[dict] = []
    t0 = time.monotonic()

    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['db_id']}: {q['question'][:60]}...", flush=True)
        results.append(eval_one(q, args.agent_url))

    elapsed = time.monotonic() - t0
    summary = summarize(results)

    out = {
        "summary": summary,
        "wall_clock_seconds": elapsed,
        "results": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
