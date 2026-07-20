import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as geo_app
from services.reference_stage0 import analyze_stage0_groups
from services.storage import load_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def run_stage0_filter(
    client_id,
    client_brand,
    date=None,
    data_dir=None,
    ai_json_fn=geo_app.ai_json,
    limit=0,
):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    stage_dir = data_dir / "reference_intelligence" / client_id / date
    input_path = stage_dir / "fetched_articles.json"
    fetched = load_json(input_path, {})
    articles = fetched.get("articles") or []
    if limit and limit > 0:
        articles = articles[:limit]
    output = analyze_stage0_groups(
        articles,
        client_brand=client_brand,
        ai_json_fn=ai_json_fn,
        stage_dir=stage_dir,
        client_id=client_id,
        date=date,
    )
    output_path = stage_dir / "stage0_filter_groups.json"
    return {
        "input": len(articles),
        "groups": output["total_groups"],
        "excluded": output["total_excluded"],
        "errors": sum(1 for item in output["groups"] if item["llm_error"]),
        "output_path": str(output_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run reference intelligence stage 0 on fetched article bodies.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-brand", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    result = run_stage0_filter(
        client_id=args.client_id,
        client_brand=args.client_brand,
        date=args.date,
        data_dir=args.data_dir,
        limit=args.limit,
    )
    print(
        f"[GEO] stage0 groups={result['groups']} excluded={result['excluded']} "
        f"llm_errors={result['errors']} input={result['input']}"
    )
    print(f"[GEO] output: {result['output_path']}")
    return 0 if result["groups"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
