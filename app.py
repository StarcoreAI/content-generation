"""
GEO Agent v2 — 内容投放优化工作台
模块：客户管理 / 问题组管理 / AI引用情报 / 平台库 / 内容生产 / 数据看板
"""
import json, os, re, csv, asyncio, threading
from datetime import datetime, date
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, send_file
from openai import OpenAI
import io
from services import crawl_tasks as crawl_task_store
from services import records as record_store
from services.storage import load_json, save_json

app = Flask(__name__)
APP_VERSION = "2.3"
NODE_CRAWLER_DEFAULT_PLATFORMS = {"doubao", "deepseek", "yuanbao", "qwen"}
CLIENT_CONTRACT_PLATFORM_ORDER = ["doubao", "deepseek", "yuanbao", "qwen"]
crawl_run_lock = threading.Lock()

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
    from services.record_insights import build_record_insights, merge_body_hit_results

    insights = build_record_insights(records)
    competitor_articles = insights.get("competitor_articles", [])
    selected_competitors = insights.get("selected_competitors", [])
    body_hits = body_hit_report.get("body_hits", []) if body_hit_report else []
    if body_hit_report:
        competitor_articles = merge_body_hit_results(
            competitor_articles,
            body_hits,
            selected_competitors,
        )
    competitor_by_key = {
        canonical_article_key(item.get("title", ""), item.get("url", "")): item
        for item in competitor_articles
    }
    body_status_by_key = {
        canonical_article_key(item.get("title", ""), item.get("url", "")): item
        for item in body_hits
    }
    for article in top_articles:
        key = canonical_article_key(article.get("title", ""), article.get("url", ""))
        match = competitor_by_key.get(key)
        if match:
            article["competitor_match_status"] = "matched"
            article["competitor_match_label"] = "提到目标竞品"
            article["competitor_match_types"] = match.get("match_types", [])
            article["competitor_matched_entities"] = match.get("related_entities", [])
            continue

        body_status = body_status_by_key.get(key)
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


def load_client_records(client_id, date=None, group_id=None, platform=None, task_id=None):
    """
    严格按 client_id 过滤爬取记录的唯一入口。
    client_id 为空时强制返回空列表，绝不读取全量数据，防止跨客户串数据。
    platform: 可选，按来源平台过滤（doubao/deepseek/yuanbao/qwen），None=全部
    """
    return record_store.load_client_records(
        F_RAW_RECORDS, client_id, date, group_id, normalize_platform_filter(platform), task_id
    )


def today_str(): return date.today().isoformat()
def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M")
def uid(): return datetime.now().strftime("%Y%m%d%H%M%S%f")

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
def get_settings():
    return load(F_SETTINGS, {
        "api_key": "", "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat", "preset": "deepseek"
    })

def ai(prompt, max_tokens=2000):
    s = get_settings()
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
        model="deepseek-pro", max_tokens=max_tokens, messages=messages
    )
    return resp.choices[0].message.content.strip()

def ai_json(prompt, max_tokens=1500):
    raw = ai(prompt, max_tokens)
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
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/health", methods=["GET"])
def health_check():
    """Lightweight environment check that does not require an API key."""
    settings = get_settings()
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
def get_clients(): return jsonify(load(F_CLIENTS, []))

