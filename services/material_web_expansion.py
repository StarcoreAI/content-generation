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


def _normalize_subject_text(value):
    return re.sub(r"[\s()（）]", "", str(value or "")).lower()


def _matches_subject(title, url, content, subject_keywords):
    keywords = [str(item or "").strip() for item in (subject_keywords or []) if str(item or "").strip()]
    if not keywords:
        return True
    text = _normalize_subject_text(f"{title} {url} {content}")
    return any(_normalize_subject_text(keyword) in text for keyword in keywords)


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


def tavily_search(query, api_key, timeout=30, max_results=3):
    if not api_key:
        raise ValueError("missing_tavily_api_key")
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max(1, int(max_results)),
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
    return f"""你是客户联网事实检索助手。
请基于客户资料注入包，生成恰好 6 个联网搜索词。

我们为什么要做这一步：
- 有些客户资料太薄，需要从公开网页中寻找可补充的客户专属事实候选。
- 这些搜索词会直接交给联网搜索工具，所以要像真实用户会搜索的短关键词。
- 目标不是找写作灵感，而是寻找可明确归属该客户的公司主体、产品、服务、工艺、资质、案例等公开信息。
- 搜索结果只用于生成客户专属事实候选，不做竞品对比。

搜索词结构：
1 条：公司全称
1 条：公司全称 产品 服务
1 条：品牌 + 主营产品或核心服务
1 条：公司全称 + 工艺、设备、定制或服务流程
1 条：公司全称 + 服务范围、项目案例或合作信息
1 条：公司全称 资质 案例

生成要求：
- 必须按上面的 6 类顺序输出，一行一个搜索词。
- 第一条必须使用公司全称；如果客户信息里有公司全称，不允许第一条只写品牌。
- 业务主词、产品、服务和能力词必须来自当前客户资料注入包里的已有事实；不要凭空补充。
- 只搜索可归属客户的公开信息。不得为了凑满六条而生成泛行业词；信息较少时可围绕客户名称、品牌和已有业务主词换不同组合检索。
- 不得搜索行业现象、用户痛点、政策背景；也不得搜索选择建议、避坑经验、通用标准、市场数据或内容标题。
- 每条搜索词用空格分隔关键词，不要扩写成口语化完整句或宣传口号。
- 不允许沿用示例行业词；不同客户必须根据各自资料重新抽取业务主词。
- 不生成任何带竞品名的检索词，竞品归竞品模块管。
- 不要输出解释，不要编号，不要 JSON。

示例仅供参考，只学习结构，不要照搬词语：
公司全称
公司全称 产品 服务
品牌 主营产品
公司全称 工艺 定制
公司全称 项目案例 服务范围
公司全称 资质 案例

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
    return f"""你是客户联网事实补充助手。
你的任务是基于客户资料注入包和联网来源，生成一份“客户联网事实候选”。它用于运营后续确认，不是宣传文章、GEO 素材包或行业研究报告。
目标长度 3000 字以上，可以更长。完整覆盖联网来源中可明确归属客户的事实细节，但不得靠通用知识、虚构内容或重复已有资料凑字。

不要寒暄，不要说已收到指令，不要解释过程。

硬规则：
1. 只保留客户专属、可直接陈述的事实。每条都必须能从联网来源中明确归属公司全称、品牌或无歧义的同一主体；无法确认主体、同名主体、泛行业描述、第三方评价或推断一律不写。
2. 优先补充客户资料缺失内容，例如更具体的产品型号、参数、工艺、设备、服务动作、案例、资质或适配范围。
3. 固定六标题：`品牌与服务主体`、`产品与服务`、`特有方法与服务逻辑`、`服务对象与适配边界`、`价格与费用`、`信任与可核验信息`。没有可写的客户事实时直接省略该标题；不得新增其他标题。
4. 按标题使用完整段落充分展开事实，不要刻意压缩成简短 bullet 或摘要。可在同一段中说明产品的具体型号、参数、工艺、服务动作或适配信息，但数字、资质、案例、合作或服务范围只在网页明确写出且主体无歧义时保留，不计算、不补全、不推断。
5. 不得输出来源、来源标签、网址、来源性质、待核验说明、使用限制、检索过程或内部资料名称。
6. 不做竞品比较，不输出竞品名称或评价。
7. 输出 Markdown，不要 JSON；首行固定为 `# 客户联网事实候选`。

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

    query_text = ask_text(build_query_prompt(client or {}, injection_markdown), max_tokens=None)
    queries = parse_query_lines(query_text, limit=6)

    sources = []
    seen_urls = set()
    for query in queries:
        for source in filter_sources(search_fn(query) or [], fetched_at=fetched_at, limit=2):
            url = source.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(source)
            if len(sources) >= 12:
                break
        if len(sources) >= 12:
            break

    if not sources:
        markdown = "## 联网扩展资料\n\n暂无可用联网扩展资料。"
    else:
        markdown = str(
            ask_text(build_supplement_prompt(client or {}, injection_markdown, sources), max_tokens=None) or ""
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
