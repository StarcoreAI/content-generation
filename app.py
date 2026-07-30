"""
GEO Agent v2 — 内容投放优化工作台
模块：客户管理 / 问题组管理 / 内容生产 / 每日分析 / 爬取任务
"""
import json, os, re, asyncio, threading, glob, random, uuid, secrets, time
from datetime import datetime, date, timedelta
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, render_template, request, jsonify, redirect, session, url_for, has_request_context, send_file
from openai import OpenAI
from services import crawl_tasks as crawl_task_store
from services import crawl_jobs as crawl_job_store
from services import records as record_store
from services.auth import authenticate_user, create_user, find_user
from services.article_structure import analyze_article_structure
from services.article_fetcher import fetch_article_text
from services.content_generations import ContentGenerationStore
from services.publications import PublicationStore
from services.rwmeiti import RWMeitiClient
from services.batch_generation import BatchGenerationJobs
from services.quality_gate import (
    effective_quality_policy,
    load_quality_policy,
    quality_gate_competitor_names,
    quality_policy_industry_key,
    run_quality_gate,
    save_quality_policy,
)
from services.materials import MaterialService
from services.material_pipeline import load_latest_material_package_result, run_material_package_pipeline
from services.material_web_expansion import expand_material_web_package, tavily_search
from services.competitor_materials import (
    analyze_competitor_upload_package,
    expand_competitor_web_package,
    load_latest_competitor_result,
    normalize_competitor_names,
)
from services.record_stats import (
    build_raw_platform_stats,
)
from services.record_trends import (
    build_article_pool,
    build_group_mention_trend,
    build_question_article_list,
    build_question_trend,
    build_source_trend,
)
from services.selection_evidence import SelectionEvidenceService
from services.knowledge_base import KnowledgeBaseService, validate_customer_content_facts
from services.content_route_library import ContentRouteLibrary
from services.content_route_generation import (
    generate_content_route_draft,
    route_context as content_route_context,
)
from services.content_route_analysis import analyze_content_route_article, ingest_content_route_analysis
from services.query_platform_reference_intelligence import select_query_platform_articles
from services.reference_route_batch_merge import merge_reference_route_batch
from services.competitor_knowledge import (
    build_competitor_master_input,
    build_high_frequency_competitor_prompt,
    collect_high_frequency_article_sources,
    merge_competitor_master_markdown,
)
from services.storage import load_json, save_json, update_json
from scripts.run_material_filter import choose_material_filter_model
from scripts.run_material_output import choose_material_output_model
from scripts.run_material_reducer import choose_material_reducer_model

app = Flask(__name__)
app.secret_key = os.environ.get("GEO_SECRET_KEY", "dev-secret-key-change-before-deploy")
APP_VERSION = "2.3"
NODE_CRAWLER_DEFAULT_PLATFORMS = {"doubao", "deepseek", "yuanbao", "qwen", "kimi"}
CLIENT_CONTRACT_PLATFORM_ORDER = ["deepseek", "yuanbao", "qwen", "kimi", "doubao"]
crawl_platform_locks_guard = threading.Lock()
crawl_platform_locks = {}
content_batch_jobs_guard = threading.RLock()
content_batch_jobs = None
content_generation_lock = threading.RLock()
reference_intelligence_lock = threading.RLock()


def get_crawl_platform_lock(platform):
    platform = (platform or "default").strip() or "default"
    with crawl_platform_locks_guard:
        if platform not in crawl_platform_locks:
            crawl_platform_locks[platform] = threading.Lock()
        return crawl_platform_locks[platform]


def extract_generated_title(content):
    for line in str(content or "").splitlines():
        title = re.sub(r"^[#\s《》「」\"']+|[#\s《》「」\"']+$", "", line.strip())
        if title:
            return title[:80]
    return "未命名文章"

# ── 数据文件路径 ────────────────────────────────────────
D = "data"
F_CLIENTS   = f"{D}/clients.json"
F_PROBES    = f"{D}/probes.json"
F_RECORDS   = f"{D}/records.json"
F_PLATFORMS = f"{D}/platforms.json"
F_ARTICLES  = f"{D}/articles.json"
F_SETTINGS  = f"{D}/settings.json"
F_GROUPS    = f"{D}/probe_groups.json"
F_RAW_RECORDS = f"{D}/raw_records.json"  # 细化版爬取记录
F_COMPETITOR_ARTICLE_BODY_HITS = f"{D}/competitor_article_body_hits.json"
F_CONTENT_GENERATIONS = f"{D}/content_generations.json"
F_USERS = f"{D}/users.json"
F_USER_SETTINGS = f"{D}/user_settings"
F_DISTRIBUTION_FAVORITES = f"{D}/distribution_favorites"
F_DISTRIBUTION_MATCH_JOBS = f"{D}/distribution_match_jobs"
F_DISTRIBUTION_CATALOG = f"{D}/distribution_catalog/rwmeiti_catalog.json"
F_DISTRIBUTION_CATALOG_JOBS = f"{D}/distribution_catalog_jobs"
F_CRAWL_JOBS = f"{D}/crawl_jobs.json"

ANONYMOUS_ENDPOINTS = {
    "static",
    "login_page",
    "auth_login",
    "auth_register",
    "auth_logout",
    "auth_me",
    "health_check",
    "publication_preview",
}


def public_user(user):
    if not user:
        return None
    return {
        "username": user.get("username", ""),
        "role": user.get("role", "operator"),
        "disabled": bool(user.get("disabled", False)),
    }


def current_user():
    username = session.get("username")
    if not username:
        return None
    user = find_user(F_USERS, username)
    if not user or user.get("disabled"):
        session.pop("username", None)
        return None
    return user


def is_admin(user=None):
    user = user or current_user()
    return bool(user and user.get("role") == "admin")


def auth_disabled():
    return bool(app.config.get("AUTH_DISABLED"))


def public_register_enabled():
    value = app.config.get("ALLOW_PUBLIC_REGISTER")
    if value is None:
        value = os.environ.get("GEO_ALLOW_PUBLIC_REGISTER", "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def can_access_client(client):
    if auth_disabled():
        return bool(client)
    user = current_user()
    if not user or not client:
        return False
    if is_admin(user):
        return True
    return client.get("owner_username") == user.get("username")


def visible_clients():
    clients = load(F_CLIENTS, [])
    if auth_disabled() or is_admin():
        return clients
    return [client for client in clients if can_access_client(client)]


def require_client_access(client_id):
    client = next((c for c in load(F_CLIENTS, []) if c.get("id") == client_id), None)
    if auth_disabled():
        return client or {"id": client_id}
    return client if can_access_client(client) else None


def request_client_id():
    view_args = request.view_args or {}
    if view_args.get("cid"):
        return view_args.get("cid")
    if request.args.get("client_id"):
        return request.args.get("client_id")
    data = request.get_json(silent=True) if request.is_json else None
    if isinstance(data, dict) and data.get("client_id"):
        return data.get("client_id")
    return ""


@app.before_request
def require_login():
    if app.config.get("AUTH_DISABLED"):
        return None
    if request.endpoint in ANONYMOUS_ENDPOINTS:
        return None
    if current_user():
        client_id = request_client_id()
        if client_id and not require_client_access(client_id):
            return jsonify({"error": "client_not_found"}), 404
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "auth_required", "message": "请先登录"}), 401
    return redirect(url_for("login_page"))

def get_raw_data_dir():
    """获取原始数据存储目录（可由用户自定义）"""
    return record_store.get_raw_data_dir(F_SETTINGS, D)

def save_daily_raw(client_id, brand, question, answer, refs, analysis):
    """保存每日原始爬取数据到独立JSON文件，按日期分组"""
    return record_store.save_daily_raw(
        F_SETTINGS, D, client_id, brand, question, answer, refs, analysis,
        uid, today_str, now_str
    )

# ── 数据操作 ────────────────────────────────────────────
def load(path, default):
    return load_json(path, default)

def save(path, data):
    save_json(path, data)


def normalize_platform_filter(platform):
    """Return None when the UI asks for all crawl platforms."""
    if not platform or platform == "all":
        return None
    return platform


def should_use_node_crawler(platform):
    """
    Route crawler execution through the external Node crawler bridge.

    Default: use the external Node crawler for supported production platforms.
    Override examples:
    - GEO_NODE_CRAWLER_PLATFORMS=doubao     -> only doubao uses Node
    - GEO_NODE_CRAWLER_PLATFORMS=doubao,qwen -> doubao and qwen use Node
    - GEO_NODE_CRAWLER_PLATFORMS=all        -> all default platforms use Node
    - GEO_NODE_CRAWLER_PLATFORMS=none       -> use Python crawlers for all platforms
    """
    raw = os.environ.get("GEO_NODE_CRAWLER_PLATFORMS")
    if raw is None:
        return platform in NODE_CRAWLER_DEFAULT_PLATFORMS

    normalized = raw.strip().lower()
    if normalized in {"", "none", "off", "false", "0", "python"}:
        return False
    if normalized == "all":
        return platform in NODE_CRAWLER_DEFAULT_PLATFORMS

    requested = {p.strip() for p in normalized.split(",") if p.strip()}
    return platform in requested


def normalize_contract_platforms(platforms):
    if not isinstance(platforms, list):
        return []
    requested = {str(item).strip() for item in platforms if str(item).strip()}
    return [platform for platform in CLIENT_CONTRACT_PLATFORM_ORDER if platform in requested]


def _body_hit_scope_value(value):
    value = str(value or "").strip()
    if value == "all":
        return ""
    return value


def load_competitor_article_body_hit_report(client_id, date_str, task_id="", group_id="", platform=""):
    scope = {
        "client_id": _body_hit_scope_value(client_id),
        "date": _body_hit_scope_value(date_str),
        "task_id": _body_hit_scope_value(task_id),
        "group_id": _body_hit_scope_value(group_id),
        "platform": _body_hit_scope_value(platform),
    }
    candidates = []
    for item in load(F_COMPETITOR_ARTICLE_BODY_HITS, []):
        if not isinstance(item, dict):
            continue
        item_scope = {key: _body_hit_scope_value(item.get(key)) for key in scope}
        if item_scope == scope:
            candidates.append(item)
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: str(x.get("generated_at") or ""))[-1]


def annotate_top_articles_with_competitor_matches(top_articles, records, body_hit_report=None):
    if not top_articles:
        return top_articles
    from services.ref_articles import canonical_article_key
    from services.record_insights import build_record_insights, select_article_match_entities

    insights = build_record_insights(records)
    selected_entities = select_article_match_entities(insights.get("mentioned_entities", []))
    body_hits = body_hit_report.get("body_hits", []) if body_hit_report else []
    body_status_by_key = {
        canonical_article_key(item.get("title", ""), item.get("url", "")): item
        for item in body_hits
    }
    for article in top_articles:
        key = canonical_article_key(article.get("title", ""), article.get("url", ""))
        article_text = f"{article.get('title', '')} {article.get('url', '')}"
        matched_entities = [
            entity_name
            for entity_name in selected_entities
            if entity_name and entity_name.lower() in article_text.lower()
        ]
        match_types = ["标题/URL命中"] if matched_entities else []

        body_status = body_status_by_key.get(key)
        if body_status and body_status.get("status") == "matched":
            body_entities = [
                entity_name
                for entity_name in body_status.get("matched_entities") or []
                if entity_name in selected_entities
            ]
            if body_entities:
                matched_entities = sorted(
                    set(matched_entities + body_entities),
                    key=selected_entities.index,
                )
                if "正文命中" not in match_types:
                    match_types.append("正文命中")

        if match_types:
            article["competitor_match_status"] = "matched"
            article["competitor_match_label"] = "提到目标竞品"
            article["competitor_match_types"] = match_types
            article["competitor_matched_entities"] = matched_entities
            continue

        if body_status and body_status.get("status") in {"fetch_failed", "skipped"}:
            article["competitor_match_status"] = "unconfirmed"
            article["competitor_match_label"] = "正文未确认"
        elif body_hit_report:
            article["competitor_match_status"] = "not_matched"
            article["competitor_match_label"] = "未提到目标竞品"
        else:
            article["competitor_match_status"] = ""
            article["competitor_match_label"] = ""
        article["competitor_match_types"] = []
        article["competitor_matched_entities"] = []
    return top_articles


def load_client_records(client_id, date=None, group_id=None, platform=None,
                        task_id=None, question=None, mentioned_only=None):
    """
    严格按 client_id 过滤爬取记录的唯一入口。
    client_id 为空时强制返回空列表，绝不读取全量数据，防止跨客户串数据。
    platform: 可选，按来源平台过滤（doubao/deepseek/yuanbao/qwen），None=全部
    """
    return record_store.load_client_records(
        F_RAW_RECORDS,
        client_id,
        date=date,
        group_id=group_id,
        platform=normalize_platform_filter(platform),
        task_id=task_id,
        question=question,
        mentioned_only=mentioned_only,
    )


def today_str(): return date.today().isoformat()
def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M")
_uid_lock = threading.Lock()
_uid_last = ""
_uid_counter = 0


def uid():
    global _uid_last, _uid_counter
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    with _uid_lock:
        if stamp == _uid_last:
            _uid_counter += 1
        else:
            _uid_last = stamp
            _uid_counter = 0
        return stamp if _uid_counter == 0 else f"{stamp}{_uid_counter:03d}"

def get_crawl_task_dir():
    return crawl_task_store.get_crawl_task_dir(D)

def build_node_output_dir(data_dir, task_id, platform):
    return os.path.abspath(os.path.join(data_dir, "tasks", "node", task_id, platform))

def save_crawl_task_report(report):
    """Persist one crawl task summary for later diagnosis."""
    return crawl_task_store.save_crawl_task_report(D, report, uid, today_str, now_str)

def compact_crawl_failure(raw, meta):
    return crawl_task_store.compact_crawl_failure(raw, meta)

def calc_geo_score(brand, question, answer, refs, analysis_result=None):
    """
    GEO评分算法 v3
    
    规则：
    - 未提及（正文无完整品牌名）→ 强制0分
    - 提及 + 排名靠前（1-3名）→ 绿色区间，60-100分
    - 提及 + 排名靠后（4名以后/无排名）→ 黄色区间，20-59分
    
    评分维度：
    1. 品牌提及基础分：提及=20，未提及=0（强制返回0）
    2. 排名位置：第1名+40，第2名+30，第3名+20，4-6名+10，7名以后+5
    3. 引用文章含品牌：每篇+5，最多+15
    4. 情感倾向：正面+5，负面-10
    5. 频次加分：出现2次以上每次+2，最多+5
    """
    if not brand:
        return 0

    # 只用完整品牌名判断提及，不用前2字缩写
    brand_in_answer = brand in (answer or '')
    if not brand_in_answer:
        return 0  # 未提及强制0分

    score = 20  # 提及基础分

    # 排名位置（决定绿/黄区间）
    rank = (analysis_result or {}).get('brand_rank')
    if rank == 1:
        score += 40   # 总分60+，绿色
    elif rank == 2:
        score += 30   # 总分50+，黄绿边界
    elif rank == 3:
        score += 20   # 总分40+，黄色
    elif rank and 4 <= rank <= 6:
        score += 10   # 黄色
    elif rank and rank > 6:
        score += 5    # 黄色偏低

    # 引用文章含品牌加分（每篇+5，最多+15）
    brand_refs_count = sum(1 for r in refs if brand in r.get('title', ''))
    score += min(brand_refs_count * 5, 15)

    # 情感倾向
    sentiment = (analysis_result or {}).get('brand_sentiment', 'neutral')
    if sentiment == 'positive':
        score += 5
    elif sentiment == 'negative':
        score -= 10

    # 频次加分（出现2次以上）
    brand_count = (answer or '').count(brand)
    if brand_count >= 2:
        score += min((brand_count - 1) * 2, 5)

    return max(0, min(100, score))


def extract_brand_snippet(answer, brand, radius=45):
    value = answer or ""
    if not brand or brand not in value:
        return ""
    idx = value.find(brand)
    start = max(0, idx - radius)
    end = min(len(value), idx + len(brand) + radius)
    return value[start:end].strip()


def calibrate_analysis_brand_mention(brand, question, answer, refs, analysis):
    """
    Keep summary records consistent with raw records: full brand mention is
    determined by the answer body, not by AI inference alone.
    """
    result = dict(analysis or {})
    mentioned_in_answer = bool(brand and brand in (answer or ""))
    result["brand_mentioned"] = mentioned_in_answer
    if mentioned_in_answer and not result.get("brand_snippet"):
        result["brand_snippet"] = extract_brand_snippet(answer, brand)
    if not mentioned_in_answer:
        result["brand_snippet"] = ""
    result["geo_score"] = calc_geo_score(brand, question, answer, refs, result)
    return result


# ── AI 调用 ─────────────────────────────────────────────
DEFAULT_SETTINGS = {
        "api_key": "", "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat", "preset": "deepseek", "tavily_api_key": ""
    }


def get_global_settings():
    return load(F_SETTINGS, DEFAULT_SETTINGS.copy())


def user_settings_path(username):
    safe = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(username or "").strip()).strip("._")
    return os.path.join(F_USER_SETTINGS, f"{safe or 'user'}.json")


def distribution_favorites_path(username):
    safe = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(username or "").strip()).strip("._")
    return os.path.join(F_DISTRIBUTION_FAVORITES, f"{safe or 'user'}.json")


def distribution_match_job_path(username):
    safe = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(username or "").strip()).strip("._")
    return os.path.join(F_DISTRIBUTION_MATCH_JOBS, f"{safe or 'user'}.json")


def distribution_catalog_path(_username=None):
    return F_DISTRIBUTION_CATALOG


def distribution_catalog_job_path(username):
    safe = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(username or "").strip()).strip("._")
    return os.path.join(F_DISTRIBUTION_CATALOG_JOBS, f"{safe or 'user'}.json")


def current_distribution_favorites():
    username = str((current_user() or {}).get("username") or "")
    if not username:
        return "", []
    favorites = load(distribution_favorites_path(username), [])
    return username, favorites if isinstance(favorites, list) else []


def current_distribution_catalog():
    username = str((current_user() or {}).get("username") or "")
    if not username:
        return "", []
    catalog = load(distribution_catalog_path(username), [])
    return username, catalog if isinstance(catalog, list) else []


def sync_distribution_catalog(username, supplier, progress=None):
    resources, scanned = [], 0
    for resource_type, list_page in (("self_media", supplier.list_self_media), ("news_media", supplier.list_news_media)):
        page = 1
        while True:
            batch = list_page(page, 200)
            scanned += len(batch)
            resources.extend({**item, "resource_type": resource_type, "synced_at": now_str()} for item in batch)
            if progress:
                progress({"status": "running", "resource_type": resource_type, "page": page, "scanned": scanned})
            if len(batch) < 200:
                break
            page += 1
    save(distribution_catalog_path(username), resources)
    link_name_only_distribution_favorites(username, resources)
    return {"count": len(resources), "scanned": scanned}


def start_distribution_catalog_sync(username, supplier):
    job = {"status": "running", "started_at": now_str(), "scanned": 0, "count": 0}
    job_path = distribution_catalog_job_path(username)
    save(job_path, job)

    def worker():
        try:
            result = sync_distribution_catalog(username, supplier, lambda update: save(job_path, {**job, **update}))
            save(job_path, {**job, **result, "status": "completed", "finished_at": now_str()})
        except Exception as exc:
            save(job_path, {**job, "status": "failed", "error": str(exc)[:200], "finished_at": now_str()})

    threading.Thread(target=worker, daemon=True).start()
    return job


def search_distribution_catalog(catalog, query, limit=50):
    query = normalize_supplier_name(query)
    matches = [item for item in catalog if not query or query in normalize_supplier_name(item.get("name"))]
    return matches[:max(1, min(int(limit or 50), 100))]


def distribution_catalog_resource(catalog, resource_id, resource_type):
    return next((item for item in catalog if str(item.get("resource_id")) == str(resource_id)
                 and str(item.get("resource_type") or "self_media") == str(resource_type)), None)


def resolved_distribution_favorites(username):
    favorites = load(distribution_favorites_path(username), [])
    catalog = load(distribution_catalog_path(username), [])
    favorites = favorites if isinstance(favorites, list) else []
    catalog = catalog if isinstance(catalog, list) else []
    resolved = []
    for favorite in favorites:
        item = dict(favorite)
        resource_type = str(item.get("resource_type") or "self_media")
        resource = distribution_catalog_resource(catalog, item.get("resource_id"), resource_type)
        if resource:
            item.update({key: resource.get(key) for key in ("name", "price", "status", "synced_at")})
            item["resource_type"] = resource_type
        resolved.append(item)
    return resolved


def update_distribution_catalog_resources(username, resources):
    catalog = load(distribution_catalog_path(username), [])
    catalog = catalog if isinstance(catalog, list) else []
    updates = {
        (str(item.get("resource_type") or "self_media"), str(item.get("resource_id") or "")): item
        for item in resources
    }
    merged = [updates.pop((str(item.get("resource_type") or "self_media"), str(item.get("resource_id") or "")), item)
              for item in catalog]
    merged.extend(updates.values())
    save(distribution_catalog_path(username), merged)


