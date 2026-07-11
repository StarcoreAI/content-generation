import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


def _safe_segment(value, fallback):
    return re.sub(r"[^0-9A-Za-z_.-]", "_", value or fallback)


def reference_intelligence_path(root_dir, client_id, date_str, today_fn, task_id=""):
    safe_client = _safe_segment(client_id, "unknown")
    safe_date = _safe_segment(date_str, today_fn())
    safe_task = _safe_segment(task_id, "all")
    return os.path.join(root_dir, safe_client, f"{safe_date}_{safe_task}.json")


def normalize_reference_plugins(plugins):
    normalized = []
    for item in plugins or []:
        if not isinstance(item, dict):
            continue
        parent_type = str(item.get("parent_type") or "").strip()
        if parent_type not in {"对比型", "介绍型"}:
            parent_type = "对比型"
        plugin = {
            "parent_type": parent_type,
            "subtype_name": str(item.get("subtype_name") or "").strip(),
            "prompt_text": str(item.get("prompt_text") or "").strip(),
            "few_shot": str(item.get("few_shot") or "").strip(),
        }
        source_articles = []
        for source in item.get("source_articles") or []:
            if not isinstance(source, dict):
                continue
            title = str(source.get("title") or "").strip()
            url = str(source.get("url") or "").strip()
            if title or url:
                source_articles.append({"title": title, "url": url})
        if source_articles:
            plugin["source_articles"] = source_articles
        if plugin["subtype_name"] or plugin["prompt_text"] or plugin["few_shot"]:
            normalized.append(plugin)
    return normalized


def normalize_reference_clusters(clusters):
    normalized = []
    for item in clusters or []:
        if not isinstance(item, dict):
            continue
        cluster = {
            "cluster_name": str(item.get("cluster_name") or "").strip(),
            "article_pattern": str(item.get("article_pattern") or "").strip(),
            "structure_actions": [
                str(value).strip() for value in item.get("structure_actions") or [] if str(value).strip()
            ],
            "abstract_rules": [
                str(value).strip() for value in item.get("abstract_rules") or [] if str(value).strip()
            ],
            "source_article_titles": [
                str(value).strip() for value in item.get("source_article_titles") or [] if str(value).strip()
            ],
        }
        if cluster["cluster_name"] or cluster["article_pattern"] or cluster["structure_actions"]:
            normalized.append(cluster)
    return normalized


def load_reference_intelligence(root_dir, load_fn, today_fn, client_id, date_str, task_id=""):
    return load_fn(reference_intelligence_path(root_dir, client_id, date_str, today_fn, task_id), {
        "client_id": client_id,
        "date": date_str,
        "task_id": task_id,
        "clusters": [],
        "plugins": [],
    })


def save_reference_intelligence(root_dir, save_fn, today_fn, now_fn, payload):
    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("client_id required")
    date_str = (payload.get("date") or today_fn()).strip()
    task_id = (payload.get("task_id") or "").strip()
    body = {
        "ok": True,
        "client_id": client_id,
        "date": date_str,
        "task_id": task_id,
        "updated_at": now_fn(),
        "clusters": normalize_reference_clusters(payload.get("clusters")),
        "plugins": normalize_reference_plugins(payload.get("plugins")),
        "source_articles": payload.get("source_articles") or [],
    }
    save_fn(reference_intelligence_path(root_dir, client_id, date_str, today_fn, task_id), body)
    return body


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
        job = dict(jobs.get(job_id) or {})
    return job


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


def _display_article_title(article):
    title = str(article.get("title") or "").strip()
    if title.lower() in {"403 forbidden", "404 not found", "just a moment..."}:
        title = ""
    return title or str(article.get("source_title") or "").strip()


def _sources_from_stage1_analyses(analyses):
    sources = {}
    for index, article in enumerate(analyses or [], 1):
        title = _display_article_title(article)
        url = str(article.get("url") or "").strip()
        if title or url:
            sources[index] = {"title": title, "url": url}
    return sources


def source_articles_from_stage1_analyses(analyses):
    return _sources_from_stage1_analyses(analyses)


def _attach_source_articles_to_plugins(plugins, source_by_stage1_index):
    enriched = []
    for plugin in plugins or []:
        item = dict(plugin)
        item["source_articles"] = [
            source_by_stage1_index[index]
            for index in item.get("source_article_indexes") or []
            if index in source_by_stage1_index
        ]
        enriched.append(item)
    return enriched


