from copy import deepcopy
from datetime import datetime, timedelta

from services.storage import load_json, update_json


PENDING_CRAWL_JOB_TTL_MINUTES = 2

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


def _parse_time(value):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_time(value):
    return value.strftime("%Y-%m-%d %H:%M")


def pending_expires_at(created_at):
    parsed = _parse_time(created_at)
    if not parsed:
        return ""
    return _format_time(parsed + timedelta(minutes=PENDING_CRAWL_JOB_TTL_MINUTES))


def is_pending_crawl_job_expired(job, now_value):
    if (job or {}).get("job_type", "crawl") != "crawl":
        return False
    if (job or {}).get("status") != "pending":
        return False
    now_dt = _parse_time(now_value)
    if not now_dt:
        return False
    expires_dt = _parse_time((job or {}).get("expires_at")) or _parse_time(
        pending_expires_at((job or {}).get("created_at"))
    )
    return bool(expires_dt and now_dt >= expires_dt)


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


def filter_jobs_by_owner(jobs, created_by=None):
    if created_by is None:
        return list(jobs or [])
    return [
        job for job in jobs or []
        if str((job or {}).get("created_by") or "") == str(created_by or "")
    ]


def create_job(path, payload, uid_fn, now_fn, created_by=""):
    job_type = payload.get("job_type") if payload.get("job_type") in {"crawl", "login"} else "crawl"
    created_at = now_fn()
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
        "batch_id": payload.get("batch_id", ""),
        "created_by": created_by,
        "created_at": created_at,
        "updated_at": created_at,
        "assigned_to": "",
    }
    if job_type == "crawl":
        job["expires_at"] = pending_expires_at(created_at)

    def append_job(jobs):
        jobs = jobs if isinstance(jobs, list) else []
        return jobs + [deepcopy(job)], deepcopy(job)

    return update_json(path, [], append_job)


def claim_next_job(path, worker_id, platform, now_fn, created_by=None):
    worker_id = (worker_id or "local-worker").strip() or "local-worker"
    platform = (platform or "").strip()
    claimed = None
    now_value = now_fn()

    def claim(jobs):
        nonlocal claimed
        jobs = jobs if isinstance(jobs, list) else []
        updated = []
        for job in jobs:
            item = dict(job)
            owner_ok = created_by is None or str(item.get("created_by") or "") == str(created_by or "")
            if owner_ok and is_pending_crawl_job_expired(item, now_value):
                item["status"] = "expired"
                item["expired_at"] = now_value
                item["updated_at"] = now_value
            if claimed is None and item.get("status") == "pending":
                if owner_ok and (not platform or item.get("platform") == platform):
                    item["status"] = "running"
                    item["assigned_to"] = worker_id
                    item["claimed_at"] = now_value
                    item["updated_at"] = now_value
                    claimed = deepcopy(item)
            updated.append(item)
        return updated, deepcopy(claimed)

    return update_json(path, [], claim)


def finish_job(path, job_id, payload, now_fn, created_by=None):
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
                if created_by is not None and str(item.get("created_by") or "") != str(created_by or ""):
                    updated.append(item)
                    continue
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
                if status == "completed":
                    try:
                        final_total = max(0, int(result_summary.get("total") or 0))
                    except (TypeError, ValueError):
                        final_total = len(payload.get("results") or [])
                    item["progress_completed"] = final_total
                    item["progress_total"] = final_total
                finished = deepcopy(item)
            updated.append(item)
        return updated, deepcopy(finished)

    return update_json(path, [], update_job)


def update_job_progress(path, job_id, payload, now_fn, created_by=None):
    payload = payload or {}
    try:
        completed = max(0, int(payload.get("completed") or 0))
    except (TypeError, ValueError):
        completed = 0
    try:
        total = max(0, int(payload.get("total") or 0))
    except (TypeError, ValueError):
        total = 0
    if total:
        completed = min(completed, total)
    message = str(payload.get("message") or "").strip()[:200]
    updated_job = None

    def update(jobs):
        nonlocal updated_job
        jobs = jobs if isinstance(jobs, list) else []
        result = []
        for job in jobs:
            item = dict(job)
            if item.get("id") == job_id:
                if created_by is not None and str(item.get("created_by") or "") != str(created_by or ""):
                    result.append(item)
                    continue
                if item.get("status") != "running":
                    updated_job = deepcopy(item)
                    result.append(item)
                    continue
                now_value = now_fn()
                item["progress_completed"] = completed
                item["progress_total"] = total
                item["progress_message"] = message
                item["heartbeat_at"] = now_value
                item["updated_at"] = now_value
                updated_job = deepcopy(item)
            result.append(item)
        return result, deepcopy(updated_job)

    return update_json(path, [], update)


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


