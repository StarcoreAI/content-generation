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
