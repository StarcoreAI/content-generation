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
- 目标是找到三类 GEO 素材：品牌优势表达素材、人群痛点与决策语境、行业公共背景锚点。
- 重心是扩素材，不是补证据；不是为了核验客户资料真假，也不是为了做竞品对比。

搜索词结构：
1 条：公司全称 / 品牌公开信息
1 条：品牌 + 服务特色或模式介绍
2 条：人群痛点与决策语境，例如行业通用用户顾虑、避坑话题、选择标准讨论
2 条：行业公共背景锚点，例如政策时间、报名规则、官方数据，带年份、省份或地区限定

生成要求：
- 必须按上面的 6 类顺序输出，一行一个搜索词。
- 第一条必须使用公司全称；如果客户信息里有公司全称，不允许第一条只写品牌。
- 业务主词、服务特色、目标人群或行业背景必须来自当前客户资料注入包里的定位、主营产品、服务范围、核心业务或缺口提示。
- 品牌优势表达素材：围绕客户品牌自身的公开信息、服务特色、模式介绍、品牌公开露出；把资料包里“仅为客户自述”的优势方向搜出更多可写的表达角度，注意是找“怎么写”的素材，不是找证明。
- 人群痛点与决策语境：围绕行业通用的用户顾虑、避坑话题、选择标准讨论，例如“学历提升机构怎么选”“学历提升服务常见坑”；这是突出优势又不拉踩的关键原料。
- 行业公共背景锚点：围绕政策时间、报名规则、官方数据，必须尽量带年份、省份或地区限定，优先适合找到官方来源。
- 资料包末尾的“公开可查”清单只是参考输入之一，不再是唯一任务单；不要只围绕补证据生成搜索词。
- 突出相对优势的安全路径：优势要有对照物，但对照物用行业通用短板和用户顾虑，不用具体品牌；搜索词可以往行业乱象、用户吐槽、踩坑经验方向生成。
- 每条搜索词用空格分隔关键词，用户痛点和使用场景要写成适合搜索的短关键词组，不要扩写成口语化完整句。
- 不要生成口号型关键词，例如品牌理念、价值观短句、广告语、宣传 slogan；要改成可检索的服务动作或用户问题。
- 不允许沿用示例行业词；不同客户必须根据各自资料重新抽取业务主词。
- 不要搜索泛泛的公司简介。
- 不生成任何带竞品名的检索词，竞品归竞品模块管。
- 不要生成给“限制使用”表述找证据的词，例如“翼升学 98% 录取率”“品牌名 通过率”“品牌名 包过”。
- 不要输出解释，不要编号，不要 JSON。

示例仅供参考，只学习结构，不要照搬词语：
公司全称
品牌 业务主词 服务模式
学历提升机构 怎么选
学历提升服务 常见坑 报名后没人管
成人高考 2026 河北 报名规则 官方
自学考试 2026 山东 报名时间 官方

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
2. 这一步只扩素材：不做核验、不做冲突仲裁、不做洗白审查；不要把联网材料包装成已经核验的客户事实。
3. 重复内容降权：客户资料注入包里已经有的事实不要简单复述，但可以基于联网来源做场景化展开、传播角度扩写、GEO问答素材扩写。
4. 优势素材的整理姿势：写成“用户顾虑/行业现象 + 客户对应能力的表达角度”，例如“行业普遍痛点：报名后无人跟进 → 可用角度：强调全流程节点提醒”。
5. 不写成与任何具体品牌的对比句；检索结果里出现竞品名的，只取其中的中性行业信息，涉及褒贬一律不采，正文素材不要输出竞品名称。
6. 保留一件轻量的事：每条素材标来源 URL 和来源性质（官方/媒体/UGC/疑似投放），并直接写 URL。不要使用“来源1”“来源2”这类代称；任何段落都不要使用来源编号。
7. 数字类内容降档处理：来源不明的数字照收但标注来源性质，用不用、怎么用交给门禁和写作规则；扩展阶段不做取舍。
8. 行业公共背景只整理政策时间、报名规则、官方数据等锚点，必须写清年份、省份或地区和来源。
9. 输出 Markdown，不要 JSON。

建议结构：
## 联网补充摘要
## 1. 品牌公开信息与优势表达角度
（含“行业现象/用户顾虑 → 客户对应能力的可写角度”结构）
## 2. 人群痛点与决策语境
（用户真实顾虑、避坑话题、选择标准讨论）
## 3. 行业公共背景锚点
（政策时间、报名规则、官方数据，带年份省份和来源）
## 来源清单
每条写明：素材要点、来源 URL、来源性质（官方/媒体/UGC/疑似投放）、可用方式或限制。

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
