"""Run a no-write query-scene experiment from a trusted server shell."""
import argparse
import json
from pathlib import Path


def run_experiment(client_id, groups, records, service, ask_json, date_str=""):
    source_date = str(date_str or "").strip()
    if not source_date:
        source_date = max((str(record.get("today") or "").strip() for record in records), default="")
    selected_records = [
        record for record in records
        if not source_date or str(record.get("today") or "").strip() == source_date
    ]
    result = service.refresh_query_scenes(
        client_id, groups, selected_records, ask_json, dry_run=True,
    )
    return {"client_id": client_id, "source_date": source_date, **result}


def main():
    parser = argparse.ArgumentParser(description="试运行问题组场景词提取，不写入缓存")
    parser.add_argument("--client-id", required=True, help="客户 ID")
    parser.add_argument("--date", default="", help="可选，指定采集日期；默认最近实际采集日")
    parser.add_argument("--output", default="", help="可选，将 JSON 结果保存到此文件")
    args = parser.parse_args()

    import app as geo_app

    client_id = args.client_id.strip()
    if not any(client.get("id") == client_id for client in geo_app.load(geo_app.F_CLIENTS, [])):
        raise SystemExit(f"client_not_found: {client_id}")
    result = run_experiment(
        client_id,
        geo_app.load(geo_app.F_GROUPS, {}).get(client_id, []),
        geo_app.load_client_records(client_id),
        geo_app.selection_evidence_service(),
        geo_app.ai_json,
        args.date,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"已写入：{path}")
    else:
        print(text)
    if result.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
