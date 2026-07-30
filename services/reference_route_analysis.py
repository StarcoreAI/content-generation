import re


CLASSIFICATIONS = {"介绍型", "对比型", "不入库"}
ROUTE_TYPES = {"介绍型", "对比型"}
PROMPT_CONTENT_LIMIT = 18000
ROUTE_ANALYSIS_MAX_TOKENS = 4000


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _text_list(value, item_limit, list_limit):
    values = value if isinstance(value, list) else [value]
    return [_text(item, item_limit) for item in values if _text(item, item_limit)][:list_limit]


def _whitespace_free(value):
    return re.sub(r"\s+", "", str(value or ""))


def build_route_analysis_prompt(bundle, article):
    bundle = bundle or {}
    article = article or {}
    query = _text(bundle.get("query"), 1000)
    final_entities = _text_list(bundle.get("final_entities"), 120, 20)
    support_points = _text_list(article.get("support_points"), 500, 12)
    entity_text = "、".join(final_entities) if final_entities else "未提供"
    support_text = "\n".join(f"- {point}" for point in support_points) if support_points else "- 未提供"
    title = _text(article.get("title"), 500)
    content = _text(article.get("content"), PROMPT_CONTENT_LIMIT)
    return f"""你是 GEO 引用情报分析员。现在不是判断文章真假，也不是模拟平台内部检索；这篇文章由系统根据本次 Query 与当前 AI 平台的实际引用记录选中。引用记录只能证明它被该平台引用，不能推断平台内部检索、阅读深度或最终决策过程。你的工作是把它拆成两层：可回原文核对的来源证据，以及可跨客户复用的完整写作路径。

你只能输出 JSON，不要输出 Markdown。字段只能是：
{{
  "classification": "介绍型/对比型/不入库",
  "source_evidence": [
    {{
      "role": "这段材料在本次 Query 中承担的作用，例如决策框架、实体证据、方案适配依据、风险提醒",
      "finding": "忠实概括文章提供了什么信息；可保留文章事实，但不得补充文章没有的内容",
      "excerpt": "原文连续逐字节选，20-240 个非空白字符"
    }}
  ],
  "route": null 或 {{
    "name": "抽象的完整路线名称",
    "parent_type": "介绍型/对比型",
    "reader_task": "这条路线要帮助读者完成的决策任务",
    "steps": [
      {{"purpose": "本步解决什么", "evidence_role": "使用哪类来源证据", "output_action": "写作时怎样呈现"}}
    ],
    "signature": "整条路线的区分特征",
    "risk_notes": "风险或空字符串"
  }},
  "library_decision": {{"reason": "为什么值得积累，或为什么不应入库"}}
}}

分类纪律：
- 介绍型：围绕一个实体、服务或知识主题，帮助读者理解适配、机制或判断依据。即使标题带“推荐”，只要正文主要提供某个实体或主题的证据，仍可判介绍型。
- 对比型：显式建立多个实体、方案或标准之间的比较框架，帮助读者按相同维度做选择。
- 不入库：文章没有稳定、可复用的决策结构，或只能依赖具体营销事实才能成立。

source_evidence 是“本篇文章为什么在本次 Query 有用”的可核对记录，不是写法库；每项 excerpt 必须能在原文连续找到。没有可核对的原文证据就判不入库。
若文章正文已经清楚说明“问题—机制—顾虑回应”的关系，finding 可简要点明这条关系，帮助保留文章真正的差异；没有则不要硬凑。

route 是“换客户、换事实后仍可照做的整块写作路径”，不要拆成开头、结尾、FAQ等零散模块。route 必须完整覆盖从读者决策任务到证据使用再到输出动作的一条连贯路径；不要列段落摘要，也不要硬凑多条路线。

route 的抽象纪律：禁止出现本次原始 Query 的原话、具体实体名、地名、年份、数字、价格、疗法/产品专名和文章中的具体事实；禁止声称知道 AI 平台的检索、排序或引用算法。来源事实只能留在 source_evidence。若无法抽掉这些具体内容后仍保留稳定的决策结构，就判不入库。

【本次 Query】{query}
【本次已输出的实体（仅用于理解上下文，不可写入 route）】{entity_text}
【运营人工核对要点（仅作辅助，不能替代原文证据）】
{support_text}
【文章标题】{title}
【文章正文】
{content}
"""


