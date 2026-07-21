import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from services.pattern_library import PatternLibrary
from services.reference_anatomy import analyze_article_anatomy
from services.reference_ingest import ingest_anatomy_cards
from services.reference_stage0 import analyze_stage0_groups
from services.storage import update_json


def _safe_segment(value, fallback):
    return re.sub(r"[^0-9A-Za-z_.-]", "_", value or fallback)


def reference_intelligence_path(root_dir, client_id, date_str, today_fn, task_id=""):
    safe_client = _safe_segment(client_id, "unknown")
    safe_date = _safe_segment(date_str, today_fn())
    safe_task = _safe_segment(task_id, "all")
    return os.path.join(root_dir, safe_client, f"{safe_date}_{safe_task}.json")


def load_reference_intelligence(root_dir, load_fn, today_fn, client_id, date_str, task_id=""):
    return load_fn(reference_intelligence_path(root_dir, client_id, date_str, today_fn, task_id), {
        "client_id": client_id,
        "date": date_str,
        "task_id": task_id,
        "clusters": [],
    })


def reference_stage_dir(root_dir, client_id, date_str, today_fn):
    safe_client = _safe_segment(client_id, "unknown")
    safe_date = _safe_segment(date_str, today_fn())
    return os.path.join(root_dir, safe_client, safe_date)


