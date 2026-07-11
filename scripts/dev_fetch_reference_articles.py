import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.article_fetcher import fetch_article_text
from services.reference_intelligence import collect_reference_articles, merge_reference_fetch_result
from services.storage import load_json, save_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def run_fetch_reference_articles(
    client_id,
    date=None,
    data_dir=None,
    limit=0,
    fetch_fn=fetch_article_text,
    timeout=25,
    max_chars=12000,
):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    daily_path = data_dir / "raw" / client_id / f"{date}.json"
    daily = load_json(daily_path, {})
    refs = collect_reference_articles(daily.get("records") or [], limit=limit if limit and limit > 0 else 0)

    articles = []
    for ref in refs:
        fetched = fetch_fn(
            ref["url"],
            timeout=timeout,
            max_chars=max_chars,
            browser_fallback=True,
        )
        articles.append(merge_reference_fetch_result(ref, fetched))

    output = {
        "client_id": client_id,
        "date": date,
        "source_path": str(daily_path),
        "total": len(articles),
        "fetched_ok": sum(1 for item in articles if item["ok"]),
        "fetched_failed": sum(1 for item in articles if not item["ok"]),
        "articles": articles,
    }
    output_path = data_dir / "reference_intelligence" / client_id / date / "fetched_articles.json"
    save_json(output_path, output)
    return {**{key: output[key] for key in ("total", "fetched_ok", "fetched_failed")}, "output_path": str(output_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch local referenced article bodies for one client/day.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    result = run_fetch_reference_articles(
        client_id=args.client_id,
        date=args.date,
        data_dir=args.data_dir,
        limit=args.limit,
    )
    print(f"[GEO] fetched articles ok={result['fetched_ok']} failed={result['fetched_failed']} total={result['total']}")
    print(f"[GEO] output: {result['output_path']}")
    return 0 if result["fetched_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
