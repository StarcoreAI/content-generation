import re
from datetime import datetime
from pathlib import Path

from services.material_package_extractor import extract_material_package
from services.material_web_expansion import _compact_text, filter_sources
from services.storage import load_json, save_json


def normalize_competitor_names(names, limit=10):
    cleaned = []
    seen = set()
    for item in names or []:
        name = re.sub(r"\s+", " ", str(item or "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned.append(name[:80])
        if len(cleaned) >= limit:
            break
    return cleaned


def competitor_qualifier(client, qualifier=""):
    value = str(qualifier or "").strip()
    if value:
        return value[:80]
    for key in ("category", "industry"):
        value = str((client or {}).get(key) or "").strip()
        if value:
            return value[:80]
    return ""


def build_competitor_search_queries(competitors, client=None, qualifier=""):
    scope = competitor_qualifier(client or {}, qualifier)
    queries = []
    for name in normalize_competitor_names(competitors):
        query = f"{name} {scope}".strip()
        queries.append({"competitor": name, "query": query})
    return queries


def _readable_units(package_dir):
    extracted = extract_material_package(package_dir)
    return [
        unit for unit in extracted.get("units") or []
        if str(unit.get("text") or "").strip()
    ]


def _unit_blocks(units):
    blocks = []
    for unit in units:
        source = unit.get("path") or unit.get("source_path") or unit.get("unit_id") or ""
        sheet = unit.get("sheet_name") or ""
        title = f"来源文件：{source}" + (f" / sheet：{sheet}" if sheet else "")
        blocks.append(
            "=== 上传资料单元 ===\n"
            f"{title}\n"
            f"unit_id：{unit.get('unit_id', '')}\n"
            f"正文：\n{_compact_text(unit.get('text'), 5000)}"
        )
    return "\n\n".join(blocks)


def build_upload_competitor_prompt(competitors, units):
    competitor_text = "\n".join(f"- {name}" for name in normalize_competitor_names(competitors)) or "未指定，按资料中出现的真实竞品名称整理。"
    return f"""你是 GEO 竞品资料整理助手。
你的任务是把上传资料中的竞品信息按真实竞品名称合并、去重、规整，生成一份可供后续对比型内容生产参考的竞品资料包。

硬规则：
1. 只整理竞品资料，不写文章，不生成推荐结论。
2. 竞品名称必须使用资料中出现的真实品牌名、机构名、门店名或公司名；禁止使用 A/B/C、竞品1、竞品2 这类占位名称。
3. 只有在名称、主体、地区、业务描述明显一致时才合并；无法确定是否同一主体时，直接分开整理，不要猜测关系。
4. 不拉踩任何竞品，不写主观否定；只客观整理其优点、适合人群、服务特点、限制和来源依据。
5. 不为了突出客户品牌而贬低竞品。
6. 不编造资料中没有的事实。价格、资质、案例、地址、效果、排名等高风险信息必须保守表达。
7. 输出 Markdown，结构根据资料自然组织；必须按真实竞品名称分组；资料没有的信息不要硬凑栏目；不要输出空栏目；不要解释过程。

运营指定或默认竞品名单：
{competitor_text}

上传资料：
{_unit_blocks(units)}
"""


def analyze_competitor_upload_package(package_dir, output_dir, competitors, ask_text, max_tokens=6000):
    if ask_text is None:
        raise ValueError("ask_text is required")
    package_dir = Path(package_dir)
    output_dir = Path(output_dir)
    units = _readable_units(package_dir)
    if not units:
        raise FileNotFoundError("no_competitor_material_files")
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown = str(
        ask_text(build_upload_competitor_prompt(competitors, units), max_tokens=max_tokens) or ""
    ).strip()
    if not markdown:
        raise ValueError("empty_competitor_upload_markdown")
    markdown_path = output_dir / "latest_upload_competitors.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    status = {
        "ok": True,
        "status": "completed",
        "unit_count": len(units),
        "competitors": normalize_competitor_names(competitors),
        "markdown_chars": len(markdown),
        "path": str(markdown_path),
    }
    save_json(output_dir / "latest_status.json", status)
    return {**status, "markdown": markdown}


def _source_blocks(competitors):
    blocks = []
    for item in competitors:
        name = item.get("name") or ""
        sources = item.get("sources") or []
        if not sources:
            continue
        source_text = []
        for source in sources:
            source_text.append(
                f"标题：{source.get('title', '')}\n"
                f"URL：{source.get('url', '')}\n"
                f"时间：{source.get('published_date') or source.get('fetched_at') or ''}\n"
                f"正文片段：{source.get('content', '')}"
            )
        blocks.append(f"=== 竞品：{name} ===\n" + "\n\n".join(source_text))
    return "\n\n".join(blocks) or "未检索到可用公开来源。"


def build_web_competitor_prompt(client, competitors):
    return f"""你是 GEO 竞品公开资料整理助手。
你的任务是基于公开网页搜索结果，为每个竞品整理客观、可追溯的竞品资料补充包。

硬规则：
1. 只使用输入中的网页来源，不使用外部知识，不编造事实。
2. 每个竞品必须使用真实竞品名称，不允许写 A/B/C、竞品1、某机构。
3. 每条重要信息必须带 URL；没有 URL 的信息不能进入结论。
4. 不拉踩，不排名，不替客户品牌下判断。
5. 对公开网页信息使用保守表述，例如“公开页面显示”“页面介绍”“该来源提到”。
6. 不强行统一格式；按竞品和资料内容自然组织。
7. 资料没有的信息不要硬凑栏目，不要输出空栏目。
8. 输出 Markdown，不要解释过程。

客户行业/品类：{(client or {}).get('category') or (client or {}).get('industry') or ''}

联网来源：
{_source_blocks(competitors)}
"""


def expand_competitor_web_package(
    client,
    competitors,
    qualifier,
    output_dir,
    ask_text,
    search_fn,
    fetched_at=None,
    per_competitor_limit=2,
    max_tokens=6000,
):
    if ask_text is None:
        raise ValueError("ask_text is required")
    if search_fn is None:
        raise ValueError("search_fn is required")
    names = normalize_competitor_names(competitors)
    if not names:
        raise ValueError("missing_competitors")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = fetched_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    competitor_results = []
    queries = build_competitor_search_queries(names, client or {}, qualifier)
    for item in queries:
        name = item["competitor"]
        sources = filter_sources(
            search_fn(item["query"]) or [],
            fetched_at=fetched_at,
            limit=per_competitor_limit,
            subject_keywords=[name],
        )
        competitor_results.append({
            "name": name,
            "query": item["query"],
            "source_count": len(sources),
            "sources": sources,
        })

    source_count = sum(item["source_count"] for item in competitor_results)
    if source_count:
        markdown = str(
            ask_text(build_web_competitor_prompt(client or {}, competitor_results), max_tokens=max_tokens) or ""
        ).strip()
    else:
        markdown = "# 竞品联网资料补充包\n\n暂无可用竞品联网资料。"
    if not markdown:
        raise ValueError("empty_competitor_web_markdown")

    markdown_path = output_dir / "latest_web_competitors.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    save_json(output_dir / "latest_web_sources.json", {
        "queries": queries,
        "competitors": competitor_results,
        "source_count": source_count,
    })
    return {
        "ok": True,
        "queries": queries,
        "source_count": source_count,
        "competitors": competitor_results,
        "markdown": markdown,
        "path": str(markdown_path),
    }


def load_latest_competitor_result(output_dir):
    output_dir = Path(output_dir)
    upload_path = output_dir / "latest_upload_competitors.md"
    web_path = output_dir / "latest_web_competitors.md"
    return {
        "ok": upload_path.exists() or web_path.exists(),
        "status": load_json(output_dir / "latest_status.json", {"status": "missing"}),
        "upload_markdown": upload_path.read_text(encoding="utf-8", errors="ignore") if upload_path.exists() else "",
        "web_markdown": web_path.read_text(encoding="utf-8", errors="ignore") if web_path.exists() else "",
    }
