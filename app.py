"""
GEO Agent v2 — 内容投放优化工作台
模块：客户管理 / 问题组管理 / 内容生产 / 每日分析 / 爬取任务
"""
import json, os, re, asyncio, threading, glob
from datetime import datetime, date
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, redirect, session, url_for, has_request_context
from openai import OpenAI
from services import crawl_tasks as crawl_task_store
from services import crawl_jobs as crawl_job_store
from services import records as record_store
from services import reference_intelligence as reference_intel
from services.auth import authenticate_user, create_user, find_user
from services.article_structure import analyze_article_structure
from services.article_fetcher import fetch_article_text
from services.content_generations import ContentGenerationStore
from services.content_prompts import (
    COMPARISON_FEW_SHOT_EXAMPLE,
    DEFAULT_COMPARISON_SUBTYPE,
    DEFAULT_GEO_CONTENT_RULES,
    build_content_article_subtype_prompt,
    build_content_article_type_prompt,
    build_content_generation_messages,
    build_reference_stage3_example_plugin,
    extract_generated_title,
    format_sample_article_context,
    normalize_sample_links,
    normalize_selected_sample_articles,
)
from services.deep_analysis import (
    build_daily_deep_analysis_context,
    build_raw_deep_analysis_context,
    extract_content_instruction,
)
from services.materials import MaterialService
from services.record_stats import (
    build_raw_platform_stats,
)
from services.reference_stage1 import analyze_stage1_article
from services.reference_stage2 import analyze_stage2_clusters
from services.reference_stage3 import analyze_stage3_plugins
from services.storage import load_json, save_json, update_json

app = Flask(__name__)
app.secret_key = os.environ.get("GEO_SECRET_KEY", "dev-secret-key-change-before-deploy")
APP_VERSION = "2.3"
NODE_CRAWLER_DEFAULT_PLATFORMS = {"doubao", "deepseek", "yuanbao", "qwen", "kimi"}
CLIENT_CONTRACT_PLATFORM_ORDER = ["deepseek", "yuanbao", "qwen", "kimi", "doubao"]
crawl_platform_locks_guard = threading.Lock()
crawl_platform_locks = {}
reference_analysis_jobs_guard = threading.RLock()
reference_analysis_jobs = {}


def get_crawl_platform_lock(platform):
    platform = (platform or "default").strip() or "default"
    with crawl_platform_locks_guard:
        if platform not in crawl_platform_locks:
            crawl_platform_locks[platform] = threading.Lock()
        return crawl_platform_locks[platform]

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
F_REFERENCE_INTELLIGENCE = f"{D}/reference_intelligence"
F_CRAWL_JOBS = f"{D}/crawl_jobs.json"

ANONYMOUS_ENDPOINTS = {
    "static",
    "login_page",
    "auth_login",
    "auth_register",
    "auth_logout",
    "auth_me",
    "health_check",
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
        "model": "deepseek-chat", "preset": "deepseek"
    }


def get_global_settings():
    return load(F_SETTINGS, DEFAULT_SETTINGS.copy())


def user_settings_path(username):
    safe = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(username or "").strip()).strip("._")
    return os.path.join(F_USER_SETTINGS, f"{safe or 'user'}.json")


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
    for key in ["base_url", "model", "preset"]:
        if key in data:
            settings[key] = data[key]
    save(path, settings)

def ai(prompt, max_tokens=2000):
    s = get_settings()
    return ai_with_settings(prompt, max_tokens, s)


