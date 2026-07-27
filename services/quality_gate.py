"""Fail-open quality checks for generated content."""
import json
import re
from copy import deepcopy
from pathlib import Path


BANNED_WORDS_PATH = Path(__file__).resolve().parents[1] / "data" / "quality_gate" / "banned_words.json"
SHINGLE_SIMILARITY_THRESHOLD = 0.80
DEFAULT_BANNED_WORDS = {
    "overpromise": ["包过", "保录取", "保过", "治愈", "根治", "保证通过"],
    "absolute": ["全国第一", "全国领先", "最大规模", "最好的机构", "顶级", "唯一", "首选", "最推荐", "第一梯队", "第二梯队", "第三梯队", "谨慎考察"],
    "marketing": ["逆龄", "冻龄", "秒变", "神器", "秒杀", "立省", "限时抢"],
}
INDUSTRY_BANNED_WORDS = {
    "medical": ["100%", "零风险", "永久", "根治", "逆龄", "年轻十岁", "无副作用"],
    "education": ["保证录取", "100%上岸", "必中", "内部渠道", "保送", "第一名", "最强师资", "王牌老师", "全国第一"],
    "finance": ["稳赚", "无风险", "保本", "高收益", "稳赚不赔", "内幕消息", "保证盈利"],
}
INDUSTRY_ALIASES = {
    "medical": ("医疗", "医美", "医院", "medical", "healthcare"),
    "education": ("教育", "升学", "培训", "education"),
    "finance": ("金融", "理财", "投资", "finance", "financial"),
}
NON_COMPETITOR_MARKDOWN_HEADERS = {
    "基本信息", "业务范围", "服务规模与覆盖", "发展历程", "服务模式与特色", "主要产品", "服务规模",
    "机构定位与介绍", "团队与规模", "领导与规模", "网络与平台", "财务数据", "规模与学生",
    "学科与专业", "教育学院", "业务线索", "规模与市场覆盖", "品牌与荣誉",
}


def load_banned_words(path=BANNED_WORDS_PATH):
    words = {category: list(values) for category, values in DEFAULT_BANNED_WORDS.items()}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            extra = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return words
    if isinstance(extra, list):
        extra = {"custom": extra}
    if not isinstance(extra, dict):
        return words
    for category, values in extra.items():
        if not isinstance(values, list):
            continue
        target = words.setdefault(str(category), [])
        for value in values:
            phrase = str(value or "").strip()
            if phrase and phrase not in target:
                target.append(phrase)
    return words


BANNED_WORDS = load_banned_words()
CAUTIONARY_CONTEXT_MARKERS = ("不要", "不应", "不得", "勿", "警惕", "谨慎", "虚假", "违规", "骗", "宣称", "声称", "所谓", "承诺")
POLICY_FIELDS = ("banned_words", "must_do", "must_not_do", "review_requirements")
DEFAULT_REVIEW_REQUIREMENTS = "核查数字和专有主张是否能回溯到合法资料来源；检查竞品是否公平呈现、是否存在过度承诺或标题营销，以及是否复读竞品资料中的强主张。竞品强主张复读仅作低置信度提示。"


def _words_from_groups(groups):
    result = []
    for values in (groups or {}).values():
        for value in values or []:
            phrase = str(value or "").strip()
            if phrase and phrase not in result:
                result.append(phrase)
    return result


def _policy_section(value=None):
    value = value if isinstance(value, dict) else {}
    def items(name):
        raw = value.get(name, [])
        raw = raw if isinstance(raw, list) else []
        return [str(item).strip() for item in raw if str(item).strip()]
    return {
        "banned_words": items("banned_words"),
        "must_do": items("must_do"),
        "must_not_do": items("must_not_do"),
        "review_requirements": str(value.get("review_requirements") or "").strip(),
    }


def default_quality_policy():
    return {
        "common": {
            "banned_words": _words_from_groups(BANNED_WORDS),
            "must_do": [],
            "must_not_do": [],
            "review_requirements": DEFAULT_REVIEW_REQUIREMENTS,
        },
        "industries": {
            key: {"banned_words": list(words), "must_do": [], "must_not_do": [], "review_requirements": ""}
            for key, words in INDUSTRY_BANNED_WORDS.items()
        },
    }


def load_quality_policy(path):
    policy = default_quality_policy()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return policy
    if not isinstance(raw, dict):
        return policy
    policy["common"] = _policy_section({**policy["common"], **(raw.get("common") or {})})
    industries = raw.get("industries") if isinstance(raw.get("industries"), dict) else {}
    for name, section in industries.items():
        key = str(name or "").strip()
        if key:
            policy["industries"][key] = _policy_section(section)
    return policy


