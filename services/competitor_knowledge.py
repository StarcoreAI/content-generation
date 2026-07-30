"""Build an editable competitor master from already collected local material."""
import re

from services.knowledge_base import clean_knowledge_markdown, is_short_placeholder_section


def _collect_referenced_articles(records, limit=20):
    by_url, order = {}, []
    for record in records or []:
        for ref in record.get("refs") or []:
            url = str(ref.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            if url not in by_url:
                by_url[url] = {
                    "url": url, "source_title": str(ref.get("title") or ""),
                    "platform": str(ref.get("platform") or ""),
                    "citation_count": 0, "_index": len(order),
                }
                order.append(url)
            by_url[url]["citation_count"] += 1
    result = sorted(by_url.values(), key=lambda item: (-item["citation_count"], item["_index"]))
    for item in result:
        item.pop("_index", None)
    return result[:limit] if limit else result


def _real_name(value):
    name = re.sub(r"\s+", " ", str(value or "")).strip(" #：:-")
    if not name or re.fullmatch(r"(?:竞品|机构|品牌)?[A-ZＡ-Ｚ0-9一二三四五六七八九十]+", name):
        return ""
    return name[:80]


def _upload_sections(markdown):
    markdown = clean_knowledge_markdown(markdown)
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown))
    sections = {}
    for index, match in enumerate(matches):
        name = _real_name(match.group(1))
        if not name:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[match.end():end].strip()
        if body and not is_short_placeholder_section(body):
            sections[name] = body
    return sections


def collect_high_frequency_article_sources(records, cached_by_url, fetcher, limit=12):
    """Fetch the globally most-cited references, preferring an existing body cache."""
    sources = []
    for reference in _collect_referenced_articles(records, limit=limit):
        url = reference["url"]
        cached = (cached_by_url or {}).get(url)
        if isinstance(cached, dict) and cached.get("ok") and str(cached.get("content") or "").strip():
            fetched = {**cached, "fetch_method": "cache"}
        else:
            try:
                fetched = dict(fetcher(url) or {})
            except Exception as exc:
                fetched = {"ok": False, "error": str(exc)}
            fetched.setdefault("fetch_method", "fetch")
        sources.append({
            **reference,
            "ok": bool(fetched.get("ok")),
            # 这里展示的是被平台实际引用时的标题，不能被抓取页的 <title> 覆盖，
            # 否则运营无法将资料追溯到原始引用记录。
            "title": str(reference.get("source_title") or fetched.get("title") or "").strip(),
            "fetched_title": str(fetched.get("title") or "").strip(),
            "description": str(fetched.get("description") or "").strip(),
            "content": str(fetched.get("content") or "").strip(),
            "fetch_method": fetched.get("fetch_method") or "fetch",
            "error": str(fetched.get("error") or ""),
        })
    return sources