def normalize_supplier_name(value):
    return str(value or "").strip().casefold()


def link_name_only_distribution_favorites(username, catalog):
    favorites = load(distribution_favorites_path(username), [])
    if not isinstance(favorites, list):
        return
    changed = False
    for favorite in favorites:
        if str(favorite.get("resource_id") or "").strip() or not normalize_supplier_name(favorite.get("name")):
            continue
        candidates = [item for item in catalog if normalize_supplier_name(item.get("name")) == normalize_supplier_name(favorite.get("name"))]
        if len(candidates) == 1:
            favorite["resource_id"] = str(candidates[0].get("resource_id") or "")
            favorite["resource_type"] = str(candidates[0].get("resource_type") or "self_media")
            changed = True
    if changed:
        save(distribution_favorites_path(username), favorites)


def match_operator_favorites(username, supplier, progress=None):
    favorites = load(distribution_favorites_path(username), [])
    targets = {normalize_supplier_name(item.get("name")) for item in favorites if normalize_supplier_name(item.get("name"))}
    matches = {target: [] for target in targets}
    scanned = 0
    for resource_type, list_page in (("self_media", supplier.list_self_media), ("news_media", supplier.list_news_media)):
        page = 1
        while True:
            batch = list_page(page, 200)
            scanned += len(batch)
            for resource in batch:
                name = normalize_supplier_name(resource.get("name"))
                if name in matches:
                    matches[name].append({**resource, "resource_type": resource_type})
            if progress:
                progress({"status": "running", "resource_type": resource_type, "page": page, "scanned": scanned})
            if len(batch) < 200:
                break
            page += 1
    saved_favorites = load(distribution_favorites_path(username), [])
    for favorite in saved_favorites:
        name = normalize_supplier_name(favorite.get("name"))
        if name in matches:
            favorite["candidates"] = matches[name]
    save(distribution_favorites_path(username), saved_favorites)
    return {"scanned": scanned, "matched": sum(bool(item.get("candidates")) for item in saved_favorites)}


def start_distribution_favorite_match(username, supplier):
    job = {"status": "running", "started_at": now_str(), "scanned": 0, "matched": 0}
    job_path = distribution_match_job_path(username)
    save(job_path, job)

    def worker():
        try:
            result = match_operator_favorites(username, supplier, lambda update: save(job_path, {**job, **update}))
            save(job_path, {**job, **result, "status": "completed", "finished_at": now_str()})
        except Exception as exc:
            save(job_path, {**job, "status": "failed", "error": str(exc)[:200], "finished_at": now_str()})

    threading.Thread(target=worker, daemon=True).start()
    return job


def settings_username():
    if has_request_context() and not auth_disabled():
        user = current_user()
        if user:
            return user.get("username", "")
    return ""


def get_settings(username=None):
    settings = get_global_settings()
    username = username if username is not None else settings_username()
    if username:
        settings.update(load(user_settings_path(username), {}))
    return settings


def save_current_settings(data):
    username = settings_username()
    path = user_settings_path(username) if username else F_SETTINGS
    settings = load(path, {}) if username else get_global_settings()
    if data.get("api_key") and data["api_key"] not in ("***", ""):
        settings["api_key"] = data["api_key"]
    if data.get("tavily_api_key") and data["tavily_api_key"] not in ("***", ""):
        settings["tavily_api_key"] = data["tavily_api_key"]
    for key in ["base_url", "model", "preset"]:
        if key in data:
            settings[key] = data[key]
    save(path, settings)

def get_tavily_api_key(settings=None):
    return os.environ.get("TAVILY_API_KEY", "").strip() or str((settings or get_settings()).get("tavily_api_key") or "").strip()

def ai(prompt, max_tokens=2000):
    s = get_settings()
    raw, _diagnostics = ai_with_settings_response(prompt, max_tokens, s)
    return raw


def ai_with_settings(prompt, max_tokens=2000, settings=None):
    raw, _diagnostics = ai_with_settings_response(prompt, max_tokens, settings)
    return raw


def _log_model_call(event, **fields):
    payload = {
        "event": event,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        **fields,
    }
    print("[model_call] " + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _model_error_summary(exc, api_key, prompt):
    message = str(exc)
    if api_key:
        message = message.replace(str(api_key), "[REDACTED]")
    if prompt:
        message = message.replace(str(prompt), "[REDACTED]")
    return message[:500]


def ai_with_settings_response(prompt, max_tokens=2000, settings=None):
    s = settings or get_settings()
    if not s.get("api_key"):
        raise Exception("请先在系统设置中配置 API Key")
    base_url = str(s["base_url"] or "").rstrip("/")
    call_fields = {
        "call_id": uuid.uuid4().hex[:12],
        "source": "ai_with_settings_response",
        "model": str(s.get("model") or ""),
        "base_url_host": urlsplit(base_url).netloc,
        "max_tokens": max_tokens,
    }
    started_at = time.monotonic()
    _log_model_call("started", **call_fields)
    kwargs = {
        "model": s["model"],
        "messages": [{"role": "user", "content": prompt}],
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    try:
        client = OpenAI(api_key=s["api_key"], base_url=base_url)
        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        raw = str(getattr(choice.message, "content", "") or "").strip()
    except Exception as exc:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", {}) or {}
        request_id = headers.get("x-request-id") or headers.get("request-id")
        _log_model_call(
            "failed",
            **call_fields,
            elapsed_ms=round((time.monotonic() - started_at) * 1000),
            error_type=type(exc).__name__,
            error_message=_model_error_summary(exc, s.get("api_key"), prompt),
            upstream_status=getattr(response, "status_code", None) or getattr(exc, "status_code", None),
            upstream_request_id=request_id,
        )
        raise
    _log_model_call(
        "finished",
        **call_fields,
        elapsed_ms=round((time.monotonic() - started_at) * 1000),
        response_model=str(getattr(resp, "model", "") or s.get("model", "")),
        finish_reason=str(getattr(choice, "finish_reason", "") or ""),
        response_length=len(raw),
    )
    return raw, {
        "model": str(getattr(resp, "model", "") or s.get("model", "")),
        "finish_reason": str(getattr(choice, "finish_reason", "") or ""),
        "response_length": len(raw),
    }

def ai_deepseek_pro(messages, max_tokens=6000):
    s = get_settings()
    if not s.get("api_key"):
        raise Exception("请先在系统设置中配置 API Key")
    client = OpenAI(api_key=s["api_key"], base_url=s.get("base_url", "https://api.deepseek.com").rstrip("/"))
    resp = client.chat.completions.create(
        model=s.get("model", "deepseek-chat"), max_tokens=max_tokens, messages=messages
    )
    return resp.choices[0].message.content.strip()

def ai_json(prompt, max_tokens=1500):
    return parse_ai_json(ai(prompt, max_tokens))


def ai_json_with_settings(prompt, max_tokens=1500, settings=None):
    raw = ai_with_settings(prompt, max_tokens, settings)
    return parse_ai_json(raw)


def parse_ai_json(raw):
    raw = re.sub(r"^```json\s*|^```\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    # 若 JSON 被截断（max_tokens不够），尝试补全后再解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 尝试截到最后一个完整的 } 或 ] 处
        for end_char in ('}', ']'):
            idx = raw.rfind(end_char)
            if idx != -1:
                try:
                    return json.loads(raw[:idx+1])
                except:
                    pass
        raise

# ══════════════════════════════════════════════════════
# 路由：页面
# ══════════════════════════════════════════════════════
@app.route("/login")
def login_page():
    register_html = ""
    register_script = ""
    if public_register_enabled():
        register_html = """
  <hr>
  <h2>新同事注册</h2>
  <form id="registerForm">
    <input name="username" placeholder="用户名" autocomplete="username">
    <input name="password" type="password" placeholder="密码" autocomplete="new-password">
    <button type="submit">注册并进入</button>
  </form>"""
        register_script = """
    document.getElementById('registerForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username: form.get('username'),
          password: form.get('password')
        })
      });
      if (response.ok) location.href = '/';
      else {
        const payload = await response.json().catch(() => ({}));
        alert(payload.message || '注册失败');
      }
    });"""
    page = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>GEO Agent 登录</title></head>
<body>
  <h1>GEO Agent</h1>
  <form id="loginForm">
    <input name="username" placeholder="用户名" autocomplete="username">
    <input name="password" type="password" placeholder="密码" autocomplete="current-password">
    <button type="submit">登录</button>
  </form>
{register_html}
  <script>
    document.getElementById('loginForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username: form.get('username'),
          password: form.get('password')
        })
      });
      if (response.ok) location.href = '/';
      else alert('用户名或密码错误');
    });
{register_script}
  </script>
