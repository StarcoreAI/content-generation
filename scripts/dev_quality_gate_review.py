# -*- coding: utf-8 -*-
"""Manually re-run LLM quality reviews for already-approved articles."""
import argparse
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.storage import save_json


def _review_article(client_id, article_id):
    import app as geo_app
    return geo_app.review_content_generation_article(client_id, article_id)


def _list_articles(client_id):
    import app as geo_app
    return geo_app.load_content_session(client_id).get("articles") or []


def run_quality_gate_review(client_id, limit=5, list_fn=None, review_fn=None, output_dir=None):
    list_fn = list_fn or _list_articles
    review_fn = review_fn or _review_article
    articles = [
        article for article in list_fn(client_id)
        if (article.get("gate_report") or {}).get("verdict") == "pass"
    ][:max(1, int(limit or 1))]
    results, failures = [], []
    for article in articles:
        try:
            reviewed = review_fn(client_id, article.get("id"))
            results.append({
                "id": article.get("id"),
                "title": article.get("title"),
                "verdict": (reviewed.get("gate_report") or {}).get("verdict", ""),
            })
        except Exception as exc:
            failures.append({"id": article.get("id"), "error": str(exc)})
    output_dir = Path(output_dir or ROOT / "data" / "briefs" / client_id / datetime.now().strftime("%Y-%m-%d"))
    output_path = output_dir / "quality_gate_review.json"
    if not save_json(output_path, {"client_id": client_id, "reviewed": results, "failures": failures}):
        raise RuntimeError("quality_gate_review_output_save_failed")
    return {"reviewed": len(results), "failed": len(failures), "output_path": str(output_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Re-run LLM quality gate checks for stored pass articles.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    result = run_quality_gate_review(args.client_id, limit=args.limit)
    print(f"[GEO] reviewed={result['reviewed']} failed={result['failed']}")
    print(f"[GEO] output: {result['output_path']}")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