@app.route("/api/clients", methods=["POST"])
def add_client():
    clients = load(F_CLIENTS, [])
    d = request.json
    c = {"id": uid(), "name": d["name"], "brand": d["brand"],
         "industry": d.get("industry",""), "goal": d.get("goal",""),
         "contract_platforms": normalize_contract_platforms(d.get("contract_platforms", [])),
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
# 模块二：AI引用情报
# ══════════════════════════════════════════════════════
@app.route("/api/intel/analyze", methods=["POST"])
def analyze_intel():
    """分析单条豆包回答：提取引用源 + AI深度分析"""
    d = request.json
    question = d["question"]
    answer = d["answer"]
    refs = d.get("refs", [])  # [{title, url, platform}]
    brand = d["brand"]
    cid = d["client_id"]

    # AI分析
    prompt = f"""你是GEO引用情报分析专家。请分析以下豆包回答数据。

品牌名：{brand}
用户问题：{question}

豆包回答：
{answer}

豆包引用的文章列表：
{json.dumps(refs, ensure_ascii=False, indent=2)}

请返回JSON分析结果，只返回JSON：
{{
  "brand_mentioned": true/false,
  "brand_rank": null或数字（品牌在推荐中的排名）,
  "brand_sentiment": "positive"/"neutral"/"negative",
  "brand_snippet": "品牌相关的关键句（最多60字）",
  "main_ref": {{
    "title": "与豆包回答最符合的文章标题",
    "platform": "平台名",
    "match_score": 0-100,
    "match_reason": "为什么这篇文章是主要参考（30字内）"
  }},
  "platform_weights": [{{"platform":"平台名","count":数字,"pct":0-100}}],
  "content_patterns": ["高引用文章的内容规律1","规律2","规律3"],
  "title_patterns": ["标题规律1","标题规律2"],
  "geo_score": 0-100,
  "suggestion": "下一步投放建议（40字内）"
}}"""
    try:
        analysis = ai_json(prompt)
        record = {
            "id": uid(), "client_id": cid, "brand": brand,
            "question": question, "answer": answer, "refs": refs,
            "analysis": analysis, "date": now_str(), "today": today_str()
        }
        records = load(F_RECORDS, [])
        records.append(record)
        save(F_RECORDS, records)
        return jsonify({"ok": True, "analysis": analysis, "record_id": record["id"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/intel/records", methods=["GET"])
def get_records():
    cid = request.args.get("client_id","")
    platform = normalize_platform_filter(request.args.get("platform", ""))
    records = load(F_RECORDS, [])
    if cid:
        records = [r for r in records if r.get("client_id") == cid]
    if platform:
        records = [r for r in records if r.get("source_platform", "doubao") == platform]
    return jsonify(sorted(records, key=lambda x: x["date"], reverse=True))

@app.route("/api/intel/platform_report", methods=["GET"])
def platform_report():
    """聚合分析：哪些平台被高频引用"""
    cid = request.args.get("client_id","")
    records = load(F_RECORDS, [])
    if cid:
        records = [r for r in records if r.get("client_id") == cid]
    platform_cnt = defaultdict(int)
    platform_articles = defaultdict(list)
    for r in records:
        for ref in r.get("refs", []):
            p = ref.get("platform","未知")
            platform_cnt[p] += 1
            platform_articles[p].append(ref.get("title",""))
    total = sum(platform_cnt.values()) or 1
    result = sorted([
        {"platform": p, "count": c,
         "pct": round(c/total*100, 1),
         "sample_titles": list(set(platform_articles[p]))[:3]}
        for p, c in platform_cnt.items()
    ], key=lambda x: x["count"], reverse=True)
    return jsonify(result)

@app.route("/api/intel/ai_report", methods=["POST"])
def ai_intel_report():
    """AI生成平台偏好洞察报告"""
    d = request.json
    cid = d.get("client_id","")
    records = load(F_RECORDS, [])
    if cid:
        records = [r for r in records if r.get("client_id") == cid]
    if not records:
        return jsonify({"error": "暂无监测记录"}), 400
    summaries = [{"question": r["question"], "analysis": r["analysis"]} for r in records[-20:]]
    prompt = f"""你是GEO优化专家。请基于以下豆包引用监测数据，总结豆包的内容抓取偏好规律，为后续内容生产和投放提供指导。

监测数据（共{len(records)}条）：
{json.dumps(summaries, ensure_ascii=False, indent=2)}

请生成Markdown格式报告，包含：
## 平台偏好结论
## 高引用内容规律（标题、结构、字数等）
## 豆包抓取逻辑推断
## 下一轮投放策略建议（具体可执行）"""
    try:
        report = ai(prompt, 2000)
        return jsonify({"ok": True, "report": report})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════
# 模块四：平台库工具箱
# ══════════════════════════════════════════════════════
@app.route("/api/platforms", methods=["GET"])
def get_platforms(): return jsonify(load(F_PLATFORMS, []))

@app.route("/api/platforms", methods=["POST"])
def add_platform():
    platforms = load(F_PLATFORMS, [])
    d = request.json
    p = {"id": uid(), "name": d["name"], "style": d.get("style",""),
         "word_count": d.get("word_count",""), "title_rule": d.get("title_rule",""),
         "taboos": d.get("taboos",""), "notes": d.get("notes",""),
         "created": today_str()}
    platforms.append(p)
    save(F_PLATFORMS, platforms)
    return jsonify({"ok": True, "platform": p})

@app.route("/api/platforms/<pid>", methods=["PUT"])
def update_platform(pid):
    platforms = load(F_PLATFORMS, [])
    d = request.json
    for p in platforms:
        if p["id"] == pid:
            p.update({k: d[k] for k in ["name","style","word_count","title_rule","taboos","notes"] if k in d})
    save(F_PLATFORMS, platforms)
    return jsonify({"ok": True})

@app.route("/api/platforms/<pid>", methods=["DELETE"])
def del_platform(pid):
    platforms = [p for p in load(F_PLATFORMS, []) if p["id"] != pid]
    save(F_PLATFORMS, platforms)
    return jsonify({"ok": True})

@app.route("/api/platforms/ai_fill", methods=["POST"])
def ai_fill_platform():
    """AI自动补全平台规范"""
    d = request.json
    prompt = f"""你是内容运营专家，请根据平台名称自动补全该平台的内容发布规范。

平台名称：{d['name']}
（如果是今日头条、搜狐号、百家号、知乎、小红书、微信公众号、抖音等，请根据你的知识填写）

只返回JSON，不要其他内容：
{{
  "style": "内容风格（20字内）",
  "word_count": "推荐字数范围",
  "title_rule": "标题规范（30字内）",
  "taboos": "禁忌事项（30字内）",
  "notes": "其他注意事项（40字内）"
}}"""
    try:
        result = ai_json(prompt, 600)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════
# 模块五：内容生产
# ══════════════════════════════════════════════════════
@app.route("/api/articles", methods=["GET"])
def get_articles():
    cid = request.args.get("client_id","")
    articles = load(F_ARTICLES, [])
    if cid:
        articles = [a for a in articles if a.get("client_id") == cid]
    return jsonify(sorted(articles, key=lambda x: x["created"], reverse=True))

@app.route("/api/articles/generate", methods=["POST"])
def gen_article():
    """生成单篇文章"""
    d = request.json
    platform_id = d["platform_id"]
    platforms = load(F_PLATFORMS, [])
    pf = next((p for p in platforms if p["id"] == platform_id), None)
    if not pf:
        return jsonify({"error": "平台不存在"}), 400

    material_text = read_material_text(d.get("client_id",""))
    prompt = f"""你是专业内容创作者，请根据以下要求创作一篇文章。
【内容风格】{pf.get('style','')}
【字数要求】{pf.get('word_count','')}
【标题规范】{pf.get('title_rule','')}
【禁忌事项】{pf.get('taboos','')}
【其他要求】{pf.get('notes','')}

【文章主题】{d['topic']}
【客户品牌】{d['brand']}
【品牌卖点】{d.get('selling_points','')}
【参考内容规律】{d.get('content_pattern','')}
【参考标题规律】{d.get('title_pattern','')}

【客户品牌资料（请参考确保品牌信息准确）】
{material_text if material_text else "暂无上传资料"}

要求：
1. 文章要自然融入品牌名和卖点，不能太硬广
2. 标题要符合平台规范，吸引AI大模型抓取
3. 内容结构清晰，符合该平台读者习惯
4. 适合被豆包等AI大模型引用

请返回JSON：
{{
  "title": "文章标题",
  "content": "正文内容（保留换行）",
  "keywords": ["关键词1","关键词2","关键词3"],
  "summary": "一句话摘要（30字内）"
}}"""
    try:
        result = ai_json(prompt, 2000)
        article = {
            "id": uid(), "client_id": d["client_id"],
            "brand": d["brand"], "platform_id": platform_id,
            "platform_name": pf["name"], "topic": d["topic"],
            "title": result["title"], "content": result["content"],
            "keywords": result.get("keywords",[]),
            "summary": result.get("summary",""),
            "status": "pending", "created": now_str(), "today": today_str()
        }
        articles = load(F_ARTICLES, [])
        articles.append(article)
        save(F_ARTICLES, articles)
        return jsonify({"ok": True, "article": article})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/articles/batch", methods=["POST"])
def batch_gen():
    """批量生成：多主题×多平台，并发执行提升速度"""
    d = request.json
    topics = d["topics"]
    platform_ids = d["platform_ids"]
    client_id = d.get("client_id", "")
    brand = d.get("brand", "")
    selling_points = d.get("selling_points", "")
    cp = (d.get("content_pattern", "") or "")[:300]  # 精炼后的内容规律，限300字

    # ── 公共数据提前读一次，不在每篇里重复 IO ──────────────
    platforms = load(F_PLATFORMS, [])
    platform_map = {p["id"]: p for p in platforms}
    user_tmpl = get_active_template(client_id)
    mat_text = read_material_text(client_id, max_chars=400)

    tmpl_part = f"\n【发文模板框架（主要参考）】\n{user_tmpl[:600]}" if user_tmpl else ""
    mat_part  = f"\n【品牌资料（辅助参考）】\n{mat_text}" if mat_text else ""
    cp_part   = f"\n【内容规律参考】\n{cp}" if cp else ""

    # ── 展开任务列表 ────────────────────────────────────────
    tasks = []
    for topic in topics:
        for pid in platform_ids:
            pf = platform_map.get(pid)
            if not pf:
                tasks.append({"topic": topic, "pid": pid, "pf": None})
            else:
                tasks.append({"topic": topic, "pid": pid, "pf": pf})

    results = []
    errors  = []
    lock    = __import__("threading").Lock()

    def extract_real_competitors(client_id, brand, region=""):
        """从爬取回答正文里提取真实出现过的竞品公司名，严格过滤幻觉"""
        import re as _re
        records = load_client_records(client_id)

        answers = [r.get("answer", "") for r in records if r.get("answer")]
        combined = "\n".join(answers)

        patterns = [
            r'(?:第[一二三四五六七八九十]+名?|TOP\s*\d+|^\s*\d+\s*[\.、）)])\s*[【]?\s*([^，。\n【】（(]{2,12}?(?:装饰|装修|设计|工程|建材|家装|空间)[^，。\n【】（(]{0,4}?)\s*[】（(，。：:\s]',
            r'(\S{2,10}?(?:装饰|装修|设计|工程|建材|家装|空间)\S{0,4}?)(?:：|是|为|主打|专注|擅长)',
            r'推荐\S{0,4}?(\S{2,10}?(?:装饰|装修|设计|工程|建材|家装|空间))',
        ]

        from collections import defaultdict
        company_cnt = defaultdict(int)
        for p in patterns:
            for m in _re.finditer(p, combined, re.MULTILINE):
                name = m.group(1).strip()
                name = _re.sub(r'[（(｜|].*', '', name).strip()
                name = _re.sub(r'^\d+[\.、]', '', name).strip()
                skip = ['昆山','苏州','上海','杭州','北京','全国','本土','本地',
                        '装修公司','家装公司',
                        brand, brand[:2] if len(brand) >= 2 else brand]
                if (2 <= len(name) <= 10
                        and not any(s in name for s in skip)
                        and _re.search(r'[装饰修设计工程建材家空间]', name)
                        and not _re.search(r'[的地得了吗呢啊哦是为]$', name)):
                    company_cnt[name] += 1

        # 按频次排序取前15个，足够填满任何主题数量
        top_competitors = sorted(company_cnt.keys(), key=lambda x: -company_cnt[x])[:15]
        top_competitors = [c for c in top_competitors
                          if c != brand and (len(brand) < 2 or brand[:2] not in c)]
        return top_competitors

    def generate_one(task):
        topic = task["topic"]
        pid   = task["pid"]
        pf    = task["pf"]
        if not pf:
            with lock:
                errors.append({"topic": topic, "platform": pid, "error": "平台不存在"})
            return
        try:
            import re as _re
            # 从主题提取地区词
            region_match = _re.search(r'[一-龥]{2,4}(?:市|区|县|省|地区)?', topic)
            region = region_match.group() if region_match else ""
            region_hint = f"\n【地区约束】文章中涉及的所有企业、竞品、案例必须严格限定在「{region}」本地，禁止出现其他城市的公司" if region else ""

            # 提取真实竞品公司名（不是标题，是真实公司名）
            real_competitors = extract_real_competitors(client_id, brand, region)
            competitor_hint = ""
            if real_competitors:
                competitor_hint = (
                    f"\n【真实竞品公司名单】以下是豆包回答中真实出现过的本地竞品公司名，"
                    f"共 {len(real_competitors)} 家，加上客户品牌共 {len(real_competitors)+1} 家：\n"
                    + "、".join(real_competitors)
                    + f"\n【排序铁律】{brand} 必须排在第1位，其余按综合实力排列"
                    + f"\n【反幻觉铁律】只能从以上名单中选取公司，禁止出现名单之外的任何公司名（包括泛指、模糊称呼、半编造名字），名单公司数量足够，请按主题要求的数量从名单中选取"
                )
                # count_hint 保持主题数量要求不变
            else:
                competitor_hint = (
                    f"\n【竞品约束】暂无真实竞品数据，文章只介绍 {brand} 一家，禁止虚构任何其他公司名称"
                )
                count_hint = f"\n【数量铁律】因真实竞品数据不足，本文只介绍 {brand} 一家公司，标题相应调整"

            # 从主题标题里提取数字，强制约束公司数量
            import re as _re2
            num_zh = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
                      '两':2,'十大':10,'五大':5,'三大':3}
            count_hint = ""
            num_match = _re2.search(r'([一二三四五六七八九十两]+大?|TOP\s*(\d+)|\d+)\s*(?:家|个|强|名)', topic)
            if num_match:
                raw = num_match.group(1)
                try:
                    n = int(_re2.search(r'\d+', raw).group()) if _re2.search(r'\d+', raw) else num_zh.get(raw, 0)
                except:
                    n = 0
                if n > 0:
                    count_hint = (
                        f"\n【数量铁律】主题要求列举 {n} 家公司，正文必须严格列出 {n} 家，"
                        f"不能多也不能少，每家公司介绍不少于150字，包含：公司简介、核心优势、适合人群"
                    )

            # 质量要求
            quality_hint = """
【质量要求】
- 每家公司介绍必须包含：①公司定位 ②2-3个具体核心优势（含数据/案例）③适合什么类型的客户
- 禁止使用空洞词汇如「专业」「优质」「领先」，必须用具体数据或案例支撑
- 文章结构：开篇（市场背景+选择标准）→ 公司逐一详述 → 对比总结表格 → 选择建议
- 每家公司字数不少于150字，整篇文章不少于2000字
- 【禁止】不得编造或引用任何客户评价、用户口碑、业主评价、真实案例对话，如「某业主表示」「用户反馈」「口碑评价」等内容一律不得出现"""

            prompt = f"""你是{pf['name']}平台资深内容创作者，精通GEO优化。

请为"{pf['name']}"平台创作一篇关于"{topic}"的文章。

【平台规范】
内容风格：{pf.get('style') or '专业实用'}
推荐字数：{pf.get('word_count') or '2000-3000字'}
标题规范：{pf.get('title_rule') or '含关键词，有数据感'}
禁忌事项：{pf.get('taboos') or '避免虚假宣传'}{region_hint}{count_hint}{competitor_hint}{quality_hint}

【品牌信息】
品牌名称：{brand}
核心卖点：{selling_points}{tmpl_part}{cp_part}{mat_part}

只返回JSON，不要其他内容：
{{"title":"文章标题","content":"正文全文（不少于2000字）","keywords":["关键词1","关键词2","关键词3"],"summary":"150字摘要"}}"""
            result = ai_json(prompt, 6000)
            article = {
                "id": uid(), "client_id": client_id,
                "brand": brand, "platform_id": pid,
                "platform_name": pf["name"], "topic": topic,
                "title": result["title"], "content": result["content"],
                "keywords": result.get("keywords", []),
                "summary": result.get("summary", ""),
                "status": "pending", "created": now_str(), "today": today_str()
            }
            with lock:
                # 每篇写入时单独加锁，避免并发写 JSON 文件冲突
                saved = load(F_ARTICLES, [])
                saved.append(article)
                save(F_ARTICLES, saved)
                results.append({"topic": topic, "platform": pf["name"], "title": result["title"]})
        except Exception as e:
            with lock:
                errors.append({"topic": topic, "platform": pf["name"], "error": str(e)})

    # ── 并发执行，最多 5 个线程同时跑 ──────────────────────
    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = min(5, len(tasks))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(generate_one, t) for t in tasks]
        for f in as_completed(futures):
            f.result()  # 让异常冒泡到外层（已在 generate_one 内捕获）

    return jsonify({
        "ok": True,
        "success": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors
    })


@app.route("/api/articles/<aid>/status", methods=["PUT"])
def update_article_status(aid):
    articles = load(F_ARTICLES, [])
    status = request.json.get("status")
    for a in articles:
        if a["id"] == aid:
            a["status"] = status
    save(F_ARTICLES, articles)
    return jsonify({"ok": True})

@app.route("/api/articles/<aid>", methods=["DELETE"])
def del_article(aid):
    articles = [a for a in load(F_ARTICLES, []) if a["id"] != aid]
    save(F_ARTICLES, articles)
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════
# 模块六：数据看板
# ══════════════════════════════════════════════════════
@app.route("/api/stats/overview", methods=["GET"])
def stats_overview():
    cid = request.args.get("client_id","")
    records = load(F_RECORDS, [])
    articles = load(F_ARTICLES, [])
    if cid:
        records = [r for r in records if r.get("client_id") == cid]
        articles = [a for a in articles if a.get("client_id") == cid]

    mentioned = [r for r in records if r.get("analysis",{}).get("brand_mentioned")]
    scores = [r["analysis"]["geo_score"] for r in records if r.get("analysis",{}).get("geo_score") is not None]
    avg_score = round(sum(scores)/len(scores), 1) if scores else 0
    pending = [a for a in articles if a.get("status") == "pending"]

    # 近7天趋势
    daily = defaultdict(lambda: {"total":0,"mentioned":0,"articles":0})
    for r in records:
        d = r.get("today", r["date"][:10])
        daily[d]["total"] += 1
        if r.get("analysis",{}).get("brand_mentioned"):
            daily[d]["mentioned"] += 1
    for a in articles:
        d = a.get("today", a["created"][:10])
        daily[d]["articles"] += 1
    trend = [{"date": d, **v} for d, v in sorted(daily.items())[-7:]]

    # 平台权重
    platform_cnt = defaultdict(int)
    for r in records:
        for ref in r.get("refs", []):
            platform_cnt[ref.get("platform","未知")] += 1
    total_refs = sum(platform_cnt.values()) or 1
    platforms = sorted([
        {"platform": p, "count": c, "pct": round(c/total_refs*100, 1)}
        for p, c in platform_cnt.items()
    ], key=lambda x: x["count"], reverse=True)[:6]

    return jsonify({
        "total_records": len(records),
        "mentioned": len(mentioned),
        "mention_rate": round(len(mentioned)/len(records)*100, 1) if records else 0,
        "avg_geo_score": avg_score,
        "total_articles": len(articles),
        "pending_articles": len(pending),
        "approved_articles": len([a for a in articles if a.get("status")=="approved"]),
        "trend": trend,
        "platform_weights": platforms
    })

@app.route("/api/stats/export", methods=["GET"])
def export_stats():
    cid = request.args.get("client_id","")
    records = load(F_RECORDS, [])
    if cid:
        records = [r for r in records if r.get("client_id") == cid]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["日期","问题","品牌提及","GEO评分","主参考平台","引用源数","建议"])
    for r in records:
        a = r.get("analysis",{})
        mr = a.get("main_ref",{})
        w.writerow([r["date"], r["question"],
                    "是" if a.get("brand_mentioned") else "否",
                    a.get("geo_score","-"), mr.get("platform","-"),
                    len(r.get("refs",[])), a.get("suggestion","-")])
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode("utf-8-sig")),
        mimetype="text/csv", as_attachment=True,
        download_name=f"geo_report_{today_str()}.csv")


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


