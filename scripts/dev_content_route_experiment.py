import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.content_route_experiment import run_content_route_experiment


def run_manual_content_route_experiment(bundle, customer_master_text, output_dir, writer_ai_fn):
    experiment_bundle = dict(bundle or {})
    experiment_bundle["customer_master_text"] = str(customer_master_text or "")
    result = run_content_route_experiment(experiment_bundle, writer_ai_fn)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "draft.md").write_text(result["draft"], encoding="utf-8")
    trace = {
        "schema_version": 1,
        "query": experiment_bundle.get("task", {}).get("query", ""),
        "route_name": experiment_bundle.get("selected_route", {}).get("name", ""),
        "customer_master_characters": len(experiment_bundle["customer_master_text"]),
        "title_entity_policy": experiment_bundle.get("task", {}).get("title_entity_policy", ""),
        "output_files": ["draft.md", "experiment_trace.json"],
    }
    (output_dir / "experiment_trace.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "customer_master_characters": trace["customer_master_characters"],
        "output_dir": str(output_dir),
        "draft_path": str(output_dir / "draft.md"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a manual introduction content-route experiment.")
    parser.add_argument("--input", required=True, help="Article task and selected route JSON path")
    parser.add_argument("--customer-master-file", required=True, help="Full operator-maintained customer master Markdown path")
    parser.add_argument("--output-dir", required=True, help="Directory for experimental outputs")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    customer_master_text = Path(args.customer_master_file).read_text(encoding="utf-8")
    import app as geo_app
    result = run_manual_content_route_experiment(
        bundle,
        customer_master_text,
        args.output_dir,
        geo_app.ai,
    )
    print(f"[GEO] customer_master_characters={result['customer_master_characters']}")
    print(f"[GEO] draft: {result['draft_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
