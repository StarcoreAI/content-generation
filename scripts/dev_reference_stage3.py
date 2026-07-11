import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as geo_app
from services import reference_intelligence as reference_intel
from services.reference_stage3 import analyze_stage3_plugins
from services.storage import load_json, save_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def save_live_reference_plugins(data_dir, client_id, date, plugins, task_id=""):
    root_dir = Path(data_dir) / "reference_intelligence"
    reference_intel.save_reference_intelligence(
        root_dir,
        save_json,
        _today,
        lambda: datetime.now().strftime("%Y-%m-%d %H:%M"),
        {
            "client_id": client_id,
            "date": date,
            "task_id": task_id,
            "clusters": [],
            "plugins": plugins,
            "source_articles": [],
        },
    )
    return Path(reference_intel.reference_intelligence_path(root_dir, client_id, date, _today, task_id))


def _article_sources(data_dir, client_id, date):
    stage1_path = data_dir / "reference_intelligence" / client_id / date / "stage1_article_structures.json"
    stage1 = load_json(stage1_path, {})
    if stage1.get("analyses"):
        return reference_intel.source_articles_from_stage1_analyses(stage1.get("analyses") or [])

    path = data_dir / "reference_intelligence" / client_id / date / "fetched_articles.json"
    fetched = load_json(path, {})
    return reference_intel.source_articles_from_stage1_analyses(fetched.get("articles") or [])


def run_stage3_prompt_plugins(
    client_id,
    date=None,
    data_dir=None,
    ai_json_fn=geo_app.ai_json,
    publish=False,
):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    input_path = data_dir / "reference_intelligence" / client_id / date / "stage2_structure_clusters.json"
    stage2 = load_json(input_path, {})
    clusters = stage2.get("clusters") or []
    result = analyze_stage3_plugins(clusters, ai_json_fn)
    plugins = reference_intel.attach_source_articles_to_plugins(
        result["plugins"], _article_sources(data_dir, client_id, date)
    )
    output = {
        "client_id": client_id,
        "date": date,
        "source_path": str(input_path),
        "total_clusters": len(clusters),
        "total_plugins": len(plugins),
        "plugins": plugins,
    }
    output_path = data_dir / "reference_intelligence" / client_id / date / "stage3_prompt_plugins.json"
    save_json(output_path, output)
    result = {
        "clusters": len(clusters),
        "plugins": len(plugins),
        "output_path": str(output_path),
    }
    if publish:
        live_output_path = save_live_reference_plugins(data_dir, client_id, date, plugins)
        result["live_output_path"] = str(live_output_path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run reference intelligence stage 3 prompt plugin generation.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--publish", action="store_true", help="Also write the formal reference intelligence JSON.")
    args = parser.parse_args(argv)

    result = run_stage3_prompt_plugins(
        client_id=args.client_id,
        date=args.date,
        data_dir=args.data_dir,
        publish=args.publish,
    )
    print(f"[GEO] stage3 plugins={result['plugins']} clusters={result['clusters']}")
    print(f"[GEO] output: {result['output_path']}")
    if result.get("live_output_path"):
        print(f"[GEO] live output: {result['live_output_path']}")
    return 0 if result["plugins"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
