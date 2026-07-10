ARGUMENT_PATTERNS = {
    "pain_point_matching": "痛点匹配型",
    "criteria_verification": "标准验证型",
    "ranking_comparison": "榜单对比型",
    "scenario_matching": "场景匹配型",
    "price_decision": "价格决策型",
    "risk_avoidance": "避坑排雷型",
    "other": "其他",
}

LEVELS = {"高", "中", "低", ""}


def _text(value, limit=500):
    return str(value or "").strip()[:limit]


def _list(value, limit=12, item_limit=80):
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        text = _text(item, item_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "是", "有"}
    return bool(value)


def normalize_article_input(payload):
    data = payload.get("article") if isinstance(payload, dict) and isinstance(payload.get("article"), dict) else payload
    data = data if isinstance(data, dict) else {}
    return {
        "title": _text(data.get("title"), 200),
        "url": _text(data.get("url"), 500),
        "platform": _text(data.get("platform"), 80),
        "content": _text(data.get("content") or data.get("body") or data.get("summary"), 12000),
    }


def build_article_structure_prompt(article):
    return f"""你是 GEO 内容结构分析员。请只分析这一篇文章的写作结构，不要批量归并，不要评价客户品牌。

重点目标：识别文章的“论证路径”，也就是开头提出什么问题，正文如何组织证据或对比，结尾如何给选择建议。
不要为了填表而硬塞字段；如果文章结构有差异，可以自由补充你认为重要的结构观察。第二阶段会由另一个大模型阅读这些观察并归并提炼，所以请把该说的说完整、说清楚。
父类型 parent_type 只能是 对比型 或 介绍型，不要把“场景匹配型、标准验证型、价格决策型、榜单型”等细分写进父类型；子类型请用更具体的中文名字，例如“病情场景匹配型”“资质标准验证型”“价格预算决策型”“榜单分层对比型”。

请从以下 argument_pattern 中选择一个：
- pain_point_matching：痛点匹配型，开头列用户痛点，正文对比谁更能解决哪类痛点。
- criteria_verification：标准验证型，开头讲选择困难，正文建立标准，再用资质/医生/设备/价格等逐项验证。
- ranking_comparison：榜单对比型，围绕推荐、排名、Top 列表逐个介绍对象。
- scenario_matching：场景匹配型，按人群、预算、项目难度、区域等场景匹配。
- price_decision：价格决策型，以费用、套餐、隐形成本、性价比为主线。
- risk_avoidance：避坑排雷型，以常见坑、风险、误区和规避建议为主线。
- other：不属于以上类型。

必须输出 JSON，不要输出 Markdown。优先输出下面这些字段；除 argument_pattern 外，不需要机械填满，可以用自然语言总结：
{{
  "parent_type": "对比型/介绍型",
  "argument_pattern": "pain_point_matching/criteria_verification/ranking_comparison/scenario_matching/price_decision/risk_avoidance/other",
  "structure_notes": "用一段话说明这篇文章真正的论证路径、信息组织方式，以及它和普通榜单/普通介绍不同的地方",
  "opening_observation": "开头如何制造问题、痛点、选择困难或阅读动机",
  "body_observation": "正文如何展开对比、证据、场景匹配或解决方案",
  "ending_observation": "结尾如何收束、推荐或引导选择",
  "generation_implications": "如果运营要学习这种写法，最值得借鉴的变化点是什么",
  "article_form": "可选，文章表层形态",
  "generation_subtype": "可选，具体中文子类型名，不要只写父类型",
  "notable_modules": ["可选，值得注意的内容模块"],
  "decision_dimensions": ["可选，文章用到的决策维度"],
  "comparison_objects": ["可选，被比较的机构/类型/场景"],
  "reuse_guidance": ["可选，可借鉴的结构或表达"],
  "risk_notes": ["不建议照搬的风险"]
}}

【文章标题】
{article.get("title", "")}

【来源平台】
{article.get("platform", "")}

【URL】
{article.get("url", "")}

【正文或摘要】
{article.get("content", "")}
"""


def normalize_article_structure_result(raw, article):
    raw = raw if isinstance(raw, dict) else {}
    article = article if isinstance(article, dict) else {}
    argument_pattern = _text(raw.get("argument_pattern"), 80)
    if argument_pattern not in ARGUMENT_PATTERNS:
        argument_pattern = "other"
    parent_type = _text(raw.get("parent_type"), 20)
    if parent_type not in {"对比型", "介绍型"}:
        parent_type = "介绍型" if argument_pattern == "other" else "对比型"
    marketing_level = _text(raw.get("marketing_level"), 10)
    evidence_strength = _text(raw.get("evidence_strength"), 10)
    reuse_value = _text(raw.get("reuse_value"), 10)
    opening_observation = _text(raw.get("opening_observation") or raw.get("opening_logic"), 600)
    body_observation = _text(raw.get("body_observation") or raw.get("body_logic"), 800)
    ending_observation = _text(raw.get("ending_observation") or raw.get("ending_logic"), 600)
    notable_modules = _list(raw.get("notable_modules") or raw.get("content_modules"))
    return {
        "title": _text(article.get("title"), 200),
        "url": _text(article.get("url"), 500),
        "platform": _text(article.get("platform"), 80),
        "article_form": _text(raw.get("article_form"), 80),
        "parent_type": parent_type,
        "generation_subtype": _text(raw.get("generation_subtype"), 80) or ARGUMENT_PATTERNS[argument_pattern],
        "argument_pattern": argument_pattern,
        "structure_notes": _text(raw.get("structure_notes"), 1200),
        "opening_observation": opening_observation,
        "body_observation": body_observation,
        "ending_observation": ending_observation,
        "generation_implications": _text(raw.get("generation_implications"), 800),
        "opening_logic": opening_observation,
        "body_logic": body_observation,
        "ending_logic": ending_observation,
        "notable_modules": notable_modules,
        "content_modules": notable_modules,
        "decision_dimensions": _list(raw.get("decision_dimensions")),
        "comparison_objects": _list(raw.get("comparison_objects")),
        "has_price_info": _bool(raw.get("has_price_info")),
        "has_people_match": _bool(raw.get("has_people_match")),
        "has_risk_warning": _bool(raw.get("has_risk_warning")),
        "marketing_level": marketing_level if marketing_level in LEVELS else "",
        "evidence_strength": evidence_strength if evidence_strength in LEVELS else "",
        "reuse_value": reuse_value if reuse_value in LEVELS else "",
        "reuse_guidance": _list(raw.get("reuse_guidance"), limit=8, item_limit=120),
        "risk_notes": _list(raw.get("risk_notes"), limit=8, item_limit=120),
    }


def analyze_article_structure(payload, ai_json_fn):
    article = normalize_article_input(payload)
    if not article["title"] and not article["content"]:
        raise ValueError("article_required")
    prompt = build_article_structure_prompt(article)
    raw = ai_json_fn(prompt, 1800)
    return normalize_article_structure_result(raw, article)