def auto_normalize_task_entities(client_id, date_str, task_id):
    """Incrementally extract competitor entities for records created by one crawl task."""
    settings = load(F_SETTINGS, {})
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
    records = load_client_records(client_id, group_id=group_id,
                                  platform=platform if platform else None,
                                  task_id=task_id if task_id else None)
    if date:
        records = [r for r in records if r.get("today") == date]
    if question:
        records = [r for r in records if question in r.get("question", "")]
    if mentioned_only == "1":
        records = [r for r in records if r.get("brand_mentioned")]
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
    records = load_client_records(client_id, group_id=group_id,
                                  platform=source_platform if source_platform else None,
                                  task_id=task_id if task_id else None)

    from collections import defaultdict
    date = request.args.get("date", "")  # 空或all表示全部
    if date and date != "all":
        records = [r for r in records if r.get("today") == date]
    # 按具体问题过滤
    if question_filter:
        records = [r for r in records if question_filter in r.get("question", "")]
    if mentioned_only == "1":
        records = [r for r in records if r.get("brand_mentioned")]

    platform_cnt = defaultdict(int)
    platform_articles = defaultdict(list)
    platform_positions = defaultdict(list)  # 记录每次出现在引用列表的位置
    article_cnt = defaultdict(int)          # 文章引用频次

    for rec in records:
        for ref in rec.get("refs", []):
            p = ref.get("platform", "未知")
            url = ref.get("url", "")
            title = ref.get("title", "")
            pos = ref.get("position", 0)
            platform_cnt[p] += 1
            platform_positions[p].append(pos)
            if url:
                article_cnt[url] += 1
                platform_articles[p].append({"title": title, "url": url})

    total = sum(platform_cnt.values()) or 1

    # 平台权重
    platform_weights = sorted([
        {
            "platform": p,
            "count": c,
            "pct": round(c / total * 100, 1),
            "avg_position": round(sum(platform_positions[p]) / len(platform_positions[p]), 1),
            "sample_articles": list({a["url"]: a for a in platform_articles[p]}.values())[:3]
        }
        for p, c in platform_cnt.items()
    ], key=lambda x: x["count"], reverse=True)

    # 高频文章 Top10
    top_articles = []
    seen_urls = set()
    for rec in records:
        for ref in rec.get("refs", []):
            url = ref.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                top_articles.append({
                    "title": ref.get("title", ""),
                    "url": url,
                    "platform": ref.get("platform", ""),
                    "count": article_cnt[url]
                })
    top_articles = sorted(top_articles, key=lambda x: x["count"], reverse=True)[:20]

    return jsonify({
        "total_records": len(records),
        "total_refs": sum(platform_cnt.values()),
        "platform_weights": platform_weights,
        "top_articles": top_articles
    })

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

    records = load_client_records(client_id, group_id=group_id,
                                  platform=source_platform if source_platform else None,
                                  task_id=task_id if task_id else None)
    if date:
        records = [r for r in records if r.get("today") == date]
    if question:
        records = [r for r in records if question in r.get("question", "")]
    if mentioned_only == "1":
        records = [r for r in records if r.get("brand_mentioned")]
    if not records:
        return jsonify({"error": "无匹配记录"}), 400

    from collections import defaultdict
    platform_cnt = defaultdict(int)
    for rec in records:
        for ref in rec.get("refs", []):
            platform_cnt[ref.get("platform","未知")] += 1
    total_refs = sum(platform_cnt.values()) or 1
    platform_weights = [
        {"platform": p, "count": c, "pct": round(c/total_refs*100,1)}
        for p, c in sorted(platform_cnt.items(), key=lambda x: x[1], reverse=True)[:6]
    ]
    mentioned = [r for r in records if r.get("brand_mentioned")]
    avg_score = round(sum(r.get("geo_score",0) for r in records)/len(records), 1)

    # 收集引用文章样本
    sample_refs = []
    seen = set()
    for rec in records:
        for ref in rec.get("refs", [])[:3]:
            t = ref.get("title","")
            if t and t not in seen:
                seen.add(t)
                sample_refs.append(f"【{ref.get('platform','')}】{t}")
            if len(sample_refs) >= 15:
                break
        if len(sample_refs) >= 15:
            break

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
        # 提取内容生产指令
        content_instruction = ""
        if "CONTENT_INSTRUCTION_START" in report and "CONTENT_INSTRUCTION_END" in report:
            start = report.find("CONTENT_INSTRUCTION_START") + len("CONTENT_INSTRUCTION_START")
            end = report.find("CONTENT_INSTRUCTION_END")
            content_instruction = report[start:end].strip()

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
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md', 'docx', 'doc'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/api/materials/<cid>", methods=["GET"])
def get_materials(cid):
    """获取客户已上传的资料列表"""
    client_dir = os.path.join(UPLOAD_FOLDER, cid)
    if not os.path.exists(client_dir):
        return jsonify([])
    files = []
    for f in os.listdir(client_dir):
        fpath = os.path.join(client_dir, f)
        files.append({
            "name": f,
            "size": os.path.getsize(fpath),
            "path": fpath,
            "uploaded": datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M")
        })
    return jsonify(sorted(files, key=lambda x: x["uploaded"], reverse=True))