</body>
</html>"""
    return page.replace("{register_html}", register_html).replace("{register_script}", register_script)


@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.json or {}
    user = authenticate_user(F_USERS, data.get("username", ""), data.get("password", ""))
    if not user:
        return jsonify({"error": "invalid_credentials", "message": "用户名或密码错误"}), 401
    session["username"] = user["username"]
    return jsonify({"ok": True, "user": public_user(user)})


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    if not public_register_enabled():
        return jsonify({"error": "registration_disabled", "message": "注册入口已关闭，请联系管理员创建账号"}), 403
    data = request.json or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    if not username:
        return jsonify({"error": "username_required", "message": "请输入用户名"}), 400
    if not password:
        return jsonify({"error": "password_required", "message": "请输入密码"}), 400
    try:
        user = create_user(F_USERS, username, password, role="operator")
    except ValueError as exc:
        if "already exists" in str(exc):
            return jsonify({"error": "user_exists", "message": "用户名已存在"}), 409
        return jsonify({"error": "invalid_registration", "message": str(exc)}), 400
    session["username"] = user["username"]
    return jsonify({"ok": True, "user": public_user(user)})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.pop("username", None)
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    return jsonify({"ok": True, "user": public_user(current_user())})


@app.route("/api/health", methods=["GET"])
def health_check():
    """Lightweight environment check that does not require an API key."""
    settings = get_global_settings()
    data_dir_ok = True
    try:
        os.makedirs(D, exist_ok=True)
        probe_path = os.path.join(D, ".healthcheck")
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write(now_str())
        os.remove(probe_path)
    except Exception:
        data_dir_ok = False

    platform_status = []
    try:
        from base_crawler import get_platform_login_status
        for key, cfg in CRAWL_PLATFORMS.items():
            status = get_platform_login_status(key)
            platform_status.append({
                "id": key,
                "name": cfg["name"],
                "logged_in": status["logged_in"],
                "status": status["status"],
                "state_file_exists": status["state_file_exists"],
                "message": status["message"],
            })
    except Exception:
        platform_status = []

    return jsonify({
        "ok": data_dir_ok,
        "version": APP_VERSION,
        "data_dir": D,
        "data_dir_writable": data_dir_ok,
        "has_api_key": bool(settings.get("api_key")),
        "base_url": settings.get("base_url", ""),
        "model": settings.get("model", ""),
        "clients_count": len(load(F_CLIENTS, [])),
        "platforms": platform_status,
        "time": now_str(),
    })

# ══════════════════════════════════════════════════════
# 模块一：客户管理
# ══════════════════════════════════════════════════════
@app.route("/api/clients", methods=["GET"])
def get_clients(): return jsonify(visible_clients())


@app.route("/api/quality-policy", methods=["GET"])
def get_quality_policy():
    cid = str(request.args.get("client_id") or "").strip()
    client = require_client_access(cid) if cid else None
    if cid and not client:
        return jsonify({"error": "client_not_found"}), 404
    policy = load_quality_policy(quality_policy_path())
    industry = str((client or {}).get("industry") or "").strip()
    key = quality_policy_industry_key(industry)
    return jsonify({
        "ok": True,
        "common": policy["common"],
        "industry": {"name": industry, "key": key, "policy": policy["industries"].get(key, {})},
    })


@app.route("/api/quality-policy/common", methods=["PUT"])
def save_common_quality_policy():
    payload = request.get_json(silent=True) or {}
    if not payload.get("confirmed_global"):
        return jsonify({"error": "global_policy_confirmation_required"}), 400
    policy = load_quality_policy(quality_policy_path())
    policy["common"] = payload.get("policy") or {}
    saved = save_quality_policy(quality_policy_path(), policy)
    return jsonify({"ok": True, "common": saved["common"]})


@app.route("/api/quality-policy/industry/<cid>", methods=["PUT"])
def save_industry_quality_policy(cid):
    client = require_client_access(cid)
    if not client:
        return jsonify({"error": "client_not_found"}), 404
    key = quality_policy_industry_key(client.get("industry", ""))
    if not key:
        return jsonify({"error": "client_industry_required"}), 400
    policy = load_quality_policy(quality_policy_path())
    policy["industries"][key] = (request.get_json(silent=True) or {}).get("policy") or {}
    saved = save_quality_policy(quality_policy_path(), policy)
    return jsonify({"ok": True, "industry": {"name": client.get("industry", ""), "key": key, "policy": saved["industries"][key]}})

@app.route("/api/clients", methods=["POST"])
def add_client():
    clients = load(F_CLIENTS, [])
    d = request.json
    user = current_user() or {}
    owner_username = user.get("username", "")
    if is_admin(user) and d.get("owner_username"):
        owner_username = str(d.get("owner_username")).strip()
    c = {"id": uid(), "name": d["name"], "brand": d["brand"],
         "industry": d.get("industry",""), "goal": d.get("goal",""),
         "contract_platforms": normalize_contract_platforms(d.get("contract_platforms", [])),
         "owner_username": owner_username,
         "created": today_str()}
    clients.append(c)
    save(F_CLIENTS, clients)
    return jsonify({"ok": True, "client": c})

@app.route("/api/clients/<cid>", methods=["PUT"])
def update_client(cid):
    clients = load(F_CLIENTS, [])
    d = request.json or {}
    legacy_fields = {"audience_angles", "faq_questions", "competitor_rules"}
    if legacy_fields.intersection(d):
        return jsonify({"error": "legacy_content_options_removed"}), 400
    updated = None
    for client in clients:
        if client["id"] != cid:
            continue
        if not can_access_client(client):
            return jsonify({"error": "client_not_found"}), 404
        if "contract_platforms" in d:
            client["contract_platforms"] = normalize_contract_platforms(d.get("contract_platforms", []))
        for key in ["name", "brand", "industry", "goal"]:
            if key in d:
                client[key] = d.get(key, "")
        updated = client
        break
    if not updated:
        return jsonify({"error": "client_not_found"}), 404
    save(F_CLIENTS, clients)
    return jsonify({"ok": True, "client": updated})

@app.route("/api/clients/<cid>", methods=["DELETE"])
def del_client(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    clients = [c for c in load(F_CLIENTS, []) if c["id"] != cid]
    save(F_CLIENTS, clients)

    # Keep local JSON stores from retaining orphaned customer data.
    probes = load(F_PROBES, {})
    if cid in probes:
        probes.pop(cid, None)
        save(F_PROBES, probes)

    groups = load(F_GROUPS, {})
    if cid in groups:
        groups.pop(cid, None)
        save(F_GROUPS, groups)

    for path in [F_RECORDS, F_RAW_RECORDS, F_ARTICLES]:
        rows = load(path, [])
        if isinstance(rows, list):
            kept = [r for r in rows if r.get("client_id") != cid]
            if len(kept) != len(rows):
                save(path, kept)

    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════
# 问题组管理模块
# ══════════════════════════════════════════════════════

@app.route("/api/groups/<cid>", methods=["GET"])
def get_groups(cid):
    """获取客户的所有问题组"""
    groups = load(F_GROUPS, {})
    return jsonify(groups.get(cid, []))

@app.route("/api/groups/<cid>", methods=["POST"])
def add_group(cid):
    """新建问题组"""
    d = request.json
    groups = load(F_GROUPS, {})
    if cid not in groups:
        groups[cid] = []
    group = {
        "id": uid(),
        "client_id": cid,
        "name": d["name"],
        "description": d.get("description", ""),
        "questions": d.get("questions", []),
        "created": today_str()
    }
    groups[cid].append(group)
    save(F_GROUPS, groups)
    return jsonify({"ok": True, "group": group})

@app.route("/api/groups/<cid>/<gid>", methods=["PUT"])
def update_group(cid, gid):
    """更新问题组（名称/描述/问题列表）"""
    d = request.json
    groups = load(F_GROUPS, {})
    for g in groups.get(cid, []):
        if g["id"] == gid:
            if "name" in d: g["name"] = d["name"]
            if "description" in d: g["description"] = d["description"]
            if "questions" in d: g["questions"] = d["questions"]
    save(F_GROUPS, groups)
    return jsonify({"ok": True})

@app.route("/api/groups/<cid>/<gid>", methods=["DELETE"])
def del_group(cid, gid):
    """删除问题组"""
    groups = load(F_GROUPS, {})
    groups[cid] = [g for g in groups.get(cid, []) if g["id"] != gid]
    save(F_GROUPS, groups)
    return jsonify({"ok": True})

@app.route("/api/groups/<cid>/<gid>/questions", methods=["POST"])
def add_question_to_group(cid, gid):
    """向问题组添加问题"""
    d = request.json
    groups = load(F_GROUPS, {})
    for g in groups.get(cid, []):
        if g["id"] == gid:
            q = d.get("question", "").strip()
            if q and q not in g["questions"]:
                g["questions"].append(q)
    save(F_GROUPS, groups)
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════
# 细化爬取记录模块
# ══════════════════════════════════════════════════════

def save_raw_record(client_id, group_id, brand, question, round_num,
                    answer, search_keywords, refs, analysis,
                    source_platform="doubao", task_id="", run_id="",
                    task_report="", crawler_engine=""):
    """保存单次爬取的完整原始记录"""
    return record_store.save_raw_record(
        F_RAW_RECORDS,
        F_SETTINGS,
        D,
        client_id,
        group_id,
        brand,
        question,
        round_num,
        answer,
        search_keywords,
        refs,
        analysis,
        uid,
        today_str,
        now_str,
        source_platform=source_platform,
        task_id=task_id,
        run_id=run_id,
        task_report=task_report,
        crawler_engine=crawler_engine,
    )


def auto_normalize_task_entities(client_id, date_str, task_id="", username=None, group_id="", platform=""):
    """Incrementally extract competitor entities for records created by one crawl task."""
    settings = get_settings(username)
    if not settings.get("api_key"):
        return {"ok": True, "skipped": True, "reason": "missing_api_key", "changed": 0}
    if not client_id or not date_str:
        return {"ok": False, "skipped": True, "reason": "missing_scope", "changed": 0}

    from scripts import normalize_entities

    records = load(F_RAW_RECORDS, [])
    selected = normalize_entities.select_records(
        records,
        client_id=client_id,
        date=date_str,
        task_id=task_id,
        group_id=group_id,
        platform=platform,
        include_existing=False,
    )
    if not selected:
        return {"ok": True, "skipped": True, "reason": "no_missing_records", "changed": 0}

    clients = load(F_CLIENTS, [])
    competitor_category = normalize_entities.resolve_competitor_category("", client_id, clients)
    own_brand = normalize_entities.resolve_own_brand(client_id, clients)
    report_body = normalize_entities.build_extract_missing_report(
        selected,
        {**settings, "progress": False},
        use_llm=True,
        competitor_category=competitor_category,
        own_brand=own_brand,
    )
    report = {
        "dry_run": False,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "client_id": client_id,
        "date": date_str,
        "task_id": task_id,
        "group_id": group_id,
        "source_platform": platform,
        "competitor_category": competitor_category,
        "own_brand": own_brand,
        "data_written": False,
        **report_body,
    }
    apply_result = normalize_entities.apply_competitor_report_results(F_RAW_RECORDS, records, report)
    report["data_written"] = True
    report["apply_result"] = apply_result
    report_dir = os.path.join(D, "reports")
    report_path = normalize_entities.write_report(report_dir, client_id, report)
    return {
        "ok": True,
        "skipped": False,
        "changed": apply_result["changed"],
        "backup_path": apply_result["backup_path"],
        "report_path": report_path,
        "selected_records": report_body.get("selected_records", 0),
        "final_entities": len(report_body.get("final_competitor_summary") or []),
    }


def run_entity_normalize_task(client_id, date_str, task_id, task_report_path, username=None, group_id="", platform=""):
    try:
        result = auto_normalize_task_entities(
            client_id,
            date_str,
            task_id,
            username=username,
            group_id=group_id,
            platform=platform,
        )
    except Exception as exc:
        result = {"ok": False, "status": "failed", "error": str(exc), "changed": 0}
    report = load(task_report_path, {})
    report["entity_normalize"] = result
    report["entity_normalize_finished_at"] = now_str()
    save(task_report_path, report)
    return result


def queue_entity_normalize_task(client_id, date_str, task_id, task_report_path, username=None, group_id="", platform=""):
    status = {"ok": True, "status": "queued", "queued": True}
    thread = threading.Thread(
        target=run_entity_normalize_task,
        args=(client_id, date_str, task_id, task_report_path, username, group_id, platform),
        daemon=True,
    )
    thread.start()
    return status

@app.route("/api/records/question_trend", methods=["GET"])
def question_trend():
    client_id = (request.args.get("client_id") or "").strip()
    if not client_id or not require_client_access(client_id):
        return jsonify({"error": "client_not_found"}), 404
    question = request.args.get("question") or ""
    return jsonify({
        "client_id": client_id,
        "question": question,
        "trend": build_question_trend(load_client_records(client_id), question),
    })


@app.route("/api/records/question_articles", methods=["GET"])
def question_articles():
    client_id = (request.args.get("client_id") or "").strip()
    if not client_id or not require_client_access(client_id):
        return jsonify({"error": "client_not_found"}), 404
    question = (request.args.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question_required"}), 400
    group_id = (request.args.get("group_id") or "").strip()
    records = load_client_records(client_id, group_id=group_id or None, question=question)
    return jsonify({
        "client_id": client_id,
        "group_id": group_id,
        "question": question,
        **build_question_article_list(records),
    })


@app.route("/api/records/group_trend", methods=["GET"])
def group_trend():
    client_id = (request.args.get("client_id") or "").strip()
    group_id = (request.args.get("group_id") or "").strip()
    if not client_id or not require_client_access(client_id):
        return jsonify({"error": "client_not_found"}), 404
    group = next((item for item in load(F_GROUPS, {}).get(client_id, []) if item.get("id") == group_id), None)
    if not group:
        return jsonify({"error": "group_not_found"}), 404
    trend = build_group_mention_trend(
        load_client_records(client_id, group_id=group_id),
        group.get("questions", []),
        request.args.get("platform") or "",
    )
    return jsonify({"client_id": client_id, "group_id": group_id, **trend})


@app.route("/api/records/article_pool", methods=["GET"])
def article_pool():
    client_id = (request.args.get("client_id") or "").strip()
    if not client_id or not require_client_access(client_id):
        return jsonify({"error": "client_not_found"}), 404
    pool = build_article_pool(load_client_records(client_id), request.args.get("date") or None)
    return jsonify({"client_id": client_id, **pool})


@app.route("/api/records/source_trend", methods=["GET"])
def source_trend():
    client_id = (request.args.get("client_id") or "").strip()
    if not client_id or not require_client_access(client_id):
        return jsonify({"error": "client_not_found"}), 404
    return jsonify({"client_id": client_id, **build_source_trend(load_client_records(client_id))})


def selection_evidence_service():
    return SelectionEvidenceService(Path(D) / "selection_evidence", fetch_article=fetch_article_text)


def selection_surface_report_paths(cid):
    root = (Path(D) / "selection_surface_reports").resolve()
    client_dir = (root / str(cid)).resolve()
    if client_dir.parent != root or not client_dir.is_dir():
        return []
    return sorted(
        (path for path in client_dir.iterdir()
         if path.is_file() and path.name.endswith("_selection_surface.md")),
        key=lambda path: path.name,
        reverse=True,
    )


@app.route("/api/records/selection-reports/<cid>", methods=["GET"])
def list_selection_surface_reports(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    reports = [{
        "id": path.name,
        "name": path.name,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    } for path in selection_surface_report_paths(cid)]
    return jsonify({"client_id": cid, "reports": reports})


@app.route("/api/records/selection-reports/<cid>/<report_id>", methods=["GET"])
def read_selection_surface_report(cid, report_id):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    allowed_reports = {path.name: path for path in selection_surface_report_paths(cid)}
    path = allowed_reports.get(report_id)
    if path is None:
        return jsonify({"error": "report_not_found"}), 404
    return jsonify({"client_id": cid, "id": path.name, "content": path.read_text(encoding="utf-8", errors="replace")})


@app.route("/api/records/selection-evidence/<cid>", methods=["GET"])
def get_selection_evidence(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    return jsonify({"client_id": cid, "rows": selection_evidence_service().load_query_scene_rows(
        cid, load(F_GROUPS, {}).get(cid, []),
    )})


@app.route("/api/records/selection-evidence/<cid>", methods=["POST"])
def save_selection_evidence(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    group_id = str(payload.get("group_id") or "").strip()
    query = str(payload.get("query") or "").strip()
    group = next((item for item in load(F_GROUPS, {}).get(cid, []) if item.get("id") == group_id), None)
    if not group or query not in (group.get("questions") or []):
        return jsonify({"error": "scene_query_not_found"}), 404
    try:
        row = selection_evidence_service().save_query_scene_terms(
            cid, group_id, group.get("name", ""), query, payload.get("scene_terms") or [],
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"client_id": cid, "row": row})


@app.route("/api/records/selection-evidence/<cid>/refresh", methods=["POST"])
def refresh_selection_evidence(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    all_records = load_client_records(cid)
    source_date = str(payload.get("date") or "").strip()
    if not source_date:
        source_date = max((str(record.get("today") or "").strip() for record in all_records), default="")
    records = [record for record in all_records if not source_date or record.get("today") == source_date]
    result = selection_evidence_service().refresh_query_scenes(
        cid,
        load(F_GROUPS, {}).get(cid, []),
        records,
        ai_json,
        dry_run=bool(payload.get("dry_run")),
    )
    return jsonify({"client_id": cid, "source_date": source_date, **result})


@app.route("/api/raw_records", methods=["GET"])
def get_raw_records():
    """查询细化爬取记录，支持多维过滤"""
    client_id = request.args.get("client_id", "")
    group_id = request.args.get("group_id", "")
    date = request.args.get("date", "")
    question = request.args.get("question", "")
    mentioned_only = request.args.get("mentioned_only", "")
    platform = request.args.get("platform", "")  # 按爬取平台过滤
    task_id = request.args.get("task_id", "")
    records = load_client_records(
        client_id,
        date=date,
        group_id=group_id,
        platform=platform,
        task_id=task_id,
        question=question,
        mentioned_only=mentioned_only,
    )
    return jsonify(sorted(records, key=lambda x: x["crawl_time"], reverse=True))

@app.route("/api/raw_records/platform_stats", methods=["GET"])
def platform_stats():
    """平台引用统计分析"""
    client_id = request.args.get("client_id", "")
    group_id = request.args.get("group_id", "")
    question_filter = request.args.get("question", "")
    mentioned_only = request.args.get("mentioned_only", "")
    source_platform = request.args.get("platform", "")  # 按爬取平台过滤
    task_id = request.args.get("task_id", "")
    date = request.args.get("date", "")
    records = load_client_records(
        client_id,
        date=None if date == "all" else date,
        group_id=group_id,
        platform=source_platform,
        task_id=task_id,
        question=question_filter,
        mentioned_only=mentioned_only,
    )

    return jsonify(build_raw_platform_stats(records))

UPLOAD_FOLDER = "data/uploads"
F_MATERIALS_INDEX = f"{D}/materials_index.json"
MATERIAL_CACHE_FOLDER = f"{D}/material_cache"
CONTENT_UPLOAD_FOLDER = f"{D}/content_uploads"
F_CONTENT_MATERIALS_INDEX = f"{D}/content_materials_index.json"
CONTENT_MATERIAL_CACHE_FOLDER = f"{D}/content_material_cache"
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md', 'docx', 'doc', 'xlsx', 'xls'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONTENT_UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def material_service():
    return MaterialService(
        root_dir=".",
        upload_dir=UPLOAD_FOLDER,
        index_path=F_MATERIALS_INDEX,
        cache_dir=MATERIAL_CACHE_FOLDER,
    )

def content_material_service():
    return MaterialService(
        root_dir=".",
        upload_dir=CONTENT_UPLOAD_FOLDER,
        index_path=F_CONTENT_MATERIALS_INDEX,
        cache_dir=CONTENT_MATERIAL_CACHE_FOLDER,
    )

def upload_and_parse_material_files(cid, service):
    files = request.files.getlist('file')
    if not files:
        return [], "没有文件"
    materials = []
    for file in files:
        if not file or not file.filename:
            continue
        if not allowed_file(file.filename):
            return [], "不支持的文件格式，请上传 txt/pdf/md/doc/docx/xlsx/xls"
        material = service.save_uploaded_material(cid, file, file.filename)
        materials.append(service.parse_material(cid, material["id"]))
    if not materials:
        return [], "没有文件"
    return materials, ""

def material_package_output_dir(cid):
    return Path(D) / "material_packages" / cid

def competitor_package_output_dir(cid):
    return Path(D) / "competitor_material_packages" / cid

def quality_policy_path():
    return Path(D) / "quality_gate" / "policy.json"

def client_quality_policy(cid):
    client = next((item for item in load(F_CLIENTS, []) if item.get("id") == cid), {})
    return effective_quality_policy(load_quality_policy(quality_policy_path()), client.get("industry", ""))

@app.route("/api/quality-gate/articles/upload", methods=["POST"])
def upload_quality_gate_article():
    cid = str(request.form.get("client_id") or "").strip()
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    storage_file = request.files.get("file")
    if not storage_file or not storage_file.filename:
        return jsonify({"error": "file_required"}), 400
    try:
        uploaded = uploaded_publication_article(storage_file)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    client = get_client(cid) or {}
    content = f"{uploaded['title']}\n{uploaded['content']}".strip()
    gate_report = run_quality_gate(
        uploaded["title"], content, {}, {"source": "operator_upload"},
        client_brand=client.get("brand", ""), competitor_names=[], competitor_markdown="",
        recent_articles=recent_content_generation_articles(cid), ai_json_fn=ai_json,
        customer_material_text=knowledge_base_service().load_customer_master(cid).get("content", "").strip(),
        content_upload_text="", industry=client.get("industry", ""), policy=client_quality_policy(cid),
    )
    created_at = now_str()
    article = append_content_generation(cid, {
        "id": uid(), "client_id": cid, "title": uploaded["title"], "content": content,
        "model": "operator-upload", "material_count": 0, "article_type": "",
        "route_context": {"source": "operator_upload"}, "gate_report": gate_report,
        "created_at": created_at, "created_by": (current_user() or {}).get("username", ""),
    }, {}, {"role": "assistant", "content": content, "created_at": created_at})
    return jsonify({"ok": True, "article": article})

def knowledge_base_service():
    return KnowledgeBaseService(Path(D) / "knowledge_base")

def competitor_knowledge_article_cache_path(cid):
    return Path(D) / "knowledge_base" / cid / "competitor_article_sources.json"

def competitor_knowledge_context(cid, date_str="", group_id="", task_id="", platform=""):
    all_records = load_client_records(cid)
    source_date = str(date_str or "").strip() or max(
        (str(record.get("today") or "").strip() for record in all_records), default=""
    )
    records = load_client_records(
        cid,
        date=source_date,
        group_id=group_id or None,
        task_id=task_id or None,
        platform=platform or None,
    ) if source_date else []
    entities = default_competitor_entities(
        cid, source_date, group_id=group_id, task_id=task_id, platform=platform
    ) if source_date else []
    hit_report = load_competitor_article_body_hit_report(
        cid, source_date, task_id=task_id, group_id=group_id, platform=platform
    ) if source_date else None
    package_dir = competitor_package_output_dir(cid)
    upload_path = package_dir / "latest_upload_competitors.md"
    web_path = package_dir / "latest_web_competitors.md"
    fallback = merge_competitor_master_markdown(
        build_competitor_master_input(
        [item.get("name", "") for item in entities],
        (hit_report or {}).get("body_hits", []),
        upload_path.read_text(encoding="utf-8", errors="ignore") if upload_path.exists() else "",
        ),
        web_path.read_text(encoding="utf-8", errors="ignore") if web_path.exists() else "",
    )
    return source_date, records, entities, fallback

def competitor_knowledge_input(cid, ask_text=None, fetch_fn=None, persist_cache=True,
                               date_str="", group_id="", task_id="", platform=""):
    source_date, records, entities, fallback = competitor_knowledge_context(
        cid, date_str=date_str, group_id=group_id, task_id=task_id, platform=platform
    )
    if not records:
        return fallback

    article_cache_path = competitor_knowledge_article_cache_path(cid)
    article_cache_body = load_json(article_cache_path, {"articles": {}}) if article_cache_path.exists() else {"articles": {}}
    local_cache = article_cache_body.get("articles", {}) if isinstance(article_cache_body, dict) else {}
    cached = dict(local_cache) if isinstance(local_cache, dict) else {}
    fetch_fn = fetch_fn or (lambda url: fetch_article_text(url, timeout=25, max_chars=12000, browser_fallback=True))
    articles = collect_high_frequency_article_sources(records, cached, fetch_fn, limit=12)
    saved_cache = dict(local_cache) if isinstance(local_cache, dict) else {}
    for article in articles:
        if article.get("ok") and article.get("content"):
            saved_cache[article["url"]] = {
                key: article.get(key, "")
                for key in ("ok", "title", "description", "content", "error")
            }
    if persist_cache and saved_cache:
        save_json(article_cache_path, {"articles": saved_cache, "source_date": source_date})

    usable = [article for article in articles if article.get("ok") and article.get("content")]
    if not usable:
        return fallback
    ask_text = ask_text or (lambda prompt, max_tokens: ai_with_settings(prompt, max_tokens, get_settings()))
    high_frequency = []
    batches = [usable[index:index + 4] for index in range(0, len(usable), 4)]
    for index, batch in enumerate(batches, 1):
        try:
            extracted = str(ask_text(
                build_high_frequency_competitor_prompt(
                    [item.get("name", "") for item in entities], batch, index, len(batches),
                ),
                6000,
            ) or "")
        except Exception:
            continue
        if extracted.strip():
            high_frequency.append(extracted)
    if not high_frequency:
        return fallback
    return merge_competitor_master_markdown(*high_frequency, fallback)

def competitor_upload_dir(cid):
    return competitor_package_output_dir(cid) / "uploads"

def material_package_ask_json(settings, model_name):
    chosen = {**settings, "model": model_name}
    return lambda prompt, max_tokens: ai_json_with_settings(prompt, max_tokens, chosen)

def material_package_ask_text(settings, model_name):
    chosen = {**settings, "model": model_name}
    return lambda prompt, max_tokens: ai_with_settings(prompt, max_tokens, chosen)

def run_client_material_package_analysis(cid):
    package_dir = Path(UPLOAD_FOLDER) / cid
    if not package_dir.exists() or not any(path.is_file() for path in package_dir.rglob("*")):
        raise FileNotFoundError("no_material_files")
    settings = get_settings()
    models = {
        "filter": choose_material_filter_model(settings),
        "reducer": choose_material_reducer_model(settings),
        "output": choose_material_output_model(settings),
    }
    result = run_material_package_pipeline(
        package_dir,
        material_package_output_dir(cid),
        ask_filter_json=material_package_ask_json(settings, models["filter"]),
        ask_reducer_json=material_package_ask_json(settings, models["reducer"]),
        ask_output_text=material_package_ask_text(settings, models["output"]),
        models=models,
    )
    if result.get("ok"):
        result["knowledge_merge"] = knowledge_base_service().sync_customer_master(
            cid, material_package_output_dir(cid),
        )
    return result

def client_material_web_context(cid):
    client = next((c for c in load(F_CLIENTS, []) if c.get("id") == cid), None) or {"id": cid}
    output_dir = material_package_output_dir(cid)
    injection_path = output_dir / "latest_injection.md"
    if not injection_path.exists():
        raise FileNotFoundError("material_injection_not_found")
    return client, output_dir, injection_path.read_text(encoding="utf-8", errors="ignore")

def run_client_material_web_expansion(cid):
    client, output_dir, injection_markdown = client_material_web_context(cid)
    knowledge_base_service().sync_customer_master(cid, output_dir)
    settings = get_settings()
    tavily_key = get_tavily_api_key(settings)
    if not tavily_key:
        raise ValueError("missing_tavily_api_key")
    ask_text = lambda prompt, max_tokens: ai_with_settings(prompt, max_tokens, settings)
    search_fn = lambda query: tavily_search(query, tavily_key)
    result = expand_material_web_package(
        client=client,
        injection_markdown=injection_markdown,
        output_dir=output_dir,
        ask_text=ask_text,
        search_fn=search_fn,
    )
    if result.get("ok"):
        result["knowledge_merge"] = knowledge_base_service().sync_customer_master(cid, output_dir)
    return result

def default_competitor_entities(cid, date_str=None, limit=10, group_id="", task_id="", platform=""):
    client = next((c for c in load(F_CLIENTS, []) if c.get("id") == cid), None) or {}
    records = load_client_records(
        cid,
        date=date_str or today_str(),
        group_id=group_id or None,
        task_id=task_id or None,
        platform=platform or None,
    )
    from services.record_insights import build_record_insights
    insights = build_record_insights(
        records,
        own_brand=client.get("brand") or client.get("name") or "",
        own_client_name=client.get("name") or "",
    )
    return [
        {"name": item.get("name", ""), "count": item.get("count", 0), "type": item.get("type", "")}
        for item in (insights.get("mentioned_entities") or [])[:limit]
        if item.get("name")
    ]

def _request_competitors(payload):
    competitors = payload.get("competitors") if isinstance(payload, dict) else None
    if isinstance(competitors, str):
        competitors = re.split(r"[\n,，]+", competitors)
    return normalize_competitor_names(competitors or [])

def _client_or_404(cid):
    return next((c for c in load(F_CLIENTS, []) if c.get("id") == cid), None)

def run_client_competitor_web_expansion(cid, competitors, qualifier="", force=None):
    client = _client_or_404(cid) or {"id": cid}
    settings = get_settings()
    tavily_key = get_tavily_api_key(settings)
    if not tavily_key:
        raise ValueError("missing_tavily_api_key")
    ask_text = lambda prompt, max_tokens: ai_with_settings(prompt, max_tokens, settings)
    search_fn = lambda query: tavily_search(query, tavily_key, max_results=5)
    material_path = material_package_output_dir(cid) / "latest_injection.md"
    competitor_path = competitor_package_output_dir(cid) / "latest_upload_competitors.md"
    package_dir = competitor_package_output_dir(cid)
    knowledge_base_service().sync_competitor_master(cid, competitor_knowledge_context(cid)[3])
    result = expand_competitor_web_package(
        client=client,
        competitors=competitors,
        qualifier=qualifier,
        output_dir=package_dir,
        ask_text=ask_text,
        search_fn=search_fn,
        force=force,
        customer_context=material_path.read_text(encoding="utf-8", errors="ignore") if material_path.exists() else "",
        competitor_context=competitor_path.read_text(encoding="utf-8", errors="ignore") if competitor_path.exists() else "",
    )
    if result.get("ok"):
        result["knowledge_merge"] = knowledge_base_service().sync_competitor_master(
            cid, competitor_knowledge_context(cid)[3],
        )
    return result

@app.route("/api/materials/<cid>", methods=["GET"])
def get_materials(cid):
    """获取客户已上传的资料列表"""
    if cid == "local":
        return jsonify({"error": "not_found"}), 404
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    service = material_service()
    indexed = service.list_client_materials(cid)
    if indexed:
        return jsonify(indexed)
    client_dir = os.path.join(UPLOAD_FOLDER, cid)
    if not os.path.exists(client_dir):
        return jsonify([])
    files = []
    for f in os.listdir(client_dir):
        fpath = os.path.join(client_dir, f)
        files.append({
            "id": f,
            "name": f,
            "stored_name": f,
            "original_name": f,
            "size": os.path.getsize(fpath),
            "path": fpath,
            "source": "legacy_upload",
            "status": "未解析",
            "confirmed": False,
            "uploaded": datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M")
        })
    return jsonify(sorted(files, key=lambda x: x["uploaded"], reverse=True))

@app.route("/api/materials/<cid>/upload", methods=["POST"])
def upload_material(cid):
    """上传客户资料文件"""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        materials, error = upload_and_parse_material_files(cid, material_service())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if error:
        return jsonify({"error": error}), 400
    first = materials[0]
    return jsonify({
        "ok": True,
        "name": first.get("original_name"),
        "saved_as": first.get("stored_name"),
        "materials": materials,
    })

@app.route("/api/content/materials/<cid>", methods=["GET"])
def get_content_materials(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    return jsonify(content_material_service().list_client_materials(cid))

@app.route("/api/content/materials/<cid>/upload", methods=["POST"])
def upload_content_material(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        materials, error = upload_and_parse_material_files(cid, content_material_service())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if error:
        return jsonify({"error": error}), 400
    first = materials[0]
    return jsonify({
        "ok": True,
        "name": first.get("original_name"),
        "saved_as": first.get("stored_name"),
        "materials": materials,
    })

@app.route("/api/content/materials/<cid>/<material_id>/confirm", methods=["POST"])
def confirm_content_material(cid, material_id):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    data = request.get_json(silent=True) or {}
    confirmed = bool(data.get("confirmed", True))
    try:
        material = content_material_service().confirm_material(cid, material_id, confirmed)
    except KeyError:
        return jsonify({"error": "找不到资料"}), 404
    return jsonify({"ok": True, "material": material})

@app.route("/api/content/materials/<cid>/<material_id>", methods=["DELETE"])
def delete_content_material(cid, material_id):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    if not content_material_service().delete_material(cid, material_id):
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True})

@app.route("/api/materials/<cid>/analyze-package", methods=["POST"])
def analyze_material_package(cid):
    """Run the three-stage material package analysis for the current client's uploads."""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        status = run_client_material_package_analysis(cid)
    except FileNotFoundError:
        return jsonify({"error": "no_material_files"}), 400
    except Exception as exc:
        output_dir = material_package_output_dir(cid)
        output_dir.mkdir(parents=True, exist_ok=True)
        status = {"ok": False, "status": "failed", "error": str(exc)}
        save_json(output_dir / "latest_status.json", status)
        return jsonify(status), 500
    result = load_latest_material_package_result(material_package_output_dir(cid))
    return jsonify({**status, "markdown": result.get("markdown", "")})

