from pathlib import Path

from services.material_filter import DEFAULT_FILTER_RULES, KEPT_STATUSES, filter_material_units
from services.material_output import build_material_output
from services.material_package_extractor import extract_material_package
from services.material_reducer import reduce_material_units
from services.storage import load_json, save_json


def _readable_units(units):
    return [unit for unit in units if str(unit.get("text") or "").strip()]


def _filter_report(package_dir, manifest, units, results):
    kept_ids = {item["unit_id"] for item in results if item.get("status") in KEPT_STATUSES}
    return {
        "package_path": str(package_dir),
        "rules": DEFAULT_FILTER_RULES,
        "unit_count": len(units),
        "filtered_count": len(results),
        "kept_count": len(kept_ids),
        "error_count": 0,
        "results": results,
        "errors": [],
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


def _select_kept_units(units, filter_results):
    kept_ids = [item["unit_id"] for item in filter_results if item.get("status") in KEPT_STATUSES]
    by_id = {str(unit.get("unit_id") or "").strip(): unit for unit in units}
    return [by_id[unit_id] for unit_id in kept_ids if unit_id in by_id]


def _reducer_report(package_dir, filter_path, units, results, model=""):
    return {
        "source_filter_report": str(filter_path),
        "package_path": str(package_dir),
        "input_count": len(units),
        "reduced_count": len([item for item in results if str(item.get("reduced_text") or "").strip()]),
        "model": model,
        "results": results,
        "errors": [],
    }


def _latest_paths(output_dir):
    output_dir = Path(output_dir)
    return {
        "filter": output_dir / "latest_filter.json",
        "reducer": output_dir / "latest_reducer.json",
        "markdown": output_dir / "latest_injection.md",
        "status": output_dir / "latest_status.json",
    }


def run_material_package_pipeline(
    package_dir,
    output_dir,
    ask_filter_json,
    ask_reducer_json,
    ask_output_text,
    models=None,
):
    package_dir = Path(package_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = _latest_paths(output_dir)
    models = models or {}

    status = {"ok": False, "status": "running", "package_path": str(package_dir)}
    save_json(paths["status"], status)

    extracted = extract_material_package(package_dir)
    units = _readable_units(extracted["units"])

    filter_results = filter_material_units(units, ask_json=ask_filter_json)
    filter_report = _filter_report(package_dir, extracted["manifest"], units, filter_results)
    save_json(paths["filter"], filter_report)

    kept_units = _select_kept_units(units, filter_results)
    reducer_results = reduce_material_units(kept_units, ask_json=ask_reducer_json) if kept_units else []
    reducer_report = _reducer_report(
        package_dir,
        paths["filter"],
        kept_units,
        reducer_results,
        model=models.get("reducer", ""),
    )
    save_json(paths["reducer"], reducer_report)

    markdown = build_material_output(reducer_report, ask_text=ask_output_text)
    paths["markdown"].write_text(markdown, encoding="utf-8")

    status = {
        "ok": True,
        "status": "completed",
        "package_path": str(package_dir),
        "filter": {
            "readable_units": len(units),
            "kept_units": filter_report["kept_count"],
            "errors": 0,
        },
        "reducer": {
            "input_units": len(kept_units),
            "reduced_units": reducer_report["reduced_count"],
            "errors": 0,
        },
        "output": {
            "markdown_chars": len(markdown),
            "errors": 0,
        },
        "outputs": {key: str(path) for key, path in paths.items()},
    }
    save_json(paths["status"], status)
    return status


def load_latest_material_package_result(output_dir):
    paths = _latest_paths(output_dir)
    status = load_json(paths["status"], {"ok": False, "status": "missing"})
    markdown = ""
    if paths["markdown"].exists():
        markdown = paths["markdown"].read_text(encoding="utf-8", errors="ignore")
    return {"ok": bool(markdown), "status": status, "markdown": markdown}
