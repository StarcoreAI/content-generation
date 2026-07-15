import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_entities import clean_json_text, get_openai_client, read_json, write_json
from services.material_filter import KEPT_STATUSES
from services.material_package_extractor import extract_material_package
from services.material_reducer import reduce_material_units


def parse_reducer_response(raw):
    try:
        payload = json.loads(clean_json_text(raw))
    except json.JSONDecodeError as exc:
        preview = str(raw or "").strip().replace("\n", " ")[:200]
        raise ValueError(f"invalid JSON response: {exc.msg}; raw={preview!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError("reducer response must be a JSON object")
    return payload


def choose_material_reducer_model(settings):
    return (
        settings.get("material_reducer_model")
        or settings.get("material_filter_model")
        or settings.get("model")
        or settings.get("extraction_model")
        or "deepseek-chat"
    )


def make_ask_json(settings, model=None):
    client = get_openai_client(settings)
    model = model or choose_material_reducer_model(settings)

    def ask_json(prompt, max_tokens):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        raw = response.choices[0].message.content
        return parse_reducer_response(raw)

    return ask_json


def kept_unit_ids(filter_report):
    ids = []
    for item in filter_report.get("results", []):
        unit_id = str(item.get("unit_id") or "").strip()
        if unit_id and item.get("status") in KEPT_STATUSES:
            ids.append(unit_id)
    return ids


def select_units_by_id(units, unit_ids):
    by_id = {str(unit.get("unit_id") or "").strip(): unit for unit in units}
    missing = [unit_id for unit_id in unit_ids if unit_id not in by_id]
    if missing:
        raise ValueError("kept units missing from extracted package: " + ", ".join(missing))
    return [by_id[unit_id] for unit_id in unit_ids]


def reduce_units_for_report(units, ask_json, max_tokens=8192):
    try:
        return reduce_material_units(units, ask_json=ask_json, max_tokens=max_tokens), []
    except Exception as exc:
        return [], [{"unit_id": "__package__", "path": "", "error": str(exc)}]


def default_output_path(package_path):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = "".join(ch if ch.isalnum() else "-" for ch in Path(package_path).name).strip("-")
    return Path("reports") / f"material_reducer_{safe_name}_{timestamp}.json"


def build_report(filter_report_path, filter_report, units, model, results, errors=None):
    errors = errors or []
    return {
        "source_filter_report": str(filter_report_path),
        "package_path": str(filter_report.get("package_path") or ""),
        "input_count": len(units),
        "reduced_count": len([item for item in results if str(item.get("reduced_text") or "").strip()]),
        "model": model,
        "results": results,
        "errors": errors,
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run the customer material Reducer Worker.")
    parser.add_argument("filter_report", help="Material filter report JSON path")
    parser.add_argument("--settings", default="data/settings.json", help="Model settings JSON")
    parser.add_argument("--output", default="", help="Report JSON path")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max output tokens for the package reducer call")
    args = parser.parse_args()

    filter_report_path = Path(args.filter_report)
    filter_report = read_json(filter_report_path, {})
    package_path = filter_report.get("package_path")
    if not package_path:
        raise ValueError("filter report missing package_path")

    extracted = extract_material_package(package_path)
    units = select_units_by_id(extracted["units"], kept_unit_ids(filter_report))
    settings = read_json(args.settings, {})
    model = choose_material_reducer_model(settings)
    results, errors = reduce_units_for_report(units, make_ask_json(settings, model), max_tokens=args.max_tokens)

    output = Path(args.output) if args.output else default_output_path(package_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(filter_report_path, filter_report, units, model, results, errors)
    write_json(output, report)
    print(f"Wrote {output}")
    print(f"Input units: {len(units)}")
    print(f"Reduced units: {report['reduced_count']}")
    if errors:
        print(f"Reducer errors: {len(errors)}")


if __name__ == "__main__":
    main()
