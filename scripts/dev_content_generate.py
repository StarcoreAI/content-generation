# -*- coding: utf-8 -*-
import argparse
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.storage import load_json, save_json


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _parse_angles(value):
    if not value:
        return None
    return [angle.strip() for angle in value.split(",") if angle.strip()]


def _execute_content_generation(payload, audience_angles=None):
    import app as geo_app
    return geo_app.run_content_generation(payload, audience_angles=audience_angles)


def _print_gate_summary(article):
    report = article.get("gate_report") or {}
    print(f"[GEO] gate verdict: {report.get('verdict', '')}")
    for check in (report.get("code_layer") or []) + (report.get("llm_layer") or []):
        print(f"[GEO] gate {check.get('check_id', '')}: passed={check.get('passed')} evidence={check.get('evidence') or []}")
    print(f"[GEO] gate llm_layer_status: {report.get('llm_layer_status', '')}")


def run_content_generate(client_id, parent_type, count=1, date=None, data_dir=None, angles=None,
                         include_injection=True, include_web_supplement=True, include_content_uploads=True,
                         include_competitors=True, execute_fn=None):
    date = date or _today()
    data_dir = Path(data_dir or ROOT / "data")
    execute_fn = execute_fn or _execute_content_generation
    payload = {
        "client_id": client_id,
        "article_type": parent_type,
        "use_material_package": bool(include_injection),
        "use_material_web_supplement": bool(include_web_supplement),
        "use_content_uploads": bool(include_content_uploads),
        "use_competitors": bool(include_competitors),
    }
    items, failures = [], []
    for index in range(max(1, int(count or 1))):
        try:
            result = execute_fn(dict(payload), audience_angles=angles)
            sampling = result.get("sampling") or {}
            article = dict(result)
            article.pop("sampling", None)
            items.append({
                "sampling": sampling,
                "brief": article.get("brief"),
                "article": article,
            })
            print(f"[GEO] generated article id: {article.get('id', '')}")
            _print_gate_summary(article)
        except Exception as exc:
            failure = {"index": index + 1, "error": str(exc)}
            failures.append(failure)
            print(f"[GEO] generation failed #{index + 1}: {failure['error']}", file=sys.stderr)

    output_path = data_dir / "briefs" / client_id / date / "generated_articles.json"
    previous = load_json(output_path, {})
    previous_items = previous.get("items", []) if isinstance(previous, dict) else []
    previous_failures = previous.get("failures", []) if isinstance(previous, dict) else []
    export = {
        "client_id": client_id,
        "date": date,
        "parent_type": parent_type,
        "angles_override": angles,
        "items": list(previous_items) + items,
        "failures": list(previous_failures) + failures,
    }
    if not save_json(output_path, export):
        raise RuntimeError("generated_articles_output_save_failed")
    return {
        "generated": len(items),
        "failed": len(failures),
        "output_path": str(output_path),
    }


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the persisted content-generation pipeline for manual review.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--parent-type", required=True, choices=["对比型", "介绍型"])
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--angles", default="", help="Comma-separated audience angles; omit to use saved client angles.")
    parser.add_argument("--no-injection", action="store_true")
    parser.add_argument("--no-web-supplement", action="store_true")
    parser.add_argument("--no-content-uploads", action="store_true")
    parser.add_argument("--no-competitors", action="store_true")
    args = parser.parse_args(argv)
    result = run_content_generate(
        client_id=args.client_id,
        parent_type=args.parent_type,
        count=args.count,
        angles=_parse_angles(args.angles),
        include_injection=not args.no_injection,
        include_web_supplement=not args.no_web_supplement,
        include_content_uploads=not args.no_content_uploads,
        include_competitors=not args.no_competitors,
    )
    print(f"[GEO] generated={result['generated']} failed={result['failed']}")
    print(f"[GEO] output: {result['output_path']}")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
