import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.article_body_hits import check_article_body_hits
from services.record_insights import build_record_insights, merge_body_hit_results

RAW_RECORDS = ROOT / "data" / "raw_records.json"
BODY_HIT_STORE = ROOT / "data" / "competitor_article_body_hits.json"
REPORTS_DIR = ROOT / "reports"


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def scope_value(value):
    value = str(value or "").strip()
    return "" if value == "all" else value


def filter_records(records, client_id, date="", task_id="", group_id="", platform=""):
    result = [r for r in records if r.get("client_id") == client_id]
    if date:
        result = [r for r in result if r.get("today") == date]
    if task_id:
        result = [r for r in result if r.get("task_id") == task_id]
    if group_id:
        result = [r for r in result if r.get("group_id") == group_id]
    if platform and platform != "all":
        result = [r for r in result if r.get("source_platform", "doubao") == platform]
    return result


def build_body_hit_report(records, limit=20, timeout=10):
    insights = build_record_insights(records)
    selected_competitors = insights.get("selected_competitors", [])
    top_articles = insights.get("top_articles", [])[:limit]
    body_hits = check_article_body_hits(top_articles, selected_competitors, timeout=timeout)
    strict_articles = merge_body_hit_results(
        insights.get("competitor_articles", []),
        body_hits,
        selected_competitors,
    )
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_records": insights.get("total_records", 0),
        "selected_competitors": selected_competitors,
        "checked_article_count": len(top_articles),
        "matched_article_count": sum(1 for item in body_hits if item.get("status") == "matched"),
        "strict_competitor_articles": strict_articles,
        "body_hits": body_hits,
        "weak_competitor_articles": insights.get("weak_competitor_articles", []),
    }


def upsert_body_hit_report(store_path, report):
    scope_keys = ("client_id", "date", "task_id", "group_id", "platform")
    scope = {key: scope_value(report.get(key)) for key in scope_keys}
    records = load_json(store_path, [])
    kept = [
        item for item in records
        if not isinstance(item, dict)
        or {key: scope_value(item.get(key)) for key in scope_keys} != scope
    ]
    kept.append(report)
    save_json(store_path, kept)
    return len(kept)


def main():
    parser = argparse.ArgumentParser(description="Check whether high-frequency Top articles mention selected competitors in body text.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--date", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--group-id", default="")
    parser.add_argument("--platform", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--output", default="")
    parser.add_argument("--store", action="store_true", help="Persist this report for /api/daily/insights frontend display.")
    args = parser.parse_args()

    records = filter_records(
        load_json(RAW_RECORDS, []),
        client_id=args.client_id,
        date=args.date,
        task_id=args.task_id,
        group_id=args.group_id,
        platform=args.platform,
    )
    report = build_body_hit_report(records, limit=args.limit, timeout=args.timeout)
    report.update({
        "client_id": args.client_id,
        "date": scope_value(args.date),
        "task_id": scope_value(args.task_id),
        "group_id": scope_value(args.group_id),
        "platform": scope_value(args.platform),
    })
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path(args.output) if args.output else REPORTS_DIR / f"competitor_article_body_hits_{args.client_id}_{stamp}.json"
    save_json(output, report)
    if args.store:
        upsert_body_hit_report(BODY_HIT_STORE, report)

    print(f"records={report['total_records']}")
    print(f"selected_competitors={','.join(report['selected_competitors'])}")
    print(f"checked={report['checked_article_count']} matched={report['matched_article_count']}")
    print(f"report={output}")
    if args.store:
        print(f"stored={BODY_HIT_STORE}")


if __name__ == "__main__":
    main()
