import json
import os

from .storage import load_json, save_json


def get_raw_data_dir(settings_path, default_data_dir):
    settings = load_json(settings_path, {})
    custom = settings.get("raw_data_path", "").strip()
    if custom and os.path.isdir(custom):
        return custom
    default = os.path.join(default_data_dir, "raw")
    os.makedirs(default, exist_ok=True)
    return default


def save_daily_raw(settings_path, default_data_dir, client_id, brand, question, answer,
                   refs, analysis, uid_fn, today_fn, now_fn):
    raw_dir = get_raw_data_dir(settings_path, default_data_dir)
    today = today_fn()
    client_dir = os.path.join(raw_dir, client_id)
    os.makedirs(client_dir, exist_ok=True)
    day_file = os.path.join(client_dir, f"{today}.json")
    if os.path.exists(day_file):
        with open(day_file, "r", encoding="utf-8") as f:
            day_data = json.load(f)
    else:
        day_data = {"date": today, "client_id": client_id, "brand": brand, "records": []}

    day_data["records"].append({
        "id": uid_fn(),
        "time": now_fn(),
        "question": question,
        "answer": answer,
        "refs": refs,
        "analysis": analysis,
        "ref_count": len(refs),
        "brand_mentioned": (
            brand in (answer or "") or
            (brand[:2] if len(brand) >= 2 else brand) in (answer or "")
        ),
        "geo_score": analysis.get("geo_score", 0),
        "main_platform": analysis.get("main_ref", {}).get("platform", ""),
    })
    with open(day_file, "w", encoding="utf-8") as f:
        json.dump(day_data, f, ensure_ascii=False, indent=2)
    return day_file


def load_client_records(raw_records_path, client_id, date=None, group_id=None, platform=None):
    if platform == "all":
        platform = None
    if not client_id:
        return []
    records = load_json(raw_records_path, [])
    records = [r for r in records if r.get("client_id") == client_id]
    if date:
        records = [r for r in records if r.get("today") == date]
    if group_id:
        records = [r for r in records if r.get("group_id") == group_id]
    if platform:
        records = [r for r in records if r.get("source_platform", "doubao") == platform]
    return records


def save_raw_record(raw_records_path, settings_path, default_data_dir, client_id, group_id,
                    brand, question, round_num, answer, search_keywords, refs, analysis,
                    uid_fn, today_fn, now_fn, source_platform="doubao"):
    records = load_json(raw_records_path, [])
    record_id = uid_fn()
    brand_mentioned = bool(analysis.get("brand_mentioned"))
    record = {
        "id": record_id,
        "client_id": client_id,
        "group_id": group_id,
        "brand": brand,
        "question": question,
        "round": round_num,
        "crawl_time": now_fn(),
        "today": today_fn(),
        "source_platform": source_platform,
        "answer": answer,
        "search_keywords": search_keywords,
        "refs": [
            {
                "position": i + 1,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "platform": r.get("platform", ""),
            }
            for i, r in enumerate(refs)
        ],
        "ref_count": len(refs),
        "analysis": analysis,
        "brand_mentioned": brand_mentioned,
        "geo_score": analysis.get("geo_score", 0),
        "main_platform": analysis.get("main_ref", {}).get("platform", ""),
    }
    records.append(record)
    save_json(raw_records_path, records)
    save_daily_raw(
        settings_path,
        default_data_dir,
        client_id,
        brand,
        question,
        answer,
        refs,
        analysis,
        uid_fn,
        today_fn,
        now_fn,
    )
    return record_id


def delete_raw_record(raw_records_path, record_id):
    records = load_json(raw_records_path, [])
    before = len(records)
    records = [r for r in records if r.get("id") != record_id]
    save_json(raw_records_path, records)
    return before - len(records)


def delete_raw_records(raw_records_path, record_ids):
    ids = set(record_ids or [])
    records = load_json(raw_records_path, [])
    before = len(records)
    records = [r for r in records if r.get("id") not in ids]
    save_json(raw_records_path, records)
    return before - len(records)


def clear_client_day_records(raw_records_path, client_id, date, source_platform=""):
    if source_platform == "all":
        source_platform = ""
    records = load_json(raw_records_path, [])
    before = len(records)

    def should_delete(r):
        if r.get("client_id") != client_id or r.get("today") != date:
            return False
        if source_platform and r.get("source_platform", "doubao") != source_platform:
            return False
        return True

    records = [r for r in records if not should_delete(r)]
    save_json(raw_records_path, records)
    return before - len(records)