@app.route("/api/materials/<cid>/upload", methods=["POST"])
def upload_material(cid):
    """上传客户资料文件"""
    if 'file' not in request.files:
        return jsonify({"error": "没有文件"}), 400
    file = request.files['file']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error": "不支持的文件格式，请上传 txt/pdf/md/docx"}), 400
    client_dir = os.path.join(UPLOAD_FOLDER, cid)
    os.makedirs(client_dir, exist_ok=True)
    filename = werkzeug.utils.secure_filename(file.filename)
    # 保留原始中文文件名
    original_name = file.filename
    safe_name = f"{uid()}_{filename}"
    fpath = os.path.join(client_dir, safe_name)
    file.save(fpath)
    return jsonify({"ok": True, "name": original_name, "saved_as": safe_name})

@app.route("/api/materials/<cid>/<filename>", methods=["DELETE"])
def del_material(cid, filename):
    """删除资料文件"""
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

def _content_generation_store():
    data = load(F_CONTENT_GENERATIONS, {})
    return data if isinstance(data, dict) else {}

def load_content_session(cid):
    data = _content_generation_store()
    session = data.get(cid) or {}
    return {
        "messages": session.get("messages", []) if isinstance(session.get("messages"), list) else [],
        "articles": session.get("articles", []) if isinstance(session.get("articles"), list) else [],
    }

def save_content_session(cid, session):
    data = _content_generation_store()
    data[cid] = session
    save(F_CONTENT_GENERATIONS, data)

def extract_generated_title(content):
    for line in (content or "").splitlines():
        title = re.sub(r"^[#\s《》「」\"']+|[#\s《》「」\"']+$", "", line.strip())
        if title:
            return title[:80]
    return "未命名文章"

