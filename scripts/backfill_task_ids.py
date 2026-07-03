import argparse
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path


TIME_FMT = "%Y-%m-%d %H:%M"
COMPLETED_STATUSES = {"completed", "completed_with_errors"}


def parse_time(value):
    if not value:
        return None
    return datetime.strptime(str(value)[:16], TIME_FMT)


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_task_reports(tasks_dir, date=None, task_ids=None):
    tasks_dir = Path(tasks_dir)
    wanted_ids = set(task_ids or [])
    tasks = []
    for path in sorted(tasks_dir.glob("*.json")):
        try:
            report = read_json(path, {})
        except Exception:
            continue
        task_id = report.get("task_id") or path.stem.split("_")[-1]
        if wanted_ids and task_id not in wanted_ids:
            continue
        if date and not path.name.startswith(f"{date}_"):
            continue
        item = dict(report)
        item["task_id"] = task_id
        item["task_report"] = str(path)
        tasks.append(item)
    return tasks


def record_matches_task(record, task, tolerance_minutes=1):
    if record.get("task_id"):
        return False
    if record.get("client_id") != task.get("client_id"):
        return False
    if record.get("group_id", "") != task.get("group_id", ""):
        return False
    if record.get("source_platform", "doubao") != task.get("platform"):
        return False
    if record.get("question") not in set(task.get("questions") or []):
        return False

    started = parse_time(task.get("started_at"))
    finished = parse_time(task.get("finished_at"))
    crawl_time = parse_time(record.get("crawl_time"))
    if not started or not finished or not crawl_time:
        return False
    started = started - timedelta(minutes=tolerance_minutes)
    finished = finished + timedelta(minutes=tolerance_minutes)
    return started <= crawl_time <= finished


def plan_backfill_updates(records, tasks, tolerance_minutes=1, completed_only=True):
    eligible_tasks = []
    for task in tasks:
        if completed_only and task.get("status") not in COMPLETED_STATUSES:
            continue
        eligible_tasks.append(task)

    task_summaries = {
        task.get("task_id"): {
            "task_id": task.get("task_id"),
            "status": task.get("status"),
            "platform": task.get("platform"),
            "started_at": task.get("started_at"),
            "finished_at": task.get("finished_at"),
            "matched": 0,
            "expected_questions": len(task.get("questions") or []),
        }
        for task in eligible_tasks
    }
    updates = []
    conflicts = []
    skipped_existing = 0

    for record in records:
        if record.get("task_id"):
            skipped_existing += 1
            continue
        exact_matches = [
            task for task in eligible_tasks
            if record_matches_task(record, task, tolerance_minutes=0)
        ]
        matches = exact_matches or [
            task for task in eligible_tasks
            if record_matches_task(record, task, tolerance_minutes=tolerance_minutes)
        ]
        if len(matches) == 1:
            task = matches[0]
            task_id = task.get("task_id")
            task_summaries[task_id]["matched"] += 1
            updates.append({
                "record_id": record.get("id"),
                "task_id": task_id,
                "run_id": task.get("session_id") or task_id,
                "task_report": task.get("task_report", ""),
                "crawler_engine": task.get("crawler_engine", ""),
                "client_id": record.get("client_id"),
                "group_id": record.get("group_id"),
                "source_platform": record.get("source_platform"),
                "crawl_time": record.get("crawl_time"),
                "question": record.get("question"),
            })
        elif len(matches) > 1:
            conflicts.append({
                "record_id": record.get("id"),
                "candidate_task_ids": [task.get("task_id") for task in matches],
            })

    return {
        "updates": updates,
        "task_summaries": task_summaries,
        "conflicts": conflicts,
        "skipped_existing": skipped_existing,
        "eligible_task_count": len(eligible_tasks),
    }


def apply_updates(raw_records_path, records, updates):
    update_by_id = {item["record_id"]: item for item in updates}
    changed = 0
    for record in records:
        update = update_by_id.get(record.get("id"))
        if not update:
            continue
        record["task_id"] = update["task_id"]
        record["run_id"] = update["run_id"]
        record["task_report"] = update["task_report"]
        if update.get("crawler_engine"):
            record["crawler_engine"] = update["crawler_engine"]
        changed += 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{raw_records_path}.bak_{timestamp}"
    shutil.copy2(raw_records_path, backup_path)
    write_json(raw_records_path, records)
    return {"changed": changed, "backup_path": backup_path}


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Preview or apply task_id backfill for raw_records.json.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default="")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-failed", action="store_true")
    parser.add_argument("--tolerance-minutes", type=int, default=1)
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data_dir)
    raw_records_path = data_dir / "raw_records.json"
    records = read_json(raw_records_path, [])
    tasks = load_task_reports(data_dir / "tasks", date=args.date or None, task_ids=args.task_id)
    plan = plan_backfill_updates(
        records,
        tasks,
        tolerance_minutes=args.tolerance_minutes,
        completed_only=not args.include_failed,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if args.apply:
        result = apply_updates(str(raw_records_path), records, plan["updates"])
        print(json.dumps({"applied": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
