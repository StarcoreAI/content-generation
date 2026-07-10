import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as geo_app
from services.reference_stage2 import analyze_stage2_clusters
from services.storage import load_json, save_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def run_stage2_cluster_structures(
    client_id,
    date=None,
    data_dir=None,
    ai_json_fn=geo_app.ai_json,
):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    input_path = data_dir / "reference_intelligence" / client_id / date / "stage1_article_structures.json"
    stage1 = load_json(input_path, {})
    analyses = stage1.get("analyses") or []
    result = analyze_stage2_clusters(analyses, ai_json_fn)
    output = {
        "client_id": client_id,
        "date": date,
        "source_path": str(input_path),
        "total_input": len(analyses),
        "total_clusters": len(result["clusters"]),
        "clusters": result["clusters"],
    }
    output_path = data_dir / "reference_intelligence" / client_id / date / "stage2_structure_clusters.json"
    save_json(output_path, output)
    return {
        "input": len(analyses),
        "clusters": len(result["clusters"]),
        "output_path": str(output_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run reference intelligence stage 2 structure clustering.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    args = parser.parse_args(argv)

    result = run_stage2_cluster_structures(
        client_id=args.client_id,
        date=args.date,
        data_dir=args.data_dir,
    )
    print(f"[GEO] stage2 clusters={result['clusters']} input={result['input']}")
    print(f"[GEO] output: {result['output_path']}")
    return 0 if result["clusters"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