def ai_with_settings(prompt, max_tokens=2000, settings=None):
    s = settings or get_settings()
    if not s.get("api_key"):
        raise Exception("请先在系统设置中配置 API Key")
    client = OpenAI(api_key=s["api_key"], base_url=s["base_url"].rstrip("/"))
    resp = client.chat.completions.create(
        model=s["model"], max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content.strip()

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
    raw = ai(prompt, max_tokens)
    return parse_ai_json(raw)


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
    return """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>GEO Agent 登录</title></head>
<body>
  <h1>GEO Agent</h1>
  <form id="loginForm">
    <input name="username" placeholder="用户名" autocomplete="username">
    <input name="password" type="password" placeholder="密码" autocomplete="current-password">
    <button type="submit">登录</button>
  </form>
  <hr>
  <h2>新同事注册</h2>
  <form id="registerForm">
    <input name="username" placeholder="用户名" autocomplete="username">
    <input name="password" type="password" placeholder="密码" autocomplete="new-password">
    <button type="submit">注册并进入</button>
  </form>
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
    });
  </script>
</body>
</html>"""


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


def auto_normalize_task_entities(client_id, date_str, task_id, username=None):
    """Incrementally extract competitor entities for records created by one crawl task."""
    settings = get_settings(username)
    if not settings.get("api_key"):
        return {"ok": True, "skipped": True, "reason": "missing_api_key", "changed": 0}
    if not client_id or not date_str or not task_id:
        return {"ok": False, "skipped": True, "reason": "missing_scope", "changed": 0}

    from scripts import normalize_entities

    records = load(F_RAW_RECORDS, [])
    selected = normalize_entities.select_records(
        records,
        client_id=client_id,
        date=date_str,
        task_id=task_id,
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


def run_entity_normalize_task(client_id, date_str, task_id, task_report_path, username=None):
    try:
        result = auto_normalize_task_entities(client_id, date_str, task_id, username=username)
    except Exception as exc:
        result = {"ok": False, "status": "failed", "error": str(exc), "changed": 0}
    report = load(task_report_path, {})
    report["entity_normalize"] = result
    report["entity_normalize_finished_at"] = now_str()
    save(task_report_path, report)
    return result


def queue_entity_normalize_task(client_id, date_str, task_id, task_report_path, username=None):
    status = {"ok": True, "status": "queued", "queued": True}
    thread = threading.Thread(
        target=run_entity_normalize_task,
        args=(client_id, date_str, task_id, task_report_path, username),
        daemon=True,
    )
    thread.start()
    return status

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

@app.route("/api/raw_records/deep_analyze", methods=["POST"])
def deep_analyze():
    """对筛选后的记录做AI深度分析"""
    d = request.json
    client_id = d.get("client_id", "")
    group_id = d.get("group_id", "")
    date = d.get("date", "")
    question = d.get("question", "")
    mentioned_only = d.get("mentioned_only", "")
    source_platform = d.get("platform", "")  # 按爬取平台过滤
    task_id = d.get("task_id", "")

    records = load_client_records(
        client_id,
        date=date,
        group_id=group_id,
        platform=source_platform,
        task_id=task_id,
        question=question,
        mentioned_only=mentioned_only,
    )
    if not records:
        return jsonify({"error": "无匹配记录"}), 400

    analysis_context = build_raw_deep_analysis_context(records)
    platform_weights = analysis_context["platform_weights"]
    mentioned = analysis_context["mentioned"]
    avg_score = analysis_context["avg_score"]
    sample_refs = analysis_context["sample_refs"]

    prompt = f"""你是GEO优化专家，请对以下豆包引用监测数据做深度分析，并输出可直接指导内容生产的分析报告。

【数据概况】
品牌：{day_data.get("brand","") if False else records[0].get("brand","") if records else ""}
监测记录数：{len(records)}条
品牌提及次数：{len(mentioned)}/{len(records)}（{round(len(mentioned)/len(records)*100,1)}%）
平均GEO评分：{avg_score}

【平台权重分布】
{json.dumps(platform_weights, ensure_ascii=False)}

【高频引用文章样本】
{chr(10).join(sample_refs)}

【各问题表现摘要】
{json.dumps([{"q": r["question"][:40], "mentioned": r.get("brand_mentioned"), "score": r.get("geo_score"), "platform": r.get("main_platform")} for r in records[:15]], ensure_ascii=False)}

请生成Markdown深度分析报告，包含以下章节：

## 一、核心发现
（3-5条关键结论，数据支撑）

## 二、平台偏好深度解读
（每个主要平台：为何被豆包偏好？内容特征是什么？适合什么文章类型？）

## 三、豆包抓取逻辑推断
（从引用文章规律反推豆包的算法偏好：标题结构、字数、内容类型、权威性信号）

## 四、高价值问题场景
（哪类问题最容易触发品牌引用？问题措辞有何规律？）

## 五、各平台内容创作指南
对每个主要平台分别给出：
- 推荐文章类型（推荐类软文/测评/横向对比/中立资讯/榜单/避坑指南等）
- 标题公式（给出2-3个可直接套用的标题模板）
- 内容结构建议（开头/中间/结尾怎么写）
- 关键词布局（哪些词必须出现）
- 字数建议
- 营销程度（强推广/轻植入/完全中立）

## 六、内容生产总指令
【重要】请在此章节输出一段结构化的内容生产指令，格式如下：

```
CONTENT_INSTRUCTION_START
品牌：[品牌名]
核心目标：[用一句话描述内容生产的核心目标]
豆包偏好规律：[总结豆包喜欢什么类型的文章，100字以内]
必含要素：[列出文章必须包含的3-5个要素]
禁忌事项：[列出文章应避免的2-3个问题]
平台策略：
  - [平台1]：[文章类型] | [标题模板] | [字数] | [营销程度]
  - [平台2]：[文章类型] | [标题模板] | [字数] | [营销程度]
  - [平台3]：[文章类型] | [标题模板] | [字数] | [营销程度]
CONTENT_INSTRUCTION_END
```

## 七、下一步投放行动计划
（按优先级排列，具体可执行，包含时间节点建议）"""

    try:
        report = ai(prompt, 2500)
        content_instruction = extract_content_instruction(report)

        return jsonify({
            "ok": True,
            "stats": {
                "total": len(records),
                "mentioned": len(mentioned),
                "mention_rate": round(len(mentioned)/len(records)*100, 1),
                "avg_score": avg_score,
                "platform_weights": platform_weights
            },
            "report": report,
            "content_instruction": content_instruction  # 可直接导入内容生产的指令
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# 客户资料上传模块
# ══════════════════════════════════════════════════════
import werkzeug
from flask import send_from_directory

UPLOAD_FOLDER = "data/uploads"
LOCAL_PDF_FOLDER = "pdf"
F_MATERIALS_INDEX = f"{D}/materials_index.json"
MATERIAL_CACHE_FOLDER = f"{D}/material_cache"
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md', 'docx', 'doc'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def material_service():
    return MaterialService(
        root_dir=".",
        upload_dir=UPLOAD_FOLDER,
        local_pdf_dir=LOCAL_PDF_FOLDER,
        index_path=F_MATERIALS_INDEX,
        cache_dir=MATERIAL_CACHE_FOLDER,
    )

@app.route("/api/materials/local", methods=["GET"])
def list_local_materials():
    """列出项目 pdf/ 文件夹下可导入的客户资料。"""
    return jsonify({"ok": True, "files": material_service().list_local_materials()})

@app.route("/api/materials/<cid>", methods=["GET"])
def get_materials(cid):
    """获取客户已上传的资料列表"""
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
    files = request.files.getlist('file')
    if not files:
        return jsonify({"error": "没有文件"}), 400
    service = material_service()
    materials = []
    try:
        for file in files:
            if not file or not file.filename:
                continue
            if not allowed_file(file.filename):
                return jsonify({"error": "不支持的文件格式，请上传 txt/pdf/md/docx"}), 400
            material = service.save_uploaded_material(cid, file, file.filename)
            materials.append(service.parse_material(cid, material["id"]))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not materials:
        return jsonify({"error": "没有文件"}), 400
    first = materials[0]
    return jsonify({
        "ok": True,
        "name": first.get("original_name"),
        "saved_as": first.get("stored_name"),
        "materials": materials,
    })

@app.route("/api/materials/<cid>/import-local", methods=["POST"])
def import_local_materials(cid):
    """从项目 pdf/ 文件夹导入资料到当前客户。"""
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    data = request.get_json(silent=True) or {}
    filenames = data.get("filenames")
    if isinstance(filenames, str):
        filenames = [filenames]
    if not isinstance(filenames, list) or not filenames:
        return jsonify({"error": "请选择要导入的文件"}), 400
    service = material_service()
    materials = []
    try:
        for filename in filenames:
            material = service.import_local_material(cid, str(filename))
            materials.append(service.parse_material(cid, material["id"]))
    except FileNotFoundError:
        return jsonify({"error": "找不到本地资料文件"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "materials": materials})

@app.route("/api/materials/<cid>/<material_id>/parse", methods=["POST"])
def parse_material(cid, material_id):
    """解析资料并生成清洗文本与事实卡。"""
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

def extract_material_file_text(fpath, max_chars=4000):
    ext = fpath.rsplit('.', 1)[-1].lower()
    if ext in ('txt', 'md'):
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
            return fp.read()[:max_chars]
    if ext == 'docx':
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(fpath) as zf:
                xml = zf.read("word/document.xml")
            root = ET.fromstring(xml)
            texts = [node.text for node in root.iter() if node.text]
            return "\n".join(texts)[:max_chars]
        except Exception:
            return ""
    if ext == 'pdf':
        try:
            import pdfplumber
            with pdfplumber.open(fpath) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages[:8])
            return text[:max_chars]
        except Exception:
            try:
                from pypdf import PdfReader
                reader = PdfReader(fpath)
                text = "\n".join(page.extract_text() or "" for page in reader.pages[:8])
                return text[:max_chars]
            except Exception:
                return ""
    return ""

def read_material_bundle(cid, max_chars=12000, per_file_chars=4000):
    """读取当前客户上传目录中的全部资料，返回带文件名的合并文本。"""
    indexed_bundle = material_service().build_generation_bundle(cid, max_chars=max_chars)
    if indexed_bundle.get("text") or indexed_bundle.get("files"):
        return indexed_bundle

    client_dir = os.path.join(UPLOAD_FOLDER, cid)
    if not os.path.exists(client_dir):
        return {"text": "", "files": []}
    sections = []
    files = []
    for filename in sorted(os.listdir(client_dir)):
        fpath = os.path.join(client_dir, filename)
        if not os.path.isfile(fpath) or not allowed_file(filename):
            continue
        try:
            text = extract_material_file_text(fpath, per_file_chars).strip()
        except Exception:
            text = ""
        files.append({
            "name": filename,
            "chars": len(text),
            "has_text": bool(text),
        })
        if text:
            sections.append(f"【资料：{filename}】\n{text}")
        else:
            sections.append(f"【资料：{filename}】\n（该文件暂未提取到可用正文，仅保留文件名作为上下文。）")
    combined = "\n\n---\n\n".join(sections)
    return {"text": combined[:max_chars], "files": files}

def read_material_text(cid, max_chars=3000):
    """读取客户资料文本内容，用于内容生产参考"""
    return read_material_bundle(cid, max_chars=max_chars, per_file_chars=1000)["text"][:max_chars]

def get_client(cid):
    return next((c for c in load(F_CLIENTS, []) if c.get("id") == cid), None)

def normalize_content_history_date(value):
    value = str(value or "").strip()
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return ""
    y, m, d = value[:4], value[5:7], value[8:10]
    return value if y.isdigit() and m.isdigit() and d.isdigit() else ""

def load_content_session(cid, history_date=None):
    return content_generation_store().load_session(cid, date=history_date)

def load_content_messages(cid, article_type, history_date=None):
    return content_generation_store().load_messages(cid, article_type=article_type, date=history_date)

def content_generation_store():
    db_path = os.path.splitext(F_CONTENT_GENERATIONS)[0] + ".sqlite3"
    return ContentGenerationStore(db_path, legacy_json_path=F_CONTENT_GENERATIONS)

def append_content_generation(cid, article, user_message, assistant_message):
    return content_generation_store().append_generation(cid, article, user_message, assistant_message)

def delete_content_generation(cid, article_id):
    return content_generation_store().delete_generation(cid, article_id)

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



def reference_intelligence_path(client_id, date_str, task_id=""):
    return reference_intel.reference_intelligence_path(
        F_REFERENCE_INTELLIGENCE, client_id, date_str, today_str, task_id
    )


def normalize_reference_plugins(plugins):
    return reference_intel.normalize_reference_plugins(plugins)


def normalize_reference_clusters(clusters):
    return reference_intel.normalize_reference_clusters(clusters)


def load_reference_intelligence(client_id, date_str, task_id=""):
    return reference_intel.load_reference_intelligence(
        F_REFERENCE_INTELLIGENCE, load, today_str, client_id, date_str, task_id
    )


def save_reference_intelligence(payload):
    return reference_intel.save_reference_intelligence(
        F_REFERENCE_INTELLIGENCE, save, today_str, now_str, payload
    )


def reference_stage_dir(client_id, date_str):
    return reference_intel.reference_stage_dir(
        F_REFERENCE_INTELLIGENCE, client_id, date_str, today_str
    )


def collect_reference_articles(records, limit=20):
    return reference_intel.collect_reference_articles(records, limit=limit)


def create_reference_analysis_job(client_id, date_str, task_id="", username=""):
    return reference_intel.create_reference_analysis_job(
        reference_analysis_jobs,
        reference_analysis_jobs_guard,
        uid,
        now_str,
        client_id,
        date_str,
        task_id,
        username,
    )


def create_or_reuse_reference_analysis_job(client_id, date_str, task_id="", username=""):
    return reference_intel.create_or_reuse_reference_analysis_job(
        reference_analysis_jobs,
        reference_analysis_jobs_guard,
        uid,
        now_str,
        client_id,
        date_str,
        task_id,
        username,
    )


def get_reference_analysis_job(job_id):
    return reference_intel.get_reference_analysis_job(
        reference_analysis_jobs, reference_analysis_jobs_guard, job_id
    )


def update_reference_analysis_job(job_id, **fields):
    return reference_intel.update_reference_analysis_job(
        reference_analysis_jobs, reference_analysis_jobs_guard, now_str, job_id, **fields
    )


def reference_analysis_cancel_requested(job_id):
    return bool(get_reference_analysis_job(job_id).get("cancel_requested"))


def cancel_reference_analysis_job(job_id):
    return reference_intel.cancel_reference_analysis_job(
        reference_analysis_jobs, reference_analysis_jobs_guard, now_str, job_id
    )


def _job_ai_json(username):
    settings = get_settings(username)
    return lambda prompt, max_tokens: ai_json_with_settings(prompt, max_tokens, settings)


def load_reference_fetch_cache(stage_dir):
    return reference_intel.load_reference_fetch_cache(stage_dir, load)


def merge_reference_fetch_result(ref, fetched, fetch_method=None):
    return reference_intel.merge_reference_fetch_result(ref, fetched, fetch_method=fetch_method)


def run_reference_analysis_job(
    job_id,
    client_id,
    date_str,
    task_id="",
    username="",
    fetch_fn=fetch_article_text,
    ai_json_fn=None,
    limit=20,
    candidate_limit=None,
    fetch_workers=3,
):
    return reference_intel.run_reference_analysis_job(
        job_id,
        client_id,
        date_str,
        root_dir=F_REFERENCE_INTELLIGENCE,
        load_fn=load,
        save_fn=save,
        today_fn=today_str,
        now_fn=now_str,
        load_client_records_fn=load_client_records,
        job_ai_json_fn=_job_ai_json,
        get_job_fn=get_reference_analysis_job,
        update_job_fn=update_reference_analysis_job,
        cancel_requested_fn=reference_analysis_cancel_requested,
        fetch_fn=fetch_fn,
        analyze_stage1_article_fn=analyze_stage1_article,
        analyze_stage2_clusters_fn=analyze_stage2_clusters,
        analyze_stage3_plugins_fn=analyze_stage3_plugins,
        task_id=task_id,
        username=username,
        ai_json_fn=ai_json_fn,
        limit=limit,
        candidate_limit=candidate_limit,
        fetch_workers=fetch_workers,
    )


def queue_reference_analysis_job(client_id, date_str, task_id="", username=""):
    job, should_start = create_or_reuse_reference_analysis_job(client_id, date_str, task_id, username=username)
    if not should_start:
        return job
    job_id = job["job_id"]
    thread = threading.Thread(
        target=run_reference_analysis_job,
        kwargs={
            "job_id": job_id,
            "client_id": client_id,
            "date_str": date_str,
            "task_id": task_id,
            "username": username,
        },
        daemon=True,
    )
    thread.start()
    return get_reference_analysis_job(job_id)


def build_reference_cluster_prompt(articles):
    return reference_intel.build_reference_cluster_prompt(articles)


def build_reference_plugin_prompt(clusters):
    return reference_intel.build_reference_plugin_prompt(
        clusters, build_reference_stage3_example_plugin()
    )


def build_reference_intelligence_prompt(articles):
    return reference_intel.build_reference_intelligence_prompt(articles)


def latest_entity_report_status(client_id, date_str, task_id=""):
    pattern = os.path.join(get_crawl_task_dir(), f"{date_str}_*.json")
    reports = []
    for path in glob.glob(pattern):
        report = load(path, {})
        if report.get("client_id") != client_id:
            continue
        if task_id and report.get("task_id") != task_id:
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
        "task_id": report.get("task_id") or "",
        "task_report": path,
        "finished_at": report.get("entity_normalize_finished_at") or "",
        "changed": entity.get("changed", 0),
        "selected_records": entity.get("selected_records", 0),
        "error": entity.get("error", ""),
        "message": entity.get("reason", ""),
    }


@app.route("/api/reference_intelligence/plugins", methods=["GET"])
def get_reference_intelligence_plugins():
    client_id = request.args.get("client_id", "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    date_str = request.args.get("date", today_str()).strip()
    task_id = request.args.get("task_id", "").strip()
    body = load_reference_intelligence(client_id, date_str, task_id)
    return jsonify({"ok": True, **body})


@app.route("/api/reference_intelligence/plugins", methods=["POST"])
def save_reference_intelligence_plugins():
    try:
        body = save_reference_intelligence(request.json or {})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(body)


@app.route("/api/reference_intelligence/analyze", methods=["POST"])
def analyze_reference_intelligence():
    payload = request.json or {}
    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    date_str = (payload.get("date") or today_str()).strip()
    task_id = (payload.get("task_id") or "").strip()
    body = queue_reference_analysis_job(
        client_id=client_id,
        date_str=date_str,
        task_id=task_id,
        username=settings_username(),
    )
    return jsonify(body)


@app.route("/api/reference_intelligence/analyze_status", methods=["GET"])
def reference_intelligence_analyze_status():
    job_id = request.args.get("job_id", "").strip()
    job = get_reference_analysis_job(job_id)
    if not job:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(job)


@app.route("/api/reference_intelligence/analyze_cancel", methods=["POST"])
def reference_intelligence_analyze_cancel():
    job_id = str((request.json or {}).get("job_id") or "").strip()
    job = cancel_reference_analysis_job(job_id)
    if not job:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(job)


@app.route("/api/daily/entity_status", methods=["GET"])
def daily_entity_status():
    client_id = request.args.get("client_id", "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    date_str = request.args.get("date", today_str()).strip()
    task_id = request.args.get("task_id", "").strip()
    return jsonify(latest_entity_report_status(client_id, date_str, task_id))


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
    opinion = (d.get("opinion") or "").strip()
    if not cid:
        return jsonify({"error": "缺少client_id"}), 400
    if not opinion:
        return jsonify({"error": "请先填写运营意见"}), 400
    client = require_client_access(cid)
    if not client:
        return jsonify({"error": "客户不存在"}), 404

    material_bundle = read_material_bundle(cid)
    sample_links = normalize_sample_links(d.get("sample_links", []))
    selected_articles = normalize_selected_sample_articles(d.get("selected_articles", []))
    article_type = d.get("article_type") if d.get("article_type") in {"对比型", "介绍型"} else "对比型"
    article_subtype = (d.get("article_subtype") or "").strip()
    article_subtype_plugin = d.get("article_subtype_plugin") if isinstance(d.get("article_subtype_plugin"), dict) else None
    history_date = normalize_content_history_date(d.get("history_date") or d.get("date")) or today_str()
    history = load_content_messages(cid, article_type, history_date=history_date)
    messages = build_content_generation_messages(
        client,
        material_bundle,
        history,
        opinion,
        sample_links=sample_links,
        selected_articles=selected_articles,
        article_type=article_type,
        article_subtype=article_subtype,
        article_subtype_plugin=article_subtype_plugin,
    )
    generation_model = get_settings().get("model", "deepseek-chat")
    try:
        content = ai_deepseek_pro(messages, 6000)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    created_at = now_str()
    article = {
        "id": uid(),
        "client_id": cid,
        "title": extract_generated_title(content),
        "content": content,
        "operator_opinion": opinion,
        "model": generation_model,
        "material_count": len(material_bundle.get("files") or []),
        "sample_link_count": len(sample_links),
        "selected_article_count": len(selected_articles),
        "sample_links": sample_links,
        "selected_articles": selected_articles,
        "article_type": article_type,
        "article_subtype": article_subtype,
        "created_at": created_at,
        "created_by": (current_user() or {}).get("username", ""),
    }
    user_message = {"role": "user", "content": opinion, "created_at": created_at, "article_id": article["id"]}
    assistant_message = {"role": "assistant", "content": content, "created_at": created_at, "article_id": article["id"]}
    article = append_content_generation(cid, article, user_message, assistant_message)
    session = load_content_session(cid, history_date=history_date)
    articles = sorted(
        session["articles"],
        key=lambda x: (int(x.get("sequence") or 0), x.get("created_at", "")),
        reverse=True,
    )
    return jsonify({"ok": True, "article": article, "articles": articles})

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
    deleted = record_store.delete_raw_record(F_RAW_RECORDS, rid)
    return jsonify({"ok": True, "deleted": deleted})

@app.route("/api/daily/records/batch_delete", methods=["POST"])
def batch_delete_records():
    """批量删除多条记录"""
    ids = set(request.json.get("ids", []))
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


@app.route("/api/daily/deep_analyze", methods=["POST"])
def daily_deep_analyze():
    """深度分析：按平台分类统计，生成详细报告和内容生产指令"""
    d = request.json
    client_id = d.get("client_id", "")
    date = d.get("date", today_str())
    brand = d.get("brand", "")
    source_platform = d.get("platform", "")  # 按爬取来源平台过滤
    group_id = d.get("group_id", "")          # 按问题组过滤（新增）
    group_name = d.get("group_name", "")      # 问题组名称（用于报告标题）
    task_id = d.get("task_id", "")

    records = load_client_records(client_id, date=date,
                                  platform=source_platform if source_platform else None,
                                  group_id=group_id if group_id else None,
                                  task_id=task_id if task_id else None)
    if not records:
        scope = f"「{group_name}」问题组" if group_name else "当日"
        return jsonify({"error": f"{scope}暂无数据，请先完成爬取"}), 400

    analysis_context = build_daily_deep_analysis_context(records)
    total_refs = analysis_context["total_refs"]
    total_records = analysis_context["total_records"]
    platform_stats = analysis_context["platform_stats"]
    top8_platforms = analysis_context["top8_platforms"]
    mentioned = analysis_context["mentioned"]
    mention_rate = analysis_context["mention_rate"]
    avg_score = analysis_context["avg_score"]
    emerging = analysis_context["emerging"]
    emerging_str = analysis_context["emerging_str"]
    platform_summary = analysis_context["platform_summary"]

    group_scope = f"问题组：{group_name}" if group_name else "问题组：全部（未筛选）"
    prompt = f"""你是GEO内容策略专家。请基于以下豆包引用监测数据生成深度分析报告。

【监测概况】
日期：{date} | 品牌：{brand} | {group_scope}
监测问题：{total_records}条 | 品牌提及率：{mention_rate}% | 平均GEO分：{avg_score}
新兴参考源：{emerging_str}

【Top8平台权重数据】
{platform_summary}

请生成深度分析报告（Markdown格式），必须包含以下章节：

## 一、核心结论（3条最重要发现）

## 二、平台权重深度解读
（对每个Top平台：为什么豆包偏好它？引用文章有何规律？文章类型偏好？）

## 三、豆包内容抓取逻辑推断
（从引用文章反推：标题格式、内容结构、字数、营销程度偏好）

## 四、新兴GEO平台机会
（{emerging_str}有何特点？为何具有GEO投放价值？）

## 五、各平台内容生产规范
（对每个Top5平台单独说明：文章类型/标题公式/结构要求/品牌植入方式）

## 六、今日内容生产总指令
（生成一段200字的综合内容生产指令，包含：目标平台特性、文章类型、结构要求、豆包友好度优化要点）"""

    try:
        report = ai(prompt, 3000)

        # 5. 读取两路参考资料（均为客户专属）
        # 主要参考：客户专属软文模板（框架基础）
        user_template = get_active_template(client_id)
        template_section = f"""━━━【主要参考：通用软文模板（框架基础，请严格以此为主体）】━━━
{user_template}""" if user_template else "━━━【无通用模板】请根据平台特性和高频文章规律自行构建完整模板框架━━━"

        # 辅助参考：客户品牌资料（仅用于验证）
        brand_material = read_material_text(client_id, max_chars=800)
        brand_section = f"""━━━【辅助参考：客户品牌资料（仅用于验证，不影响模板结构）】━━━
{brand_material}
注意：品牌资料仅用于 ① 确认哪些卖点可写 ② 了解品牌调性和禁忌，不要让品牌资料影响模板结构和文章类型判断""" if brand_material else ""

        # 6. 读取平台库工具箱规范
        all_platforms = load(F_PLATFORMS, [])

        # 7. 为每个平台生成完整的专属发文模板
        platform_prompts = {}
        for pf in top8_platforms[:5]:
            titles = chr(10).join([
                f"  - {a['title'][:45]}（被引{a['count']}次）"
                for a in pf["top_articles"][:5]
            ])

            # 从平台库工具箱读取用户自定义规范
            pf_spec = next((p for p in all_platforms if p["name"] == pf["platform"]), None)
            if pf_spec:
                spec_section = f"""━━━【用户自定义平台规范（来自平台库工具箱，必须严格遵守）】━━━
内容风格：{pf_spec.get('style', '未设置')}
推荐字数：{pf_spec.get('word_count', '未设置')}
标题规范：{pf_spec.get('title_rule', '未设置')}
禁忌事项：{pf_spec.get('taboos', '未设置')}
备注要求：{pf_spec.get('notes', '未设置')}"""
            else:
                spec_section = f'━━━【{pf["platform"]}平台规范】━━━\n（平台库中暂无该平台的自定义规范，请根据平台特性自行判断）'

            pf_prompt = f"""你是{pf['platform']}平台资深内容创作者，精通GEO优化。

请生成一份{pf['platform']}平台专属发文模板。

{template_section}

━━━【{pf['platform']}豆包引用数据（用于了解豆包内容偏好）】━━━
豆包引用权重：{pf['weight_pct']}%  |  平均引用排名：第{pf['avg_position']}位
品牌提及率：{pf['mention_rate']}%  |  GEO价值：{'★新兴高价值平台' if pf.get('is_emerging') else '稳定核心平台'}
豆包高频引用文章（分析内容规律）：
{titles}

{spec_section}

{brand_section}

━━━【输出要求】━━━
以通用模板为主体框架，结合平台规范和豆包偏好进行改造，输出完整可填写的发文模板。

## 一、{pf['platform']}内容偏好分析
（结合豆包高频文章和平台规范：文章类型/标题规律/字数/营销程度/结构特征）

## 二、标题公式（3个可直接套用，必须符合平台标题规范）

## 三、完整文章结构模板
（严格基于通用模板框架，按平台字数要求逐段给出具体写法和占位符）

## 四、品牌植入指南
（结合品牌调性和平台禁忌，说明植入位置、方式、注意事项）

## 五、豆包友好度优化清单
（让文章更容易被豆包抓取的5条具体要点）"""

            try:
                platform_prompts[pf["platform"]] = ai(pf_prompt, 1500)  # 从2000降到1500减少超时
            except Exception as e:
                # 生成失败时给一个简短的备用提示词
                # 生成失败给备用提示词
                fallback = '你是' + pf['platform'] + '平台内容创作者（权重' + str(pf['weight_pct']) + '%）。请参考该平台高频文章风格，生成关于[主题]的文章。'
                platform_prompts[pf['platform']] = fallback
        return jsonify({
            "ok": True,
            "date": date,
            "group_id": group_id,
            "group_name": group_name,
            "stats": {
                "total_records": total_records,
                "mentioned": len(mentioned),
                "mention_rate": mention_rate,
                "avg_score": avg_score,
                "emerging_platforms": [p["platform"] for p in emerging]
            },
            "platform_stats": platform_stats,
            "top8_platforms": top8_platforms,
            "report": report,
            "platform_prompts": platform_prompts  # 各平台专属提示词
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    s_safe = {k: v for k, v in s.items() if k != "api_key"}
    s_safe["has_key"] = bool(s.get("api_key"))
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


@app.route("/api/crawl_jobs", methods=["GET"])
def list_crawl_jobs_api():
    client_id = request.args.get("client_id", "").strip()
    jobs = crawl_job_store.load_jobs(F_CRAWL_JOBS)
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
    job = crawl_job_store.claim_next_job(F_CRAWL_JOBS, worker_id, platform, now_str)
    return jsonify({"ok": True, "job": job})


@app.route("/api/crawl_jobs/<job_id>/cancel", methods=["POST"])
def cancel_crawl_job_api(job_id):
    job = crawl_job_store.cancel_job(F_CRAWL_JOBS, job_id, now_str)
    if not job:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify({"ok": True, "job": job})


@app.route("/api/crawl_jobs/<job_id>/result", methods=["POST"])
def finish_crawl_job_api(job_id):
    job = crawl_job_store.finish_job(F_CRAWL_JOBS, job_id, request.json or {}, now_str)
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

    entity_normalize = {"ok": True, "status": "queued", "queued": True}

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
        "entity_normalize": entity_normalize,
    })
    task_path = save_crawl_task_report(task_report)
    entity_normalize = queue_entity_normalize_task(
        client_id,
        today_str(),
        task_id,
        task_path,
        settings_username(),
    )

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
        "entity_normalize": entity_normalize,
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