def persist_local_crawl_job_results(
    job,
    *,
    load_records_fn,
    save_crawl_task_report_fn,
    compact_crawl_failure_fn,
    basic_brand_analysis_fn,
    calibrate_analysis_fn,
    save_raw_record_fn,
    now_fn,
):
    if not job or job.get("status") != "completed":
        return {"ok": True, "skipped": True, "reason": "job_not_completed", "saved": 0}
    if job.get("job_type", "crawl") != "crawl":
        return {"ok": True, "skipped": True, "reason": "login_job", "saved": 0, "errors": 0}

    job_id = job.get("id", "")
    existing = load_records_fn()
    if any(item.get("task_id") == job_id for item in existing if isinstance(item, dict)):
        return {"ok": True, "skipped": True, "reason": "already_persisted", "saved": 0}

    payload = job.get("result_payload") or {}
    results = payload.get("results") or []
    if not results:
        return {"ok": True, "skipped": True, "reason": "no_results", "saved": 0}

    client_id = job.get("client_id", "")
    group_id = job.get("group_id", "")
    brand = job.get("brand", "")
    platform = job.get("platform", "")
    crawler_engine = payload.get("crawler_engine") or "local_worker_node"
    task_report = {
        "task_id": job_id,
        "status": "completed",
        "client_id": client_id,
        "brand": brand,
        "group_id": group_id,
        "source_platform": platform,
        "crawler_engine": crawler_engine,
        "started_at": job.get("claimed_at") or job.get("created_at") or "",
        "finished_at": job.get("finished_at") or now_fn(),
        "worker_id": job.get("assigned_to", ""),
        "questions": job.get("questions") or [],
        "repeat_count": job.get("repeat_count") or 1,
        "analysis_mode": "basic_no_api_key",
    }
    task_report_path = save_crawl_task_report_fn(task_report)
    round_by_question = {}
    saved = []
    failures = []

    for raw in results:
        if not isinstance(raw, dict):
            failures.append({"error": "invalid_result"})
            continue
        question = str(raw.get("question") or "").strip()
        answer = str(raw.get("answer") or "")
        refs = raw.get("refs") if isinstance(raw.get("refs"), list) else []
        if raw.get("error") or raw.get("ok") is False or not question or not answer:
            failures.append(compact_crawl_failure_fn(raw, {"question": question}))
            continue

        round_by_question[question] = round_by_question.get(question, 0) + 1
        analysis = basic_brand_analysis_fn(
            brand,
            question,
            answer,
            refs,
            analysis_status="local_worker_basic",
            analysis_mode="local_worker_basic",
            summary="本地 worker 已回传爬取结果，云端已保存原始回答和引用源，深度分析可后续异步补充。",
            suggestion="优先检查品牌是否被提及、引用源是否有效；竞品实体可等待异步分析补全。",
        )
        analysis = calibrate_analysis_fn(brand, question, answer, refs, analysis)
        save_raw_record_fn(
            client_id=client_id,
            group_id=group_id,
            brand=brand,
            question=question,
            round_num=round_by_question[question],
            answer=answer,
            search_keywords=[],
            refs=refs,
            analysis=analysis,
            source_platform=platform,
            task_id=job_id,
            run_id=job.get("assigned_to", ""),
            task_report=task_report_path,
            crawler_engine=crawler_engine,
        )
        saved.append({
            "question": question,
            "round": round_by_question[question],
            "brand_mentioned": analysis.get("brand_mentioned"),
            "geo_score": analysis.get("geo_score"),
            "ref_count": len(refs),
        })

    task_report.update({
        "saved": len(saved),
        "errors": len(failures),
        "success": saved,
        "failures": failures,
    })
    save_crawl_task_report_fn(task_report)
    return {
        "ok": True,
        "skipped": False,
        "saved": len(saved),
        "errors": len(failures),
        "task_report": task_report_path,
    }


def cancel_job(path, job_id, now_fn, created_by=None):
    canceled = None

    def update_job(jobs):
        nonlocal canceled
        jobs = jobs if isinstance(jobs, list) else []
        updated = []
        for job in jobs:
            item = dict(job)
            if item.get("id") == job_id:
                if created_by is not None and str(item.get("created_by") or "") != str(created_by or ""):
                    updated.append(item)
                    continue
                item["status"] = "canceled"
                item["canceled_at"] = now_fn()
                item["updated_at"] = now_fn()
                canceled = deepcopy(item)
            updated.append(item)
        return updated, deepcopy(canceled)

    return update_json(path, [], update_job)