@app.route("/api/materials/<cid>/package-result", methods=["GET"])
def get_material_package_result(cid):
    """Return latest material injection markdown for browser preview."""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    result = load_latest_material_package_result(material_package_output_dir(cid))
    if not result.get("markdown"):
        return jsonify({"ok": False, "status": result.get("status", {}).get("status", "missing"), "markdown": ""}), 404
    return jsonify(result)

@app.route("/api/materials/<cid>/expand-web", methods=["POST"])
def expand_material_package_web(cid):
    """Generate a lightweight public-web supplement for the latest material injection."""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        result = run_client_material_web_expansion(cid)
    except FileNotFoundError:
        return jsonify({"error": "material_injection_not_found"}), 404
    except ValueError as exc:
        if str(exc) == "missing_tavily_api_key":
            return jsonify({"error": "missing_tavily_api_key"}), 400
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(result)

@app.route("/api/materials/<cid>/web-supplement", methods=["GET"])
def get_material_web_supplement(cid):
    """Return latest web supplement markdown for browser preview."""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    path = material_package_output_dir(cid) / "latest_web_supplement.md"
    if not path.exists():
        return jsonify({"ok": False, "status": "missing", "markdown": ""}), 404
    markdown = path.read_text(encoding="utf-8", errors="ignore")
    return jsonify({"ok": True, "status": "completed", "markdown": markdown})

@app.route("/api/materials/<cid>/injection.md", methods=["GET"])
def download_material_injection(cid):
    """Download latest material injection markdown."""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    path = material_package_output_dir(cid) / "latest_injection.md"
    if not path.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(path, as_attachment=True, download_name="material_injection.md", mimetype="text/markdown; charset=utf-8")

@app.route("/api/materials/<cid>/web-supplement.md", methods=["GET"])
def download_material_web_supplement(cid):
    """Download latest web supplement markdown."""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    path = material_package_output_dir(cid) / "latest_web_supplement.md"
    if not path.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(path, as_attachment=True, download_name="material_web_supplement.md", mimetype="text/markdown; charset=utf-8")

