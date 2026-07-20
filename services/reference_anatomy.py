import re


MODULE_TYPES = {"开头", "结尾", "FAQ段", "对比表", "其他"}
PARENT_TYPES = {"对比型", "介绍型"}
PROMPT_CONTENT_LIMIT = 12000
STAGE1_MAX_TOKENS = 1200


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _text_list(value, item_limit, list_limit):
    if not isinstance(value, list):
        value = [value]
    return [_text(item, item_limit) for item in value if _text(item, item_limit)][:list_limit]


def _whitespace_free(value):
    return re.sub(r"\s+", "", str(value or ""))


def _risk_marks(article):
    marks = _text_list((article or {}).get("risk_marks"), 80, 12)
    return "、".join(marks) if marks else "无"


def build_anatomy_prompt(article):
    article = article or {}
    title = _text(article.get("title") or article.get("source_title"), 200)
    content = _text(article.get("content"), PROMPT_CONTENT_LIMIT)
    return f"""你是 GEO 引用文章套路分析员。这篇文章被 AI 平台高频引用，且已确认值得学习。请从中抽取“可复用的写作套路”——换一个品牌、换一批事实仍然能照做的结构性做法。你在为一个跨文章积累的写法库供货，抽的是“形状”，不是“内容”。

你只能输出 JSON，不要输出 Markdown。字段只能是：
{{
  "skeleton": null 或 {{
    "name": "临时名，概括骨架核心特征，如'观察分类型''白皮书打分型'",
    "parent_type": "对比型/介绍型",
    "sections": ["按顺序每节一句话功能"],
    "signature": "识别特征与基调，一两句：什么让这个骨架区别于其他骨架，整体写作姿态是什么",
    "risk_notes": "该骨架的风险提示，没有则空字符串"
  }},
  "modules": [
    {{
      "type": "开头/结尾/FAQ段/对比表/其他",
      "name": "临时名，如'痛点连问型'",
      "pattern": "套路描述：写清结构动作，让别人不看原文也能照做；如果它有特别的生效机制（如每个问句都是用户会对AI说的话），用一句话点明",
      "excerpt": "原文逐字节选，30-150字，作为示范",
      "risk_notes": "没有则空字符串"
    }}
  ],
  "citability_features": ["文章具备的引用友好特征，短标签"]
}}

parent_type 判定：对比型是通过多个机构、方案、标准或路径帮助读者做选择；介绍型是围绕一个品牌、服务或知识主题展开。详细讲解多个机构、逐个介绍而非显式对比，也归为对比型。

抽取纪律（比数量更重要）：
- 宁缺毋滥。最多 1 个骨架、3 个段落模式，这是上限不是配额：骨架平庸就输出 null，没有值得学的模式就输出空数组。“开头引出主题”“结尾总结全文”这类任何文章都成立的描述是废话，禁止输出。
- 择优不遍历。段落模式只挑这篇文章里最有辨识度、最值得模仿的，不要逐段描述。
- 套路是形状不是内容。sections、pattern、signature 里禁止出现具体机构名、品牌名、具体数字、具体年份和地名，这些只能出现在 excerpt 里。自检判据：把品牌和事实全部换掉，套路描述依然成立，才算合格。
- sections 是功能序列不是段落摘要。“逐家侧重：每家=定位一句话+服务重点+适配人群”是功能；“介绍了某机构的课程”是摘要，禁止摘要式写法。
- excerpt 必须是原文逐字节选，禁止改写、拼接、编造。

citability_features 从这些方向找（有则列出，没有不要硬凑）：标题含年份/地域/决策词、官方时间或数字锚点、横向对比表、FAQ且问题为用户原话句式、数据来源声明、分人群建议、免责或广告标注。

【前置定性给出的风险标记】{_risk_marks(article)}
如有风险标记，判断它落在哪个骨架或模式上，写进对应的 risk_notes（例如拉踩通常落在“竞品短板拆解”类模块）。带风险的结构仍然要抽，标注“手段禁用，仅结构可参考”即可，不要因为有风险就放弃抽取。

【颗粒度示例】（来自其他行业，只参考颗粒度，禁止照抄内容）
骨架示例：name=避坑清单型；sections=["还原用户常见踩坑场景","给出3-5条可核验的判断标准，每条带'怎么验证'","按预算和需求分人群给建议","FAQ 4-6问，问题用用户原话句式","回到'按标准选、不按名气选'收束"]；signature=每条标准都配验证方法，全文不推荐具体商家，中性不排名
模式示例：type=开头；name=踩坑场景还原型；pattern=用2-3句还原一个具体踩坑场景，点出这类坑的普遍性，末句声明本文只给判断标准不做推荐

【文章标题】{title}
【文章正文】
{content}
"""


def normalize_anatomy_result(raw, article_content=""):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "skeleton": _normalize_skeleton(raw.get("skeleton")),
        "modules": _normalize_modules(raw.get("modules"), article_content),
        "citability_features": _text_list(raw.get("citability_features"), 80, 12),
    }


def analyze_article_anatomy(article, ai_json_fn):
    article = article or {}
    raw = ai_json_fn(build_anatomy_prompt(article), STAGE1_MAX_TOKENS)
    return {
        "source": source_from_article(article),
        **normalize_anatomy_result(raw, article.get("content") or ""),
    }


def source_from_article(article):
    article = article or {}
    try:
        citation_count = max(0, int(article.get("citation_count") or 0))
    except (TypeError, ValueError):
        citation_count = 0
    return {
        "url": _text(article.get("url"), 2000),
        "title": _text(article.get("title") or article.get("source_title"), 500),
        "group_id": _text(article.get("group_id"), 200),
        "published_at": _text(article.get("published_at"), 40),
        "platform": _text(article.get("platform"), 80),
        "citation_count": citation_count,
    }


def _normalize_skeleton(value):
    value = value if isinstance(value, dict) else {}
    name = _text(value.get("name"), 120)
    if not name:
        return None
    parent_type = _text(value.get("parent_type"), 20)
    return {
        "name": name,
        "parent_type": parent_type if parent_type in PARENT_TYPES else "介绍型",
        "sections": _text_list(value.get("sections"), 240, 8),
        "signature": _text(value.get("signature"), 300),
        "risk_notes": _text(value.get("risk_notes"), 300),
    }


def _normalize_excerpt(value, article_content):
    excerpt = str(value or "").strip()
    excerpt_length = len(_whitespace_free(excerpt))
    if not 30 <= excerpt_length <= 150:
        return "", False
    return excerpt, _whitespace_free(excerpt) in _whitespace_free(article_content)


def _normalize_modules(value, article_content):
    modules = value if isinstance(value, list) else []
    normalized = []
    for item in modules:
        if not isinstance(item, dict):
            continue
        pattern = _text(item.get("pattern"), 1000)
        if not pattern:
            continue
        module_type = _text(item.get("type"), 20)
        excerpt, excerpt_verified = _normalize_excerpt(item.get("excerpt"), article_content)
        normalized.append({
            "type": module_type if module_type in MODULE_TYPES else "其他",
            "name": _text(item.get("name"), 120),
            "pattern": pattern,
            "excerpt": excerpt,
            "excerpt_verified": excerpt_verified,
            "risk_notes": _text(item.get("risk_notes"), 300),
        })
        if len(normalized) >= 3:
            break
    return normalized
