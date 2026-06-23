import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SOURCE_CANDIDATES = [
    Path("data/bird/dev_20240627/dev.json"),
    Path("data/bird/dev_20240627/dev.jsonl"),
    Path("data/bird/dev_20240627/dev/dev.json"),
    Path("data/bird/dev_20240627/dev/dev.jsonl"),
    Path("load_test/perf_pool.jsonl"),
]

OUT = Path("evals/eval_smart.jsonl")
REPORT = Path("evals/eval_smart_explanations.json")
TARGET_SIZE = 30

CATEGORY_RULES = {
    "count": ["how many", "number of", "count"],
    "aggregation": ["average", "avg", "sum", "total", "percentage", "percent", "difference"],
    "ranking": ["highest", "lowest", "most", "least", "fastest", "top", "greater", "higher"],
    "date_time": ["date", "time", "pm", "am", "/", "year", "month"],
    "boolean_majority": ["mostly", "whether", "are they", "or not"],
    "list_attribute": ["which", "who", "mention", "list", "what is", "indicate"], 
}

def load_source():
    for path in SOURCE_CANDIDATES:
        if not path.exists():
            continue

        print(f"Using source: {path}")

        if path.suffix == ".jsonl":
            rows = []
            for line in path.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
            return rows

        obj = json.loads(path.read_text())
        if isinstance(obj, list):
            return obj

        if isinstance(obj, dict):
            for key in ["data", "questions", "examples"]:
                if key in obj and isinstance(obj[key], list):
                    return obj[key]

    print("Could not find any source file.")
    print("Available files:")
    for p in Path("data/bird").rglob("*"):
        if p.is_file():
            print(p)
    raise SystemExit(1)

def normalize_item(x):
    db_id = (
        x.get("db_id")
        or x.get("db")
        or x.get("database_id")
    )

    question = (
        x.get("question")
        or x.get("query")
        or x.get("utterance")
    )

    gold_sql = (
        x.get("SQL")
        or x.get("sql")
        or x.get("gold_sql")
        or x.get("query_sql")
    )

    if not db_id or not question:
        return None

    item = {
        "db_id": db_id,
        "question": question,
    }

    if gold_sql:
        item["gold_sql"] = gold_sql

    return item

def categorize(question, sql=""):
    q = question.lower()
    s = (sql or "").lower()
    cats = []

    for cat, needles in CATEGORY_RULES.items():
        if any(n in q for n in needles):
            cats.append(cat)

    if " join " in s or " inner join " in s:
        cats.append("join")
    if "group by" in s:
        cats.append("group_by")
    if "order by" in s or "limit" in s:
        cats.append("order_limit")
    if "case when" in s or "iif(" in s:
        cats.append("case")
    if re.search(r"\d{4}-\d{2}-\d{2}", s) or " like " in s:
        cats.append("date_or_like")

    if not cats:
        cats.append("basic")

    return sorted(set(cats))

def complexity_score(item):
    q = item["question"].lower()
    sql = item.get("gold_sql", "").lower()

    score = 0
    score += 2 * sql.count(" join ")
    score += 2 if "group by" in sql else 0
    score += 2 if "order by" in sql else 0
    score += 1 if "limit" in sql else 0
    score += 2 if "case when" in sql or "iif(" in sql else 0
    score += 2 if "select max" in sql or "select min" in sql else 0
    score += 1 if any(x in q for x in ["percentage", "difference", "average", "mostly", "fastest"]) else 0
    score += 1 if any(x in q for x in ["which", "who", "mention", "indicate"]) else 0
    return score

def main():
    raw = load_source()

    items = []
    for x in raw:
        item = normalize_item(x)
        if item is None:
            continue
        item["categories"] = categorize(item["question"], item.get("gold_sql", ""))
        item["complexity"] = complexity_score(item)
        items.append(item)

    print(f"Loaded usable questions: {len(items)}")

    if not items:
        raise SystemExit("No usable questions found. Need to inspect source JSON keys.")

    by_db = defaultdict(list)
    for item in items:
        by_db[item["db_id"]].append(item)

    for db_id in by_db:
        by_db[db_id].sort(key=lambda z: z["complexity"], reverse=True)

    selected = []
    explanations = []
    category_counts = Counter()

    dbs = sorted(by_db.keys())
    pointer = 0

    while len(selected) < TARGET_SIZE and any(by_db.values()):
        db_id = dbs[pointer % len(dbs)]
        pointer += 1

        if not by_db[db_id]:
            continue

        candidate = None

        for idx, item in enumerate(by_db[db_id]):
            if all(category_counts[c] < 8 for c in item["categories"]):
                candidate = by_db[db_id].pop(idx)
                break

        if candidate is None:
            candidate = by_db[db_id].pop(0)

        selected.append(candidate)
        for c in candidate["categories"]:
            category_counts[c] += 1

        explanations.append({
            "db_id": candidate["db_id"],
            "question": candidate["question"],
            "gold_sql": candidate.get("gold_sql"),
            "categories": candidate["categories"],
            "complexity": candidate["complexity"],
            "why_selected": (
                "Selected for balanced coverage across databases and SQL skills: "
                + ", ".join(candidate["categories"])
            ),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)

    with OUT.open("w") as f:
        for item in selected:
            row = {
                "db_id": item["db_id"],
                "question": item["question"],
            }
            if "gold_sql" in item:
                row["gold_sql"] = item["gold_sql"]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    REPORT.write_text(json.dumps({
        "num_selected": len(selected),
        "category_counts": dict(category_counts),
        "selection_strategy": [
            "Read BIRD dev questions from data/bird/dev_20240627/dev.json when available",
            "Fallback to load_test/perf_pool.jsonl",
            "Round-robin across DBs for domain coverage",
            "Prefer higher-complexity SQL",
            "Balance categories such as count, aggregation, ranking, joins, dates, CASE, and list questions",
        ],
        "items": explanations,
    }, indent=2, ensure_ascii=False))

    print(f"Wrote {OUT}")
    print(f"Wrote {REPORT}")

if __name__ == "__main__":
    main()