def save_quality_policy(path, policy):
    normalized = {
        "common": _policy_section((policy or {}).get("common")),
        "industries": {
            str(name).strip(): _policy_section(section)
            for name, section in ((policy or {}).get("industries") or {}).items()
            if str(name or "").strip()
        },
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def quality_policy_industry_key(industry):
    value = str(industry or "").strip()
    lower = value.lower()
    for key, aliases in INDUSTRY_ALIASES.items():
        if any(alias.lower() in lower for alias in aliases):
            return key
    return re.split(r"[·/|,，]", value, maxsplit=1)[0].strip()


def effective_quality_policy(policy, industry=""):
    policy = policy if isinstance(policy, dict) else default_quality_policy()
    common = _policy_section(policy.get("common"))
    key = quality_policy_industry_key(industry)
    industry_section = _policy_section((policy.get("industries") or {}).get(key))
    result = deepcopy(common)
    for field in ("banned_words", "must_do", "must_not_do"):
        result[field] = list(dict.fromkeys(common[field] + industry_section[field]))
    result["review_requirements"] = "\n".join(
        item for item in (common["review_requirements"], industry_section["review_requirements"]) if item
    )
    result["industry_key"] = key
    return result


def quality_gate_competitor_names(markdown, provided_names=None):
    """Return unique institution candidates from explicit names and Markdown headings."""
    names = provided_names or []
    if isinstance(names, str):
        names = re.split(r"[\n,，]+", names)
    candidates = list(names) if isinstance(names, list) else []
    for line in str(markdown or "").splitlines():
        match = re.match(r"^\s{0,3}##(?!#)\s+(.+?)\s*$", line)
        if not match:
            continue
        name = re.sub(r"^(?:竞品(?:名称)?\s*[:：]\s*)", "", match.group(1)).strip()
        name = re.split(r"[（(]", name, maxsplit=1)[0].strip(" *#:-：")
        if name and "竞品资料" not in name and name not in {"竞品", "竞品信息", "竞品公开资料整理包"} | NON_COMPETITOR_MARKDOWN_HEADERS:
            candidates.append(name)
    result = []
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def _check(check_id, layer, passed, severity, evidence=None, **extra):
    return {
        "check_id": check_id,
        "layer": layer,
        "passed": bool(passed),
        "severity": severity,
        "evidence": list(evidence or []),
        **extra,
    }


def _industry_banned_words(industry):
    value = str(industry or "").strip().lower()
    for key, aliases in INDUSTRY_ALIASES.items():
        if any(alias.lower() in value for alias in aliases):
            return INDUSTRY_BANNED_WORDS[key]
    return []


def check_banned_words(article_content, banned_words=None, industry=""):
    text = str(article_content or "")
    if banned_words is None:
        phrases = effective_quality_policy(default_quality_policy(), industry)["banned_words"]
    elif isinstance(banned_words, dict):
        phrases = _words_from_groups(banned_words)
    else:
        phrases = [str(item).strip() for item in banned_words if str(item).strip()]
    hits = []
    cautionary_hits = []
    for phrase in phrases:
        start = text.find(phrase) if phrase else -1
        while start >= 0:
            target = cautionary_hits if _has_cautionary_context(text, phrase, start) else hits
            if phrase not in target:
                target.append(phrase)
            start = text.find(phrase, start + len(phrase))
    evidence = hits + [phrase for phrase in cautionary_hits if phrase not in hits]
    return _check(
        "banned_words", "code", not evidence, "warn", evidence,
        cautionary_context=bool(cautionary_hits),
        cautionary_evidence=cautionary_hits,
    )


def _has_cautionary_context(text, phrase, start):
    end = start + len(phrase)
    window = text[max(0, start - 20):min(len(text), end + 20)]
    if start and end < len(text) and text[start - 1] in "“\"'「『" and text[end] in "”\"'」』":
        return True
    if any(marker in window for marker in CAUTIONARY_CONTEXT_MARKERS if marker != "承诺"):
        return True
    return "承诺" in window and any(marker in window for marker in ("不要", "不应", "不得", "勿", "警惕", "谨慎", "虚假", "违规", "骗", "宣称", "声称", "所谓"))


def check_title_brand(article_title, client_brand, competitor_names):
    title = str(article_title or "")
    names = [str(client_brand or "").strip()] + [str(name or "").strip() for name in competitor_names or []]
    hits = []
    for name in names:
        if name and name in title and name not in hits:
            hits.append(name)
    return _check("title_brand", "code", not hits, "warn", hits)


def check_meta_discourse(article_content):
    text = str(article_content or "")
    phrases = [
        "作为AI", "以下是", "【", "】", "占位", "补充位", "待运营补充", "本节保留结构位置",
        "竞品", "客户资料", "客户提供资料", "竞品资料", "资料包", "现有资料", "资料未提供", "资料中未提供", "资料缺失", "未提供",
    ]
    hits = [phrase for phrase in phrases if phrase in text]
    return _check("meta_discourse", "code", not hits, "warn", hits)


def _shingles(value, size=5):
    text = re.sub(r"\s+", "", str(value or ""))
    if not text:
        return set()
    if len(text) <= size:
        return {text}
    return {text[index:index + size] for index in range(len(text) - size + 1)}


def check_shingle_duplicate(article_content, recent_articles, threshold=SHINGLE_SIMILARITY_THRESHOLD):
    current = _shingles(article_content)
    if not current:
        return _check("shingle_duplicate", "code", True, "warn")
    best_score, best_text = 0.0, ""
    for article in recent_articles or []:
        text = article.get("content", "") if isinstance(article, dict) else article
        other = _shingles(text)
        if not other:
            continue
        score = len(current & other) / len(current | other)
        if score > best_score:
            best_score, best_text = score, str(text or "")
    evidence = []
    if best_score >= threshold:
        evidence.append(f"similarity={best_score:.2f}: {best_text[:120]}")
    return _check("shingle_duplicate", "code", not evidence, "warn", evidence)


def _quality_gate_prompt(article_title, article_content, brief, provenance, competitor_names, competitor_markdown,
                         customer_material_text="", content_upload_text="", policy=None):
    policy = _policy_section(policy)
    rules = "\n".join([
        policy["review_requirements"],
        "必须做：" + "；".join(policy["must_do"] or ["无"]),
        "不能做：" + "；".join(policy["must_not_do"] or ["无"]),
    ])
    return f"""你是内容质量门禁。只输出 JSON，不要 Markdown。
业务审核要求（由运营维护，只按下列要求审核）：
{rules}
输出 schema：{{\"checks\":[{{\"check_id\":\"fact_traceability|competitor_fairness|semantic_marketing|competitor_claim_repetition\",\"passed\":true,\"evidence\":[\"命中片段\"]}}]}}。

标题：{article_title}
正文：{article_content}
简报：{json.dumps(brief or {}, ensure_ascii=False)}
溯源：{json.dumps(provenance or {}, ensure_ascii=False)}
合法可回溯来源（客户资料包）：{customer_material_text or '无'}
合法可回溯来源（内容上传资料）：{content_upload_text or '无'}
本次竞品名称：{json.dumps(competitor_names or [], ensure_ascii=False)}
竞品 Markdown：{competitor_markdown or '无'}
"""


def _parse_llm_checks(raw):
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            raise ValueError("empty_llm_response")
        raw = re.sub(r"^```json\s*|^```\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        raw = json.loads(raw)
    checks = raw.get("checks") if isinstance(raw, dict) else raw
    if not isinstance(checks, list):
        raise ValueError("invalid_llm_response")
    normalized = []
    for item in checks:
        if not isinstance(item, dict) or not str(item.get("check_id") or "").strip():
            raise ValueError("invalid_llm_check")
        check_id = str(item["check_id"]).strip()
        normalized.append(_check(
            check_id,
            "llm",
            bool(item.get("passed")),
            "warn",
            item.get("evidence") if isinstance(item.get("evidence"), list) else [str(item.get("evidence") or "")],
            **({"low_confidence": True} if check_id == "competitor_claim_repetition" else {}),
        ))
    return normalized


def _failed_llm_check(exc):
    return _check("llm_response", "llm", False, "warn", [str(exc) or type(exc).__name__])


def run_quality_gate(article_title, article_content, brief, provenance, *, client_brand, competitor_names,
                     competitor_markdown, recent_articles, ai_json_fn, customer_material_text="", content_upload_text="", industry="", policy=None):
    """Run deterministic checks first, then a non-blocking injected LLM review."""
    try:
        code_layer = [
            check_banned_words(
                article_content,
                (policy or effective_quality_policy(default_quality_policy(), industry))["banned_words"],
            ),
            check_title_brand(article_title, client_brand, competitor_names),
            check_meta_discourse(article_content),
            check_shingle_duplicate(article_content, recent_articles),
        ]
    except Exception as exc:  # Gate failures must never discard a generated draft.
        code_layer = [_check("quality_gate_internal", "code", False, "warn", [str(exc) or type(exc).__name__])]

    try:
        active_policy = policy or effective_quality_policy(default_quality_policy(), industry)
        llm_layer = _parse_llm_checks(ai_json_fn(
            _quality_gate_prompt(
                article_title, article_content, brief, provenance, competitor_names, competitor_markdown,
                customer_material_text, content_upload_text, active_policy,
            ),
            4000,
        ))
        llm_status = "passed"
    except Exception as exc:
        llm_layer = [_failed_llm_check(exc)]
        llm_status = "failed"

    has_warning = any(not item["passed"] for item in code_layer + llm_layer) or llm_status == "failed"
    verdict = "warn" if has_warning else "pass"
    return {
        "passed": verdict == "pass",
        "verdict": verdict,
        "code_layer": code_layer,
        "llm_layer": llm_layer,
        "llm_layer_status": llm_status,
    }