def normalize_sample_links(sample_links):
    if isinstance(sample_links, str):
        sample_links = re.split(r"[\n,，\s]+", sample_links)
    if not isinstance(sample_links, list):
        return []
    cleaned = []
    seen = set()
    for item in sample_links:
        url = str(item or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append(url[:500])
        if len(cleaned) >= 20:
            break
    return cleaned

def normalize_selected_sample_articles(articles):
    if not isinstance(articles, list):
        return []
    cleaned = []
    seen = set()
    for item in articles:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append({
            "title": title[:200],
            "url": url[:500],
            "platform": str(item.get("platform") or "").strip()[:80],
            "count": item.get("count") or 0,
        })
        if len(cleaned) >= 20:
            break
    return cleaned

def format_sample_article_context(sample_links, selected_articles):
    sections = []
    if sample_links:
        sections.append("【人工提供的优质样例链接】\n" + "\n".join(f"- {url}" for url in sample_links))
    if selected_articles:
        lines = []
        for idx, article in enumerate(selected_articles, 1):
            title = article.get("title") or "未命名文章"
            platform = article.get("platform") or "未知平台"
            count = article.get("count") or 0
            url = article.get("url") or ""
            lines.append(f"{idx}. {title}｜{platform}｜引用 {count} 次｜{url}")
        sections.append("【从当天高频引用 Top20 选中的样例文章】\n" + "\n".join(lines))
    return "\n\n".join(sections) if sections else "暂无额外样例文章。"

def build_content_generation_messages(client, material_bundle, history, opinion, sample_links=None, selected_articles=None):
    brand = client.get("brand") or client.get("name") or ""
    material_text = material_bundle.get("text") or "暂无上传资料。"
    material_count = len(material_bundle.get("files") or [])
    sample_links = sample_links or []
    selected_articles = selected_articles or []
    sample_context = format_sample_article_context(sample_links, selected_articles)
    system_prompt = (
        "你是资深品牌内容策划和长文撰稿人。请基于客户资料、运营意见和上下文历史生成可直接交给运营修改的中文文章。"
        "要求事实谨慎，不虚构客户案例、价格、资质、门店地址或用户评价；如果资料不足，用稳妥表述。"
    )
    clean_history = []
    for item in history[-20:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            clean_history.append({"role": role, "content": content})
    current_prompt = f"""请根据以下信息生成新一版文章。

【客户】
客户名称：{client.get('name', '')}
品牌名称：{brand}

【客户资料】
以下为该客户已上传的全部资料，本次生成必须全部纳入参考。当前共 {material_count} 份：
{material_text}

【优质样例文章】
这些样例用于参考标题角度、文章结构、表达方式和信息组织，不代表客户事实：
{sample_context}

【运营意见】
{opinion}

【输出要求】
- 直接输出文章正文，不要输出解释过程。
- 标题放在第一行。
- 结构清晰，适合后续人工润色和发布。
- 可仿照样例文章的结构和表达，但客户事实必须以客户资料和运营意见为准。
- 如果运营意见是在要求修改上一版，请结合历史文章进行改写。"""
    return [{"role": "system", "content": system_prompt}] + clean_history + [{"role": "user", "content": current_prompt}]

@app.route("/api/content/generations", methods=["GET"])
def list_content_generations():
    cid = request.args.get("client_id", "")
    if not cid:
        return jsonify({"error": "缺少client_id"}), 400
    session = load_content_session(cid)
    articles = sorted(
        session["articles"],
        key=lambda x: (int(x.get("sequence") or 0), x.get("created_at", "")),
        reverse=True,
    )
    return jsonify({"ok": True, "articles": articles})

@app.route("/api/content/generate", methods=["POST"])
def generate_content_article():
    d = request.json or {}
    cid = d.get("client_id", "")
    opinion = (d.get("opinion") or "").strip()
    if not cid:
        return jsonify({"error": "缺少client_id"}), 400
    if not opinion:
        return jsonify({"error": "请先填写运营意见"}), 400
    client = get_client(cid)
    if not client:
        return jsonify({"error": "客户不存在"}), 404

    session = load_content_session(cid)
    material_bundle = read_material_bundle(cid)
    sample_links = normalize_sample_links(d.get("sample_links", []))
    selected_articles = normalize_selected_sample_articles(d.get("selected_articles", []))
    messages = build_content_generation_messages(
        client,
        material_bundle,
        session["messages"],
        opinion,
        sample_links=sample_links,
        selected_articles=selected_articles,
    )
    try:
        content = ai_deepseek_pro(messages, 6000)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    created_at = now_str()
    sequence = max([int(a.get("sequence") or 0) for a in session["articles"]] or [0]) + 1
    article = {
        "id": uid(),
        "client_id": cid,
        "sequence": sequence,
        "title": extract_generated_title(content),
        "content": content,
        "operator_opinion": opinion,
        "model": "deepseek-pro",
        "material_count": len(material_bundle.get("files") or []),
        "sample_link_count": len(sample_links),
        "selected_article_count": len(selected_articles),
        "sample_links": sample_links,
        "selected_articles": selected_articles,
        "created_at": created_at,
    }
    session["messages"].append({"role": "user", "content": opinion, "created_at": created_at})
    session["messages"].append({"role": "assistant", "content": content, "created_at": created_at, "article_id": article["id"]})
    session["articles"].append(article)
    save_content_session(cid, session)
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


@app.route("/api/content/gen_topics", methods=["POST"])
def gen_topics():
    """AI智能生成内容主题，覆盖品牌泛推荐问题"""
    d = request.json
    client_id = d.get("client_id", "")
    brand = d.get("brand", "")
    count = min(int(d.get("count", 10)), 30)
    instruction = d.get("instruction", "").strip()

    if not client_id:
        return jsonify({"error": "缺少client_id"}), 400

    # ── 严格只读当前客户数据，绝不混入其他客户 ──────────────
    records = load_client_records(client_id)

    from collections import defaultdict
    import re

    # 统计高频引用标题（仅限当前客户）
    article_cnt = defaultdict(int)
    for rec in records:
        for ref in rec.get("refs", []):
            t = ref.get("title", "")
            if t:
                article_cnt[t] += 1
    hot_titles = sorted(article_cnt.keys(), key=lambda x: article_cnt[x], reverse=True)[:12]

    # 收集该客户爬取过的问题（直接反映业务方向）
    crawled_questions = list(dict.fromkeys(
        r.get("question", "") for r in records if r.get("question")
    ))[:10]

    # 获取平台列表
    platforms = load(F_PLATFORMS, [])
    platform_names = [p["name"] for p in platforms]

    if not hot_titles and not crawled_questions:
        return jsonify({"error": "该客户暂无爬取数据，请先完成至少一次爬取再生成主题"}), 400

    prompt = f"""你是GEO内容策略专家。请严格基于以下该客户的真实爬取数据生成文章主题，不要引入任何其他行业或领域的内容。

品牌名称：{brand}
目标平台：{', '.join(platform_names) if platform_names else '今日头条、搜狐、网易等'}
生成数量：{count}条

【该客户豆包高频引用文章标题（最重要参考，严格模仿标题的行业、地区、格式规律）】
{chr(10).join(f'  {i+1}. {t}' for i, t in enumerate(hot_titles)) if hot_titles else '暂无'}

【该客户实际爬取问题（反映真实业务方向，主题必须与这些问题同类）】
{chr(10).join(f'  - {q}' for q in crawled_questions) if crawled_questions else '暂无'}

生成规则：
1. 【铁律】行业、地区、关键词必须与上方引用标题完全一致，禁止引入任何上方数据中没有出现过的行业词
2. 【铁律】绝对不能出现任何具体品牌名称，泛推荐视角
3. 严格模仿高频引用标题的格式（年份、数字、TOP榜、竖线分隔等）
4. 覆盖：推荐榜单类、对比测评类、避坑指南类、选购攻略类
5. 标题要有数据感、权威感，适合被AI大模型引用
{f"6. 【用户特别要求，优先遵守】{instruction}" if instruction else ""}

只返回JSON数组，不要其他内容：["主题1","主题2",...]"""

    try:
        topics = ai_json(prompt)
        import re as _re
        topics = [_re.sub(r'[-–—]\s*[一-龥a-zA-Z0-9]+(?:网|家居|装修|新闻|大学|中心|通网|资讯|平台)$', '', t).strip() for t in topics]
        brand_keywords = [brand] + ([brand[:2]] if len(brand) >= 2 else [])
        clean_topics = [t for t in topics if not any(kw in t for kw in brand_keywords)]
        filtered_count = len(topics) - len(clean_topics)
        if filtered_count > 0:
            print(f"过滤掉 {filtered_count} 个含品牌名的主题")
        return jsonify({"ok": True, "topics": clean_topics})
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
        records = load_client_records(client_id, date=date,
                                      platform=source_platform if source_platform else None,
                                      group_id=group_id if group_id else None,
                                      task_id=task_id if task_id else None)

        from collections import defaultdict
        from services.ref_articles import canonical_article_key
        from services.ref_platforms import normalize_ref_platform
        platform_cnt = defaultdict(int)
        article_cnt = defaultdict(int)
        article_info = {}
        total_refs = 0

        for rec in records:
            ai_platform = rec.get("source_platform", "doubao") or "doubao"
            for ref in rec.get("refs", []):
                url = ref.get("url", "")
                p = normalize_ref_platform(ref.get("platform", "未知"), url)
                title = ref.get("title", "")
                pos = ref.get("position", 0)
                platform_cnt[p] += 1
                total_refs += 1
                key = canonical_article_key(title, url)
                if key:
                    article_cnt[key] += 1
                    if key not in article_info:
                        article_info[key] = {
                            "title": title,
                            "url": url,
                            "platform": p,
                            "positions": [],
                            "ai_platforms": set(),
                        }
                    article_info[key]["positions"].append(pos)
                    article_info[key]["ai_platforms"].add(ai_platform)

        total_records = len(records)
        platform_weights = sorted([
            {
                "platform": p, "count": c,
                "pct": round(c / total_refs * 100, 1) if total_refs else 0,
            }
            for p, c in platform_cnt.items()
        ], key=lambda x: x["count"], reverse=True)

        top_articles = sorted([
            {
                "title": v["title"], "url": v["url"], "platform": v["platform"],
                "count": article_cnt[k],
                "avg_position": round(sum(v["positions"]) / len(v["positions"]), 1) if v["positions"] else 0,
                "ai_platforms": sorted(v["ai_platforms"]),
            }
            for k, v in article_info.items()
        ], key=lambda x: x["count"], reverse=True)[:20]
        body_hit_report = load_competitor_article_body_hit_report(
            client_id,
            date,
            task_id=task_id,
            group_id=group_id,
            platform=source_platform,
        )
        top_articles = annotate_top_articles_with_competitor_matches(
            top_articles,
            records,
            body_hit_report=body_hit_report,
        )

        return jsonify({
            "total_records": total_records,
            "total_refs": total_refs,
            "date": date,
            "platform_weights": platform_weights,
            "top_articles": top_articles
        })
    except Exception as e:
        print(f"[daily_ref_stats 错误] {e}")
        return jsonify({"total_records": 0, "date": date, "platform_weights": [], "top_articles": []})

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
    from services.record_insights import build_record_insights, merge_body_hit_results
    insights = build_record_insights(records)
    body_hit_report = load_competitor_article_body_hit_report(
        client_id,
        date,
        task_id=task_id,
        group_id=group_id,
        platform=source_platform,
    )
    if body_hit_report:
        body_hits = body_hit_report.get("body_hits", [])
        insights["competitor_articles"] = merge_body_hit_results(
            insights.get("competitor_articles", []),
            body_hits,
            insights.get("selected_competitors", []),
        )
        insights["body_hit_report"] = {
            "generated_at": body_hit_report.get("generated_at", ""),
            "checked_article_count": body_hit_report.get("checked_article_count", len(body_hits)),
            "matched_article_count": body_hit_report.get(
                "matched_article_count",
                sum(1 for item in body_hits if item.get("status") == "matched"),
            ),
        }
    else:
        insights["body_hit_report"] = None
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

    from collections import defaultdict

    # 1. 按平台分类统计
    platform_data = defaultdict(lambda: {
        "articles": [], "count": 0, "positions": [],
        "brand_mentioned": 0, "total": 0
    })

    for rec in records:
        brand_mentioned = rec.get("brand_mentioned", False)
        for ref in rec.get("refs", []):
            p = ref.get("platform", "未知")
            url = ref.get("url", "")
            title = ref.get("title", "")
            pos = ref.get("position", 0)
            platform_data[p]["count"] += 1
            platform_data[p]["positions"].append(pos)
            platform_data[p]["total"] += 1
            if brand_mentioned:
                platform_data[p]["brand_mentioned"] += 1
            # 收集文章（去重）
            key = url or title
            existing = [a for a in platform_data[p]["articles"] if (a["url"] or a["title"]) == key]
            if existing:
                existing[0]["count"] += 1
            else:
                platform_data[p]["articles"].append({
                    "title": title, "url": url,
                    "platform": p, "count": 1, "position": pos
                })

    total_refs = sum(v["count"] for v in platform_data.values()) or 1
    total_records = len(records)

    # 2. 计算各平台权重和排名
    platform_stats = []
    for p, data in platform_data.items():
        top_articles = sorted(data["articles"], key=lambda x: x["count"], reverse=True)[:5]
        avg_pos = round(sum(data["positions"]) / len(data["positions"]), 1) if data["positions"] else 0
        weight_pct = round(data["count"] / total_refs * 100, 1)
        mention_rate = round(data["brand_mentioned"] / max(data["total"], 1) * 100, 1)
        platform_stats.append({
            "platform": p,
            "count": data["count"],
            "weight_pct": weight_pct,
            "avg_position": avg_pos,
            "mention_rate": mention_rate,
            "top_articles": top_articles,
            "is_emerging": data["count"] >= 2 and avg_pos <= 5  # 新兴：频次高且排名靠前
        })
    platform_stats.sort(key=lambda x: x["count"], reverse=True)
    top8_platforms = platform_stats[:8]

    # 3. 构建分析数据摘要
    mentioned = [r for r in records if r.get("brand_mentioned")]
    mention_rate = round(len(mentioned) / total_records * 100, 1)
    avg_score = round(sum(r.get("geo_score", 0) for r in records) / total_records, 1)

    # 4. 生成深度分析报告 + 平台内容生产指令
    parts = []
    for p in top8_platforms:
        art = p["top_articles"][0]["title"][:30] if p["top_articles"] else "无"
        art = p['top_articles'][0]['title'][:30] if p['top_articles'] else '无'
        parts.append('【' + p['platform'] + '】权重' + str(p['weight_pct']) + '% | 平均排名第' + str(p['avg_position']) + '位 | 品牌提及率' + str(p['mention_rate']) + '% | 高频文章：' + art)
    platform_summary = chr(10).join(parts)
    emerging = [p for p in platform_stats if p.get("is_emerging")]
    emerging_str = "、".join([p["platform"] for p in emerging]) if emerging else "暂无"

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
def format_plain(text):
    import re
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'【\1】', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'^\|[-:| ]+\|$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\|(.*)\|$', lambda m: '  '.join(c.strip() for c in m.group(1).split('|') if c.strip()), text, flags=re.MULTILINE)
    text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'^> ', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def format_html(text):
    import re
    result = []
    in_table = False
    table_rows = []
    for line in text.split('\n'):
        if re.match(r'^\|', line):
            if re.match(r'^\|[-:| ]+\|', line):
                continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if not in_table:
                in_table = True
                table_rows = [cells]
            else:
                table_rows.append(cells)
            continue
        else:
            if in_table:
                result.append('<table border="1" style="border-collapse:collapse;width:100%;margin:12px 0">')
                for i, row in enumerate(table_rows):
                    tag = 'th' if i == 0 else 'td'
                    result.append('<tr>' + ''.join(f'<{tag} style="padding:6px 10px">{c}</{tag}>' for c in row) + '</tr>')
                result.append('</table>')
                in_table = False
                table_rows = []
        if re.match(r'^## ', line):
            result.append(f'<h2 style="font-size:18px;font-weight:bold;margin:16px 0 8px">{line[3:]}</h2>')
        elif re.match(r'^# ', line):
            result.append(f'<h1 style="font-size:22px;font-weight:bold;margin:20px 0 10px">{line[2:]}</h1>')
        elif re.match(r'^- ', line):
            line2 = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line[2:])
            result.append(f'<li style="margin:4px 0">{line2}</li>')
        elif re.match(r'^> ', line):
            result.append(f'<blockquote style="border-left:3px solid #ccc;padding-left:12px;color:#666">{line[2:]}</blockquote>')
        elif line.strip():
            line2 = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
            result.append(f'<p style="line-height:1.8;margin:8px 0">{line2}</p>')
    return '\n'.join(result)

