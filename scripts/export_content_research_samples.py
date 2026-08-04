# -*- coding: utf-8 -*-
"""Export selected clients' content-research evidence for offline review."""
import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTORS = ("崔红蕾", "古齐装饰")
RESEARCH_DIRECTORIES = (
    "material_packages",
    "competitor_material_packages",
    "selection_surface_reports",
    "selection_evidence",
    "reference_intelligence",
)
KNOWLEDGE_FILES = ("customer_master.md", "competitor_master.md")


def _load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return fallback


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _matched_clients(clients, selectors):
    matched, missing = [], []
    for selector in selectors:
        selector = str(selector or "").strip()
        found = [item for item in clients if selector in {
            str(item.get("id") or "").strip(),
            str(item.get("name") or "").strip(),
            str(item.get("brand") or "").strip(),
        }]
        if not found:
            missing.append(selector)
        elif len(found) > 1:
            raise ValueError("ambiguous_client_selector: " + selector)
        elif found[0] not in matched:
            matched.append(found[0])
    if missing:
        raise ValueError("missing_client_selectors: " + "、".join(missing))
    return matched


def _copy_client_tree(data_dir, output_dir, directory, client_id):
    source = data_dir / directory / client_id
    if not source.is_dir():
        return False
    shutil.copytree(source, output_dir / directory / client_id)
    return True


def _copy_knowledge_masters(data_dir, output_dir, client_id):
    source_dir = data_dir / "knowledge_base" / client_id
    target_dir = output_dir / "knowledge_base" / client_id
    copied = False
    for filename in KNOWLEDGE_FILES:
        source = source_dir / filename
        if not source.is_file():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_dir / filename)
        copied = True
    return copied


def export_citation_research_data(data_dir, output_dir, selectors, days=3):
    """Export only selected clients' latest crawl records and question groups."""
    if not isinstance(days, int) or days < 1:
        raise ValueError("invalid_days")
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    clients = _load_json(data_dir / "clients.json", [])
    if not isinstance(clients, list):
        raise ValueError("invalid_clients_json")
    selected_clients = _matched_clients(clients, selectors)
    if output_dir.exists():
        raise ValueError(f"output_dir_already_exists: {output_dir}")

    records = _load_json(data_dir / "raw_records.json", [])
    records = records if isinstance(records, list) else []
    groups = _load_json(data_dir / "probe_groups.json", {})
    groups = groups if isinstance(groups, dict) else {}
    selected_ids = [str(client.get("id") or "").strip() for client in selected_clients]
    crawl_dates = {}
    for client_id in selected_ids:
        dates = sorted({
            str(record.get("today") or "").strip()
            for record in records
            if record.get("client_id") == client_id and str(record.get("today") or "").strip()
        })
        crawl_dates[client_id] = dates[-days:]

    output_dir.mkdir(parents=True)
    _write_json(output_dir / "probe_groups.json", {
        client_id: groups.get(client_id, []) for client_id in selected_ids
    })
    for client_id, dates in crawl_dates.items():
        for date in dates:
            date_records = [
                record for record in records
                if record.get("client_id") == client_id and record.get("today") == date
            ]
            target = output_dir / "crawl_records" / date / client_id / "raw_records.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_json(
                target,
                date_records,
            )
    summary = {
        "client_ids": selected_ids,
        "crawl_dates": crawl_dates,
        "output_dir": str(output_dir.resolve()),
    }
    _write_json(output_dir / "manifest.json", summary)
    return summary


def export_content_research_samples(data_dir, output_dir, selectors=DEFAULT_SELECTORS):
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    clients = _load_json(data_dir / "clients.json", [])
    if not isinstance(clients, list):
        raise ValueError("invalid_clients_json")
    selected_clients = _matched_clients(clients, selectors)
    if output_dir.exists():
        raise ValueError(f"output_dir_already_exists: {output_dir}")

    groups = _load_json(data_dir / "probe_groups.json", {})
    groups = groups if isinstance(groups, dict) else {}
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "clients.json", selected_clients)
    _write_json(output_dir / "probe_groups.json", {
        str(client.get("id") or ""): groups.get(str(client.get("id") or ""), [])
        for client in selected_clients
    })

    copied = {}
    for client in selected_clients:
        client_id = str(client.get("id") or "").strip()
        copied[client_id] = {
            directory: _copy_client_tree(data_dir, output_dir, directory, client_id)
            for directory in RESEARCH_DIRECTORIES
        }
        copied[client_id]["knowledge_masters"] = _copy_knowledge_masters(
            data_dir, output_dir, client_id,
        )
    summary = {
        "client_ids": [str(client.get("id") or "") for client in selected_clients],
        "output_dir": str(output_dir.resolve()),
        "copied": copied,
    }
    _write_json(output_dir / "manifest.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export selected clients' content-research evidence.")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--output-dir", required=True, help="A new cloud-side directory to create.")
    parser.add_argument("--client", action="append", dest="selectors", help="Exact client ID, name, or brand; repeatable.")
    parser.add_argument("--citation-research", action="store_true", help="Export only recent crawl records and question groups.")
    parser.add_argument("--days", type=int, default=3, help="Recent actual crawl dates per client in citation-research mode.")
    args = parser.parse_args(argv)
    selectors = args.selectors or list(DEFAULT_SELECTORS)
    try:
        if args.citation_research:
            summary = export_citation_research_data(
                args.data_dir, args.output_dir, selectors, days=args.days,
            )
        else:
            summary = export_content_research_samples(args.data_dir, args.output_dir, selectors)
    except ValueError as exc:
        parser.error(str(exc))
    print("[GEO] 已导出客户：" + "、".join(summary["client_ids"]))
    print("[GEO] 云端导出目录：" + summary["output_dir"])
    print("[GEO] 下载模板：scp -r <云端账号>@<云端主机>:" + summary["output_dir"] + " <本地目录>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
