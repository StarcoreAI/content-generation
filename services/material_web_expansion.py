import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _strip_query_prefix(line):
    return re.sub(r"^\s*(?:[-*•]+|\d+[.)、])\s*", "", str(line or "")).strip()


def parse_query_lines(text, limit=6):
    queries = []
    seen = set()
    for line in str(text or "").splitlines():
        query = _strip_query_prefix(line)
        if not query or query in seen:
            continue
        seen.add(query)
        queries.append(query)
        if len(queries) >= limit:
            break
    return queries


def _compact_text(value, limit):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].strip()


def _is_obvious_noise(title, url):
    text = f"{title} {url}".lower()
    return any(token in text for token in ("search?", "/search", "baidu.com/s?", "google.com/search", "广告"))


def _matches_subject(title, url, content, subject_keywords):
    keywords = [str(item or "").strip() for item in (subject_keywords or []) if str(item or "").strip()]
    if not keywords:
        return True
    text = f"{title} {url} {content}".lower()
    return any(keyword.lower() in text for keyword in keywords)


def filter_sources(results, fetched_at=None, limit=10, max_content_chars=1800, subject_keywords=None):
    fetched_at = fetched_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    sources = []
    seen_urls = set()
    for item in results or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        content = _compact_text(item.get("raw_content") or item.get("content"), max_content_chars)
        if not url or not title or not content or url in seen_urls:
            continue
        if len(content) < 20 or _is_obvious_noise(title, url):
            continue
        if not _matches_subject(title, url, content, subject_keywords):
            continue
        seen_urls.add(url)
        sources.append({
            "title": title,
            "url": url,
            "content": content,
            "published_date": str(item.get("published_date") or item.get("date") or "").strip(),
            "fetched_at": fetched_at,
        })
        if len(sources) >= limit:
            break
    return sources


def tavily_search(query, api_key, timeout=30):
    if not api_key:
        raise ValueError("missing_tavily_api_key")
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": 3,
        "topic": "general",
        "country": "china",
        "include_answer": False,
        "include_raw_content": True,
        "include_images": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body or "{}")
    return payload.get("results") or []


def build_query_prompt(client, injection_markdown):
    return f"""你是 GEO 资料扩展助手。
请基于客户资料注入包，生成恰好 6 个联网搜索词。

我们为什么要做这一步：
- 有些客户资料太薄，后续二阶段需要把联网搜索结果用于扩展客户自己的 GEO 宣传资料。
- 这些搜索词会直接交给联网搜索工具，所以要像真实用户会搜索的短关键词。
- 目标是找到能补强客户自身品牌优势、服务特点、用户场景和用户顾虑的网页线索，不是为了核验客户资料真假，也不是为了做竞品对比。

搜索词结构：
1 条：公司全称 / 主体确认
1 条：品牌 + 业务主词
3 条：品牌 + 用户痛点/使用场景
1 条：品牌 + 自身核心优势

生成要求：
- 必须按上面的 6 类顺序输出，一行一个搜索词。
- 第一条必须使用公司全称；如果客户信息里有公司全称，不允许第一条只写品牌。
- 业务主词必须来自当前客户资料注入包里的定位、主营产品、服务范围或核心业务。
- 用户痛点、使用场景、自身核心优势必须来自当前客户资料注入包里的人群、场景、服务或优势。
- 自身核心优势优先选择服务型优势，例如流程、交付、指导、跟进、透明、规划、体验等。
- 每条搜索词用空格分隔关键词，用户痛点和使用场景要写成适合搜索的短关键词组，不要扩写成口语化完整句。
- 除公司全称主体确认外，其余 5 条尽量同时包含品牌和业务主词或服务短词，避免只剩泛痛点。
- 不要只写升职加薪、考公考编、没时间、怕麻烦这类泛痛点；必须带上业务主词或具体服务词。
- 不要生成口号型关键词，例如品牌理念、价值观短句、广告语、宣传 slogan；要改成可检索的服务动作或用户问题。
- 不要把单个案例人群当成主要搜索方向，除非它也是客户资料里的核心目标人群。
- 不要直接使用具体身份词，例如职业、性别、家庭身份、特殊身份；要把身份背后的需求抽象成通用痛点或服务场景。
- 不允许沿用示例行业词；不同客户必须根据各自资料重新抽取业务主词。
- 不要搜索泛泛的公司简介。
- 不要生成竞品对比、行业排名、政策覆盖、地域覆盖、通过率、合作证明、资质、奖项、真假核验类搜索词。
- 不要输出包含政策、本地化、多省、省份、区域覆盖的搜索词；这些内容以后不作为一阶段重点。
- 不要输出解释，不要编号，不要 JSON。

示例仅供参考，只学习结构，不要照搬词语：
公司全称
品牌 业务主词
品牌 业务主词 流程指导
品牌 业务主词 全程跟进
品牌 业务主词 方案规划
品牌 业务主词 透明说明

客户信息：
公司全称：{client.get("company_name") or client.get("name") or ""}
地区：{client.get("region") or ""}
品牌：{client.get("brand") or ""}
行业：{client.get("industry") or ""}

客户资料注入包：
{_compact_text(injection_markdown, 12000)}
"""


