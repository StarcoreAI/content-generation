import os

from .storage import load_json, save_json, update_json


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

    daily_record = {
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
    }

    def append_daily(day_data):
        if not isinstance(day_data, dict):
            day_data = {}
        day_data.setdefault("date", today)
        day_data.setdefault("client_id", client_id)
        day_data.setdefault("brand", brand)
        records = day_data.get("records")
        if not isinstance(records, list):
            records = []
        records.append(daily_record)
        day_data["records"] = records
        return day_data, None

    update_json(day_file, {"date": today, "client_id": client_id, "brand": brand, "records": []}, append_daily)
    return day_file


def load_client_records(raw_records_path, client_id, date=None, group_id=None,
                        platform=None, task_id=None):
    if platform == "all":
        platform = None
    if task_id == "all":
        task_id = None
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
    if task_id:
        records = [r for r in records if r.get("task_id") == task_id]
    return records


def save_raw_record(raw_records_path, settings_path, default_data_dir, client_id, group_id,
                    brand, question, round_num, answer, search_keywords, refs, analysis,
                    uid_fn, today_fn, now_fn, source_platform="doubao",
                    task_id="", run_id="", task_report="", crawler_engine=""):
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
    if task_id:
        record["task_id"] = task_id
    if run_id:
        record["run_id"] = run_id
    if task_report:
        record["task_report"] = task_report
    if crawler_engine:
        record["crawler_engine"] = crawler_engine

    def append_record(records):
        if not isinstance(records, list):
            records = []
        records.append(record)
        return records, record_id

    update_json(raw_records_path, [], append_record)
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


def delete_entity_mentions(raw_records_path, client_id, date, entity_name,
                           platform=None, group_id=None, task_id=None):
    if platform == "all":
        platform = None
    if task_id == "all":
        task_id = None
    entity_name = (entity_name or "").strip()
    if not client_id or not entity_name:
        return {"removed": 0, "records_changed": 0}

    records = load_json(raw_records_path, [])
    removed = 0
    records_changed = 0

    def in_scope(r):
        if r.get("client_id") != client_id:
            return False
        if date and r.get("today") != date:
            return False
        if group_id and r.get("group_id") != group_id:
            return False
        if platform and r.get("source_platform", "doubao") != platform:
            return False
        if task_id and r.get("task_id") != task_id:
            return False
        return True

    for record in records:
        if not in_scope(record):
            continue
        entities = record.get("mentioned_entities")
        if not isinstance(entities, list):
            continue
        kept = []
        removed_here = 0
        for entity in entities:
            name = ""
            if isinstance(entity, dict):
                name = str(entity.get("name", "")).strip()
            if name == entity_name:
                removed += 1
                removed_here += 1
            else:
                kept.append(entity)
        if removed_here:
            record["mentioned_entities"] = kept
            records_changed += 1

    if removed:
        save_json(raw_records_path, records)
    return {"removed": removed, "records_changed": records_changed}


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
