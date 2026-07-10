from copy import deepcopy

from services.storage import load_json, update_json


SENSITIVE_KEYS = {
    "cookie",
    "cookies",
    "storage_state",
    "state",
    "password",
    "token",
    "authorization",
    "session",
}


def sanitize_worker_payload(value):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                continue
            clean[key] = sanitize_worker_payload(item)
        return clean
    if isinstance(value, list):
        return [sanitize_worker_payload(item) for item in value]
    return value


def load_jobs(path):
    jobs = load_json(path, [])
    return jobs if isinstance(jobs, list) else []


def create_job(path, payload, uid_fn, now_fn, created_by=""):
    job_type = payload.get("job_type") if payload.get("job_type") in {"crawl", "login"} else "crawl"
    job = {
        "id": uid_fn(),
        "job_type": job_type,
        "status": "pending",
        "client_id": payload.get("client_id", ""),
        "brand": payload.get("brand", ""),
        "group_id": payload.get("group_id", ""),
        "platform": payload.get("platform", ""),
        "questions": list(payload.get("questions") or []),
        "repeat_count": int(payload.get("repeat_count") or 1),
        "created_by": created_by,
        "created_at": now_fn(),
        "updated_at": now_fn(),
        "assigned_to": "",
    }

    def append_job(jobs):
        jobs = jobs if isinstance(jobs, list) else []
        return jobs + [deepcopy(job)], deepcopy(job)

    return update_json(path, [], append_job)


def claim_next_job(path, worker_id, platform, now_fn):
    worker_id = (worker_id or "local-worker").strip() or "local-worker"
    platform = (platform or "").strip()
    claimed = None

    def claim(jobs):
        nonlocal claimed
        jobs = jobs if isinstance(jobs, list) else []
        updated = []
        for job in jobs:
            item = dict(job)
            if claimed is None and item.get("status") == "pending":
                if not platform or item.get("platform") == platform:
                    item["status"] = "running"
                    item["assigned_to"] = worker_id
                    item["claimed_at"] = now_fn()
                    item["updated_at"] = now_fn()
                    claimed = deepcopy(item)
            updated.append(item)
        return updated, deepcopy(claimed)

    return update_json(path, [], claim)


def finish_job(path, job_id, payload, now_fn):
    payload = payload or {}
    status = payload.get("status") if payload.get("status") in {"completed", "failed"} else "completed"
    result_summary = payload.get("summary") or {
        "total": len(payload.get("results") or []),
        "success": len([item for item in payload.get("results") or [] if item.get("ok", True)]),
    }
    result_payload = sanitize_worker_payload({
        "status": status,
        "summary": result_summary,
        "results": payload.get("results") or [],
        "error": payload.get("error", ""),
        "logs": payload.get("logs") or [],
    })
    finished = None

    def update_job(jobs):
        nonlocal finished
        jobs = jobs if isinstance(jobs, list) else []
        updated = []
        for job in jobs:
            item = dict(job)
            if item.get("id") == job_id:
                if item.get("status") == "canceled":
                    item["updated_at"] = now_fn()
                    item["ignored_result_summary"] = sanitize_worker_payload(result_summary)
                    item["ignored_result_payload"] = result_payload
                    finished = deepcopy(item)
                    updated.append(item)
                    continue
                item["status"] = status
                item["finished_at"] = now_fn()
                item["updated_at"] = now_fn()
                item["result_summary"] = sanitize_worker_payload(result_summary)
                item["result_payload"] = result_payload
                finished = deepcopy(item)
            updated.append(item)
        return updated, deepcopy(finished)

    return update_json(path, [], update_job)


def record_persist_result(path, job_id, persist_result, now_fn):
    saved = int((persist_result or {}).get("saved") or 0)
    errors = int((persist_result or {}).get("errors") or 0)
    persisted = None

    def update_job(jobs):
        nonlocal persisted
        jobs = jobs if isinstance(jobs, list) else []
        updated = []
        for job in jobs:
            item = dict(job)
            if item.get("id") == job_id:
                item["persist_result"] = sanitize_worker_payload(persist_result or {})
                item["persisted_records"] = saved
                item["persisted_errors"] = errors
                item["updated_at"] = now_fn()
                persisted = deepcopy(item)
            updated.append(item)
        return updated, deepcopy(persisted)

    return update_json(path, [], update_job)


def cancel_job(path, job_id, now_fn):
    canceled = None

    def update_job(jobs):
        nonlocal canceled
        jobs = jobs if isinstance(jobs, list) else []
        updated = []
        for job in jobs:
            item = dict(job)
            if item.get("id") == job_id:
                item["status"] = "canceled"
                item["canceled_at"] = now_fn()
                item["updated_at"] = now_fn()
                canceled = deepcopy(item)
            updated.append(item)
        return updated, deepcopy(canceled)

    return update_json(path, [], update_job)
