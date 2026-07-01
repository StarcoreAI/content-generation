import json
import os


def get_crawl_task_dir(data_dir):
    task_dir = os.path.join(data_dir, "tasks")
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def save_crawl_task_report(data_dir, report, uid_fn, today_fn, now_fn):
    task_id = report.get("task_id") or uid_fn()
    report["task_id"] = task_id
    report["updated_at"] = now_fn()
    path = os.path.join(get_crawl_task_dir(data_dir), f"{today_fn()}_{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


def compact_crawl_failure(raw, meta):
    raw = raw or {}
    meta = meta or {}
    answer = raw.get("answer") or ""
    return {
        "question": meta.get("question") or raw.get("question", ""),
        "round": meta.get("round"),
        "error": raw.get("error") or "未获得有效结果",
        "answer_length": raw.get("answer_length", len(answer)),
        "answer_tail": raw.get("answer_tail") or answer[-120:],
        "url": raw.get("url", ""),
        "page_hint": raw.get("page_hint", ""),
    }
