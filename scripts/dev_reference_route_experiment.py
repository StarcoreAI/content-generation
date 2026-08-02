import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.reference_route_analysis import analyze_reference_route_article


def run_route_experiment(bundle, output_dir, ai_json_fn=None):
    if ai_json_fn is None:
        import app as geo_app
        ai_json_fn = geo_app.ai_json
    bundle = _validate_bundle(bundle)
    analyses = [
        analyze_reference_route_article(bundle, article, ai_json_fn)
        for article in bundle["articles"]
    ]
    output = {
        "schema_version": 1,
        "query": bundle["query"],
        "final_entities": bundle.get("final_entities") or [],
        "total_articles": len(analyses),
        "total_eligible": sum(
            1 for analysis in analyses
            if analysis["library_decision"]["eligible"]
        ),
        "articles": analyses,
    }
    output_path = Path(output_dir) / "route_analysis.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "total_articles": output["total_articles"],
        "total_eligible": output["total_eligible"],
        "output_path": str(output_path),
    }


def _validate_bundle(bundle):
    if not isinstance(bundle, dict):
        raise ValueError("bundle_must_be_object")
    query = str(bundle.get("query") or "").strip()
    if not query:
        raise ValueError("query_required")
    articles = bundle.get("articles")
    if not isinstance(articles, list) or not articles:
        raise ValueError("articles_required")
    normalized_articles = [_validate_article(article, index) for index, article in enumerate(articles)]
    final_entities = bundle.get("final_entities")
    if final_entities is not None and not isinstance(final_entities, list):
        raise ValueError("final_entities_must_be_list")
    return {
        "query": query,
        "final_entities": [str(item).strip() for item in final_entities or [] if str(item).strip()],
        "articles": normalized_articles,
    }


def _validate_article(article, index):
    if not isinstance(article, dict):
        raise ValueError(f"article_{index}_must_be_object")
    url = str(article.get("url") or "").strip()
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError(f"article_{index}_url_invalid")
    title = str(article.get("title") or "").strip()
    if not title:
        raise ValueError(f"article_{index}_title_required")
    content = str(article.get("content") or "").strip()
    if not content:
        raise ValueError(f"article_{index}_content_required")
    support_points = article.get("support_points")
    if support_points is not None and not isinstance(support_points, list):
        raise ValueError(f"article_{index}_support_points_must_be_list")
    return {
        "url": url,
        "title": title,
        "content": content,
        "support_points": [str(item).strip() for item in support_points or [] if str(item).strip()],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run manual reference route analysis without fetching URLs.")
    parser.add_argument("--input", required=True, help="Manual JSON bundle path")
    parser.add_argument("--output-dir", required=True, help="Directory for route_analysis.json")
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    bundle = json.loads(input_path.read_text(encoding="utf-8"))
    result = run_route_experiment(bundle, args.output_dir)
    print(
        f"[GEO] articles={result['total_articles']} eligible={result['total_eligible']}"
    )
    print(f"[GEO] output: {result['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
