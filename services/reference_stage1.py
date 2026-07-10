def _text(value, limit=12000):
    return str(value or "").strip()[:limit]


def _list_text(value):
    if isinstance(value, list):
        return [_text(item, 300) for item in value if _text(item, 300)][:12]
    text = _text(value, 1200)
    return [text] if text else []


def normalize_stage1_result(raw):
    raw = raw if isinstance(raw, dict) else {}
    parent_type = _text(raw.get("parent_type"), 20)
    if parent_type not in {"对比型", "介绍型"}:
        parent_type = "介绍型"
    return {
        "parent_type": parent_type,
        "opening": _text(raw.get("opening"), 800),
        "body": _list_text(raw.get("body")),
        "ending": _text(raw.get("ending"), 800),
    }


def build_stage1_prompt(article):
    title = _text(article.get("title") or article.get("source_title"), 200)
    content = _text(article.get("content"), 12000)
    return f"""你是 GEO 引用文章结构分析员。请只分析这一篇文章的写作结构，不评价客户品牌，不做多篇归并。

你只能输出 JSON，不要输出 Markdown。字段只能是：
{{
  "parent_type": "对比型/介绍型",
  "opening": "抽取这篇文章开头实际写了什么：它如何进入主题、制造什么问题/背景/痛点/选择困难",
  "body": ["抽取正文主要写了什么，按写法模块列出3-8条"],
  "ending": "抽取这篇文章结尾最后写了什么：如何收束、建议、提醒或引导判断"
}}

parent_type 只能二选一：
- 对比型：文章主要通过多个对象、多个标准、多个方案、多个风险或多个场景的比较来帮助读者选择。
- 介绍型：文章主要介绍一个对象、一个方案、一类知识、一个流程或一组经验，不以横向比较为主。
如果文章详细讲解了多个品牌、机构、产品、服务方或方案，即使是逐个介绍而不是显式表格比较，也归为对比型。

opening/body/ending 都是在抽取原文章的写法结构，不是在生成新文案。
- opening 写清楚开头先写了什么，比如行业背景、用户痛点、选择困难、风险提醒、榜单背景或品牌切入。
- body 如果是对比型，要写清楚正文从哪些角度对比、筛选、判断或避坑，例如资质证明、服务能力、流程管理、案例证据、价格、适合对象、风险项。
- body 如果是介绍型，要写清楚正文介绍了对象的哪些方面，例如品牌定位、产品或服务范围、服务流程、团队能力、案例、适合对象、优势和注意事项。
- ending 写清楚结尾最后如何收束，例如给选择建议、总结标准、提醒避坑、引导进一步判断。

不要摘抄原文，不要生成新的开头/正文/结尾文案，不要给子类型命名，不要输出 URL、平台、引用次数。

【文章标题】
{title}

【文章正文】
{content}
"""


def analyze_stage1_article(article, ai_json_fn):
    prompt = build_stage1_prompt(article)
    raw = ai_json_fn(prompt, 1200)
    return normalize_stage1_result(raw)