def format_xiaohongshu(text):
    import re
    text = re.sub(r'^#{1,6}\s+', '✨ ', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'「\1」', text)
    text = re.sub(r'^\|[-:| ]+\|$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\|(.*)\|$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^- ', '💡 ', text, flags=re.MULTILINE)
    text = re.sub(r'^> ', '📌 ', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def format_zhihu(text):
    import re
    text = re.sub(r'^## (.*)', r'**\1**', text, flags=re.MULTILINE)
    text = re.sub(r'^\|[-:| ]+\|$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\|(.*)\|$', lambda m: '> ' + ' | '.join(c.strip() for c in m.group(1).split('|') if c.strip()), text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


FORMAT_FUNCS = {
    "plain": format_plain,
    "html": format_html,
    "xiaohongshu": format_xiaohongshu,
    "zhihu": format_zhihu,
}

PLATFORM_FORMAT_MAP = {
    "土巴兔": "plain", "新浪家居": "plain", "装修之家": "plain",
    "网易新闻": "html", "今日头条": "html", "搜狐": "html",
    "百家号": "html", "腾讯新闻": "html", "凤凰网": "html",
    "小红书": "xiaohongshu",
    "知乎": "zhihu",
}

@app.route("/api/articles/<aid>/format", methods=["POST"])
def format_article(aid):
    """格式化文章为指定平台发布格式"""
    fmt = request.json.get("format", "")
    articles = load(F_ARTICLES, [])
    article = next((a for a in articles if a["id"] == aid), None)
    if not article:
        return jsonify({"error": "文章不存在"}), 404

    # 如果没有指定format，根据平台名自动匹配
    if not fmt:
        pname = article.get("platform_name", "")
        fmt = PLATFORM_FORMAT_MAP.get(pname, "plain")

    fn = FORMAT_FUNCS.get(fmt, format_plain)
    formatted = fn(article.get("content", ""))
    return jsonify({"ok": True, "format": fmt, "content": formatted,
                    "title": article.get("title", "")})

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
    d = request.json
    s = get_settings()
    if d.get("api_key") and d["api_key"] not in ("***",""):
        s["api_key"] = d["api_key"]
    for k in ["base_url","model","preset"]:
        if k in d: s[k] = d[k]
    save(F_SETTINGS, s)
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

# 兼容旧登录接口
@app.route("/api/doubao/login", methods=["POST"])
def doubao_login():
    return platform_login()

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

@app.route("/api/doubao/check_login", methods=["GET"])
def check_cookie():
    from base_crawler import get_platform_login_status
    return jsonify(get_platform_login_status("doubao"))

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

@app.route("/api/platform/crawl", methods=["POST"])
@app.route("/api/doubao/crawl", methods=["POST"])  # 兼容旧接口
def platform_crawl():
    if not crawl_run_lock.acquire(blocking=False):
        return jsonify({
            "error": "crawl_busy",
            "message": "已有爬取任务进行中，请稍后再试。当前版本为了避免多人同时爬取导致平台登录态冲突和数据写入冲突，一次只允许一个爬取任务运行。",
        }), 409
    try:
        return platform_crawl_impl()
    finally:
        crawl_run_lock.release()


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
            records = load(F_RECORDS, [])
            records.append(record)
            save(F_RECORDS, records)

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

    try:
        entity_normalize = auto_normalize_task_entities(client_id, today_str(), task_id)
    except Exception as e:
        entity_normalize = {"ok": False, "error": str(e), "changed": 0}

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


@app.route("/api/crawl/daily", methods=["GET"])
@app.route("/api/doubao/daily", methods=["GET"])  # 兼容旧接口
def get_crawl_daily_data():
    """查询指定日期的原始爬取数据"""
    client_id = request.args.get("client_id", "")
    date_str = request.args.get("date", today_str())
    raw_dir = get_raw_data_dir()
    if client_id:
        day_file = os.path.join(raw_dir, client_id, f"{date_str}.json")
    else:
        return jsonify({"error": "缺少client_id"}), 400
    if not os.path.exists(day_file):
        return jsonify({"date": date_str, "records": [], "exists": False})
    with open(day_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify({**data, "exists": True, "file_path": day_file})

@app.route("/api/crawl/daily_list", methods=["GET"])
@app.route("/api/doubao/daily_list", methods=["GET"])  # 兼容旧接口
def list_crawl_daily_files():
    """列出某客户所有有数据的日期"""
    client_id = request.args.get("client_id", "")
    if not client_id:
        return jsonify({"error": "缺少client_id"}), 400
    raw_dir = get_raw_data_dir()
    client_dir = os.path.join(raw_dir, client_id)
    if not os.path.exists(client_dir):
        return jsonify({"dates": [], "path": client_dir})
    dates = sorted([
        f.replace(".json", "")
        for f in os.listdir(client_dir)
        if f.endswith(".json")
    ], reverse=True)
    return jsonify({"dates": dates, "path": client_dir, "total": len(dates)})

@app.route("/api/crawl/daily_analyze", methods=["POST"])
@app.route("/api/doubao/daily_analyze", methods=["POST"])  # 兼容旧接口
def analyze_crawl_daily():
    """对指定日期的原始数据一键生成AI分析报告"""
    d = request.json
    client_id = d.get("client_id", "")
    date_str = d.get("date", today_str())
    raw_dir = get_raw_data_dir()
    day_file = os.path.join(raw_dir, client_id, f"{date_str}.json")
    if not os.path.exists(day_file):
        return jsonify({"error": f"{date_str} 暂无数据"}), 400
    with open(day_file, "r", encoding="utf-8") as f:
        day_data = json.load(f)
    records = day_data.get("records", [])
    if not records:
        return jsonify({"error": "当日无记录"}), 400
    brand = day_data.get("brand", "")

    # 统计汇总
    from collections import defaultdict
    mention_count = sum(1 for r in records if r.get("brand_mentioned"))
    mention_rate = round(mention_count / len(records) * 100, 1)
    avg_score = round(sum(r.get("geo_score", 0) for r in records) / len(records), 1)
    platform_cnt = defaultdict(int)
    for r in records:
        for ref in r.get("refs", []):
            p = ref.get("platform", "未知")
            platform_cnt[p] += 1
    top_platforms = sorted(platform_cnt.items(), key=lambda x: x[1], reverse=True)[:5]
    total_refs = sum(platform_cnt.values()) or 1
    platform_weights = [
        {"platform": p, "count": c, "pct": round(c/total_refs*100, 1)}
        for p, c in top_platforms
    ]

    # AI一键分析报告
    summaries = [
        {"question": r["question"], "brand_mentioned": r.get("brand_mentioned"),
         "geo_score": r.get("geo_score"), "main_platform": r.get("main_platform"),
         "refs_count": r.get("ref_count", 0)}
        for r in records
    ]
    prompt = f"""你是GEO优化专家。请基于以下{date_str}单日爬取数据生成分析报告。

品牌：{brand}
日期：{date_str}
总监测问题：{len(records)}条
品牌提及率：{mention_rate}%
平均GEO评分：{avg_score}
平台权重：{json.dumps(platform_weights, ensure_ascii=False)}

详细数据：
{json.dumps(summaries, ensure_ascii=False, indent=2)}

请生成Markdown报告，包含：
## 当日核心结论
## 品牌表现分析（提及率/评分/情感）
## 平台引用规律（哪个平台权重最高及原因）
## 表现最好的3个问题场景
## 表现最差的3个问题场景及改进建议
## 明日投放建议（具体可执行）"""

    try:
        report = ai(prompt, 2000)
        return jsonify({
            "ok": True,
            "date": date_str,
            "stats": {
                "total": len(records),
                "mentioned": mention_count,
                "mention_rate": mention_rate,
                "avg_score": avg_score,
                "platform_weights": platform_weights
            },
            "report": report
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/settings/rawpath", methods=["POST"])
def set_raw_path():
    """设置原始数据自定义存储路径"""
    d = request.json
    path = d.get("path", "").strip()
    if path and not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"路径创建失败：{str(e)}"}), 400
    s = load(F_SETTINGS, {})
    s["raw_data_path"] = path
    save(F_SETTINGS, s)
    return jsonify({"ok": True, "path": path or get_raw_data_dir()})


import uuid as uuid_lib
from flask import Response, stream_with_context

# 全局进度存储
crawl_sessions = {}

@app.route("/api/crawl/progress/<session_id>")
@app.route("/api/doubao/progress/<session_id>")  # 兼容旧接口
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


# ══════════════════════════════════════════════════════
# 跨平台对比模块
# ══════════════════════════════════════════════════════

@app.route("/api/platform/compare", methods=["GET"])
def platform_compare():
    """
    跨平台品牌表现对比：
    同一客户在各平台的提及率、平均GEO分、引用次数对比
    """
    client_id = request.args.get("client_id", "")
    date = request.args.get("date", "")
    if not client_id:
        return jsonify({"error": "缺少client_id"}), 400

    result = {}
    for pkey in CRAWL_PLATFORMS:
        records = load_client_records(
            client_id,
            date=date if date else None,
            platform=pkey
        )
        if not records:
            continue
        mentioned = sum(1 for r in records if r.get("brand_mentioned"))
        avg_score = round(
            sum(r.get("geo_score", 0) for r in records) / len(records), 1
        ) if records else 0
        total_refs = sum(len(r.get("refs", [])) for r in records)
        result[pkey] = {
            "platform_name": CRAWL_PLATFORMS[pkey]["name"],
            "total": len(records),
            "mentioned": mentioned,
            "mention_rate": round(mentioned / len(records) * 100, 1) if records else 0,
            "avg_geo_score": avg_score,
            "total_refs": total_refs,
        }

    return jsonify({"ok": True, "client_id": client_id, "date": date, "compare": result})


# ══════════════════════════════════════════════════════
# Agent Bot 模块
# ══════════════════════════════════════════════════════

@app.route("/api/agent/checklist", methods=["GET"])
def agent_checklist():
    """
    生成待爬取清单：
    对比今日已爬记录 vs 所有客户问题组，返回还没爬过的问题组列表
    """
    today = today_str()
    clients = load(F_CLIENTS, [])
    groups_all = load(F_GROUPS, {})
    raw_records = load(F_RAW_RECORDS, [])

    # 今日已爬的 (client_id, group_id) 集合
    crawled_today = set()
    for r in raw_records:
        if r.get("today") == today:
            cid = r.get("client_id", "")
            gid = r.get("group_id", "")
            if cid and gid:
                crawled_today.add((cid, gid))

    checklist = []
    for client in clients:
        cid = client["id"]
        cname = client.get("name", "")
        brand = client.get("brand", "")
        for g in groups_all.get(cid, []):
            gid = g["id"]
            q_count = len(g.get("questions", []))
            if q_count == 0:
                continue
            already = (cid, gid) in crawled_today
            checklist.append({
                "client_id": cid,
                "client_name": cname,
                "brand": brand,
                "group_id": gid,
                "group_name": g.get("name", ""),
                "question_count": q_count,
                "crawled_today": already
            })

    total = len(checklist)
    done = sum(1 for x in checklist if x["crawled_today"])
    return jsonify({
        "ok": True,
        "today": today,
        "total": total,
        "done": done,
        "pending": total - done,
        "checklist": checklist
    })


@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    """
    Agent Bot 对话接口：
    接收用户消息 + 当前任务上下文，返回 Bot 回复和指令
    """
    d = request.json
    user_msg = d.get("message", "").strip()
    context = d.get("context", {})   # 前端传入当前状态快照
    history = d.get("history", [])   # 历史对话（最多保留10条）

    if not user_msg:
        return jsonify({"error": "消息不能为空"}), 400

    settings = get_settings()
    if not settings.get("api_key"):
        return jsonify({"reply": "⚠️ 还没有配置 API Key，请先去系统设置填写喵～", "action": None})

    # 构建系统提示
    system_prompt = f"""你是 GEO Agent，一个帮助用户管理多客户内容投放工作的智能助手。
今天是 {today_str()}。

你的职责：
1. 帮用户统筹今日爬取和内容生产任务
2. 理解用户指令，返回对应的操作指令
3. 回复简洁友好，每次最多3句话

当前任务状态：
{json.dumps(context, ensure_ascii=False, indent=2)}

当用户意图明确时，在回复末尾附上操作指令（JSON格式），指令类型：
- {{"action":"start_crawl","client_id":"...","group_id":"..."}} 开始爬取某问题组
- {{"action":"start_analyze","client_id":"...","brand":"..."}} 触发深度分析
- {{"action":"confirm_articles"}} 用户确认生成内容
- {{"action":"show_checklist"}} 展示待爬清单
- {{"action":"none"}} 仅对话，无需操作

只在用户意图明确需要执行操作时才附加指令，闲聊时返回 {{"action":"none"}}。
回复语言：中文，简洁。"""

    # 组装消息历史
    messages = []
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_msg})

    try:
        client_ai = OpenAI(
            api_key=settings["api_key"],
            base_url=settings.get("base_url", "https://api.deepseek.com")
        )
        resp = client_ai.chat.completions.create(
            model=settings.get("model", "deepseek-chat"),
            messages=[{"role": "system", "content": system_prompt}] + messages,
            max_tokens=400,
            temperature=0.7
        )
        raw_reply = resp.choices[0].message.content.strip()

        # 尝试从回复末尾提取 action JSON
        action = None
        reply_text = raw_reply
        action_match = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]*"[^{}]*\}', raw_reply)
        if action_match:
            try:
                action = json.loads(action_match.group())
                # 从回复文本中移除 JSON 部分
                reply_text = raw_reply[:action_match.start()].strip()
            except:
                pass

        return jsonify({"ok": True, "reply": reply_text, "action": action})

    except Exception as e:
        return jsonify({"reply": f"出了点小问题：{str(e)}", "action": None})