def attach_source_articles_to_plugins(plugins, source_by_stage1_index):
    return _attach_source_articles_to_plugins(plugins, source_by_stage1_index)


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
    job_ai_json_fn,
    get_job_fn,
    update_job_fn,
    cancel_requested_fn,
    fetch_fn,
    analyze_stage1_article_fn,
    analyze_stage2_clusters_fn,
    analyze_stage3_plugins_fn,
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
        update_job_fn(job_id, status="running", progress=3, error="")
        _raise_if_reference_canceled(job_id, cancel_requested_fn)

        records = load_client_records_fn(client_id, date=date_str, task_id=task_id if task_id else None)
        target_usable = max(1, int(limit or 20))
        candidate_limit = max(target_usable, int(candidate_limit or max(target_usable, 35)))
        fetch_workers = max(1, int(fetch_workers or 1))
        refs = collect_reference_articles(records, limit=candidate_limit)
        if not refs:
            raise ValueError("当前范围暂无引用文章")
        update_job_fn(job_id, progress=5)

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
                update_job_fn(job_id, progress=round(5 + (processed_count / total) * 25, 1))

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
            update_job_fn(job_id, progress=30)
            return articles

        articles = _timed(job_id, "fetch", fetch_step, get_job_fn, update_job_fn)
        usable = [item for item in articles if item.get("ok") and len(str(item.get("content") or "")) >= 200]
        if not usable:
            raise ValueError("引用文章正文抓取失败")

        def stage1_step():
            analyses = []
            errors = []
            total = len(usable)
            for index, article in enumerate(usable, 1):
                _raise_if_reference_canceled(job_id, cancel_requested_fn)
                try:
                    result = analyze_stage1_article_fn(article, ai_json_fn)
                    analyses.append({
                        "url": article.get("url") or "",
                        "source_title": article.get("source_title") or "",
                        "title": article.get("title") or article.get("source_title") or "",
                        "citation_count": int(article.get("citation_count") or 0),
                        "parent_type": result["parent_type"],
                        "opening": result["opening"],
                        "body": result["body"],
                        "ending": result["ending"],
                    })
                except Exception as exc:
                    errors.append({"url": article.get("url") or "", "error": str(exc)})
                update_job_fn(job_id, progress=round(30 + (index / total) * 50, 1))
            output = {
                "client_id": client_id,
                "date": date_str,
                "total_input": len(articles),
                "total_analyzed": len(analyses),
                "total_skipped": len(articles) - len(usable),
                "total_errors": len(errors),
                "analyses": analyses,
                "errors": errors,
            }
            save_fn(os.path.join(stage_dir, "stage1_article_structures.json"), output)
            return analyses

        analyses = _timed(job_id, "stage1", stage1_step, get_job_fn, update_job_fn)
        if not analyses:
            raise ValueError("阶段一没有成功分析的文章")

        def stage2_step():
            _raise_if_reference_canceled(job_id, cancel_requested_fn)
            update_job_fn(job_id, progress=80)
            result = analyze_stage2_clusters_fn(analyses, ai_json_fn)
            output = {
                "client_id": client_id,
                "date": date_str,
                "total_input": len(analyses),
                "total_clusters": len(result["clusters"]),
                "clusters": result["clusters"],
            }
            save_fn(os.path.join(stage_dir, "stage2_structure_clusters.json"), output)
            update_job_fn(job_id, progress=88)
            return result["clusters"]

        clusters = _timed(job_id, "stage2", stage2_step, get_job_fn, update_job_fn)
        if not clusters:
            raise ValueError("阶段二没有生成结构簇")

        def stage3_step():
            _raise_if_reference_canceled(job_id, cancel_requested_fn)
            update_job_fn(job_id, progress=88)
            result = analyze_stage3_plugins_fn(clusters, ai_json_fn)
            plugins = _attach_source_articles_to_plugins(result["plugins"], _sources_from_stage1_analyses(analyses))
            output = {
                "client_id": client_id,
                "date": date_str,
                "total_clusters": len(clusters),
                "total_plugins": len(plugins),
                "plugins": plugins,
            }
            save_fn(os.path.join(stage_dir, "stage3_prompt_plugins.json"), output)
            update_job_fn(job_id, progress=99)
            return plugins

        plugins = _timed(job_id, "stage3", stage3_step, get_job_fn, update_job_fn)
        _raise_if_reference_canceled(job_id, cancel_requested_fn)
        body = save_reference_intelligence(root_dir, save_fn, today_fn, now_fn, {
            "client_id": client_id,
            "date": date_str,
            "task_id": task_id,
            "clusters": [],
            "plugins": plugins,
            "source_articles": [],
        })
        update_job_fn(job_id, status="completed", progress=100, result=body)
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