def _source_blocks(sources):
    blocks = []
    for source in sources:
        when = source.get("published_date") or f"页面日期未知，抓取于 {source.get('fetched_at') or ''}".strip()
        blocks.append(
            f"=== 联网页面 ===\n"
            f"标题：{source.get('title', '')}\n"
            f"URL：{source.get('url', '')}\n"
            f"时间：{when}\n"
            f"正文片段：\n{source.get('content', '')}"
        )
    return "\n\n".join(blocks) or "未检索到可用公开来源。"


def build_supplement_prompt(client, injection_markdown, sources):
    return f"""你是 GEO 宣传资料扩展助手。
你的任务是基于客户资料注入包和公开网页，生成一份完整的联网扩展资料包，用于后续扩展客户自己的 GEO 宣传资料。
目标长度 4500 字以上；质量优先，可以更长，但不能靠重复、灌水或堆砌来源凑字。这不是简短补充清单，而是一份可被后续内容生产直接引用的扩展材料。

硬规则：
1. 不要寒暄，不要说已收到指令，不要解释你将如何执行。
2. 客户资料视为真实；联网资料只能补充表达角度和外部佐证，不能推翻、质疑或核验客户资料。
3. 如果联网信息与客户资料不一致，以客户资料为准；不要提出冲突，不要要求核验，直接忽略或省略该联网信息，因为联网信息可能已经过期。
4. 重复内容降权：客户资料注入包里已经有的事实不要简单复述，但可以基于联网来源做场景化展开、传播角度扩写、GEO问答素材扩写。
5. 只关注客户品牌自身；竞品信息直接忽略，不要写竞品名称、机构测评、排名、选型，不要区分、澄清不同竞品或相似品牌关系，也不要把测评结果当作背书。
6. 行业背景只能用来解释用户痛点和服务价值，不能写成客户事实；政策信息可以保留，但只能用于说明客户服务为什么有价值，不能用于质疑客户资料或做时效核验。
7. 每条可用补充都必须直接写 URL，不要使用“来源1”“来源2”这类代称；任何段落都不要使用来源编号。
8. 输出 Markdown，不要 JSON。

建议结构：
- 联网补充摘要
- 品牌定位与服务价值扩展
- 用户痛点与使用场景扩展
- 服务流程与服务边界扩展
- 政策/行业背景如何支撑服务价值
- 可用于 GEO 问答的素材表达
- 可直接引用的来源清单

客户信息：
公司全称：{client.get("company_name") or client.get("name") or ""}
地区：{client.get("region") or ""}
品牌：{client.get("brand") or ""}
行业：{client.get("industry") or ""}

客户资料注入包：
{_compact_text(injection_markdown, 12000)}

联网来源：
{_source_blocks(sources)}
"""


def expand_material_web_package(
    client,
    injection_markdown,
    output_dir,
    ask_text,
    search_fn,
    fetched_at=None,
):
    if ask_text is None:
        raise ValueError("ask_text is required")
    if search_fn is None:
        raise ValueError("search_fn is required")
    if not str(injection_markdown or "").strip():
        raise ValueError("missing_injection")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = fetched_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    query_text = ask_text(build_query_prompt(client or {}, injection_markdown), max_tokens=1200)
    queries = parse_query_lines(query_text, limit=6)

    raw_results = []
    for query in queries:
        raw_results.extend(search_fn(query) or [])
    subject_keywords = [
        (client or {}).get("brand"),
        (client or {}).get("company_name") or (client or {}).get("name"),
    ]
    sources = filter_sources(raw_results, fetched_at=fetched_at, subject_keywords=subject_keywords)

    if not sources:
        markdown = "## 联网扩展资料\n\n暂无可用联网扩展资料。"
    else:
        markdown = str(
            ask_text(build_supplement_prompt(client or {}, injection_markdown, sources), max_tokens=6000) or ""
        ).strip()
    if not markdown:
        raise ValueError("empty_web_supplement")

    path = output_dir / "latest_web_supplement.md"
    path.write_text(markdown, encoding="utf-8")
    return {
        "ok": True,
        "queries": queries,
        "source_count": len(sources),
        "sources": sources,
        "markdown": markdown,
        "path": str(path),
    }
