import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as geo_app
from services.pattern_library import PatternLibrary
from services.reference_ingest import ingest_anatomy_cards
from services.storage import load_json, save_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def run_reference_ingest(client_id, industry, date=None, data_dir=None, ai_json_fn=geo_app.ai_json):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    stage_dir = data_dir / "reference_intelligence" / client_id / date
    stage1 = load_json(stage_dir / "stage1_anatomy_cards.json", {})
    stage0 = load_json(stage_dir / "stage0_filter_groups.json", {})
    groups_by_id = {
        str(group.get("group_id") or "").strip(): group
        for group in stage0.get("groups") or []
        if isinstance(group, dict) and str(group.get("group_id") or "").strip()
    }
    scope = f"industry:{str(industry or '').strip()}"
    library = PatternLibrary(data_dir / "pattern_library")
    report = ingest_anatomy_cards(
        stage1.get("cards") or [],
        library=library,
        scope=scope,
        groups_by_id=groups_by_id,
        ai_json_fn=ai_json_fn,
    )
    output = {
        "client_id": client_id,
        "date": date,
        **report,
    }
    output_path = stage_dir / "stage2_ingest_report.json"
    save_json(output_path, output)
    return {
        "cards": report["total_cards"],
        "items": report["total_items"],
        "llm_calls": report["llm_calls"],
        "errors": len(report["errors"]),
        "output_path": str(output_path),
        "library_path": str(data_dir / "pattern_library"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest stage-1 anatomy cards into the pattern library.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--industry", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    args = parser.parse_args(argv)
    result = run_reference_ingest(
        client_id=args.client_id,
        industry=args.industry,
        date=args.date,
        data_dir=args.data_dir,
    )
    print(
        f"[GEO] stage2 cards={result['cards']} items={result['items']} "
        f"llm_calls={result['llm_calls']} errors={result['errors']}"
    )
    print(f"[GEO] report: {result['output_path']}")
    print(f"[GEO] library: {result['library_path']}")
    return 0 if result["cards"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