def collect_reference_articles(records, limit=20):
    by_url = {}
    order = []
    for record in records or []:
        question = str(record.get("question") or "")
        for ref in record.get("refs") or []:
            url = str(ref.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            if url not in by_url:
                by_url[url] = {
                    "url": url,
                    "source_title": str(ref.get("title") or ""),
                    "platform": str(ref.get("platform") or ""),
                    "first_question": question,
                    "citation_count": 0,
                    "_index": len(order),
                }
                order.append(url)
            by_url[url]["citation_count"] += 1
    articles = [by_url[url] for url in order]
    articles.sort(key=lambda item: (-item["citation_count"], item["_index"]))
    for article in articles:
        article.pop("_index", None)
    return articles[:limit] if limit else articles


def create_reference_analysis_job(jobs, jobs_guard, uid_fn, now_fn, client_id, date_str, task_id="", username=""):
    job_id = uid_fn()
    created_at = now_fn()
    job = {
        "ok": True,
        "job_id": job_id,
        "client_id": client_id,
        "date": date_str,
        "task_id": task_id,
        "username": username,
        "status": "queued",
        "stage": "queued",
        "progress": 3,
        "error": "",
        "created_at": created_at,
        "updated_at": created_at,
        "timings": {},
    }
    with jobs_guard:
        jobs[job_id] = job
    return job_id


def create_or_reuse_reference_analysis_job(jobs, jobs_guard, uid_fn, now_fn, client_id, date_str, task_id="", username=""):
    with jobs_guard:
        for job in jobs.values():
            if (
                job.get("client_id") == client_id
                and job.get("date") == date_str
                and (job.get("task_id") or "") == (task_id or "")
                and job.get("status") in {"queued", "running"}
            ):
                return dict(job), False
        job_id = uid_fn()
        created_at = now_fn()
        job = {
            "ok": True,
            "job_id": job_id,
            "client_id": client_id,
            "date": date_str,
            "task_id": task_id,
            "username": username,
            "status": "queued",
            "stage": "queued",
            "progress": 3,
            "error": "",
            "created_at": created_at,
            "updated_at": created_at,
            "timings": {},
        }
        jobs[job_id] = job
        return dict(job), True


def get_reference_analysis_job(jobs, jobs_guard, job_id):
    with jobs_guard:
        return dict(jobs.get(job_id) or {})


def update_reference_analysis_job(jobs, jobs_guard, now_fn, job_id, **fields):
    with jobs_guard:
        job = jobs.get(job_id)
        if not job:
            return {}
        job.update(fields)
        job["updated_at"] = now_fn()
        return dict(job)


def cancel_reference_analysis_job(jobs, jobs_guard, now_fn, job_id):
    with jobs_guard:
        job = jobs.get(job_id)
        if not job:
            return {}
        if job.get("status") in {"completed", "failed", "canceled"}:
            return dict(job)
        job["cancel_requested"] = True
        job["status"] = "canceled"
        job["updated_at"] = now_fn()
        return dict(job)


def _raise_if_reference_canceled(job_id, cancel_requested_fn):
    if cancel_requested_fn(job_id):
        raise RuntimeError("reference_analysis_canceled")


def load_reference_fetch_cache(stage_dir, load_fn):
    cached = {}
    body = load_fn(os.path.join(stage_dir, "fetched_articles.json"), {})
    for article in body.get("articles") or []:
        if not isinstance(article, dict):
            continue
        url = str(article.get("url") or "").strip()
        content = str(article.get("content") or "")
        if url and article.get("ok") and len(content) >= 200:
            cached[url] = article
    return cached


def merge_reference_fetch_result(ref, fetched, fetch_method=None):
    content = fetched.get("content") or ""
    return {
        **ref,
        "ok": bool(fetched.get("ok")),
        "title": fetched.get("title") or "",
        "description": fetched.get("description") or "",
        "content_len": len(content),
        "content": content,
        "fetch_method": fetch_method or fetched.get("fetch_method") or "",
        "error": fetched.get("error") or "",
        "static_error": fetched.get("static_error") or "",
    }


def _timed(job_id, name, fn, get_job_fn, update_job_fn):
    started = datetime.now()
    result = fn()
    elapsed = round((datetime.now() - started).total_seconds(), 2)
    job = get_job_fn(job_id)
    timings = dict(job.get("timings") or {})
    timings[name] = elapsed
    update_job_fn(job_id, timings=timings)
    return result


def _record_stage1_success(ledger_path, url):
    def record_success(current):
        current = dict(current or {})
        urls = [str(value).strip() for value in current.get("successful_urls") or [] if str(value).strip()]
        if url not in urls:
            urls.append(url)
        return {"schema_version": 1, "successful_urls": urls}, url

    update_json(ledger_path, {"schema_version": 1, "successful_urls": []}, record_success)


def run_reference_analysis_job(
    job_id,
    client_id,
    date_str,
    *,
    root_dir,
    load_fn,
    save_fn,
    today_fn,
    now_fn,
    load_client_records_fn,
    load_client_fn,
    job_ai_json_fn,
    get_job_fn,
    update_job_fn,
    cancel_requested_fn,
    fetch_fn,
    task_id="",
    username="",
    ai_json_fn=None,
    limit=20,
    candidate_limit=None,
    fetch_workers=3,
):
    ai_json_fn = ai_json_fn or job_ai_json_fn(username)
    stage_dir = reference_stage_dir(root_dir, client_id, date_str, today_fn)
    try:
        update_job_fn(job_id, status="running", stage="fetch", progress=3, error="")
        _raise_if_reference_canceled(job_id, cancel_requested_fn)

        records = load_client_records_fn(client_id, date=date_str, task_id=task_id if task_id else None)
        target_usable = max(1, int(limit or 20))
        candidate_limit = max(target_usable, int(candidate_limit or max(target_usable, 35)))
        fetch_workers = max(1, int(fetch_workers or 1))
        refs = collect_reference_articles(records, limit=candidate_limit)
        if not refs:
            raise ValueError("当前范围暂无引用文章")
        update_job_fn(job_id, stage="fetch", progress=5)

        def fetch_step():
            articles = []
            cache = load_reference_fetch_cache(stage_dir, load_fn)
            usable_count = 0
            processed_count = 0
            total = len(refs)

            def fetch_one(ref):
                if ref["url"] in cache:
                    return merge_reference_fetch_result(ref, cache[ref["url"]], fetch_method="cache")
                try:
                    fetched = fetch_fn(ref["url"], timeout=25, max_chars=12000, browser_fallback=True)
                    return merge_reference_fetch_result(ref, fetched)
                except Exception as exc:
                    return merge_reference_fetch_result(ref, {
                        "ok": False,
                        "title": "",
                        "description": "",
                        "content": "",
                        "error": str(exc),
                        "fetch_method": "browser",
                    })

            def append_article(article):
                nonlocal usable_count, processed_count
                articles.append(article)
                if article.get("ok") and len(str(article.get("content") or "")) >= 200:
                    usable_count += 1
                processed_count += 1
                update_job_fn(job_id, stage="fetch", progress=round(5 + (processed_count / total) * 25, 1))

            index = 0
            with ThreadPoolExecutor(max_workers=fetch_workers) as pool:
                while index < total and usable_count < target_usable:
                    _raise_if_reference_canceled(job_id, cancel_requested_fn)
                    batch = []
                    batch_size = min(fetch_workers, max(1, target_usable - usable_count))
                    while index < total and len(batch) < batch_size and usable_count < target_usable:
                        ref = refs[index]
                        index += 1
                        if ref["url"] in cache:
                            append_article(merge_reference_fetch_result(ref, cache[ref["url"]], fetch_method="cache"))
                        else:
                            batch.append(ref)
                    if not batch:
                        continue
                    futures = [pool.submit(fetch_one, ref) for ref in batch]
                    for future in futures:
                        _raise_if_reference_canceled(job_id, cancel_requested_fn)
                        append_article(future.result())
            output = {
                "client_id": client_id,
                "date": date_str,
                "candidate_total": len(refs),
                "target_usable": target_usable,
                "total": len(articles),
                "fetched_ok": sum(1 for item in articles if item["ok"]),
                "fetched_failed": sum(1 for item in articles if not item["ok"]),
                "articles": articles,
            }
            save_fn(os.path.join(stage_dir, "fetched_articles.json"), output)
            update_job_fn(job_id, stage="fetch", progress=30)
            return articles

        articles = _timed(job_id, "fetch", fetch_step, get_job_fn, update_job_fn)
        usable = [item for item in articles if item.get("ok") and len(str(item.get("content") or "")) >= 200]
        if not usable:
            raise ValueError("引用文章正文抓取失败")

        client = load_client_fn(client_id) or {}
        client_brand = str(client.get("brand") or "").strip()
        industry = str(client.get("industry") or "").strip() or "通用"

        def stage0_step():
            _raise_if_reference_canceled(job_id, cancel_requested_fn)
            update_job_fn(job_id, stage="filter", progress=32)
            result = analyze_stage0_groups(
                articles,
                client_brand=client_brand,
                ai_json_fn=ai_json_fn,
                stage_dir=stage_dir,
                client_id=client_id,
                date=date_str,
                save_fn=save_fn,
            )
            update_job_fn(job_id, stage="filter", progress=52)
            return result

        stage0 = _timed(job_id, "stage0_filter", stage0_step, get_job_fn, update_job_fn)
        _raise_if_reference_canceled(job_id, cancel_requested_fn)

        def stage1_anatomy_step():
            update_job_fn(job_id, stage="anatomy", progress=52)
            ledger_path = os.path.join(os.path.dirname(stage_dir), "stage1_anatomy_ledger.json")
            ledger = load_fn(ledger_path, {"schema_version": 1, "successful_urls": []})
            successful_urls = {
                str(url).strip() for url in ledger.get("successful_urls") or [] if str(url).strip()
            }
            articles_by_url = {
                str(article.get("url") or "").strip(): article
                for article in articles
                if isinstance(article, dict) and str(article.get("url") or "").strip()
            }
            groups = stage0.get("groups") or []
            cards, errors = [], []
            skipped = 0
            for index, group in enumerate(groups, 1):
                _raise_if_reference_canceled(job_id, cancel_requested_fn)
                if not isinstance(group, dict) or group.get("learnable") is not True:
                    skipped += 1
                    continue
                representative = group.get("representative") or {}
                url = str(representative.get("url") or "").strip()
                if url in successful_urls:
                    skipped += 1
                    continue
                article = articles_by_url.get(url)
                if not article:
                    errors.append({"group_id": group.get("group_id") or "", "error": "representative_article_missing"})
                    continue
                try:
                    cards.append(analyze_article_anatomy({
                        **article,
                        "group_id": group.get("group_id") or "",
                        "risk_marks": group.get("risk_marks") or [],
                    }, ai_json_fn))
                    _record_stage1_success(ledger_path, url)
                    successful_urls.add(url)
                except Exception as exc:
                    errors.append({"group_id": group.get("group_id") or "", "error": str(exc)})
                update_job_fn(job_id, stage="anatomy", progress=round(52 + (index / max(1, len(groups))) * 26, 1))
            output = {
                "client_id": client_id,
                "date": date_str,
                "total_input_groups": len(groups),
                "total_analyzed": len(cards),
                "total_skipped": skipped,
                "total_errors": len(errors),
                "cards": cards,
                "errors": errors,
            }
            save_fn(os.path.join(stage_dir, "stage1_anatomy_cards.json"), output)
            update_job_fn(job_id, stage="anatomy", progress=78)
            return output

        stage1 = _timed(job_id, "stage1_anatomy", stage1_anatomy_step, get_job_fn, update_job_fn)
        _raise_if_reference_canceled(job_id, cancel_requested_fn)

        def stage2_ingest_step():
            _raise_if_reference_canceled(job_id, cancel_requested_fn)
            update_job_fn(job_id, stage="ingest", progress=80)
            groups_by_id = {
                str(group.get("group_id") or "").strip(): group
                for group in stage0.get("groups") or []
                if isinstance(group, dict) and str(group.get("group_id") or "").strip()
            }
            report = ingest_anatomy_cards(
                stage1.get("cards") or [],
                library=PatternLibrary(Path(root_dir).parent / "pattern_library"),
                scope=f"industry:{industry}",
                groups_by_id=groups_by_id,
                ai_json_fn=ai_json_fn,
            )
            output = {"client_id": client_id, "date": date_str, **report}
            save_fn(os.path.join(stage_dir, "stage2_ingest_report.json"), output)
            update_job_fn(job_id, stage="ingest", progress=98)
            return output

        stage2 = _timed(job_id, "stage2_ingest", stage2_ingest_step, get_job_fn, update_job_fn)
        _raise_if_reference_canceled(job_id, cancel_requested_fn)
        body = {"client_id": client_id, "date": date_str, "stage0": stage0, "stage1": stage1, "stage2": stage2}
        update_job_fn(job_id, status="completed", stage="completed", progress=100, result=body)
        return body
    except RuntimeError as exc:
        if str(exc) == "reference_analysis_canceled":
            update_job_fn(job_id, status="canceled")
            return {}
        update_job_fn(job_id, status="failed", error=str(exc))
        return {}
    except Exception as exc:
        update_job_fn(job_id, status="failed", error=str(exc))
        return {}