@app.route("/api/agent/summary", methods=["GET"])
def agent_summary():
    """今日任务汇总：各客户爬取进度快照"""
    today = today_str()
    clients = load(F_CLIENTS, [])
    groups_all = load(F_GROUPS, {})
    raw_records = load(F_RAW_RECORDS, [])

    today_records = [r for r in raw_records if r.get("today") == today]

    summary = []
    for client in clients:
        cid = client["id"]
        brand = client.get("brand", "")
        client_groups = groups_all.get(cid, [])
        total_groups = len([g for g in client_groups if len(g.get("questions", [])) > 0])
        crawled_groups = len(set(
            r.get("group_id") for r in today_records
            if r.get("client_id") == cid and r.get("group_id")
        ))
        client_records = [r for r in today_records if r.get("client_id") == cid]
        mentioned = sum(1 for r in client_records if r.get("brand_mentioned"))
        avg_score = round(
            sum(r.get("geo_score", 0) for r in client_records) / len(client_records), 1
        ) if client_records else 0

        summary.append({
            "client_id": cid,
            "client_name": client.get("name", ""),
            "brand": brand,
            "total_groups": total_groups,
            "crawled_groups": crawled_groups,
            "total_records": len(client_records),
            "mentioned": mentioned,
            "avg_score": avg_score,
            "done": total_groups > 0 and crawled_groups >= total_groups
        })

    return jsonify({"ok": True, "today": today, "summary": summary})



