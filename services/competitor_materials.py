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
        for query in [
            f"{name} {scope}".strip(),
            f"{name} 怎么样 靠谱",
            f"{name} 简介",
        ]:
            queries.append({"competitor": name, "query": query})
    return queries


def build_competitor_search_query_prompt(competitors, client=None, qualifier="", customer_context="", competitor_context=""):
    names = normalize_competitor_names(competitors)
    scope = competitor_qualifier(client or {}, qualifier)
    return f"""你是 GEO 竞品联网检索词策划助手。
请为每个真实竞品名称生成用于公开网页搜索的检索词，帮助后续整理该竞品的详细业务资料。

客户行业/品类：{scope}
客户地区：{(client or {}).get('region') or ''}
竞品名单：
{"\n".join(f"- {name}" for name in names)}

规则：
1. 每行严格输出“真实竞品名称 | 检索词”，不输出标题、编号或解释。
2. 检索词必须保留对应真实竞品名称，并结合客户行业/品类。
3. 围绕业务、服务、项目、案例、流程、施工或交付、团队、售后等能展开具体资料的方向生成；同一竞品的词要有不同角度。客户资料只用于识别同行业的业务场景、服务主词和目标人群，再结合竞品名称搜索同类公开资料；不要把客户品牌、客户优势或行业公共背景原样改成竞品检索词。可选竞品上传资料只取与该行竞品名称相同的分节，用来补充该竞品的主体、地区或服务线索，不借用其他竞品的信息。
4. 不使用 A/B/C、竞品1、某机构等占位名称，不生成泛化的“哪家好”“排行榜”“怎么选”类词。

客户资料注入包：
{_compact_text(customer_context, 12000)}

可选竞品上传资料：
{_compact_text(competitor_context, 12000)}
"""


