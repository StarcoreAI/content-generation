import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as geo_app
from services.reference_stage1 import analyze_stage1_article
from services.storage import load_json, save_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _usable_article(article, min_content_chars):
    if not article.get("ok"):
        return False
    content = str(article.get("content") or "")
    return len(content) >= min_content_chars


def run_stage1_article_structure(
    client_id,
    date=None,
    data_dir=None,
    ai_json_fn=geo_app.ai_json,
    min_content_chars=200,
    limit=0,
):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    input_path = data_dir / "reference_intelligence" / client_id / date / "fetched_articles.json"
    fetched = load_json(input_path, {})
    articles = fetched.get("articles") or []
    if limit and limit > 0:
        articles = articles[:limit]

    analyses = []
    skipped = 0
    errors = []
    for article in articles:
        if not _usable_article(article, min_content_chars):
            skipped += 1
            continue
        try:
            result = analyze_stage1_article(article, ai_json_fn)
        except Exception as exc:
            errors.append({"url": article.get("url") or "", "error": str(exc)})
            continue
        analyses.append({
            "url": article.get("url") or "",
            "source_title": article.get("source_title") or "",
            "title": article.get("title") or article.get("source_title") or "",
            "citation_count": int(article.get("citation_count") or 0),
            "parent_type": result["parent_type"],
            "opening": result["opening"],
            "body": result["body"],
            "ending": result["ending"],
        })

    output = {
        "client_id": client_id,
        "date": date,
        "source_path": str(input_path),
        "total_input": len(articles),
        "total_analyzed": len(analyses),
        "total_skipped": skipped,
        "total_errors": len(errors),
        "analyses": analyses,
        "errors": errors,
    }
    output_path = data_dir / "reference_intelligence" / client_id / date / "stage1_article_structures.json"
    save_json(output_path, output)
    return {
        "input": len(articles),
        "analyzed": len(analyses),
        "skipped": skipped,
        "errors": len(errors),
        "output_path": str(output_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run reference intelligence stage 1 on fetched article bodies.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    result = run_stage1_article_structure(
        client_id=args.client_id,
        date=args.date,
        data_dir=args.data_dir,
        limit=args.limit,
    )
    print(f"[GEO] stage1 analyzed={result['analyzed']} skipped={result['skipped']} errors={result['errors']} input={result['input']}")
    print(f"[GEO] output: {result['output_path']}")
    return 0 if result["analyzed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