@app.route("/api/competitors/<cid>/entities", methods=["GET"])
def get_competitor_entities(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    entities = default_competitor_entities(
        cid,
        date_str=request.args.get("date") or today_str(),
        limit=10,
    )
    return jsonify({"ok": True, "entities": entities})

@app.route("/api/competitors/<cid>/result", methods=["GET"])
def get_competitor_material_result(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    result = load_latest_competitor_result(competitor_package_output_dir(cid))
    if not result.get("ok"):
        return jsonify(result), 404
    return jsonify(result)

@app.route("/api/competitors/<cid>/analyze-upload", methods=["POST"])
def analyze_competitor_upload(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    files = request.files.getlist("file")
    if not files:
        return jsonify({"error": "no_competitor_material_files"}), 400
    upload_dir = competitor_upload_dir(cid) / uid()
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for file in files:
        if not file or not file.filename:
            continue
        if not allowed_file(file.filename):
            return jsonify({"error": "不支持的文件格式，请上传 txt/pdf/md/doc/docx/xlsx/xls"}), 400
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(file.filename).name).strip(" .")
        target = upload_dir / f"{uid()}_{safe_name or 'competitor_material'}"
        file.save(str(target))
        saved.append(str(target))
    if not saved:
        return jsonify({"error": "no_competitor_material_files"}), 400
    competitors = normalize_competitor_names(
        re.split(r"[\n,，]+", request.form.get("competitors", ""))
    )
    if not competitors:
        competitors = [item["name"] for item in default_competitor_entities(cid)]
    settings = get_settings()
    ask_text = lambda prompt, max_tokens: ai_with_settings(prompt, max_tokens, settings)
    try:
        result = analyze_competitor_upload_package(
            upload_dir,
            competitor_package_output_dir(cid),
            competitors,
            ask_text=ask_text,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    if result.get("ok"):
        result["knowledge_merge"] = knowledge_base_service().sync_competitor_master(
            cid, competitor_knowledge_context(cid)[3],
        )
    return jsonify(result)

@app.route("/api/competitors/<cid>/expand-web", methods=["POST"])
def expand_competitor_web(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    payload = request.json or {}
    competitors = _request_competitors(payload)
    if not competitors:
        competitors = [item["name"] for item in default_competitor_entities(cid)]
    if not competitors:
        return jsonify({"error": "missing_competitors"}), 400
    try:
        result = run_client_competitor_web_expansion(
            cid,
            competitors,
            qualifier=(payload.get("qualifier") or "").strip(),
            force=_request_competitors({"competitors": payload.get("force")}),
        )
    except ValueError as exc:
        if str(exc) == "missing_tavily_api_key":
            return jsonify({"error": "missing_tavily_api_key"}), 400
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(result)


@app.route("/api/knowledge/customer/<cid>", methods=["GET"])
def get_customer_knowledge_master(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    result = knowledge_base_service().sync_customer_master(cid, material_package_output_dir(cid))
    return jsonify({"ok": True, **result})


@app.route("/api/knowledge/customer/<cid>/sync", methods=["POST"])
def sync_customer_knowledge_master(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    result = knowledge_base_service().sync_customer_master(
        cid,
        material_package_output_dir(cid),
        overwrite=bool(payload.get("overwrite")),
    )
    return jsonify({"ok": True, **result})


@app.route("/api/knowledge/customer/<cid>", methods=["PUT"])
def save_customer_knowledge_master(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        result = knowledge_base_service().save_customer_master(
            cid,
            str((request.get_json(silent=True) or {}).get("content") or ""),
            (request.get_json(silent=True) or {}).get("removed_sections") or [],
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, **result})


@app.route("/api/knowledge/customer/<cid>/migration", methods=["GET"])
def prepare_customer_knowledge_migration(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    result = knowledge_base_service().prepare_customer_fact_migration(cid, material_package_output_dir(cid))
    return jsonify({"ok": True, **result})


@app.route("/api/knowledge/customer/<cid>/migration", methods=["POST"])
def confirm_customer_knowledge_migration(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        result = knowledge_base_service().confirm_customer_fact_migration(
            cid, str((request.get_json(silent=True) or {}).get("content") or ""), material_package_output_dir(cid),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, **result})


@app.route("/api/knowledge/competitors/<cid>", methods=["GET"])
def get_competitor_knowledge_master(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    service = knowledge_base_service()
    _source_date, _records, _entities, existing_materials = competitor_knowledge_context(cid)
    result = service.sync_competitor_master(cid, existing_materials)
    return jsonify({"ok": True, **result})


@app.route("/api/knowledge/competitors/<cid>/sync", methods=["POST"])
def sync_competitor_knowledge_master(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    result = knowledge_base_service().sync_competitor_master(
        cid,
        competitor_knowledge_input(
            cid,
            date_str=str(payload.get("date") or "").strip(),
            group_id=str(payload.get("group_id") or "").strip(),
            task_id=str(payload.get("task_id") or "").strip(),
            platform=str(payload.get("platform") or "").strip(),
        ),
        overwrite=bool(payload.get("overwrite")),
    )
    return jsonify({"ok": True, **result})


@app.route("/api/knowledge/competitors/<cid>", methods=["PUT"])
def save_competitor_knowledge_master(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        result = knowledge_base_service().save_competitor_master(
            cid,
            str((request.get_json(silent=True) or {}).get("content") or ""),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, **result})


@app.route("/api/competitors/<cid>/upload.md", methods=["GET"])
def download_competitor_upload_markdown(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    path = competitor_package_output_dir(cid) / "latest_upload_competitors.md"
    if not path.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(path, as_attachment=True, download_name="competitor_upload_materials.md", mimetype="text/markdown; charset=utf-8")

@app.route("/api/competitors/<cid>/web.md", methods=["GET"])
def download_competitor_web_markdown(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    path = competitor_package_output_dir(cid) / "latest_web_competitors.md"
    if not path.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(path, as_attachment=True, download_name="competitor_web_materials.md", mimetype="text/markdown; charset=utf-8")

@app.route("/api/materials/<cid>/<material_id>/parse", methods=["POST"])
def parse_material(cid, material_id):
    """解析资料并生成清洗文本与诊断信息。"""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        material = material_service().parse_material(cid, material_id)
    except KeyError:
        return jsonify({"error": "找不到资料"}), 404
    return jsonify({"ok": True, "material": material})

@app.route("/api/materials/<cid>/<material_id>/confirm", methods=["POST"])
def confirm_material(cid, material_id):
    """确认或取消确认资料参与内容生成。"""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    data = request.get_json(silent=True) or {}
    confirmed = bool(data.get("confirmed", True))
    try:
        material = material_service().confirm_material(cid, material_id, confirmed)
    except KeyError:
        return jsonify({"error": "找不到资料"}), 404
    return jsonify({"ok": True, "material": material})

@app.route("/api/materials/<cid>/<filename>", methods=["DELETE"])
def del_material(cid, filename):
    """删除资料文件"""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    service = material_service()
    if not service.delete_material(cid, filename):
        fpath = os.path.join(UPLOAD_FOLDER, cid, filename)
        if os.path.exists(fpath):
            os.remove(fpath)
    return jsonify({"ok": True})

def content_material_package_section(path, label):
    if not path.exists():
        return None
    markdown = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not markdown:
        return None
    stat = path.stat()
    return {
        "text": f"【{label}：{path.name}】\n{markdown}",
        "file": {
            "id": path.name,
            "name": path.name,
            "original_name": label,
            "source": "material_package",
            "size": stat.st_size,
            "path": str(path),
            "confirmed": True,
            "uploaded": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        },
    }

def read_content_material_bundle(
    cid,
    include_material_package=True,
    include_material_web_supplement=True,
):
    bundle = content_material_service().build_generation_bundle(cid)
    sections = [bundle.get("text", "").strip()] if bundle.get("text", "").strip() else []
    files = list(bundle.get("files") or [])
    output_dir = material_package_output_dir(cid)
    package_sources = []
    if include_material_package:
        package_sources.append(content_material_package_section(output_dir / "latest_injection.md", "AI解析资料包"))
    if include_material_web_supplement:
        package_sources.append(content_material_package_section(output_dir / "latest_web_supplement.md", "AI联网扩展资料包"))
    for source in package_sources:
        if not source:
            continue
        sections.append(source["text"])
        files.append(source["file"])
    combined = "\n\n---\n\n".join(sections)
    return {
        **bundle,
        "text": combined,
        "files": files,
        "material_count": len(files),
        "confirmed_count": len(files),
    }


def read_content_generation_sources(cid, include_material_package=True, include_material_web_supplement=True,
                                    include_content_uploads=True, include_competitors=True):
    content_bundle = (
        content_material_service().build_generation_bundle(cid)
        if include_content_uploads else {"text": "", "files": []}
    )
    package_dir = material_package_output_dir(cid)
    customer_sections = []
    package_files = []
    if include_material_package:
        source = content_material_package_section(package_dir / "latest_injection.md", "AI解析资料包")
        if source:
            customer_sections.append(source["text"])
            package_files.append(source["file"])
    if include_material_web_supplement:
        source = content_material_package_section(package_dir / "latest_web_supplement.md", "AI联网扩展资料包")
        if source:
            customer_sections.append(source["text"])
            package_files.append(source["file"])
    competitor_text = ""
    if include_competitors:
        competitor_dir = competitor_package_output_dir(cid)
        competitor_text = "\n\n---\n\n".join(
            text for text in [
                (competitor_dir / "latest_upload_competitors.md").read_text(encoding="utf-8", errors="ignore").strip()
                if (competitor_dir / "latest_upload_competitors.md").exists() else "",
                (competitor_dir / "latest_web_competitors.md").read_text(encoding="utf-8", errors="ignore").strip()
                if (competitor_dir / "latest_web_competitors.md").exists() else "",
            ] if text
        )
    return {
        "customer_material_text": "\n\n---\n\n".join(customer_sections),
        "content_upload_text": content_bundle.get("text", "").strip(),
        "competitor_markdown": competitor_text,
        "files": list(content_bundle.get("files") or []) + package_files,
    }


def read_selected_competitor_facts(cid, selected_names):
    """Read only operator-selected competitor sections from the independent competitor master."""
    selected = [str(name or "").strip() for name in selected_names or [] if str(name or "").strip()]
    master = knowledge_base_service().load_competitor_master(cid).get("content", "")
    sections = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", master))
    available = {}
    for index, match in enumerate(sections):
        name = match.group(1).strip()
        end = sections[index + 1].start() if index + 1 < len(sections) else len(master)
        facts = master[match.end():end].strip()
        if name and facts:
            available[name] = facts
    missing = [name for name in selected if name not in available]
    if missing:
        raise ValueError("selected_competitor_not_found:" + ",".join(missing))
    return [{"name": name, "facts": available[name]} for name in selected]


def _clean_scene_terms(value):
    terms = []
    for item in value or []:
        term = str(item or "").strip()
        if term and term not in terms:
            terms.append(term[:80])
    return terms


def content_generation_scene_terms(cid, group_id, query):
    """Keep the selected Query primary, with same-group terms as optional context."""
    query = str(query or "").strip()
    group_id = str(group_id or "").strip()
    primary = []
    supplementary = []
    for row in selection_evidence_service().load_query_scene_rows(cid):
        row_query = str(row.get("query") or "").strip()
        terms = _clean_scene_terms(row.get("scene_terms"))
        if row_query == query:
            primary = terms
        elif group_id and str(row.get("group_id") or "").strip() == group_id and row_query and terms:
            supplementary.append({"query": row_query, "scene_terms": terms})
    return {"primary": primary, "supplementary": supplementary}


def content_query_scene_terms(cid, query):
    """Compatibility helper for callers that only need the exact Query terms."""
    return content_generation_scene_terms(cid, "", query)["primary"]


def get_client(cid):
    return next((c for c in load(F_CLIENTS, []) if c.get("id") == cid), None)

def normalize_content_history_date(value):
    value = str(value or "").strip()
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return ""
    y, m, d = value[:4], value[5:7], value[8:10]
    return value if y.isdigit() and m.isdigit() and d.isdigit() else ""


def recent_content_generation_articles(cid, days=30):
    cutoff = date.today() - timedelta(days=max(1, int(days)))
    recent = []
    for article in load_content_session(cid).get("articles", []):
        created_at = str(article.get("created_at") or "")[:10]
        try:
            if datetime.strptime(created_at, "%Y-%m-%d").date() >= cutoff:
                recent.append(article)
        except ValueError:
            continue
    return recent


def generate_content_draft(messages, ai_text_fn=None):
    ai_text_fn = ai_text_fn or ai_deepseek_pro
    for _ in range(2):
        content = str(ai_text_fn(messages, 10000) or "").strip()
        if content:
            return content
    raise ValueError("empty_content_generation_response")


def run_content_generation(payload, created_by="", batch_id=""):
    with content_generation_lock:
        return _run_content_generation(payload, created_by=created_by, batch_id=batch_id)


def _run_content_generation(payload, created_by="", batch_id=""):
    """Run the only supported, explicit-material content-generation path."""
    return _run_content_route_generation(dict(payload or {}), created_by=created_by, batch_id=batch_id)


def content_route_library_service():
    return ContentRouteLibrary(Path(D) / "content_route_library")


def reference_intelligence_task_path(cid):
    return Path(D) / "reference_intelligence_tasks" / f"{cid}.json"


def save_reference_intelligence_task(cid, task):
    path = reference_intelligence_task_path(cid)
    history = load(str(path), [])
    history = history if isinstance(history, list) else []
    history.append(task)
    save(str(path), history[-100:])


def reference_route_source(analysis, candidate, query, ai_platform):
    return {
        **dict(analysis.get("source") or {}),
        "source_evidence": list(analysis.get("source_evidence") or []),
        "citation_contexts": [{
            "query": query,
            "ai_platform": ai_platform,
            "citation_count": int(candidate.get("citation_count") or 0),
        }],
    }


def apply_reference_batch_updates(industry, library, analyses, candidates, query, ai_platform, updates):
    routes = []
    for update in updates:
        indexes = update.get("analysis_indexes") if isinstance(update.get("analysis_indexes"), list) else []
        sources = [
            reference_route_source(analyses[index], candidates[index], query, ai_platform)
            for index in indexes
            if isinstance(index, int) and 0 <= index < len(analyses)
        ]
        if not sources:
            continue
        if update.get("action") == "create":
            entry = library.create_route(industry, update["route"], sources[0])
            for source in sources[1:]:
                entry = library.add_or_merge_source(industry, entry["id"], source)
            routes.append(entry)
        elif update.get("action") == "reinforce":
            entry = None
            for source in sources:
                entry = library.add_or_merge_source(industry, update["route_id"], source)
            if entry:
                routes.append(entry)
    return routes


@app.route("/api/content-routes", methods=["GET"])
def get_content_routes():
    cid = str(request.args.get("client_id") or "").strip()
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    client = get_client(cid) or {}
    industry = str(client.get("industry") or "").strip()
    if not industry:
        return jsonify({"error": "client_industry_required"}), 400
    try:
        routes = content_route_library_service().list_routes(industry)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "industry": industry, "routes": routes})


@app.route("/api/knowledge/routes/<cid>", methods=["GET"])
def get_knowledge_content_routes(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    client = get_client(cid) or {}
    industry = str(client.get("industry") or "").strip()
    if not industry:
        return jsonify({"error": "client_industry_required"}), 400
    try:
        routes = content_route_library_service().list_routes(industry)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    groups = {"介绍型": [], "对比型": []}
    for route in routes:
        if route.get("parent_type") in groups:
            groups[route["parent_type"]].append(route)
    return jsonify({"ok": True, "industry": industry, "groups": groups})


@app.route("/api/content-routes/analyze", methods=["POST"])
def analyze_and_ingest_content_route():
    payload = request.get_json(silent=True) or {}
    cid = str(payload.get("client_id") or "").strip()
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    client = get_client(cid) or {}
    industry = str(client.get("industry") or "").strip()
    if not industry:
        return jsonify({"error": "client_industry_required"}), 400
    article_payload = payload.get("article") if isinstance(payload.get("article"), dict) else {}
    url = str(article_payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "article_url_required", "message": "请提供文章链接"}), 400
    fetched_article = fetch_article_text(url, timeout=25, max_chars=12000, browser_fallback=True)
    if not fetched_article.get("ok") or not str(fetched_article.get("content") or "").strip():
        return jsonify({
            "error": "article_fetch_failed",
            "message": f"文章抓取失败：{fetched_article.get('error') or '未取得足够正文'}",
        }), 502
    article = {
        "confirmed_for_route_analysis": True,
        "url": url,
        "title": str(fetched_article.get("title") or url).strip(),
        "content": str(fetched_article.get("content") or "").strip(),
    }
    try:
        analysis = analyze_content_route_article({
            "query": str(payload.get("query") or "").strip(),
            "final_entities": payload.get("final_entities") or [],
        }, article, ai_json)
        entry = None
        if analysis["library_decision"]["eligible"]:
            entry = ingest_content_route_analysis(
                analysis, industry, content_route_library_service(), payload.get("existing_route_id") or "",
            )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "analysis": analysis, "entry": entry})


@app.route("/api/content-routes/analyze-query-platform", methods=["POST"])
def analyze_query_platform_content_routes():
    payload = request.get_json(silent=True) or {}
    cid = str(payload.get("client_id") or "").strip()
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    group_id = str(payload.get("group_id") or "").strip()
    query = str(payload.get("query") or "").strip()
    ai_platform = str(payload.get("ai_platform") or "").strip()
    if not group_id:
        return jsonify({"error": "query_group_required"}), 400
    groups = load(F_GROUPS, {})
    group = next((item for item in groups.get(cid, []) if item.get("id") == group_id), None)
    if group is None:
        return jsonify({"error": "query_group_not_found"}), 400
    if query not in (group.get("questions") or []):
        return jsonify({"error": "query_not_in_group"}), 400
    if ai_platform not in CRAWL_PLATFORMS:
        return jsonify({"error": "ai_platform_required"}), 400
    client = get_client(cid) or {}
    if ai_platform not in normalize_contract_platforms(client.get("contract_platforms")):
        return jsonify({"error": "ai_platform_not_configured"}), 400
    industry = str(client.get("industry") or "").strip()
    if not industry:
        return jsonify({"error": "client_industry_required"}), 400

    with reference_intelligence_lock:
        records = load_client_records(cid, question=query, platform=ai_platform)
        task = select_query_platform_articles(records, query, ai_platform, secrets.randbits(32))
        if not task["selected"]:
            return jsonify({"error": "query_platform_citations_not_found"}), 400
        task.update({"id": uid(), "client_id": cid, "group_id": group_id, "created_at": now_str(), "analyses": [], "merge_results": [], "routes": []})
        analyzed, analyzed_candidates = [], []
        for candidate in task["selected"]:
            fetched = fetch_article_text(candidate["url"], timeout=25, max_chars=12000, browser_fallback=True)
            if not fetched.get("ok") or not str(fetched.get("content") or "").strip():
                task["analyses"].append({"url": candidate["url"], "status": "fetch_failed", "error": str(fetched.get("error") or "article_fetch_failed")})
                continue
            article = {
                "confirmed_for_route_analysis": True,
                "url": candidate["url"],
                "title": str(fetched.get("title") or candidate.get("title") or candidate["url"]).strip(),
                "content": str(fetched.get("content") or "").strip(),
            }
            try:
                analysis = analyze_content_route_article({"query": query}, article, ai_json)
            except Exception as exc:
                task["analyses"].append({"url": candidate["url"], "status": "analysis_failed", "error": str(exc) or type(exc).__name__})
                continue
            analyzed.append(analysis)
            analyzed_candidates.append(candidate)
            task["analyses"].append({
                "url": candidate["url"], "title": article["title"], "status": "analyzed",
                "citation_count": candidate["citation_count"], "classification": analysis.get("classification"),
                "eligible": bool((analysis.get("library_decision") or {}).get("eligible")),
                "analysis": analysis,
            })

        library = content_route_library_service()
        created_or_updated = []
        for parent_type in ("介绍型", "对比型"):
            indexes = [
                index for index, analysis in enumerate(analyzed)
                if analysis.get("classification") == parent_type and (analysis.get("library_decision") or {}).get("eligible")
            ]
            if not indexes:
                continue
            batch_analyses = [analyzed[index] for index in indexes]
            merged = merge_reference_route_batch(batch_analyses, library.list_routes(industry), ai_json)
            batch_routes = apply_reference_batch_updates(
                industry, library, batch_analyses, [analyzed_candidates[index] for index in indexes],
                query, ai_platform, merged["updates"],
            )
            task["merge_results"].append({"parent_type": parent_type, **merged})
            created_or_updated.extend(batch_routes)
        unique_routes = {route["id"]: route for route in created_or_updated}
        task["routes"] = list(unique_routes)
        save_reference_intelligence_task(cid, task)
    return jsonify({"ok": True, "task": task, "analyses": task["analyses"], "merge_results": task["merge_results"], "routes": task["routes"]})


@app.route("/api/content-routes/<route_id>", methods=["DELETE"])
def delete_content_route(route_id):
    cid = str(request.args.get("client_id") or "").strip()
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    client = get_client(cid) or {}
    industry = str(client.get("industry") or "").strip()
    try:
        entry = content_route_library_service().delete_route(industry, str(route_id or "").strip())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "entry": entry})


def _run_content_route_generation(d, *, created_by="", batch_id=""):
    """Formal explicit-material, single-writer route generation path."""
    cid = str(d.get("client_id") or "").strip()
    if not cid:
        raise ValueError("missing_client_id")
    client = get_client(cid)
    if not client:
        raise ValueError("client_not_found")
    article_type = d.get("article_type")
    if article_type not in {"介绍型", "对比型"}:
        raise ValueError("article_type_required")
    group_id = str(d.get("group_id") or "").strip()
    query = str(d.get("query") or "").strip()
    if not group_id:
        raise ValueError("query_group_required")
    group = next((item for item in load(F_GROUPS, {}).get(cid, []) if item.get("id") == group_id), None)
    if group is None:
        raise ValueError("query_group_not_found")
    if query not in (group.get("questions") or []):
        raise ValueError("query_not_in_group")
    use_customer_master = d.get("use_customer_master") is True
    use_content_uploads = d.get("use_content_uploads") is True
    if article_type == "介绍型" and not (use_customer_master or use_content_uploads):
        raise ValueError("introduction_material_required")
    if article_type == "对比型" and not use_customer_master:
        raise ValueError("comparison_customer_facts_required")

    customer_facts = ""
    if use_customer_master:
        customer_facts = knowledge_base_service().load_customer_master(cid).get("content", "").strip()
        validation = validate_customer_content_facts(customer_facts)
        if not validation["usable_for_generation"]:
            raise ValueError("customer_content_facts_migration_required")
    uploads = ""
    upload_files = []
    if use_content_uploads:
        bundle = content_material_service().build_generation_bundle(cid)
        uploads = str(bundle.get("text") or "").strip()
        upload_files = list(bundle.get("files") or [])

    selected_names = d.get("selected_competitor_names") if isinstance(d.get("selected_competitor_names"), list) else []
    if article_type == "介绍型" and selected_names:
        raise ValueError("introduction_competitors_forbidden")
    competitors = read_selected_competitor_facts(cid, selected_names) if selected_names else []
    if article_type == "对比型" and len(competitors) < 2:
        raise ValueError("comparison_competitors_required")

    industry = str(client.get("industry") or "").strip()
    if not industry:
        raise ValueError("client_industry_required")
    route = content_route_library_service().sample_route(industry, article_type, set())
    scene_context = content_generation_scene_terms(cid, group_id, query)
    bundle = {
        "task": {
            "query": query,
            "article_type": article_type,
            "title_entity_policy": str(d.get("title_entity_policy") or "实体不入标题"),
        },
        "client": {"name": client.get("name", ""), "brand": client.get("brand", "")},
        "route": route,
        "customer_facts": customer_facts,
        "content_uploads": uploads,
        "competitors": competitors,
        "scene_terms": scene_context["primary"],
        "supplementary_scene_terms": scene_context["supplementary"],
    }
    content = generate_content_route_draft(bundle, lambda messages, max_tokens: ai_deepseek_pro(messages, max_tokens))
    route_context = content_route_context(bundle)
    created_at = now_str()
    title = extract_generated_title(content)
    competitor_markdown = "\n\n".join(f"## {item['name']}\n{item['facts']}" for item in competitors)
    gate_report = run_quality_gate(
        title, content, {}, route_context,
        client_brand=client.get("brand", ""),
        competitor_names=route_context["competitor_names"], competitor_markdown=competitor_markdown,
        recent_articles=recent_content_generation_articles(cid), ai_json_fn=ai_json,
        customer_material_text=customer_facts, content_upload_text=uploads,
        industry=industry, policy=client_quality_policy(cid),
    )
    article = {
        "id": uid(), "client_id": cid, "title": title, "content": content,
        "model": get_settings().get("model", "deepseek-chat"),
        "material_count": len(upload_files) + int(bool(customer_facts)),
        "article_type": article_type, "batch_id": str(batch_id or ""),
        "route_context": route_context, "gate_report": gate_report,
        "created_at": created_at, "created_by": created_by,
    }
    assistant_message = {"role": "assistant", "content": content, "created_at": created_at, "article_id": article["id"]}
    article = append_content_generation(cid, article, {}, assistant_message)
    return {**article, "sampling": {"route": route}}


def content_batch_generation_service():
    global content_batch_jobs
    with content_batch_jobs_guard:
        if content_batch_jobs is None:
            content_batch_jobs = BatchGenerationJobs(
                uid, now_str, _run_content_batch_article, _prepare_content_batch_generation,
            )
        return content_batch_jobs


def _prepare_content_batch_generation(payload):
    """The formal route payload is already complete; there are no lazy choices."""
    return None


def _run_content_batch_article(payload, *, batch_id, created_by):
    return run_content_generation(
        payload,
        created_by=created_by,
        batch_id=batch_id,
    )


def queue_content_batch_generation_job(payload, count, created_by=""):
    service = content_batch_generation_service()
    job = service.create(payload, count, created_by=created_by)
    thread = threading.Thread(target=service.run, args=(job["job_id"],), daemon=True)
    thread.start()
    return service.get(job["job_id"])


def get_content_batch_generation_job(job_id):
    return content_batch_generation_service().get(job_id)


def cancel_content_batch_generation_job(job_id):
    return content_batch_generation_service().cancel(job_id)


def load_content_session(cid, history_date=None):
    return content_generation_store().load_session(cid, date=history_date)

def load_content_messages(cid, article_type, history_date=None):
    return content_generation_store().load_messages(cid, article_type=article_type, date=history_date)

def content_generation_store():
    db_path = os.path.splitext(F_CONTENT_GENERATIONS)[0] + ".sqlite3"
    return ContentGenerationStore(db_path, legacy_json_path=F_CONTENT_GENERATIONS)


def publication_store():
    db_path = os.path.splitext(F_CONTENT_GENERATIONS)[0] + ".sqlite3"
    return PublicationStore(db_path)


def rwmeiti_client_from_env():
    username = settings_username()
    personal = load(user_settings_path(username), {}) if username else {}
    return RWMeitiClient(
        personal.get("rwmeiti_base_url") or "http://dr.rwmeiti.com/meijieapi/daili3",
        personal.get("rwmeiti_secret_id") or "",
        personal.get("rwmeiti_secret_key") or "",
    )

def append_content_generation(cid, article, user_message, assistant_message):
    return content_generation_store().append_generation(cid, article, user_message, assistant_message)


def content_article_gate_report(cid, article, ai_json_fn=None):
    client = get_client(cid) or {}
    route = dict(article.get("route_context") or {})
    route.setdefault("parent_type", article.get("article_type") or "")
    customer_facts = knowledge_base_service().load_customer_master(cid).get("content", "").strip()
    competitor_names = route.get("competitor_names") or []
    competitors = read_selected_competitor_facts(cid, competitor_names) if competitor_names else []
    competitor_markdown = "\n\n".join(f"## {item['name']}\n{item['facts']}" for item in competitors)
    return run_quality_gate(
        article.get("title") or extract_generated_title(article.get("content", "")),
        article.get("content", ""),
        {},
        route,
        client_brand=client.get("brand", ""),
        competitor_names=competitor_names,
        competitor_markdown=competitor_markdown,
        recent_articles=[item for item in recent_content_generation_articles(cid) if item.get("id") != article.get("id")],
        ai_json_fn=ai_json_fn or ai_json,
        customer_material_text=customer_facts,
        content_upload_text="",
        industry=client.get("industry", ""),
        policy=client_quality_policy(cid),
    )


def content_revision_messages(article, lineage, instruction):
    history = [
        {"article_id": item.get("id"), "instruction": item.get("modify_instruction")}
        for item in lineage
        if item.get("modify_instruction")
    ]
    return [
        {"role": "system", "content": "你是中文文章编辑。只输出修改后的完整文章，不解释过程。保持原文可核验事实，不得编造、拉踩或作出绝对化承诺。"},
        {"role": "user", "content": f"""请按本次修改指令改写当前文章，标题仍在第一行。

【历史修改词】
{json.dumps(history, ensure_ascii=False)}

【当前文章】
{article.get('content') or ''}

【本次修改指令】
{instruction}
"""},
    ]


def run_content_revision(cid, article_id, instruction, created_by=""):
    store = content_generation_store()
    parent = store.get_article(cid, article_id)
    if not parent:
        raise ValueError("article_not_found")
    instruction = str(instruction or "").strip()
    if not instruction:
        raise ValueError("missing_modify_instruction")
    content = generate_content_draft(content_revision_messages(parent, store.load_revision_lineage(cid, article_id), instruction))
    created_at = now_str()
    revision = {
        **parent,
        "id": uid(),
        "title": extract_generated_title(content),
        "content": content,
        "model": get_settings().get("model", "deepseek-chat"),
        "parent_id": parent["id"],
        "root_id": parent.get("root_id") or parent["id"],
        "modify_instruction": instruction,
        "created_at": created_at,
        "created_by": created_by,
    }
    revision["gate_report"] = content_article_gate_report(cid, revision)
    if revision["gate_report"]["verdict"] == "blocked":
        revision["generation_status"] = "门禁拦截"
    user_message = {"role": "user", "content": instruction, "created_at": created_at, "article_id": revision["id"]}
    assistant_message = {"role": "assistant", "content": content, "created_at": created_at, "article_id": revision["id"]}
    return store.append_generation(cid, revision, user_message, assistant_message)


def review_content_generation_article(cid, article_id, ai_json_fn=None):
    store = content_generation_store()
    article = store.get_article(cid, article_id)
    if not article:
        raise ValueError("article_not_found")
    return store.update_article_gate_report(cid, article_id, content_article_gate_report(cid, article, ai_json_fn=ai_json_fn))

def delete_content_generation(cid, article_id):
    if publication_store().article_has_publication_state(cid, article_id):
        return None
    return content_generation_store().delete_generation(cid, article_id)


@app.route("/public/publications/<preview_token>")
def publication_preview(preview_token):
    draft = publication_store().get_draft_by_preview_token(preview_token)
    if not draft:
        return "Not Found", 404
    response = app.make_response(render_template("publication_preview.html", draft=draft))
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.route("/api/distribution/drafts", methods=["POST"])
def create_publication_draft_route():
    data = request.get_json(silent=True) or {}
    cid = str(data.get("client_id") or "")
    article_id = str(data.get("article_id") or "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    article = content_generation_store().get_article(cid, article_id)
    if not article:
        return jsonify({"error": "article_not_found"}), 404
    draft = publication_store().create_draft(cid, article, (current_user() or {}).get("username", ""))
    return jsonify({"ok": True, "draft": draft})


def uploaded_publication_article(storage_file):
    filename = str(storage_file.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".md", ".docx"}:
        raise ValueError("unsupported_file_type")
    if suffix == ".docx":
        try:
            import docx
            content = "\n\n".join(paragraph.text.strip() for paragraph in docx.Document(storage_file.stream).paragraphs if paragraph.text.strip())
        except Exception as exc:
            raise ValueError("invalid_docx") from exc
    else:
        content = storage_file.read().decode("utf-8-sig", errors="replace")
    content = content.replace("\r\n", "\n").strip()
    if not content:
        raise ValueError("empty_article")
    lines = content.split("\n")
    title_index = next((index for index, line in enumerate(lines) if line.strip()), 0)
    first_line = lines[title_index].strip()
    title = first_line.lstrip("#").strip() or Path(filename).stem
    body = "\n".join(lines[title_index + 1:]).lstrip()
    if not body:
        raise ValueError("empty_article_body")
    return {"id": "upload-" + uuid.uuid4().hex, "title": title, "content": body}


@app.route("/api/distribution/drafts/upload", methods=["POST"])
def upload_publication_drafts_route():
    cid = str(request.form.get("client_id") or "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    files = [file for file in request.files.getlist("files") if file and file.filename]
    if not files:
        return jsonify({"error": "files_required"}), 400
    drafts, rejected = [], []
    created_by = (current_user() or {}).get("username", "")
    for storage_file in files:
        try:
            drafts.append(publication_store().create_draft(cid, uploaded_publication_article(storage_file), created_by))
        except ValueError as exc:
            rejected.append({"filename": storage_file.filename, "error": str(exc)})
    return jsonify({"ok": True, "drafts": drafts, "rejected": rejected})


@app.route("/api/distribution/drafts", methods=["GET"])
def list_publication_drafts_route():
    cid = request.args.get("client_id", "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    return jsonify({"ok": True, "drafts": publication_store().list_drafts(cid)})


@app.route("/api/distribution/credentials", methods=["GET", "POST"])
def distribution_credentials_route():
    username = settings_username()
    if not username:
        return jsonify({"error": "operator_not_found"}), 400
    path = user_settings_path(username)
    settings = load(path, {})
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for input_key, setting_key in (("secret_id", "rwmeiti_secret_id"), ("secret_key", "rwmeiti_secret_key")):
            value = str(data.get(input_key) or "").strip()
            if value and value != "***":
                settings[setting_key] = value
        base_url = str(data.get("base_url") or "").strip()
        if base_url:
            settings["rwmeiti_base_url"] = base_url.rstrip("/")
        save(path, settings)
    return jsonify({
        "ok": True,
        "configured": bool(settings.get("rwmeiti_secret_id") and settings.get("rwmeiti_secret_key")),
        "base_url": settings.get("rwmeiti_base_url") or "http://dr.rwmeiti.com/meijieapi/daili3",
    })


@app.route("/api/distribution/catalog/sync", methods=["GET", "POST"])
def distribution_catalog_sync_route():
    username, _ = current_distribution_catalog()
    if not username:
        return jsonify({"error": "operator_not_found"}), 400
    job_path = distribution_catalog_job_path(username)
    job = load(job_path, {"status": "idle"})
    if request.method == "GET":
        return jsonify({"ok": True, "job": job})
    if job.get("status") == "running":
        return jsonify({"error": "catalog_sync_already_running", "job": job}), 409
    return jsonify({"ok": True, "job": start_distribution_catalog_sync(username, rwmeiti_client_from_env())}), 202


@app.route("/api/distribution/catalog", methods=["GET"])
def distribution_catalog_route():
    username, catalog = current_distribution_catalog()
    if not username:
        return jsonify({"error": "operator_not_found"}), 400
    query = str(request.args.get("query") or "")
    return jsonify({"ok": True, "resources": search_distribution_catalog(catalog, query, request.args.get("limit", 50)),
                    "count": len(catalog)})


@app.route("/api/distribution/resources/sync", methods=["POST"])
def sync_distribution_resources_route():
    data = request.get_json(silent=True) or {}
    cid = str(data.get("client_id") or "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    raw_resources = data.get("resources")
    if raw_resources is None:
        raw_ids = data.get("resource_ids") or []
        if isinstance(raw_ids, str):
            raw_ids = raw_ids.replace("，", ",").split(",")
        raw_resources = [{"resource_id": item, "resource_type": "self_media"} for item in raw_ids]
    if not isinstance(raw_resources, list):
        return jsonify({"error": "invalid_resources"}), 400
    requested_resources = list(dict.fromkeys(
        (str(item.get("resource_type") or "self_media"), str(item.get("resource_id") or "").strip())
        for item in raw_resources if isinstance(item, dict) and str(item.get("resource_id") or "").strip()
    ))
    if not requested_resources:
        return jsonify({"error": "resource_ids_required"}), 400
    if any(resource_type not in {"self_media", "news_media"} or not resource_id.isdigit() or int(resource_id) < 1
           for resource_type, resource_id in requested_resources):
        return jsonify({"error": "invalid_resource_ids"}), 400
    client = rwmeiti_client_from_env()
    resources = []
    for resource_type, resource_id in requested_resources:
        list_resource = client.list_news_media if resource_type == "news_media" else client.list_self_media
        resources.extend(list_resource(1, 5, resource_id=resource_id))
    publication_store().upsert_resources(cid, resources, now_str())
    return jsonify({"ok": True, "count": len(resources), "requested_count": len(requested_resources)})


@app.route("/api/distribution/favorites", methods=["GET", "POST"])
def distribution_favorites_route():
    username, favorites = current_distribution_favorites()
    if not username:
        return jsonify({"error": "operator_not_found"}), 400
    if request.method == "GET":
        return jsonify({"ok": True, "favorites": resolved_distribution_favorites(username)})
    data = request.get_json(silent=True) or {}
    favorite_id = str(data.get("id") or "")
    name = str(data.get("name") or "").strip()
    resource_id = str(data.get("resource_id") or "").strip()
    resource_type = str(data.get("resource_type") or "self_media")
    if resource_type not in {"self_media", "news_media"}:
        return jsonify({"error": "invalid_resource_type"}), 400
    if resource_id and not name and not favorite_id:
        _, catalog = current_distribution_catalog()
        resource = distribution_catalog_resource(catalog, resource_id, resource_type)
        if not resource:
            return jsonify({"error": "catalog_resource_not_found"}), 404
        if any(str(item.get("resource_id")) == resource_id and str(item.get("resource_type") or "self_media") == resource_type
               for item in favorites):
            return jsonify({"error": "favorite_resource_exists"}), 409
        favorite = {"id": uuid.uuid4().hex, "resource_id": resource_id, "resource_type": resource_type}
        favorites.append(favorite)
        save(distribution_favorites_path(username), favorites)
        return jsonify({"ok": True, "favorite": {**favorite, **resource}, "favorites": resolved_distribution_favorites(username)})
    existing = next((item for item in favorites if item.get("id") == favorite_id), None)
    if favorite_id and not existing:
        return jsonify({"error": "favorite_not_found"}), 404
    if existing:
        if name:
            existing["name"] = name
        existing["resource_id"] = resource_id
        favorite = existing
    else:
        if not name:
            return jsonify({"error": "favorite_name_required"}), 400
        if any(item.get("name") == name for item in favorites):
            return jsonify({"error": "favorite_name_exists"}), 409
        favorite = {"id": uuid.uuid4().hex, "name": name, "resource_id": resource_id}
        favorites.append(favorite)
    save(distribution_favorites_path(username), favorites)
    return jsonify({"ok": True, "favorite": favorite, "favorites": favorites})


@app.route("/api/distribution/favorites/<favorite_id>", methods=["DELETE"])
def delete_distribution_favorite_route(favorite_id):
    username, favorites = current_distribution_favorites()
    if not username:
        return jsonify({"error": "operator_not_found"}), 400
    updated = [item for item in favorites if item.get("id") != favorite_id]
    if len(updated) == len(favorites):
        return jsonify({"error": "favorite_not_found"}), 404
    save(distribution_favorites_path(username), updated)
    return jsonify({"ok": True})


@app.route("/api/distribution/favorites/refresh", methods=["POST"])
def refresh_distribution_favorites_route():
    username, favorites = current_distribution_favorites()
    if not username:
        return jsonify({"error": "operator_not_found"}), 400
    supplier, updated, failures = rwmeiti_client_from_env(), [], []
    for favorite in favorites:
        resource_id = str(favorite.get("resource_id") or "")
        resource_type = str(favorite.get("resource_type") or "self_media")
        if not resource_id:
            continue
        try:
            list_resource = supplier.list_news_media if resource_type == "news_media" else supplier.list_self_media
            result = list_resource(1, 5, resource_id=resource_id)
            updated.extend({**item, "resource_type": resource_type, "synced_at": now_str()} for item in result)
        except Exception as exc:
            failures.append({"resource_id": resource_id, "error": str(exc)[:120]})
    update_distribution_catalog_resources(username, updated)
    return jsonify({"ok": True, "count": len(updated), "failed": failures})


@app.route("/api/distribution/favorites/match", methods=["GET", "POST"])
def distribution_favorite_match_route():
    username, _ = current_distribution_favorites()
    if not username:
        return jsonify({"error": "operator_not_found"}), 400
    job_path = distribution_match_job_path(username)
    job = load(job_path, {"status": "idle"})
    if request.method == "GET":
        return jsonify({"ok": True, "job": job})
    if job.get("status") == "running":
        return jsonify({"error": "match_already_running", "job": job}), 409
    return jsonify({"ok": True, "job": start_distribution_favorite_match(username, rwmeiti_client_from_env())}), 202


@app.route("/api/distribution/resources", methods=["GET"])
def list_distribution_resources_route():
    cid = request.args.get("client_id", "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    username, _ = current_distribution_favorites()
    resources = resolved_distribution_favorites(username) if username else publication_store().list_resources(cid)
    return jsonify({"ok": True, "resources": resources})


@app.route("/api/distribution/orders", methods=["GET", "POST"])
def distribution_orders_route():
    if request.method == "GET":
        cid = request.args.get("client_id", "")
        if not require_client_access(cid):
            return jsonify({"error": "client_not_found"}), 404
        return jsonify({"ok": True, "orders": publication_store().list_orders(cid)})
    data = request.get_json(silent=True) or {}
    cid, draft_id, resource_id = str(data.get("client_id") or ""), str(data.get("draft_id") or ""), str(data.get("resource_id") or "")
    resource_type = str(data.get("resource_type") or "self_media")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    if resource_type not in {"self_media", "news_media"}:
        return jsonify({"error": "invalid_resource_type"}), 400
    username, _ = current_distribution_favorites()
    resources = resolved_distribution_favorites(username) if username else publication_store().list_resources(cid)
    resource = next((item for item in resources if str(item.get("resource_id")) == resource_id
                     and str(item.get("resource_type") or "self_media") == resource_type), None)
    draft = publication_store().get_draft(cid, draft_id)
    if not draft or not resource:
        return jsonify({"error": "draft_or_resource_not_found"}), 404
    existing_order = next((order for order in publication_store().list_orders(cid)
                           if str(order.get("draft_id")) == draft_id), None)
    if existing_order:
        return jsonify({"error": "draft_already_has_supplier_order", "order": existing_order}), 409
    personal = load(user_settings_path(settings_username()), {}) if settings_username() else {}
    if not personal.get("rwmeiti_secret_id") or not personal.get("rwmeiti_secret_key"):
        return jsonify({"error": "rwmeiti_credentials_not_configured"}), 400
    public_base = os.environ.get("GEO_PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base.startswith(("http://", "https://")):
        return jsonify({"error": "public_preview_url_not_configured"}), 400
    order_no = "geo-" + draft_id
    preview_url = public_base + "/public/publications/" + draft["preview_token"]
    supplier_content = '稿件链接：<a href="' + preview_url + '">' + preview_url + "</a>"
    supplier = rwmeiti_client_from_env()
    create_order = supplier.create_news_media_order if resource_type == "news_media" else supplier.create_self_media_order
    try:
        result = create_order(draft["article_title"], supplier_content, resource_id, order_no, resource["price"])
    except Exception as exc:
        order = publication_store().create_supplier_order(cid, draft_id, order_no, resource_type, resource_id, resource["name"], resource["price"])
        publication_store().update_supplier_order(cid, order["id"], "submit_unknown", "", str(exc))
        return jsonify({"ok": True, "order": {**order, "status": "submit_unknown"}}), 202
    provider_result = result if isinstance(result, dict) else {}
    if str(provider_result.get("code")) != "200":
        return jsonify({"error": str(provider_result.get("msg") or "rwmeiti_order_rejected"),
                        "provider_code": provider_result.get("code")}), 400
    order = publication_store().create_supplier_order(cid, draft_id, order_no, resource_type, resource_id, resource["name"], resource["price"])
    return jsonify({"ok": True, "order": order, "provider": result})


@app.route("/api/distribution/orders/<order_id>/refresh", methods=["POST"])
def refresh_distribution_order(order_id):
    data = request.get_json(silent=True) or {}
    cid = str(data.get("client_id") or "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    order = next((item for item in publication_store().list_orders(cid) if item["id"] == order_id), None)
    if not order:
        return jsonify({"error": "order_not_found"}), 404
    personal = load(user_settings_path(settings_username()), {}) if settings_username() else {}
    if not personal.get("rwmeiti_secret_id") or not personal.get("rwmeiti_secret_key"):
        return jsonify({"error": "rwmeiti_credentials_not_configured"}), 400
    try:
        supplier = rwmeiti_client_from_env()
        query_orders = supplier.query_news_media_orders if order["resource_type"] == "news_media" else supplier.query_self_media_orders
        provider_orders = query_orders([order["provider_order_no"]])
    except Exception as exc:
        return jsonify({"error": "rwmeiti_order_query_failed", "message": str(exc)}), 502
    provider_order = next((item for item in provider_orders
                           if str(item.get("no3") or item.get("no") or "") == order["provider_order_no"]), None)
    if not provider_order:
        return jsonify({"error": "supplier_order_not_found"}), 404
    status_map = {"-2": "deleted", "-1": "rejected", "0": "pending", "1": "publishing", "2": "published"}
    status = status_map.get(str(provider_order.get("status")), "pending")
    provider_url = str(provider_order.get("url") or "")
    provider_reason = str(provider_order.get("msg") or provider_order.get("reason") or "")
    publication_store().update_supplier_order(cid, order_id, status, provider_url, provider_reason)
    refreshed = next(item for item in publication_store().list_orders(cid) if item["id"] == order_id)
    if status == "published" and provider_url:
        draft = publication_store().get_draft(cid, order["draft_id"])
        if draft:
            publication_store().record_completed_publication(
                cid, order_id, order["resource_name"], provider_url, draft["article_title"], now_str()
            )
    return jsonify({"ok": True, "order": refreshed, "provider": provider_order})


@app.route("/api/content/generations", methods=["GET"])
def list_content_generations():
    cid = request.args.get("client_id", "")
    if not cid:
        return jsonify({"error": "缺少client_id"}), 400
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    history_date = normalize_content_history_date(request.args.get("date"))
    session = load_content_session(cid, history_date=history_date)
    articles = sorted(
        session["articles"],
        key=lambda x: (int(x.get("sequence") or 0), x.get("created_at", "")),
        reverse=True,
    )
    return jsonify({"ok": True, "articles": articles})

@app.route("/api/content/generations/<article_id>", methods=["DELETE"])
def delete_content_generation_route(article_id):
    cid = request.args.get("client_id", "")
    if not cid:
        return jsonify({"error": "缺少client_id"}), 400
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    if publication_store().article_has_publication_state(cid, article_id):
        return jsonify({"error": "article_has_publication_state"}), 409
    if not delete_content_generation(cid, article_id):
        return jsonify({"error": "article_not_found"}), 404
    history_date = normalize_content_history_date(request.args.get("date"))
    session = load_content_session(cid, history_date=history_date)
    articles = sorted(
        session["articles"],
        key=lambda x: (int(x.get("sequence") or 0), x.get("created_at", "")),
        reverse=True,
    )
    return jsonify({"ok": True, "articles": articles})


@app.route("/api/content/generations/<article_id>", methods=["PUT"])
def update_content_generation_route(article_id):
    try:
        d = request.json or {}
        cid = d.get("client_id") or request.args.get("client_id", "")
        if not require_client_access(cid):
            return jsonify({"error": "client_not_found"}), 404
        content = str(d.get("content") or "").strip()
        if not content:
            return jsonify({"error": "content_required"}), 400
        store = content_generation_store()
        previous = store.get_article(cid, article_id)
        if not previous:
            return jsonify({"error": "article_not_found"}), 404
        article = store.update_article_content(
            cid, article_id, content, title=extract_generated_title(content),
            gate_report=previous.get("gate_report"), generation_status="人工已编辑",
        )
        return jsonify({"ok": True, "article": article})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/content/generations/<article_id>/ai_modify", methods=["POST"])
def ai_modify_content_generation_route(article_id):
    d = request.json or {}
    cid = d.get("client_id") or request.args.get("client_id", "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    try:
        article = run_content_revision(cid, article_id, d.get("instruction"), created_by=(current_user() or {}).get("username", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "article": article})



def latest_entity_report_status(client_id, date_str, task_id=""):
    pattern = os.path.join(get_crawl_task_dir(), f"{date_str}_*.json")
    reports = []
    for path in glob.glob(pattern):
        report = load(path, {})
        if report.get("client_id") != client_id:
            continue
        if "entity_normalize" not in report and not report.get("entity_normalize_finished_at"):
            continue
        report_task_id = report.get("task_id") or ""
        scope_task_id = report.get("scope_task_id") or ""
        if task_id and task_id not in {report_task_id, scope_task_id}:
            continue
        reports.append((report.get("created_at") or report.get("finished_at") or "", path, report))
    if not reports:
        return {"ok": True, "status": "not_found", "message": "暂无实体识别任务"}
    reports.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, path, report = reports[0]
    entity = report.get("entity_normalize") or {}
    if report.get("entity_normalize_finished_at"):
        status = "completed" if entity.get("ok", True) else "failed"
    else:
        status = entity.get("status") or ("queued" if entity.get("queued") else "unknown")
    return {
        "ok": True,
        "status": status,
        "task_id": report.get("scope_task_id") or report.get("task_id") or "",
        "task_report": path,
        "finished_at": report.get("entity_normalize_finished_at") or "",
        "changed": entity.get("changed", 0),
        "selected_records": entity.get("selected_records", 0),
        "error": entity.get("error", ""),
        "message": entity.get("reason", ""),
    }


@app.route("/api/daily/entity_status", methods=["GET"])
def daily_entity_status():
    client_id = request.args.get("client_id", "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    date_str = request.args.get("date", today_str()).strip()
    task_id = request.args.get("task_id", "").strip()
    return jsonify(latest_entity_report_status(client_id, date_str, task_id))


@app.route("/api/daily/entities/generate", methods=["POST"])
def generate_daily_entities():
    payload = request.json or {}
    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    if not require_client_access(client_id):
        return jsonify({"error": "client_not_found"}), 404

    date_str = (payload.get("date") or today_str()).strip()
    group_id = (payload.get("group_id") or "").strip()
    platform = normalize_platform_filter((payload.get("platform") or "").strip()) or ""
    scope_task_id = (payload.get("task_id") or "").strip()
    report_task_id = f"entity_{uid()}"
    entity_normalize = {"ok": True, "status": "queued", "queued": True}
    report = {
        "task_id": report_task_id,
        "scope_task_id": scope_task_id,
        "status": "entity_normalize",
        "created_at": now_str(),
        "client_id": client_id,
        "date": date_str,
        "group_id": group_id,
        "source_platform": platform,
        "entity_normalize": entity_normalize,
    }
    task_report_path = save_crawl_task_report(report)
    entity_normalize = queue_entity_normalize_task(
        client_id,
        date_str,
        scope_task_id,
        task_report_path,
        username=settings_username(),
        group_id=group_id,
        platform=platform,
    )
    return jsonify({
        "ok": True,
        "task_id": report_task_id,
        "scope_task_id": scope_task_id,
        "task_report": task_report_path,
        "entity_normalize": entity_normalize,
    })


@app.route("/api/article_structure/extract", methods=["POST"])
def extract_article_structure():
    payload = request.json or {}
    fetched_article = None
    article_payload = payload.get("article") if isinstance(payload.get("article"), dict) else payload
    if isinstance(article_payload, dict) and not (
        article_payload.get("content") or article_payload.get("body") or article_payload.get("summary")
    ) and article_payload.get("url"):
        fetched_article = fetch_article_text(article_payload.get("url"))
        if fetched_article.get("content"):
            article_payload = {
                **article_payload,
                "title": article_payload.get("title") or fetched_article.get("title"),
                "content": fetched_article.get("content"),
            }
            payload = {**payload, "article": article_payload} if isinstance(payload.get("article"), dict) else article_payload
    try:
        analysis = analyze_article_structure(payload, ai_json)
    except ValueError as exc:
        if str(exc) == "article_required":
            return jsonify({"error": "article_required", "message": "请提供文章标题或正文"}), 400
        return jsonify({"error": "invalid_article", "message": str(exc)}), 400
    except Exception as exc:
        print(f"[article_structure_extract 错误] {exc}")
        return jsonify({"error": "extract_failed", "message": str(exc)}), 500
    response = {"ok": True, "analysis": analysis}
    if fetched_article is not None:
        response["fetched_article"] = fetched_article
    return jsonify(response)


@app.route("/api/article_structure/fetch", methods=["POST"])
def fetch_article_structure_source():
    payload = request.json or {}
    url = str(payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url_required", "message": "请提供文章 URL"}), 400
    article = fetch_article_text(url)
    status = 200 if article.get("ok") else 502
    return jsonify({"ok": bool(article.get("ok")), "article": article}), status


@app.route("/api/content/generate", methods=["POST"])
def generate_content_article():
    d = request.json or {}
    cid = d.get("client_id", "")
    if not cid:
        return jsonify({"error": "缺少client_id"}), 400
    client = require_client_access(cid)
    if not client:
        return jsonify({"error": "客户不存在"}), 404
    history_date = normalize_content_history_date(d.get("history_date") or d.get("date")) or today_str()
    try:
        result = run_content_generation(d, created_by=(current_user() or {}).get("username", ""))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    article = dict(result)
    article.pop("sampling", None)
    session = load_content_session(cid, history_date=history_date)
    articles = sorted(
        session["articles"],
        key=lambda x: (int(x.get("sequence") or 0), x.get("created_at", "")),
        reverse=True,
    )
    return jsonify({"ok": True, "article": article, "articles": articles})


@app.route("/api/content/generate_batch", methods=["POST"])
def generate_content_article_batch():
    d = request.json or {}
    cid = str(d.get("client_id") or "").strip()
    if not cid:
        return jsonify({"error": "缺少client_id"}), 400
    if not require_client_access(cid):
        return jsonify({"error": "客户不存在"}), 404
    try:
        count = int(d.get("count"))
    except (TypeError, ValueError):
        count = 0
    if count not in {1, 3, 5}:
        return jsonify({"error": "count仅支持1、3、5"}), 400
    job = queue_content_batch_generation_job(
        {key: value for key, value in d.items() if key != "count"},
        count,
        created_by=(current_user() or {}).get("username", ""),
    )
    return jsonify({"ok": True, "job": job})


@app.route("/api/content/generate_batch/<job_id>", methods=["GET"])
def get_content_article_batch(job_id):
    job = get_content_batch_generation_job(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404
    if not require_client_access(job["client_id"]):
        return jsonify({"error": "客户不存在"}), 404
    return jsonify({"ok": True, "job": job})


@app.route("/api/content/generate_batch/<job_id>/cancel", methods=["POST"])
def cancel_content_article_batch(job_id):
    job = get_content_batch_generation_job(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404
    if not require_client_access(job["client_id"]):
        return jsonify({"error": "客户不存在"}), 404
    return jsonify({"ok": True, "job": cancel_content_batch_generation_job(job_id)})

# ══════════════════════════════════════════════════════
# 智能主题生成模块
# ══════════════════════════════════════════════════════

@app.route("/api/content/refine_pattern", methods=["POST"])
def refine_pattern():
    """把平台提示词/深度分析报告提炼成300字以内的内容规律摘要"""
    d = request.json
    raw_text = (d.get("text") or "").strip()
    if not raw_text:
        return jsonify({"error": "文本为空"}), 400
    prompt = f"""请将以下内容提炼成300字以内的「内容规律摘要」，用于指导文章生成。

要求：
- 只保留文章结构、标题格式、写作风格、必须包含的元素等规律性信息
- 去掉所有开场白、客套话、重复说明
- 用简洁的关键词和短句表达，不要长段落
- 严格控制在300字以内

原文：
{raw_text[:2000]}

只返回提炼后的规律摘要，不要其他内容："""
    try:
        result = ai(prompt, 600)
        return jsonify({"ok": True, "refined": result[:300]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# 当日数据整理模块
# ══════════════════════════════════════════════════════

@app.route("/api/daily/records", methods=["GET"])
def get_daily_records():
    """获取指定日期的所有爬取记录，支持按客户和平台筛选"""
    client_id = request.args.get("client_id", "")
    date = request.args.get("date", today_str())
    source_platform = request.args.get("platform", "")
    group_id = request.args.get("group_id", "")
    task_id = request.args.get("task_id", "")
    result = load_client_records(client_id, date=date,
                                  platform=source_platform if source_platform else None,
                                  group_id=group_id if group_id else None,
                                  task_id=task_id if task_id else None)
    result.sort(key=lambda x: x.get("crawl_time", ""), reverse=True)
    return jsonify(result)

@app.route("/api/daily/records/<rid>", methods=["DELETE"])
def delete_daily_record(rid):
    """删除单条爬取记录（用于清理错爬漏爬数据）"""
    records = load(F_RAW_RECORDS, [])
    record = next((item for item in records if str(item.get("id") or "") == rid), None)
    if not record or not require_client_access(str(record.get("client_id") or "")):
        return jsonify({"error": "record_not_found"}), 404
    deleted = record_store.delete_raw_record(F_RAW_RECORDS, rid)
    return jsonify({"ok": True, "deleted": deleted})

@app.route("/api/daily/records/batch_delete", methods=["POST"])
def batch_delete_records():
    """批量删除多条记录"""
    payload = request.json or {}
    client_id = str(payload.get("client_id") or "").strip()
    if not client_id or not require_client_access(client_id):
        return jsonify({"error": "client_not_found"}), 404
    ids = {str(item) for item in (payload.get("ids") or [])}
    records = load(F_RAW_RECORDS, [])
    selected = [item for item in records if str(item.get("id") or "") in ids]
    if any(str(item.get("client_id") or "") != client_id for item in selected):
        return jsonify({"error": "record_not_found"}), 404
    deleted = record_store.delete_raw_records(F_RAW_RECORDS, ids)
    return jsonify({"ok": True, "deleted": deleted})

@app.route("/api/daily/records/clear", methods=["POST"])
def clear_daily_records():
    """清空指定客户指定日期的所有记录"""
    d = request.json
    client_id = d.get("client_id", "")
    date = d.get("date", today_str())
    source_platform = d.get("platform", "")
    if not client_id:
        return jsonify({"error": "缺少client_id"}), 400
    deleted = record_store.clear_client_day_records(F_RAW_RECORDS, client_id, date, source_platform)
    return jsonify({"ok": True, "deleted": deleted, "date": date, "platform": source_platform})

@app.route("/api/daily/ref_stats", methods=["GET"])
def daily_ref_stats():
    """对当日筛选后的数据做引用源统计，支持按平台/问题组过滤"""
    client_id = request.args.get("client_id", "")
    date = request.args.get("date", today_str())
    source_platform = request.args.get("platform", "")
    group_id = request.args.get("group_id", "")
    task_id = request.args.get("task_id", "")
    try:
        records = load_client_records(
            client_id,
            date=date,
            platform=source_platform,
            group_id=group_id,
            task_id=task_id,
        )
        from services.daily_stats import build_daily_ref_stats
        stats = build_daily_ref_stats(
            records,
            platform_names={key: cfg["name"] for key, cfg in CRAWL_PLATFORMS.items()},
            platform_order=CLIENT_CONTRACT_PLATFORM_ORDER,
        )
        body_hit_report = load_competitor_article_body_hit_report(
            client_id,
            date,
            task_id=task_id,
            group_id=group_id,
            platform=source_platform,
        )
        top_articles = annotate_top_articles_with_competitor_matches(
            stats["top_articles"],
            records,
            body_hit_report=body_hit_report,
        )
        for group in stats["top_articles_by_ai"]:
            group["top_articles"] = annotate_top_articles_with_competitor_matches(
                group["top_articles"],
                records,
                body_hit_report=body_hit_report,
            )

        return jsonify({
            "total_records": stats["total_records"],
            "total_refs": stats["total_refs"],
            "date": date,
            "platform_weights": stats["platform_weights"],
            "top_articles": top_articles,
            "top_articles_by_ai": stats["top_articles_by_ai"],
        })
    except Exception as e:
        print(f"[daily_ref_stats 错误] {e}")
        return jsonify({
            "total_records": 0,
            "date": date,
            "platform_weights": [],
            "top_articles": [],
            "top_articles_by_ai": [],
        })

@app.route("/api/daily/insights", methods=["GET"])
def daily_insights():
    """当日或指定批次的证据层聚合，用于平台分类、竞品/门店和高频引用展示。"""
    client_id = request.args.get("client_id", "")
    date = request.args.get("date", today_str())
    source_platform = request.args.get("platform", "")
    group_id = request.args.get("group_id", "")
    task_id = request.args.get("task_id", "")
    records = load_client_records(
        client_id,
        date=date,
        platform=source_platform if source_platform else None,
        group_id=group_id if group_id else None,
        task_id=task_id if task_id else None,
    )
    configured_platforms = []
    own_brand = ""
    own_client_name = ""
    for client in load(F_CLIENTS, []):
        if client.get("id") == client_id:
            configured_platforms = client.get("contract_platforms") or []
            own_brand = client.get("brand") or client.get("name") or ""
            own_client_name = client.get("name") or ""
            break
    from services.record_insights import build_record_insights
    insights = build_record_insights(
        records,
        configured_platforms=configured_platforms,
        own_brand=own_brand,
        own_client_name=own_client_name,
    )
    return jsonify({
        "ok": True,
        "date": date,
        "client_id": client_id,
        "group_id": group_id,
        "task_id": task_id,
        "insights": insights,
    })

# ══════════════════════════════════════════════════════
# 深度分析增强模块（按平台分类）
# ══════════════════════════════════════════════════════

@app.route("/api/daily/entities/delete", methods=["POST"])
def delete_daily_entity():
    """Remove one AI-recognized entity from the current daily insight scope."""
    d = request.json or {}
    client_id = (d.get("client_id") or "").strip()
    entity_name = (d.get("name") or "").strip()
    if not client_id:
        return jsonify({"ok": False, "error": "client_id required"}), 400
    if not entity_name:
        return jsonify({"ok": False, "error": "name required"}), 400

    result = record_store.delete_entity_mentions(
        F_RAW_RECORDS,
        client_id=client_id,
        date=d.get("date") or today_str(),
        entity_name=entity_name,
        platform=normalize_platform_filter(d.get("platform", "")),
        group_id=d.get("group_id") or None,
        task_id=d.get("task_id") or None,
    )
    return jsonify({
        "ok": True,
        "name": entity_name,
        "removed": result["removed"],
        "records_changed": result["records_changed"],
    })


@app.route("/api/daily/platform_detail", methods=["GET"])
def platform_detail():
    """获取单个平台的详细数据（文章列表、引用规律）"""
    client_id = request.args.get("client_id", "")
    date = request.args.get("date", today_str())
    platform = request.args.get("platform", "")
    task_id = request.args.get("task_id", "")

    records = load_client_records(client_id, date=date, task_id=task_id if task_id else None)

    articles = {}
    questions_with_platform = []

    for rec in records:
        for ref in rec.get("refs", []):
            if platform and ref.get("platform") != platform:
                continue
            key = ref.get("url") or ref.get("title")
            if key:
                if key not in articles:
                    articles[key] = {
                        "title": ref.get("title", ""),
                        "url": ref.get("url", ""),
                        "platform": ref.get("platform", ""),
                        "count": 0, "positions": [],
                        "questions": []
                    }
                articles[key]["count"] += 1
                articles[key]["positions"].append(ref.get("position", 0))
                q = rec.get("question", "")
                if q not in articles[key]["questions"]:
                    articles[key]["questions"].append(q)

    result = sorted([
        {**v,
         "avg_position": round(sum(v["positions"]) / len(v["positions"]), 1) if v["positions"] else 0
         }
        for v in articles.values()
    ], key=lambda x: x["count"], reverse=True)

    return jsonify({
        "platform": platform,
        "date": date,
        "article_count": len(result),
        "articles": result[:20]
    })

# ══════════════════════════════════════════════════════
# 软文模板管理模块
# ══════════════════════════════════════════════════════
TEMPLATE_FOLDER = "data/templates"
os.makedirs(TEMPLATE_FOLDER, exist_ok=True)

def _template_dir(cid):
    """返回客户专属模板目录，不存在则创建"""
    d = os.path.join(TEMPLATE_FOLDER, cid) if cid else TEMPLATE_FOLDER
    os.makedirs(d, exist_ok=True)
    return d

def get_active_template(cid=""):
    """读取指定客户当前激活的软文模板内容"""
    folder = _template_dir(cid)
    files = [f for f in os.listdir(folder)
             if f.endswith(('.txt', '.md')) and not f.endswith('.meta')]
    if not files:
        return ""
    latest = max(files, key=lambda f: os.path.getmtime(os.path.join(folder, f)))
    with open(os.path.join(folder, latest), 'r', encoding='utf-8', errors='ignore') as fp:
        return fp.read()

@app.route("/api/templates/<cid>", methods=["GET"])
def list_templates(cid):
    """获取指定客户已上传的模板列表"""
    folder = _template_dir(cid)
    files = []
    raw = [f for f in os.listdir(folder)
           if f.endswith(('.txt', '.md')) and not f.endswith('.meta')]
    raw.sort(key=lambda f: os.path.getmtime(os.path.join(folder, f)), reverse=True)
    for i, f in enumerate(raw):
        fpath = os.path.join(folder, f)
        meta_path = fpath + ".meta"
        original = f
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as mf:
                original = mf.read().strip()
        files.append({
            "name": f,
            "original": original,
            "size": os.path.getsize(fpath),
            "modified": datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M"),
            "active": i == 0   # 最新的为激活状态
        })
    return jsonify(files)

@app.route("/api/templates/<cid>/upload", methods=["POST"])
def upload_template(cid):
    """上传软文模板文件（客户专属）"""
    if 'file' not in request.files:
        return jsonify({"error": "没有文件"}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'txt'
    if ext not in ('txt', 'md'):
        return jsonify({"error": "只支持 .txt 或 .md 格式"}), 400
    folder = _template_dir(cid)
    safe_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
    fpath = os.path.join(folder, safe_name)
    file.save(fpath)
    with open(fpath + ".meta", "w", encoding="utf-8") as mf:
        mf.write(file.filename)
    return jsonify({"ok": True, "name": safe_name, "original": file.filename})

@app.route("/api/templates/<cid>/<filename>", methods=["DELETE"])
def delete_template(cid, filename):
    """删除客户模板文件"""
    folder = _template_dir(cid)
    fpath = os.path.join(folder, filename)
    if os.path.exists(fpath):
        os.remove(fpath)
    meta = fpath + ".meta"
    if os.path.exists(meta):
        os.remove(meta)
    return jsonify({"ok": True})

@app.route("/api/templates/<cid>/preview", methods=["GET"])
def preview_template(cid):
    """预览指定客户当前激活的模板内容"""
    content_text = get_active_template(cid)
    return jsonify({"content": content_text, "length": len(content_text)})



# ══════════════════════════════════════════════════════
# 文章格式优化
# ══════════════════════════════════════════════════════
# 系统设置
# ══════════════════════════════════════════════════════
@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    s = get_settings()
    s_safe = {k: v for k, v in s.items() if k not in (
        "api_key", "tavily_api_key", "rwmeiti_secret_id", "rwmeiti_secret_key",
    )}
    s_safe["has_key"] = bool(s.get("api_key"))
    s_safe["has_tavily_key"] = bool(get_tavily_api_key(s))
    return jsonify(s_safe)

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    d = request.json or {}
    save_current_settings(d)
    return jsonify({"ok": True})

@app.route("/api/settings/test", methods=["POST"])
def test_api():
    try:
        result = ai('请回复连接成功四个字，不要其他内容。', 50)
        return jsonify({"ok": True, "reply": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

# ══════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════
# 多平台爬取模块
# ══════════════════════════════════════════════════════
import threading
import queue

# 支持的平台配置
CRAWL_PLATFORMS = {
    "doubao":   {"name": "豆包",     "module": "doubao_crawler",   "url": "https://www.doubao.com/chat/"},
    "deepseek": {"name": "DeepSeek", "module": "deepseek_crawler", "url": "https://chat.deepseek.com/"},
    "yuanbao":  {"name": "元宝",     "module": "yuanbao_crawler",  "url": "https://yuanbao.tencent.com/chat"},
    "qwen":     {"name": "千问",     "module": "qwen_crawler",     "url": "https://tongyi.aliyun.com/qianwen"},
    "kimi":     {"name": "Kimi",     "module": "kimi_crawler",     "url": "https://kimi.moonshot.cn"},
}

def get_crawler_module(platform: str):
    """动态加载平台爬虫模块"""
    import importlib
    cfg = CRAWL_PLATFORMS.get(platform)
    if not cfg:
        raise ValueError(f"不支持的平台: {platform}")
    return importlib.import_module(cfg["module"])

# 全局进度队列（SSE推送用）
progress_queues = {}

@app.route("/api/platform/login", methods=["POST"])
def platform_login():
    """后台线程打开浏览器，用户手动登录指定平台"""
    d = request.json
    platform = d.get("platform", "doubao")
    if platform not in CRAWL_PLATFORMS:
        return jsonify({"error": f"不支持的平台: {platform}"}), 400

    def do_login():
        import asyncio
        mod = get_crawler_module(platform)
        login_fn = getattr(mod, f"login_{platform}_async", None)
        if not login_fn:
            print(f"平台 {platform} 没有登录函数")
            return
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(login_fn())
            ok = result is True or (isinstance(result, dict) and result.get("ok"))
            if not ok:
                from base_crawler import mark_login_status
                mark_login_status(platform, "expired", "登录未完成，请重新登录")
        except Exception as e:
            from base_crawler import mark_login_status
            mark_login_status(platform, "expired", "登录窗口已关闭或登录失败，请重新登录")
            print(f"[{platform}] 登录出错: {e}")
        finally:
            loop.close()

    t = threading.Thread(target=do_login, daemon=True)
    t.start()
    pname = CRAWL_PLATFORMS[platform]["name"]
    return jsonify({"ok": True, "message": f"浏览器已打开，请在窗口中完成 {pname} 登录"})

@app.route("/api/platform/check_login", methods=["GET"])
def check_platform_login():
    """检查指定平台登录状态。状态文件存在不等于真实会话可用。"""
    platform = request.args.get("platform", "doubao")
    if platform not in CRAWL_PLATFORMS:
        return jsonify({"error": f"不支持的平台: {platform}"}), 400
    from base_crawler import get_platform_login_status
    status = get_platform_login_status(platform)
    return jsonify({
        **status,
        "name": CRAWL_PLATFORMS.get(platform, {}).get("name", platform),
    })

@app.route("/api/platform/list", methods=["GET"])
def list_platforms_api():
    """返回所有支持的爬取平台及登录状态"""
    from base_crawler import get_platform_login_status
    result = []
    for key, cfg in CRAWL_PLATFORMS.items():
        status = get_platform_login_status(key)
        result.append({
            "id": key,
            "name": cfg["name"],
            "logged_in": status["logged_in"],
            "status": status["status"],
            "state_file_exists": status["state_file_exists"],
            "message": status["message"],
        })
    return jsonify(result)

def basic_brand_analysis_without_api(
    brand,
    question,
    answer,
    refs,
    *,
    analysis_status="pending_api",
    analysis_mode="basic_no_api_key",
    summary=None,
    suggestion=None,
):
    """
    Fallback analysis used when no API key is configured.
    It keeps crawler verification possible and marks records for later AI analysis.
    """
    clean_answer = "" if is_noise_answer(answer) else (answer or "")
    brand_mentioned = bool(brand and brand in clean_answer)
    main_ref = refs[0] if refs else {}
    result = {
        "brand_mentioned": brand_mentioned,
        "brand_rank": None,
        "brand_sentiment": "neutral",
        "main_ref": main_ref,
        "source_count": len(refs),
        "summary": summary or "未配置 API Key，已保存原始爬取结果，暂未进行 AI 深度分析。",
        "suggestion": suggestion or "配置 API Key 后可重新生成深度分析；当前记录可用于验证平台登录、回答抓取和引用源提取。",
        "analysis_status": analysis_status,
        "analysis_mode": analysis_mode,
    }
    result["geo_score"] = calc_geo_score(brand, question, clean_answer, refs, result)
    return result


def analyze_brand_intel_with_retry(brand, question, answer, refs, settings, max_attempts=3):
    failures = []
    attempts = max(1, int(max_attempts or 1))
    for attempt in range(1, attempts + 1):
        try:
            return analyze_brand_intel(brand, question, answer, refs, settings), None
        except Exception as exc:
            failures.append({"attempt": attempt, "error": str(exc)})

    fallback = basic_brand_analysis_without_api(
        brand,
        question,
        answer,
        refs,
        analysis_status="fallback_basic",
        analysis_mode="api_failed_basic",
        summary="AI 深度分析连续失败，已使用基础规则分析并保留原始爬取结果。",
        suggestion="建议稍后重新分析该题；当前记录已可用于回答、引用源和品牌提及的基础统计。",
    )
    fallback["analysis_error"] = failures[-1]["error"] if failures else ""
    fallback["analysis_attempts"] = attempts
    return fallback, {
        "question": question,
        "attempts": attempts,
        "errors": failures,
        "fallback": "basic_brand_analysis",
    }


def persist_local_crawl_job_results(job):
    return crawl_job_store.persist_local_crawl_job_results(
        job,
        load_records_fn=lambda: load(F_RAW_RECORDS, []),
        save_crawl_task_report_fn=save_crawl_task_report,
        compact_crawl_failure_fn=compact_crawl_failure,
        basic_brand_analysis_fn=basic_brand_analysis_without_api,
        calibrate_analysis_fn=calibrate_analysis_brand_mention,
        save_raw_record_fn=save_raw_record,
        now_fn=now_str,
    )


def current_crawl_job_owner_filter():
    if auth_disabled() or is_admin():
        return None
    user = current_user() or {}
    return user.get("username", "")


def current_crawl_job_worker_owner_filter():
    if auth_disabled():
        return None
    user = current_user() or {}
    return user.get("username", "")


@app.route("/api/crawl_jobs", methods=["GET"])
def list_crawl_jobs_api():
    client_id = request.args.get("client_id", "").strip()
    jobs = crawl_job_store.filter_jobs_by_owner(
        crawl_job_store.load_jobs(F_CRAWL_JOBS),
        current_crawl_job_owner_filter(),
    )
    if client_id:
        jobs = [job for job in jobs if job.get("client_id") == client_id]
    return jsonify({"ok": True, "jobs": jobs})


@app.route("/api/crawl_jobs", methods=["POST"])
def create_crawl_job_api():
    payload = request.json or {}
    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    client = require_client_access(client_id)
    if not client:
        return jsonify({"error": "client_not_found"}), 404
    platform = (payload.get("platform") or "").strip()
    if platform not in CRAWL_PLATFORMS:
        return jsonify({"error": f"不支持的平台: {platform}"}), 400

    group_id = (payload.get("group_id") or "").strip()
    questions = [str(item).strip() for item in payload.get("questions") or [] if str(item).strip()]
    if not questions and group_id:
        groups = load(F_GROUPS, {})
        target_group = next((g for g in groups.get(client_id, []) if g.get("id") == group_id), None)
        if target_group:
            questions = [str(item).strip() for item in target_group.get("questions") or [] if str(item).strip()]
    if not questions:
        return jsonify({"error": "questions required", "message": "该任务没有可爬取问题"}), 400

    try:
        repeat_count = max(1, min(int(payload.get("repeat_count") or 1), 10))
    except (TypeError, ValueError):
        repeat_count = 1
    job = crawl_job_store.create_job(
        F_CRAWL_JOBS,
        {
            "client_id": client_id,
            "brand": (payload.get("brand") or client.get("brand") or client.get("name") or "").strip(),
            "group_id": group_id,
            "platform": platform,
            "questions": questions,
            "repeat_count": repeat_count,
            "batch_id": (payload.get("batch_id") or "").strip(),
        },
        uid,
        now_str,
        created_by=(current_user() or {}).get("username", ""),
    )
    return jsonify({"ok": True, "job": job})


@app.route("/api/crawl_jobs/login", methods=["POST"])
def create_login_job_api():
    payload = request.json or {}
    platform = (payload.get("platform") or "").strip()
    if platform not in CRAWL_PLATFORMS:
        return jsonify({"error": f"不支持的平台: {platform}"}), 400
    job = crawl_job_store.create_job(
        F_CRAWL_JOBS,
        {
            "job_type": "login",
            "platform": platform,
            "questions": [],
            "repeat_count": 1,
        },
        uid,
        now_str,
        created_by=(current_user() or {}).get("username", ""),
    )
    return jsonify({"ok": True, "job": job})


@app.route("/api/crawl_jobs/next", methods=["GET"])
def claim_next_crawl_job_api():
    worker_id = request.args.get("worker_id", "").strip()
    platform = request.args.get("platform", "").strip()
    if platform and platform not in CRAWL_PLATFORMS:
        return jsonify({"error": f"不支持的平台: {platform}"}), 400
    job = crawl_job_store.claim_next_job(
        F_CRAWL_JOBS,
        worker_id,
        platform,
        now_str,
        created_by=current_crawl_job_worker_owner_filter(),
    )
    return jsonify({"ok": True, "job": job})


@app.route("/api/crawl_jobs/<job_id>/cancel", methods=["POST"])
def cancel_crawl_job_api(job_id):
    job = crawl_job_store.cancel_job(
        F_CRAWL_JOBS,
        job_id,
        now_str,
        created_by=current_crawl_job_owner_filter(),
    )
    if not job:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify({"ok": True, "job": job})


@app.route("/api/crawl_jobs/<job_id>/result", methods=["POST"])
def finish_crawl_job_api(job_id):
    job = crawl_job_store.finish_job(
        F_CRAWL_JOBS,
        job_id,
        request.json or {},
        now_str,
        created_by=current_crawl_job_worker_owner_filter(),
    )
    if not job:
        return jsonify({"error": "job_not_found"}), 404
    persisted = persist_local_crawl_job_results(job)
    job = crawl_job_store.record_persist_result(F_CRAWL_JOBS, job_id, persisted, now_str) or job
    return jsonify({"ok": True, "job": job, "persisted": persisted})


@app.route("/api/platform/crawl", methods=["POST"])
def platform_crawl():
    payload = request.get_json(silent=True) or {}
    source_platform = (payload.get("platform") or "doubao").strip() or "doubao"
    platform_lock = get_crawl_platform_lock(source_platform)
    if not platform_lock.acquire(blocking=False):
        return jsonify({
            "error": "crawl_busy",
            "message": f"{source_platform} 平台已有爬取任务进行中，请稍后再试。同一平台不允许并行爬取。",
            "platform": source_platform,
        }), 409
    try:
        return platform_crawl_impl()
    finally:
        platform_lock.release()


def platform_crawl_impl():
    """
    多平台批量爬取（增强版）：
    - 支持 doubao / deepseek / yuanbao / qwen 四个平台
    - 支持每题自定义爬取次数（repeat_count）
    - 爬取完自动AI分析并录入系统
    - 原始数据保存到每日文件
    - 多次爬取结果汇总后综合分析
    """
    d = request.json
    client_id = d.get("client_id", "")
    brand = d.get("brand", "")
    source_platform = d.get("platform", "doubao")  # 新增：爬取平台
    selected_questions = d.get("questions", [])
    repeat_count = max(1, min(int(d.get("repeat_count", 1)), 10))
    parallel = max(1, min(int(d.get("parallel", 2)), 3))
    group_id = d.get("group_id", "")

    if source_platform not in CRAWL_PLATFORMS:
        return jsonify({"error": f"不支持的平台: {source_platform}"}), 400

    if not client_id or not brand:
        return jsonify({"error": "缺少客户信息"}), 400

    # 问题必须来自问题组或前端显式传入；旧问题库不再参与主流程。
    if not selected_questions:
        if group_id:
            groups = load(F_GROUPS, {})
            target_group = next(
                (g for g in groups.get(client_id, []) if g["id"] == group_id), None
            )
            if target_group:
                selected_questions = target_group["questions"]
                print(f"从问题组「{target_group['name']}」获取 {len(selected_questions)} 条问题")
    if not selected_questions:
        return jsonify({"error": "该问题组暂无问题，请先在问题组中手动添加问题"}), 400

    task_id = uid()
    task_report_path = os.path.join(get_crawl_task_dir(), f"{today_str()}_{task_id}.json")
    task_report = {
        "task_id": task_id,
        "status": "running",
        "started_at": now_str(),
        "client_id": client_id,
        "brand": brand,
        "group_id": group_id,
        "platform": source_platform,
        "question_count": len(selected_questions),
        "repeat_count": repeat_count,
        "parallel": parallel,
        "questions": selected_questions,
        "success": [],
        "failures": [],
        "analysis_errors": [],
    }

    settings = get_settings()
    has_api_key = bool(settings.get("api_key"))
    use_node_crawler = should_use_node_crawler(source_platform)
    task_report["crawler_engine"] = "node" if use_node_crawler else "python"
    from base_crawler import get_platform_login_status, mark_login_status
    login_status = get_platform_login_status(source_platform)
    if not login_status["logged_in"]:
        error_code = "need_login" if login_status["status"] == "missing" else "cookie_expired"
        task_report.update({
            "status": "blocked",
            "finished_at": now_str(),
            "error": error_code,
            "message": login_status["message"],
            "login_status": login_status,
        })
        task_path = save_crawl_task_report(task_report)
        return jsonify({
            "error": error_code,
            "message": login_status["message"],
            "login_status": login_status["status"],
            "state_file_exists": login_status["state_file_exists"],
            "has_api_key": has_api_key,
            "task_id": task_id,
            "task_report": task_path,
        }), 401

    # 生成本次爬取的session_id，用于SSE进度推送
    session_id = str(uuid_lib.uuid4())
    crawl_sessions[session_id] = {"events": []}

    # 展开问题列表：每题重复 repeat_count 次
    expanded_questions = []
    for q in selected_questions:
        for i in range(repeat_count):
            expanded_questions.append({"question": q, "round": i + 1})

    # 执行爬取
    if use_node_crawler:
        from services.node_crawler_bridge import NodeCrawlerBridgeError, run_node_crawler
        node_output_dir = build_node_output_dir(D, task_id, source_platform)
        os.makedirs(node_output_dir, exist_ok=True)
        task_report["node_output_dir"] = node_output_dir
        try:
            try:
                timeout_s = max(1, int(os.environ.get("GEO_NODE_CRAWLER_TIMEOUT", "1800")))
            except ValueError:
                timeout_s = 1800
            crawl_result = run_node_crawler(
                source_platform,
                [item["question"] for item in expanded_questions],
                timeout_s=timeout_s,
                output_dir=node_output_dir,
            )
        except NodeCrawlerBridgeError as e:
            print(f"Node爬虫异常: {e}")
            if "need_login" in str(e):
                mark_login_status(source_platform, "expired", "Node 爬虫检测到登录状态失效，请重新登录")
                task_report.update({
                    "status": "blocked",
                    "finished_at": now_str(),
                    "error": "cookie_expired",
                    "message": "Node 爬虫检测到登录状态失效，请重新登录",
                })
                task_path = save_crawl_task_report(task_report)
                return jsonify({
                    "error": "cookie_expired",
                    "message": "Node 爬虫检测到登录状态失效，请重新登录",
                    "task_id": task_id,
                    "task_report": task_path,
                }), 401
            if "verification_required" in str(e) or "rate limited" in str(e):
                message = "平台触发验证码或限流，请关闭 VPN/代理、完成平台验证或稍后重试"
                mark_login_status(source_platform, "expired", message)
                task_report.update({
                    "status": "blocked",
                    "finished_at": now_str(),
                    "error": "verification_required",
                    "message": message,
                })
                task_path = save_crawl_task_report(task_report)
                return jsonify({
                    "error": "verification_required",
                    "message": message,
                    "task_id": task_id,
                    "task_report": task_path,
                }), 429
            task_report.update({
                "status": "failed",
                "finished_at": now_str(),
                "error": "node_crawler_exception",
                "message": str(e),
            })
            task_path = save_crawl_task_report(task_report)
            return jsonify({
                "error": f"Node爬虫过程发生错误: {str(e)}",
                "task_id": task_id,
                "task_report": task_path,
            }), 500
    else:
        import asyncio
        crawler_mod = get_crawler_module(source_platform)
        crawl_batch_async = crawler_mod.crawl_batch_async
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            crawl_result = loop.run_until_complete(
                crawl_batch_async([item["question"] for item in expanded_questions],
                                 parallel=parallel)
            )
        except TimeoutError as e:
            loop.close()
            task_report.update({
                "status": "failed",
                "finished_at": now_str(),
                "error": "captcha_timeout",
                "message": "人机验证等待超时，任务已中止。请重新发起爬取，并在弹出验证码时5分钟内完成验证。",
            })
            task_path = save_crawl_task_report(task_report)
            return jsonify({
                "error": "人机验证等待超时，任务已中止。请重新发起爬取，并在弹出验证码时5分钟内完成验证。",
                "task_id": task_id,
                "task_report": task_path,
            }), 400
        except Exception as e:
            loop.close()
            print(f"爬取异常: {e}")
            task_report.update({
                "status": "failed",
                "finished_at": now_str(),
                "error": "crawl_exception",
                "message": str(e),
            })
            task_path = save_crawl_task_report(task_report)
            return jsonify({
                "error": f"爬取过程发生错误: {str(e)}",
                "task_id": task_id,
                "task_report": task_path,
            }), 500
        finally:
            try:
                loop.close()
            except:
                pass

    if not crawl_result or not crawl_result.get("ok"):
        err = crawl_result.get("error", "") if crawl_result else ""
        if err == "need_login":
            mark_login_status(source_platform, "expired", "登录状态已失效，请重新登录")
            task_report.update({
                "status": "blocked",
                "finished_at": now_str(),
                "error": "need_login",
                "message": "请先登录平台",
            })
            task_path = save_crawl_task_report(task_report)
            return jsonify({"error": "need_login", "message": "请先登录平台", "task_id": task_id, "task_report": task_path}), 401
        if err == "cookie_expired":
            mark_login_status(source_platform, "expired", "登录状态已过期，请重新登录")
            task_report.update({
                "status": "blocked",
                "finished_at": now_str(),
                "error": "cookie_expired",
                "message": "登录状态已失效，请重新登录后再爬取",
            })
            task_path = save_crawl_task_report(task_report)
            return jsonify({"error": "cookie_expired", "message": "登录状态已失效，请重新登录后再爬取", "task_id": task_id, "task_report": task_path}), 401
        error_msg = crawl_result.get("error", "爬取失败") if crawl_result else "爬取失败"
        task_report.update({
            "status": "failed",
            "finished_at": now_str(),
            "error": error_msg,
            "message": error_msg,
        })
        task_path = save_crawl_task_report(task_report)
        return jsonify({"error": error_msg, "task_id": task_id, "task_report": task_path}), 500

    # 过滤掉 cookie_expired 的结果，已保存的正常继续处理
    valid_results = []
    result_errors = []
    crawl_failures = []
    for raw, meta in zip(crawl_result["results"], expanded_questions):
        raw_error = raw.get("error")
        if raw_error:
            result_errors.append(raw_error)
            crawl_failures.append(compact_crawl_failure(raw, meta))
        if raw_error == "cookie_expired":
            print(f"  跳过 cookie 失效题目: {meta['question'][:30]}")
        elif raw.get("ok"):
            valid_results.append((raw, meta))
        elif not raw_error:
            crawl_failures.append(compact_crawl_failure(raw, meta))
    
    if not valid_results and crawl_result.get("success", 0) == 0:
        task_report.update({
            "status": "failed",
            "finished_at": now_str(),
            "error": "crawl_failed",
            "message": "本次爬取没有获得有效结果",
            "failures": crawl_failures,
            "raw_result": {
                "total": crawl_result.get("total"),
                "success": crawl_result.get("success"),
            },
        })
        task_path = save_crawl_task_report(task_report)
        if "cookie_expired" in result_errors or "need_login" in result_errors:
            mark_login_status(source_platform, "expired", "登录状态已过期，请重新登录")
            return jsonify({
                "error": "cookie_expired",
                "message": "登录状态中途失效，请重新登录后继续爬取",
                "task_id": task_id,
                "task_report": task_path,
                "error_details": crawl_failures,
            }), 401
        return jsonify({
            "error": "crawl_failed",
            "message": "本次爬取没有获得有效结果",
            "details": result_errors[:10],
            "results": crawl_result.get("results", [])[:10],
            "task_id": task_id,
            "task_report": task_path,
            "error_details": crawl_failures,
        }), 500

    # 按问题分组，汇总多次爬取结果
    from collections import defaultdict
    question_groups = defaultdict(list)
    for raw, meta in (valid_results if valid_results else []):
        question_groups[meta["question"]].append(raw)

    saved = []
    errors = []
    analysis_fallbacks = []

    for question, rounds in question_groups.items():
        try:
            # 合并多轮回答和引用源
            all_answers = [r["answer"] for r in rounds if r.get("answer")]
            all_refs = []
            seen_titles = set()
            for r in rounds:
                for ref in r.get("refs", []):
                    t = ref.get("title", "")
                    if t and t not in seen_titles:
                        seen_titles.add(t)
                        all_refs.append(ref)

            # 构建综合分析prompt（含多轮数据）
            combined_answer = f"【共爬取{len(rounds)}次，以下为各次回答汇总】\n\n"


            for i, ans in enumerate(all_answers, 1):
                combined_answer += f"--- 第{i}次回答 ---\n{ans[:800]}\n\n"
            full_answer_for_mention = "\n\n".join(all_answers)

            # 有 API Key 时做 AI 综合分析；没有时保留原始爬取结果并标记待分析。
            if has_api_key:
                analysis, fallback_info = analyze_brand_intel_with_retry(
                    brand, question, combined_answer, all_refs, settings
                )
                if fallback_info:
                    analysis_fallbacks.append(fallback_info)
            else:
                analysis = basic_brand_analysis_without_api(brand, question, combined_answer, all_refs)
            analysis = calibrate_analysis_brand_mention(
                brand, question, full_answer_for_mention, all_refs, analysis
            )
            analysis["sample_count"] = len(rounds)  # 记录样本数

            # 保存到主分析系统（records.json）
            record = {
                "id": uid(), "client_id": client_id, "brand": brand,
                "group_id": group_id,
                "question": question,
                "answer": combined_answer,
                "refs": all_refs,
                "analysis": analysis,
                "date": now_str(), "today": today_str(),
                "auto_crawled": True,
                "repeat_count": len(rounds),
                "task_id": task_id,
                "run_id": session_id,
                "task_report": task_report_path,
                "source_platform": source_platform,
                "crawler_engine": task_report["crawler_engine"],
            }
            update_json(
                F_RECORDS,
                [],
                lambda records: ((records if isinstance(records, list) else []) + [record], None),
            )

            # 写入细化记录（每轮单独存，每轮都用共享analysis保证数据完整）
            brand_short_key = brand[:2] if len(brand) >= 2 else brand
            for i, rnd in enumerate(rounds):
                ans_text = rnd.get("answer", "")
                rnd_refs = rnd.get("refs", [])
                # 每轮单独做规则检测：只有回答正文出现完整品牌名才算已提及
                rule_check = brand in (ans_text or "")
                # 每轮使用规则结果直接赋值（不再与AI结果做OR）
                rnd_analysis = dict(analysis)
                rnd_analysis["brand_mentioned"] = rule_check
                save_raw_record(
                    client_id=client_id,
                    group_id=group_id,
                    brand=brand,
                    question=question,
                    round_num=i + 1,
                    answer=ans_text,
                    search_keywords=[],
                    refs=rnd_refs,
                    analysis=rnd_analysis,
                    source_platform=source_platform,
                    task_id=task_id,
                    run_id=session_id,
                    task_report=task_report_path,
                    crawler_engine=task_report["crawler_engine"],
                )

            # 同时保存到每日原始数据文件
            save_daily_raw(client_id, brand, question, combined_answer, all_refs, analysis)

            result_item = {
                "question": question,
                "geo_score": analysis.get("geo_score"),
                "brand_mentioned": analysis.get("brand_mentioned"),
                "sample_count": len(rounds),
                "ref_count": len(all_refs),
                "main_platform": analysis.get("main_ref", {}).get("platform", ""),
                "suggestion": analysis.get("suggestion", ""),
                "analysis_status": analysis.get("analysis_status", "ok"),
                "analysis_mode": analysis.get("analysis_mode", "ai"),
            }
            saved.append(result_item)
            # 推送进度事件
            crawl_sessions[session_id]["events"].append({
                "current": len(saved) + len(errors),
                "total": len(question_groups),
                "question": question,
                "status": "done",
                "geo_score": analysis.get("geo_score"),
                "brand_mentioned": analysis.get("brand_mentioned")
            })
        except Exception as e:
            errors.append({"question": question, "error": str(e)})

    # 爬取完成后自动生成本次汇总
    batch_summary = None
    if saved:
        try:
            mentioned_count = len([s for s in saved if s["brand_mentioned"]])
            mention_rate = round(mentioned_count / len(saved) * 100, 1)
            avg_score = round(
                sum(s["geo_score"] or 0 for s in saved) / len(saved), 1
            )
            platform_cnt = defaultdict(int)
            for s in saved:
                if s["main_platform"]:
                    platform_cnt[s["main_platform"]] += 1
            top_platforms = sorted(platform_cnt.items(), key=lambda x: x[1], reverse=True)[:3]
            batch_summary = {
                "total_questions": len(selected_questions),
                "total_samples": sum(s["sample_count"] for s in saved),
                "mentioned_count": mentioned_count,
                "mention_rate": mention_rate,
                "avg_geo_score": avg_score,
                "top_platforms": [{"platform": p, "count": c} for p, c in top_platforms],
                "date": today_str()
            }
        except:
            pass

    # 推送完成事件
    crawl_sessions[session_id]["events"].append({"status": "finished"})

    error_details = crawl_failures + errors
    task_report.update({
        "status": "completed" if not error_details else "completed_with_errors",
        "finished_at": now_str(),
        "session_id": session_id,
        "analysis_mode": "ai" if has_api_key else "basic_no_api_key",
        "total_samples": len(crawl_result["results"]),
        "analyzed": len(saved),
        "errors": len(error_details),
        "success": saved,
        "failures": crawl_failures,
        "analysis_errors": errors,
        "analysis_fallbacks": analysis_fallbacks,
        "batch_summary": batch_summary,
    })
    task_path = save_crawl_task_report(task_report)

    return jsonify({
        "ok": True,
        "task_id": task_id,
        "task_report": task_path,
        "session_id": session_id,
        "crawler_engine": task_report["crawler_engine"],
        "analysis_mode": "ai" if has_api_key else "basic_no_api_key",
        "has_api_key": has_api_key,
        "message": "" if has_api_key else "未配置 API Key：已跳过 AI 深度分析，仅保存原始回答、引用源和规则评分。",
        "total": len(selected_questions),
        "repeat_count": repeat_count,
        "total_samples": len(crawl_result["results"]),
        "analyzed": len(saved),
        "errors": len(error_details),
        "results": saved,
        "batch_summary": batch_summary,
        "analysis_fallbacks": analysis_fallbacks,
        "error_details": error_details
    })

import uuid as uuid_lib
from flask import Response, stream_with_context

# 全局进度存储
crawl_sessions = {}

@app.route("/api/crawl/progress/<session_id>")
def crawl_progress(session_id):
    """SSE：实时推送爬取进度"""
    def generate():
        import time
        sent = 0
        for _ in range(300):  # 最多等5分钟
            session = crawl_sessions.get(session_id, {})
            events = session.get("events", [])
            while sent < len(events):
                evt = events[sent]
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                sent += 1
                if evt.get("status") == "finished":
                    yield "event: done\ndata: {}\n\n"
                    return
            time.sleep(1)
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

def is_noise_answer(answer):
    """判断抓到的回答是否是豆包界面噪音"""
    import re
    if not answer or len(answer) < 30:
        return True
    # 真实回答保护（最高优先级）：豆包回答特有标志
    if re.search(r'参考.{0,5}篇资料', answer):
        return False
    if re.search(r'搜索.{0,5}个关键词', answer):
        return False
    # 文件上传界面
    if '拖放文件' in answer or ('文件类型' in answer and 'pdf' in answer.lower()):
        return True
    # 豆包首页空白页
    if '有什么我能帮你的吗' in answer:
        return True
    # 首页推荐流（多个资讯标签）
    if answer.count('资讯：') >= 2:
        return True
    # 导航栏噪音（3个以上导航词）
    noise_signs = ['Ctrl K', '新对话', '历史对话', 'AI 创作', '下载客户端']
    if sum(1 for s in noise_signs if s in answer) >= 3:
        return True
    return False

def analyze_brand_intel(brand, question, answer, refs, settings):
    """AI分析品牌引用情况（供爬取模块调用）"""
    # 如果回答是噪音，清空它，只用refs分析
    clean_answer = "" if is_noise_answer(answer) else answer

    # 预先检查回答正文中是否有品牌名（用于提示AI）
    brand_in_answer = brand in (clean_answer or "")
    brand_short = brand[:2] if len(brand) >= 2 else brand
    brand_hint = ""
    if brand_in_answer:
        brand_hint = f"注意：回答正文中已明确出现品牌名{brand}，brand_mentioned必须为true"
    elif brand_short in (clean_answer or ""):
        brand_hint = f"注意：回答正文中出现了品牌简称{brand_short}，brand_mentioned必须为true"
    else:
        brand_hint = f"注意：回答正文中未出现品牌名{brand}或其简称，brand_mentioned必须为false（引用标题含品牌名不算提及）"

    # 构建分析内容：有回答用回答，没有就只分析引用源
    if clean_answer:
        answer_section = f"豆包回答：\n{clean_answer[:2000]}"
    else:
        answer_section = "豆包回答：（未能获取，请根据引用文章列表推断）"

    prompt = f"""你是GEO引用情报分析专家。请分析以下豆包数据。

品牌名：{brand}
用户问题：{question}

{answer_section}

豆包引用的文章列表（这是最可靠的数据）：
{json.dumps(refs[:15], ensure_ascii=False, indent=2)}

{brand_hint}
分析要求：
- brand_mentioned=true 当且仅当豆包回答正文中出现了品牌名（全称或简称）
- 引用文章标题中含有品牌名，但回答正文中没有，brand_mentioned=false
- main_ref选引用列表中第一篇权威平台文章

请返回JSON，只返回JSON：
{{
  "brand_mentioned": true/false,
  "brand_rank": null或数字,
  "brand_sentiment": "positive"/"neutral"/"negative",
  "brand_snippet": "品牌相关的关键句（最多60字，无则填空字符串）",
  "main_ref": {{
    "title": "引用列表中最权威的文章标题",
    "platform": "平台名",
    "match_score": 0-100,
    "match_reason": "原因（30字内）"
  }},
  "platform_weights": [{{"platform":"平台名","count":数字,"pct":0-100}}],
  "content_patterns": ["内容规律1","规律2"],
  "title_patterns": ["标题规律1"],
  "suggestion": "下一步投放建议（40字内）"
}}"""
    raw = ai(prompt, 1500)
    raw = re.sub(r"^```json\s*|^```\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    result = json.loads(raw)

    # 规则强制覆盖：只有回答正文中出现完整品牌名才判定为"已提及"
    # 与 calc_geo_score 保持一致，不用前2字缩写避免误判
    rule_mentioned = brand in (clean_answer or "")
    result["brand_mentioned"] = rule_mentioned

    # 用算法计算GEO分（使用清洗后的回答）
    result["geo_score"] = calc_geo_score(brand, question, clean_answer, refs, result)
    return result


if __name__ == "__main__":
    host = os.environ.get("GEO_HOST", "127.0.0.1")
    port = int(os.environ.get("GEO_PORT", "5000"))
    print("="*50)
    print(f"GEO Agent v{APP_VERSION} 启动中...")
    if host in ("0.0.0.0", "::"):
        print(f"本机访问: http://localhost:{port}")
        print(f"局域网访问: http://<你的电脑IPv4地址>:{port}")
    else:
        print(f"访问地址: http://localhost:{port}")
    print("="*50)
    app.run(debug=False, host=host, port=port)