def generate_competitor_search_queries(competitors, client=None, qualifier="", ask_text=None,
                                       customer_context="", competitor_context=""):
    names = normalize_competitor_names(competitors)
    fallback = build_competitor_search_queries(names, client or {}, qualifier)
    if not names or ask_text is None:
        return fallback
    try:
        generated = str(ask_text(
            build_competitor_search_query_prompt(
                names, client or {}, qualifier, customer_context, competitor_context,
            ),
            max_tokens=1600,
        ) or "")
    except Exception:
        return fallback

    by_name = {name: [] for name in names}
    for line in generated.splitlines():
        parts = re.split(r"\s*[|｜]\s*", line.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        name, query = (part.strip() for part in parts)
        if name not in by_name or not query or name not in query or query in by_name[name]:
            continue
        by_name[name].append(query)

    queries = []
    fallback_by_name = {}
    for item in fallback:
        fallback_by_name.setdefault(item["competitor"], []).append(item["query"])
    for name in names:
        for query in by_name[name] or fallback_by_name.get(name, []):
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
4. 不拉踩任何竞品，不写主观否定；只客观整理其定位、业务侧重、适合人群、服务特点、限制和来源依据。
4a. 正文描述统一使用直接陈述句，直接写定位、业务、服务或地址等常规事实；不要写“公开页面显示其……”“页面自述”“根据资料显示”等转述句式。
5. 不为了突出客户品牌而贬低竞品。
6. 不编造资料中没有的事实。价格、资质、案例、地址、效果、排名等高风险信息必须保守表达。
7. 每个竞品的第一行用一句话概括定位与业务侧重；资料允许时补一句"适合人群"；其余内容按资料自然组织，保持简短。
8. 竞品的宣传性数字和绝对化主张（通过率、学员数、排名、"唯一/第一"、荣誉称号）不要混入正文描述；如资料中出现，在该竞品末尾集中列一行"宣传主张（仅记录，禁止在我方内容中复述）：……"。
9. 资料中夹带的主观负面评价（服务差、投诉多等无法核验的内容）不进入竞品描述；如有，统一放到文末"内部观点备注（仅内部参考，不入内容）"一节。
10. 输出 Markdown；必须按真实竞品名称分组；资料没有的信息不要硬凑栏目；不要输出空栏目；不要解释过程。

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
        expandable = []
        for source in sources:
            title = source.get("title", "")
            content = source.get("content", "")
            if len(str(content or "").strip()) < 200:
                continue
            expandable.append(
                f"标题：{source.get('title', '')}\n"
                f"时间：{source.get('published_date') or source.get('fetched_at') or ''}\n"
                f"正文片段：{content}"
            )
        blocks.append(
            f"=== 竞品：{name} ===\n"
            "【可展开来源】\n"
            + ("\n\n".join(expandable) or "无")
        )
    return "\n\n".join(blocks) or "未检索到可用公开来源。"


def build_web_competitor_prompt(client, competitor):
    name = competitor.get("name") or ""
    return f"""你是 GEO 竞品公开资料整理助手。
你的任务是基于公开网页搜索结果，只为“{name}”整理客观、可追溯的竞品资料补充包，
供后续对比型文章中的"其他机构简评"段落和对比表参考。

硬规则：
1. 只使用输入中的网页来源，不使用外部知识，不编造事实。
2. 必须使用真实竞品名称“{name}”，不允许写 A/B/C、竞品1、某机构。
3. 资料允许时写充分的结构化条目，可自然覆盖定位、业务与项目、规模与网点、价格线索、口碑与评价、适合人群。对【可展开来源】中的独有事实，不为了简洁省略案例、城市或门店、服务步骤、公开数据、团队和售后等具体信息，也不要压成“提供一站式服务”等泛化句。
4. 正文描述统一使用直接陈述句，直接写定位、业务、服务、网点或地址等常规事实；不要写“公开页面显示其……”“页面自述”“据 X 介绍”“根据资料显示”等转述句式。
5. 不拉踩，不排名，不替客户品牌下判断；对公开信息使用保守表述。
6. 来源没有的信息不要硬凑栏目，不要输出空栏目。
7. 输出 Markdown，第一行必须是“## {name}”，不要输出总标题或解释过程。只保留该竞品的事实；不得输出链接、URL、来源标签或来源说明；不得添加“适合对比关注的维度”“对比关注点”“怎么选”“选择建议”等面向读者的比较指导小节。

客户行业/品类：{(client or {}).get('category') or (client or {}).get('industry') or ''}

联网来源：
{_source_blocks([competitor])}
"""


def _load_web_sections(markdown):
    text = str(markdown or "").strip()
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if not matches:
        return "# 竞品联网资料补充包", []
    preamble = text[:matches[0].start()].strip() or "# 竞品联网资料补充包"
    sections = []
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if name:
            sections.append((name, text[match.start():end].strip()))
    return preamble, sections


_META_COMPARISON_HEADING = re.compile(r"适合对比|对比关注|怎么选|选择建议|使用建议|核验建议")


def _competitor_section(name, markdown):
    text = str(markdown or "").strip()
    if not text:
        return ""
    lines = []
    skipping = False
    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            skipping = bool(_META_COMPARISON_HEADING.search(heading.group(1)))
        if not skipping:
            lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    if re.fullmatch(rf"##\s+{re.escape(name)}", first_line):
        return text
    return f"## {name}\n\n{text}"


def _load_web_sources(path):
    data = load_json(path, {})
    competitors = data.get("competitors") if isinstance(data, dict) else {}
    if isinstance(competitors, dict):
        return dict(competitors)
    merged = {}
    for item in competitors or []:
        name = str(item.get("name") or "").strip()
        if name:
            merged[name] = {
                "queries": [item.get("query")] if item.get("query") else [],
                "sources": item.get("sources") or [],
                "fetched_at": str(item.get("fetched_at") or ""),
            }
    return merged


def expand_competitor_web_package(
    client,
    competitors,
    qualifier,
    output_dir,
    ask_text,
    search_fn,
    fetched_at=None,
    per_competitor_limit=8,
    max_tokens=6000,
    force=None,
    customer_context="",
    competitor_context="",
):
    if ask_text is None:
        raise ValueError("ask_text is required")
    if search_fn is None:
        raise ValueError("search_fn is required")
    force_names = normalize_competitor_names(force)
    requested = force_names or normalize_competitor_names(competitors)
    if not requested:
        raise ValueError("missing_competitors")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = fetched_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    markdown_path = output_dir / "latest_web_competitors.md"
    preamble, stored_sections = _load_web_sections(
        markdown_path.read_text(encoding="utf-8", errors="ignore") if markdown_path.exists() else ""
    )
    section_map = {name: section for name, section in stored_sections} if force_names else {}
    query_map = {}
    for item in generate_competitor_search_queries(
        requested, client or {}, qualifier, ask_text=ask_text,
        customer_context=customer_context, competitor_context=competitor_context,
    ):
        query_map.setdefault(item["competitor"], []).append(item)

    source_path = output_dir / "latest_web_sources.json"
    source_map = _load_web_sources(source_path) if force_names else {}
    competitor_results, updated, failed = [], [], []
    for name in requested:
        raw_sources = []
        try:
            for item in query_map.get(name, []):
                raw_sources.extend(search_fn(item["query"]) or [])
        except Exception:
            failed.append(name)
            continue
        sources = filter_sources(
            raw_sources, fetched_at=fetched_at, limit=per_competitor_limit,
            max_content_chars=3000, subject_keywords=[name],
        )
        if not sources:
            failed.append(name)
            continue
        competitor = {"name": name, "sources": sources}
        try:
            markdown = _competitor_section(
                name, ask_text(build_web_competitor_prompt(client or {}, competitor), max_tokens)
            )
        except Exception:
            failed.append(name)
            continue
        if not markdown:
            failed.append(name)
            continue
        section_map[name] = markdown
        source_map[name] = {
            "queries": [item["query"] for item in query_map.get(name, [])],
            "sources": sources,
            "fetched_at": fetched_at,
        }
        competitor_results.append({"name": name, "queries": source_map[name]["queries"], "source_count": len(sources), "sources": sources})
        updated.append(name)

    if updated:
        ordered_names = [name for name, _section in stored_sections if name in section_map] if force_names else []
        ordered_names.extend(name for name in updated if name not in ordered_names)
        markdown = "\n\n".join([preamble] + [section_map[name] for name in ordered_names]).strip() + "\n"
        markdown_path.write_text(markdown, encoding="utf-8")
        save_json(source_path, {
            "competitors": source_map,
            "source_count": sum(len(item.get("sources") or []) for item in source_map.values()),
        })
    else:
        markdown = markdown_path.read_text(encoding="utf-8", errors="ignore") if markdown_path.exists() else ""
    queries = [item for name in requested for item in query_map.get(name, [])]
    source_count = sum(item["source_count"] for item in competitor_results)
    return {
        "ok": True,
        "queries": queries,
        "source_count": source_count,
        "competitors": competitor_results,
        "markdown": markdown,
        "path": str(markdown_path),
        "skipped": [],
        "updated": updated,
        "failed": failed,
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
