import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import shutil


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def norm(value):
    return " ".join(str(value or "").split())


def normalized_refs(record):
    refs = record.get("refs") if isinstance(record.get("refs"), list) else []
    return [
        {
            "url": norm(ref.get("url") if isinstance(ref, dict) else ""),
            "title": norm(ref.get("title") if isinstance(ref, dict) else ""),
        }
        for ref in refs
    ]


def record_fingerprint(record):
    payload = {
        "client_id": norm(record.get("client_id")),
        "group_id": norm(record.get("group_id")),
        "today": norm(record.get("today")),
        "source_platform": norm(record.get("source_platform") or "doubao"),
        "question": norm(record.get("question")),
        "round": record.get("round") or 1,
        "answer": norm(record.get("answer")),
        "refs": normalized_refs(record),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def is_importable(record):
    return (
        isinstance(record, dict)
        and norm(record.get("client_id"))
        and norm(record.get("today"))
        and norm(record.get("question"))
        and norm(record.get("answer"))
    )


def matches_filters(record, client_id="", date="", platform=""):
    if client_id and record.get("client_id") != client_id:
        return False
    if date and record.get("today") != date:
        return False
    if platform and (record.get("source_platform") or "doubao") != platform:
        return False
    return True


def make_import_id(original_id, used_ids, index):
    base = norm(original_id) or "missing-id"
    candidate = f"{base}_imported_{index}"
    while candidate in used_ids:
        index += 1
        candidate = f"{base}_imported_{index}"
    return candidate


def plan_missing_records(source_records, target_records, client_id="", date="", platform=""):
    target_records = target_records if isinstance(target_records, list) else []
    source_records = source_records if isinstance(source_records, list) else []
    target_fingerprints = {
        record_fingerprint(record)
        for record in target_records
        if is_importable(record)
    }
    used_ids = {norm(record.get("id")) for record in target_records if isinstance(record, dict) and norm(record.get("id"))}

    append_records = []
    duplicate_count = 0
    invalid_count = 0
    id_collision_count = 0

    for source_index, record in enumerate(source_records, start=1):
        if not is_importable(record):
            invalid_count += 1
            continue
        if not matches_filters(record, client_id=client_id, date=date, platform=platform):
            continue
        fingerprint = record_fingerprint(record)
        if fingerprint in target_fingerprints:
            duplicate_count += 1
            continue

        item = deepcopy(record)
        record_id = norm(item.get("id"))
        if record_id and record_id in used_ids:
            item["import_source_id"] = record_id
            item["id"] = make_import_id(record_id, used_ids, source_index)
            id_collision_count += 1
        used_ids.add(norm(item.get("id")))
        target_fingerprints.add(fingerprint)
        append_records.append(item)

    return {
        "source_count": len(source_records),
        "target_count": len(target_records),
        "append_count": len(append_records),
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "id_collision_count": id_collision_count,
        "append_records": append_records,
    }


def summarize(records):
    return {
        "by_date": dict(Counter(record.get("today", "") for record in records)),
        "by_platform": dict(Counter(record.get("source_platform", "doubao") or "doubao" for record in records)),
        "by_client": dict(Counter(record.get("client_id", "") for record in records)),
    }


def import_missing_records(source_path, target_path, apply=False, client_id="", date="", platform=""):
    source_path = Path(source_path)
    target_path = Path(target_path)
    source_records = read_json(source_path, [])
    target_records = read_json(target_path, [])
    plan = plan_missing_records(
        source_records,
        target_records,
        client_id=client_id,
        date=date,
        platform=platform,
    )
    append_records = plan.pop("append_records")
    result = {
        **plan,
        **summarize(append_records),
        "applied": bool(apply),
        "backup_path": "",
        "source_path": str(source_path),
        "target_path": str(target_path),
    }
    if apply and append_records:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = target_path.with_name(f"{target_path.name}.bak_import_{timestamp}")
        if target_path.exists():
            shutil.copy2(target_path, backup_path)
        else:
            write_json(backup_path, [])
        write_json(target_path, target_records + append_records)
        result["backup_path"] = str(backup_path)
    return result


def main():
    parser = argparse.ArgumentParser(description="Append missing local raw_records into a cloud raw_records.json.")
    parser.add_argument("source", help="local/exported raw_records.json")
    parser.add_argument("--target", default="data/raw_records.json", help="target cloud raw_records.json")
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    parser.add_argument("--client-id", default="", help="optional client_id filter")
    parser.add_argument("--date", default="", help="optional today/date filter, for example 2026-07-09")
    parser.add_argument("--platform", default="", help="optional source_platform filter")
    args = parser.parse_args()

    result = import_missing_records(
        args.source,
        args.target,
        apply=args.apply,
        client_id=args.client_id,
        date=args.date,
        platform=args.platform,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