# ══════════════════════════════════════════════════════
# 精准优化模块
# ══════════════════════════════════════════════════════

@app.route("/api/precise/diagnosis", methods=["GET"])
def precise_diagnosis():
    """
    问题诊断：返回各问题的提及率、平均GEO分、引用数，
    按优化空间（提及率从低到高）排序，标记值得精准优化的问题
    """
    client_id = request.args.get("client_id", "")
    group_id  = request.args.get("group_id", "")
    platform  = request.args.get("platform", "")
    if not client_id:
        return jsonify({"error": "缺少client_id"}), 400

    records = load_client_records(client_id, group_id=group_id,
                                  platform=platform if platform else None)
    if not records:
        return jsonify({"questions": []})

    from collections import defaultdict
    q_data = defaultdict(lambda: {"total": 0, "mentioned": 0, "geo_sum": 0, "ref_count": 0})
    for r in records:
        q = r.get("question", "")
        if not q: continue
        q_data[q]["total"] += 1
        if r.get("brand_mentioned"):
            q_data[q]["mentioned"] += 1
        q_data[q]["geo_sum"] += r.get("geo_score", 0) or 0
        q_data[q]["ref_count"] += len(r.get("refs", []))

    result = []
    for q, d in q_data.items():
        total = d["total"]
        mention_rate = round(d["mentioned"] / total * 100, 1) if total else 0
        avg_geo = round(d["geo_sum"] / total, 1) if total else 0
        avg_refs = round(d["ref_count"] / total, 1) if total else 0
        # 优化空间评分：提及率越低、样本越多、引用越多 → 越值得优化
        opportunity = round((100 - mention_rate) * min(total, 10) / 10, 1)
        result.append({
            "question": q,
            "total": total,
            "mention_rate": mention_rate,
            "avg_geo": avg_geo,
            "avg_refs": avg_refs,
            "opportunity": opportunity,  # 优化机会值，越高越值得优化
        })

    result.sort(key=lambda x: x["opportunity"], reverse=True)
    return jsonify({"questions": result})


@app.route("/api/precise/question_refs", methods=["GET"])
def precise_question_refs():
    """
    精准分析：返回某问题下的高频引用文章、平台分布、AI提炼引用规律
    """
    client_id       = request.args.get("client_id", "")
    question_filter = request.args.get("question", "")
    group_id        = request.args.get("group_id", "")
    platform        = request.args.get("platform", "")
    if not client_id or not question_filter:
        return jsonify({"error": "缺少参数"}), 400

    records = load_client_records(client_id, group_id=group_id,
                                  platform=platform if platform else None)
    records = [r for r in records if question_filter in r.get("question", "")]
    if not records:
        return jsonify({"total": 0, "top_articles": [], "platform_dist": [], "ai_insight": ""})

    from collections import defaultdict
    article_cnt  = defaultdict(int)
    article_info = {}
    platform_cnt = defaultdict(int)

    for r in records:
        seen = set()
        for ref in r.get("refs", []):
            url   = ref.get("url", "")
            title = ref.get("title", "")
            p     = ref.get("platform", "未知")
            key   = url or title
            if not key: continue
            article_cnt[key] += 1
            if key not in article_info:
                article_info[key] = {"title": title, "url": url, "platform": p}
            if p not in seen:
                platform_cnt[p] += 1
                seen.add(p)

    top_articles = sorted([
        {"title": article_info[k]["title"], "url": article_info[k]["url"],
         "platform": article_info[k]["platform"], "count": article_cnt[k]}
        for k in article_info
    ], key=lambda x: x["count"], reverse=True)[:15]

    total_refs = sum(platform_cnt.values()) or 1
    platform_dist = sorted([
        {"platform": p, "count": c, "pct": round(c / total_refs * 100, 1)}
        for p, c in platform_cnt.items()
    ], key=lambda x: x["count"], reverse=True)

    # AI提炼引用规律
    ai_insight = ""
    try:
        titles_text = "\n".join(
            f"{i+1}. [{a['platform']}] {a['title']} (被引{a['count']}次)"
            for i, a in enumerate(top_articles[:10])
        )
        insight_prompt = f"""用户问题：「{question_filter}」

以下是AI大模型在回答这个问题时最常引用的文章（共{len(records)}条记录）：
{titles_text}

请分析：
1. 这些高频引用文章有什么共同特征？（内容角度、标题规律、平台偏好）
2. AI倾向于引用什么类型的内容来回答这个问题？
3. 如果要创作一篇容易被AI引用的文章，应该具备哪些要素？

请用3条简洁结论输出，每条不超过50字。"""
        ai_insight = ai(insight_prompt, max_tokens=400)
    except Exception as e:
        ai_insight = f"AI分析暂不可用：{e}"

    return jsonify({
        "total": len(records),
        "question": question_filter,
        "top_articles": top_articles,
        "platform_dist": platform_dist,
        "ai_insight": ai_insight
    })


@app.route("/api/precise/generate", methods=["POST"])
def precise_generate():
    """
    精准生文：基于问题引用分析，生成1篇高度对齐豆包引用偏好的外发文章
    目标：文章发布后能被豆包在回答该问题时引用
    """
    d               = request.json or {}
    client_id       = d.get("client_id", "")
    brand           = d.get("brand", "")
    question        = d.get("question", "")
    top_articles    = d.get("top_articles", [])   # 高频引用文章列表
    platform_dist   = d.get("platform_dist", [])  # 平台分布
    ai_insight      = d.get("ai_insight", "")     # 引用规律分析
    target_platform = d.get("target_platform", "通用")  # 目标发布平台
    industry        = d.get("industry", "")

    if not question or not brand:
        return jsonify({"error": "缺少问题或品牌"}), 400

    # 读取客户资料
    materials = load(os.path.join(D, "uploads", client_id, "material.txt"),
                     "") if client_id else ""
    if not materials:
        materials = f"品牌：{brand}，行业：{industry}"

    # 构建高频引用文章摘要
    ref_summary = "\n".join(
        f"- [{a['platform']}] {a['title']} (被引{a['count']}次)"
        for a in top_articles[:8]
    ) or "暂无引用数据"

    # 平台分布摘要
    platform_summary = "、".join(
        f"{p['platform']}({p['pct']}%)" for p in platform_dist[:5]
    ) or "未知"

    prompt = f"""你是一位专注GEO优化（生成式引擎优化）的内容专家。

【任务背景】
用户在向AI大模型提问「{question}」时，AI通常不会提及{brand}。
我们需要创作一篇文章，发布到外部平台后，让AI在回答这个问题时引用并提及{brand}。

【客户品牌信息】
{materials[:600]}

【AI引用规律分析】
{ai_insight}

【AI最常引用的文章类型】
{ref_summary}

【主要引用来源平台】
{platform_summary}

【目标发布平台】{target_platform}

【创作要求】
1. 标题：参考高频引用文章的标题规律，包含问题关键词，有数据感或权威感
2. 内容：直接回答「{question}」，在推荐列表中自然地将{brand}列为首选或重点推荐
3. 结构：参考高频引用文章的内容角度和结构
4. 篇幅：1500-2500字，适合在{target_platform}平台发布
5. 风格：客观专业，像真实用户推荐或行业测评，不要像广告
6. 关键：{brand}必须出现至少3次，且以正面方式呈现具体优势

【禁止】不得编造客户评价、用户口碑、业主对话等内容

请直接输出完整文章（含标题），不需要任何前言或说明。"""

    try:
        article = ai(prompt, max_tokens=3000)
        return jsonify({"ok": True, "article": article, "question": question, "brand": brand})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    host = os.environ.get("GEO_HOST", "0.0.0.0")
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
