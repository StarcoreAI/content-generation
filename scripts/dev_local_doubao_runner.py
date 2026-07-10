import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import records as record_store
from services.node_crawler_bridge import run_node_crawler
from services.storage import load_json


def default_data_dir():
    return ROOT / "data"


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _uid():
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _load_client(data_dir, client_id):
    clients = load_json(Path(data_dir) / "clients.json", [])
    for client in clients if isinstance(clients, list) else []:
        if str(client.get("id") or "") == client_id:
            return client
    raise ValueError(f"client not found: {client_id}")


def _load_group(data_dir, client_id, group_id):
    groups = load_json(Path(data_dir) / "probe_groups.json", {})
    for group in groups.get(client_id, []) if isinstance(groups, dict) else []:
        if str(group.get("id") or "") == group_id:
            return group
    raise ValueError(f"group not found: {group_id}")


def _basic_analysis(brand, answer, refs):
    brand = str(brand or "")
    answer = str(answer or "")
    brand_mentioned = bool(brand and brand in answer)
    main_ref = refs[0] if refs else {}
    return {
        "brand_mentioned": brand_mentioned,
        "brand_rank": None,
        "brand_sentiment": "neutral",
        "brand_snippet": brand if brand_mentioned else "",
        "main_ref": {
            "title": main_ref.get("title", ""),
            "platform": main_ref.get("platform", ""),
            "match_score": 100 if main_ref else 0,
            "match_reason": "local dev basic analysis",
        },
        "geo_score": 100 if brand_mentioned else 0,
        "analysis_status": "local_dev_basic",
        "analysis_mode": "basic_no_api_key",
    }


def _prefer_local_playwright_cache():
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return
    browser_cache = Path(local_app_data) / "ms-playwright"
    if browser_cache.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)


def _expand_questions(questions, repeat_count):
    repeat_count = max(1, min(int(repeat_count or 1), 10))
    expanded = []
    for question in questions:
        question = str(question or "").strip()
        if question:
            expanded.extend([question] * repeat_count)
    return expanded


def run_local_doubao_group(
    client_id,
    group_id,
    data_dir=None,
    repeat_count=1,
    run_crawler=run_node_crawler,
    uid_fn=_uid,
    today_fn=_today_str,
    now_fn=_now_str,
):
    data_dir = Path(data_dir or default_data_dir())
    client = _load_client(data_dir, client_id)
    group = _load_group(data_dir, client_id, group_id)
    brand = str(client.get("brand") or client.get("name") or "").strip()
    questions = _expand_questions(group.get("questions") or [], repeat_count)
    if not questions:
        raise ValueError(f"group has no questions: {group_id}")

    _prefer_local_playwright_cache()
    run_id = f"local-dev-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    output_dir = ROOT / "logs" / "local-dev" / run_id / "doubao"
    crawl_result = run_crawler("doubao", questions, output_dir=output_dir)

    raw_records_path = data_dir / "raw_records.json"
    settings_path = data_dir / "settings.json"
    round_by_question = defaultdict(int)
    saved = 0
    errors = []

    for item in crawl_result.get("results") or []:
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        if item.get("error") or not item.get("ok"):
            errors.append({"question": question, "error": item.get("error") or "crawl_failed"})
            continue
        refs = item.get("refs") or []
        answer = item.get("answer") or ""
        round_by_question[question] += 1
        analysis = _basic_analysis(brand, answer, refs)
        record_store.save_raw_record(
            raw_records_path,
            settings_path,
            data_dir,
            client_id,
            group_id,
            brand,
            question,
            round_by_question[question],
            answer,
            [],
            refs,
            analysis,
            uid_fn,
            today_fn,
            now_fn,
            source_platform="doubao",
            run_id=run_id,
            crawler_engine="local_dev_node",
        )
        saved += 1

    return {
        "ok": saved > 0 and not errors,
        "client_id": client_id,
        "group_id": group_id,
        "brand": brand,
        "platform": "doubao",
        "total": len(crawl_result.get("results") or []),
        "saved": saved,
        "errors": errors,
        "run_id": run_id,
        "output_dir": str(output_dir),
    }


def _choose_from_list(items, label_fn, title):
    print(title)
    for index, item in enumerate(items, 1):
        print(f"{index}. {label_fn(item)}")
    selected = input("Select number: ").strip()
    try:
        index = int(selected) - 1
    except ValueError as exc:
        raise ValueError("invalid selection") from exc
    if index < 0 or index >= len(items):
        raise ValueError("selection out of range")
    return items[index]


def choose_client_and_group(data_dir):
    data_dir = Path(data_dir)
    clients = load_json(data_dir / "clients.json", [])
    clients = clients if isinstance(clients, list) else []
    client = _choose_from_list(
        clients,
        lambda item: f"{item.get('name') or item.get('brand') or item.get('id')} ({item.get('id')})",
        "Local clients:",
    )
    groups = load_json(data_dir / "probe_groups.json", {})
    client_groups = groups.get(client.get("id"), []) if isinstance(groups, dict) else []
    group = _choose_from_list(
        client_groups,
        lambda item: f"{item.get('name') or item.get('id')} ({len(item.get('questions') or [])} questions)",
        "Probe groups:",
    )
    return client.get("id"), group.get("id")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a local Doubao crawl for a local client probe group.")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--group-id", default="")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    args = parser.parse_args(argv)

    client_id = args.client_id
    group_id = args.group_id
    if not client_id or not group_id:
        client_id, group_id = choose_client_and_group(args.data_dir)

    result = run_local_doubao_group(
        client_id=client_id,
        group_id=group_id,
        data_dir=args.data_dir,
        repeat_count=args.repeat,
    )
    print(f"[GEO] local doubao crawl saved={result['saved']} total={result['total']}")
    print(f"[GEO] output: {result['output_dir']}")
    if result["errors"]:
        print(f"[GEO] errors: {len(result['errors'])}")
    return 0 if result["saved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