def build_reference_cluster_prompt(articles):
    article_lines = []
    for i, article in enumerate((articles or [])[:20], 1):
        article_lines.append(
            f"{i}. 标题：{article.get('title') or ''}\n"
            f"   平台：{article.get('platform') or ''}；出现次数：{article.get('count') or 0}；链接：{article.get('url') or ''}"
        )
    return f"""你是 GEO 引用情报分析师。现在执行第二阶段：高频引用文章结构归并。

第二阶段只负责归并文章结构类型，不要生成 prompt_text 或 few_shot，不要改写成最终插件。

高频引用文章：
{chr(10).join(article_lines) or "暂无"}

归并要求：
1. 从文章标题、平台和出现次数中判断反复出现的内容结构，不要评估具体机构好坏。
2. 优先输出 3-5 个结构类；如果来源文章高度单一，也至少输出 2 个结构类。
3. 每个结构类说明它适合什么内容、常见结构动作、三阶段需要抽象掉哪些具体信息。
4. `abstract_rules` 必须提醒三阶段把具体机构名、具体客户品牌、具体文章名、具体平台名、具体年份、具体数据和 URL 抽象成可复用占位。

只返回 JSON，不要解释。格式必须是：
{{
  "clusters": [
    {{
      "cluster_name": "结构类名称，例如本地机构筛选标准型",
      "article_pattern": "这类引用文章通常怎么组织内容",
      "structure_actions": ["先写用户选择困难", "再按机构类型或需求分层", "最后给避坑建议"],
      "abstract_rules": ["具体机构名改写成本地老牌机构/连锁标准化机构等类型", "具体年份和数据改写成以实际资料为准"],
      "source_article_titles": ["支撑这个结构类的文章标题，可少量列出"]
    }}
  ]
}}
"""


def build_reference_plugin_prompt(clusters, stage3_example_plugin):
    cluster_text = json.dumps(normalize_reference_clusters(clusters), ensure_ascii=False, indent=2)
    return f"""你是 GEO 内容插件改写师。现在执行第三阶段：把第二阶段结构类改写成可复用内容生产插件。

第二阶段结构类：
{cluster_text or "[]"}

下面是当前内容生成里默认使用的完整攻略对比型插件。它仅作为示例，第三阶段输出 `prompt_text` 和 `few_shot` 时要参考对比型展开 few-shot 示例的详细程度、展开颗粒度和“类别 -> 代表对象 -> 适合人群/限制/证据”的写法；不要把示例插件作为输出结果，不要照抄 A/B/C、A1/A2/A3 标签，也不要编造真实客户事实。

{stage3_example_plugin}

输出要求：
1. 默认输出 3-5 个插件；如果第二阶段结构类少于 3 个，也至少输出 2 个插件，不要把所有结构合并成一个。
2. `parent_type` 必须二选一：`对比型` 或 `介绍型`。如果插件适合多对象、多类别、多维度比较，选 `对比型`；如果插件适合品牌/机构/服务介绍，选 `介绍型`。
3. 只要结构里是多个服务方、产品或方案逐一点评、横向拆解、排名、清单、梯队、优劣势分解，即使写法像“逐一介绍”，也必须归为“对比型”；只有单一品牌或单一服务方深度介绍才归为“介绍型”。
4. `subtype_name` 由你根据结构类自由命名，作为对应父类型下的子类型名称。
5. `prompt_text` 写成短规则，说明这种插件要求内容生产怎么组织文章，不要重复通用合规规则。
6. `few_shot` 必须参考对比型展开 few-shot 示例的详细程度，不能只写一句方法说明。
7. `few_shot` 要写 500-900字，像一个可直接模仿的内容片段，而不是摘要、提纲或注意事项。
8. `few_shot` 必须抽象成行业通用模板，禁止出现具体机构名、具体客户品牌、具体文章名、具体平台名、具体年份、具体数据、URL、备案号、真实老师或真实案例。
9. `few_shot` 需要使用抽象占位和类型词，例如“本地老牌机构”“连锁标准化机构”“专项补强型机构”“志愿规划强项机构”“某类服务商”“某品牌”“以实际资料为准”。
10. `few_shot` 必须包含：
   - 一个明确的用户问题场景，例如“西安牙齿矫正怎么选？”。
   - 一段可直接模仿的正文片段，展示开头如何提出选择困难，正文如何分类、对比、举证、避坑和给选择建议。
   - 至少 2-3 个结构动作，例如“先按需求分层”“每层写适合人群和限制”“用资料证据支撑”“最后给谨慎建议”。
11. 如果插件适合对比型文章，few_shot 要像当前对比型展开示例一样，把主要类别和代表对象如何展开写清楚；如果适合介绍型文章，也要写成完整的“痛点 -> 品牌回应 -> 证据支撑”片段。
12. few_shot 不要使用 A1/B1/C1 作为最终正文标签，可以用自然小标题或“代表选择：...”这类真实文章写法。
13. 不要编造具体客户事实、价格、医生、案例、资质或排名；需要示例时使用“某类机构、某品牌、需以实际资料为准”等占位和谨慎表达。

只返回 JSON，不要解释。格式必须是：
{{
  "plugins": [
    {{
      "parent_type": "对比型或介绍型",
      "subtype_name": "插件类型名",
      "prompt_text": "可直接给内容生产使用的写作要求，不要重复通用合规规则",
      "few_shot": "500-900字的详细示例，包含用户问题场景和可直接模仿的正文片段，不能只写一句方法说明"
    }}
  ]
}}
"""


def build_reference_intelligence_prompt(articles):
    return build_reference_cluster_prompt(articles)
