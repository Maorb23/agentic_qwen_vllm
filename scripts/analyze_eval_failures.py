from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def get_first_existing(d: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return default


def classify_failure(row: dict[str, Any]) -> str:
    question = str(get_first_existing(row, ["question"], "")).lower()
    pred_sql = str(get_first_existing(row, ["predicted_sql", "prediction", "sql", "answer"], "")).lower()
    gold_sql = str(get_first_existing(row, ["gold_sql", "gold", "reference_sql"], "")).lower()
    error = str(get_first_existing(row, ["error"], "")).lower()

    if error:
        return "sql_execution_error"

    if "join" in gold_sql and "join" not in pred_sql:
        return "missing_join"

    if "group by" in gold_sql and "group by" not in pred_sql:
        return "missing_group_by"

    if "order by" in gold_sql and "order by" not in pred_sql:
        return "missing_order_by"

    if "limit" in gold_sql and "limit" not in pred_sql:
        return "missing_limit"

    if "count(" in gold_sql and "count(" not in pred_sql:
        return "wrong_count_or_result_shape"

    if "avg(" in gold_sql and "avg(" not in pred_sql:
        return "wrong_average"

    if "sum(" in gold_sql and "sum(" not in pred_sql:
        return "wrong_sum"

    if "where" in gold_sql and "where" not in pred_sql:
        return "missing_filter"

    if "distinct" in gold_sql and "distinct" not in pred_sql:
        return "missing_distinct"

    if "which" in question or "what" in question or "list" in question or "name" in question:
        if "count(" in pred_sql:
            return "returned_count_instead_of_entity"

    return "other_logic_mismatch"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = json.load(open(args.input))
    results = data.get("results", [])

    failures = []
    for row in results:
        if not row.get("correct", False):
            row = dict(row)
            row["failure_type_auto"] = classify_failure(row)
            failures.append(row)

    counts = Counter(r["failure_type_auto"] for r in failures)

    report = {
        "summary": data.get("summary", {}),
        "num_results": len(results),
        "num_failures": len(failures),
        "failure_type_counts": dict(counts.most_common()),
        "failures": failures,
    }

    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(json.dumps({
        "num_results": len(results),
        "num_failures": len(failures),
        "failure_type_counts": dict(counts.most_common()),
    }, indent=2))


if __name__ == "__main__":
    main()
