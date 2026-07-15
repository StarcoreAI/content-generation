import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_entities import clean_json_text, get_openai_client, read_json, write_json
from services.material_filter import DEFAULT_FILTER_RULES, KEPT_STATUSES, filter_material_units
from services.material_package_extractor import extract_material_package


def parse_filter_response(raw):
    try:
        payload = json.loads(clean_json_text(raw))
    except json.JSONDecodeError as exc:
        preview = str(raw or "").strip().replace("\n", " ")[:200]
        raise ValueError(f"invalid JSON response: {exc.msg}; raw={preview!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError("filter response must be a JSON object")
    return payload


def choose_material_filter_model(settings):
    return (
        settings.get("material_filter_model")
        or settings.get("model")
        or settings.get("extraction_model")
        or "deepseek-chat"
    )


def make_ask_json(settings):
    client = get_openai_client(settings)
    model = choose_material_filter_model(settings)

    def ask_json(prompt, max_tokens):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        raw = response.choices[0].message.content
        return parse_filter_response(raw)

    return ask_json


def readable_units(units, limit=0):
    selected = [unit for unit in units if str(unit.get("text") or "").strip()]
    if limit:
        return selected[:limit]
    return selected


def filter_units_for_report(units, ask_json, max_tokens=4096):
    try:
        return filter_material_units(units, ask_json=ask_json, max_tokens=max_tokens), []
    except Exception as exc:
        return [], [{"unit_id": "__package__", "path": "", "error": str(exc)}]


def default_output_path(package_path):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = "".join(ch if ch.isalnum() else "-" for ch in Path(package_path).name).strip("-")
    return Path("reports") / f"material_filter_{safe_name}_{timestamp}.json"


def build_report(package_path, manifest, units, results, errors=None):
    errors = errors or []
    kept_ids = {item["unit_id"] for item in results if item.get("status") in KEPT_STATUSES}
    return {
        "package_path": str(package_path),
        "rules": DEFAULT_FILTER_RULES,
        "unit_count": len(units),
        "filtered_count": len(results),
        "kept_count": len(kept_ids),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
        "kept_units": [
            {
                "unit_id": unit.get("unit_id"),
                "path": unit.get("path"),
                "kind": unit.get("kind"),
                "sheet_name": unit.get("sheet_name", ""),
                "sample": unit.get("sample", ""),
            }
            for unit in units
            if unit.get("unit_id") in kept_ids
        ],
        "manifest": manifest,
    }


def main():
    parser = argparse.ArgumentParser(description="Run the customer material Filter Worker.")
    parser.add_argument("package_path", help="Folder extracted from a customer material package")
    parser.add_argument("--settings", default="data/settings.json", help="Model settings JSON")
    parser.add_argument("--output", default="", help="Report JSON path")
    parser.add_argument("--limit", type=int, default=0, help="Only filter the first N readable units")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max output tokens for the package filter call")
    parser.add_argument("--dry-run", action="store_true", help="Extract units and write a report without model calls")
    args = parser.parse_args()

    extracted = extract_material_package(args.package_path)
    units = readable_units(extracted["units"], args.limit)
    results = []
    errors = []
    if not args.dry_run:
        settings = read_json(args.settings, {})
        results, errors = filter_units_for_report(units, make_ask_json(settings), max_tokens=args.max_tokens)

    output = Path(args.output) if args.output else default_output_path(args.package_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(args.package_path, extracted["manifest"], units, results, errors)
    write_json(output, report)
    print(f"Wrote {output}")
    print(f"Readable units: {len(units)}")
    if not args.dry_run:
        print(f"Kept units: {report['kept_count']}")
        if errors:
            print(f"Filter errors: {len(errors)}")


if __name__ == "__main__":
    main()