def build_high_frequency_competitor_prompt(competitors, articles, batch_index=1, batch_count=1):
    names = "\n".join(f"- {name}" for name in (_real_name(item) for item in competitors or []) if name) or "由文章中出现的真实竞品名称决定。"
    blocks = []
    for index, article in enumerate(articles or [], 1):
        content = str(article.get("content") or "").strip()[:8000]
        if not content:
            continue
        blocks.append(
            f"=== 高频引用文章 {index} ===\n"
            f"标题：{article.get('title') or ''}\n"
            f"URL：{article.get('url') or ''}\n"
            f"累计引用次数：{article.get('citation_count') or 0}\n"
            f"正文：\n{content}"
        )
    return f"""你是 GEO 竞品资料整理助手。
请从所有平台合并后、累计引用次数最高的 12 篇引用文章中，整理其中出现的竞品资料，供运营维护竞品知识库。本次是第 {batch_index}/{batch_count} 批文章；后续会按竞品名称合并，不需要在本批压缩或概括资料。

硬规则：
1. 只使用以下文章正文，不使用外部知识，不联网搜索，不补充文章没有写出的事实。
2. 先判断文章的主要介绍或比较对象，只为这些主要对象建立竞品分节并收集资料。关联实体只能作为主要对象的一条事实中的所属、任职、团队、合作或服务关系，不另建竞品分节、不单独收集。比如主要介绍医生时，医院只是所属关系，只收集医生资料；主要介绍学校时，老师只是学校信息，只收集学校资料。只有某个关联实体本身也被文章独立、持续地介绍或横向比较时，才可视为另一个主要对象。
3. 主要对象可以是真实品牌名、机构名、门店名、公司名，或专家、医生、设计师、顾问等真实个人名称；禁止 A/B/C、竞品1、竞品2、某机构等占位名称。
4. 不拉踩、不排名、不写推荐结论，不为了突出客户品牌贬低竞品。
5. 这是详尽事实抽取，不写摘要：尽量保留文章中每一条明确、可核对的竞品事实。定位、业务/项目、服务动作、地区/网点、流程、团队、售后、适合人群、价格、资质、案例、效果、排名和数字等，只要文章明确写出就分别列出；不同事实不得泛化合并或因同类而省略。
6. 每个竞品按名称单独分节；没有可用信息就不要输出该竞品；不要输出空栏目、来源标签、URL、解释或选购建议。
7. 输出 Markdown。每个分节必须以“## 真实竞品名称”开头；标题下先写 1–3 句客观概述，作为自然段，不加“概述”标签。概述只能归纳下方明确事实，不能新增判断，也不要和条目逐句重复。
8. 概述后再用条目列出全部可核对的详细事实。

当日已识别的竞品名称（仅作核对，不代表可以编造）：
{names}

固定文章来源：
{"\n\n".join(blocks) or "无可用文章正文。"}
"""


def merge_competitor_master_markdown(*documents):
    """Merge Markdown sections without exposing source labels in the master."""
    sections = {}
    order = []
    for document in documents:
        for name, body in _upload_sections(document).items():
            if name not in sections:
                sections[name] = []
                order.append(name)
            if body and body not in sections[name] and body != "暂无可合并资料。":
                sections[name].append(body)
    chunks = ["# 竞品总资料", "", "按真实竞品名称汇总，支持运营直接编辑。"]
    for name in order:
        # ponytail: 只去掉完全相同的行，语义近似的事实留给运营人工判断。
        unique_lines = []
        seen = set()
        for body in sections[name]:
            for line in body.splitlines():
                normalized = re.sub(r"\s+", " ", line).strip()
                if normalized and normalized in seen:
                    continue
                if normalized:
                    seen.add(normalized)
                unique_lines.append(line)
        body = "\n".join(unique_lines).strip()
        if body and not is_short_placeholder_section(body):
            chunks.extend(["", f"## {name}", "", body])
    return "\n".join(chunks).strip() + "\n"


def build_competitor_master_input(entity_names, body_hits, upload_markdown):
    """Return one Markdown master with a section for every real competitor name."""
    uploads = _upload_sections(upload_markdown)
    names = []
    for name in list(entity_names or []) + list(uploads):
        name = _real_name(name)
        if name and name not in names:
            names.append(name)

    evidence_by_name = {name: [] for name in names}
    for hit in body_hits or []:
        if not isinstance(hit, dict) or hit.get("status") != "matched":
            continue
        evidence = str(hit.get("evidence") or "").strip()
        fallback = str(hit.get("title") or "").strip()
        for name in hit.get("matched_entities") or []:
            name = _real_name(name)
            if name not in evidence_by_name:
                continue
            line = evidence or (f"正文命中：{fallback}" if fallback else "")
            if line and line not in evidence_by_name[name]:
                evidence_by_name[name].append(line)

    chunks = ["# 竞品总资料", "", "按真实竞品名称汇总，支持运营直接编辑。"]
    for name in names:
        entries = []
        if uploads.get(name):
            entries.append(uploads[name])
        for line in evidence_by_name[name]:
            entries.append(f"- {line}")
        body = "\n".join(entries).strip()
        if body and not is_short_placeholder_section(body):
            chunks.extend(["", f"## {name}", "", body])
    return "\n".join(chunks).strip() + "\n"