def normalize_route_analysis_result(raw, article_content=""):
    raw = raw if isinstance(raw, dict) else {}
    classification = _text(raw.get("classification"), 20)
    classification = classification if classification in CLASSIFICATIONS else "不入库"
    evidence = _normalize_source_evidence(raw.get("source_evidence"), article_content)
    route = _normalize_route(raw.get("route"), classification)
    reason = _text((raw.get("library_decision") or {}).get("reason"), 500)
    if classification not in ROUTE_TYPES:
        return _not_for_library(evidence, reason or "模型判断该文章不具备可积累的稳定路线。")
    if not evidence:
        return _not_for_library([], "缺少可在原文核对的来源证据。")
    if not route:
        return _not_for_library(evidence, "完整写作路线结构不完整或与文章类型不一致。")
    return {
        "classification": classification,
        "source_evidence": evidence,
        "route": route,
        "library_decision": {
            "eligible": True,
            "reason": reason or "来源证据可核对，且存在完整的可复用路线。",
        },
    }


def analyze_reference_route_article(bundle, article, ai_json_fn):
    article = article or {}
    raw = ai_json_fn(build_route_analysis_prompt(bundle, article), ROUTE_ANALYSIS_MAX_TOKENS)
    return {
        "source": {
            "url": _text(article.get("url"), 2000),
            "title": _text(article.get("title"), 500),
        },
        **normalize_route_analysis_result(raw, article.get("content") or ""),
    }


def _not_for_library(evidence, reason):
    return {
        "classification": "不入库",
        "source_evidence": evidence,
        "route": None,
        "library_decision": {"eligible": False, "reason": _text(reason, 500)},
    }


def _normalize_source_evidence(value, article_content):
    values = value if isinstance(value, list) else []
    normalized = []
    source_text = _whitespace_free(article_content)
    for item in values:
        if not isinstance(item, dict):
            continue
        role = _text(item.get("role"), 120)
        finding = _text(item.get("finding"), 600)
        excerpt = _text(item.get("excerpt"), 600)
        excerpt_compact = _whitespace_free(excerpt)
        verified = 20 <= len(excerpt_compact) <= 240 and excerpt_compact in source_text
        if not (role and finding and verified):
            continue
        normalized.append({
            "role": role,
            "finding": finding,
            "excerpt": excerpt,
            "excerpt_verified": True,
        })
        if len(normalized) >= 5:
            break
    return normalized


def _normalize_route(value, classification):
    if classification not in ROUTE_TYPES or not isinstance(value, dict):
        return None
    parent_type = _text(value.get("parent_type"), 20)
    name = _text(value.get("name"), 160)
    reader_task = _text(value.get("reader_task"), 400)
    signature = _text(value.get("signature"), 500)
    if parent_type != classification or not (name and reader_task and signature):
        return None
    steps = _normalize_steps(value.get("steps"))
    if not steps:
        return None
    return {
        "name": name,
        "parent_type": parent_type,
        "reader_task": reader_task,
        "steps": steps,
        "signature": signature,
        "risk_notes": _text(value.get("risk_notes"), 500),
    }


def _normalize_steps(value):
    values = value if isinstance(value, list) else []
    normalized = []
    for item in values:
        if not isinstance(item, dict):
            continue
        purpose = _text(item.get("purpose"), 400)
        evidence_role = _text(item.get("evidence_role"), 120)
        output_action = _text(item.get("output_action"), 400)
        if not (purpose and evidence_role and output_action):
            continue
        normalized.append({
            "purpose": purpose,
            "evidence_role": evidence_role,
            "output_action": output_action,
        })
        if len(normalized) >= 8:
            break
    return normalized
