"""Fail-open quality checks for generated content."""
import json
import re
from pathlib import Path


BANNED_WORDS_PATH = Path(__file__).resolve().parents[1] / "data" / "quality_gate" / "banned_words.json"
SHINGLE_SIMILARITY_THRESHOLD = 0.80
DEFAULT_BANNED_WORDS = {
    "overpromise": ["100%", "包过", "保录取", "保过", "治愈", "根治", "保证通过"],
    "absolute": ["全国第一", "最大规模", "最好的机构", "顶级", "首选", "最推荐", "第一梯队", "第二梯队", "第三梯队", "谨慎考察"],
    "marketing": ["逆龄", "冻龄", "秒杀", "立省", "限时抢"],
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


def quality_gate_competitor_names(markdown, provided_names=None):
    """Return unique institution candidates from explicit names and Markdown headings."""
    names = provided_names or []
    if isinstance(names, str):
        names = re.split(r"[\n,，]+", names)
    candidates = list(names) if isinstance(names, list) else []
    for line in str(markdown or "").splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if not match:
            continue
        name = re.sub(r"^(?:竞品(?:名称)?\s*[:：]\s*)", "", match.group(1)).strip()
        name = re.split(r"[（(]", name, maxsplit=1)[0].strip(" *#:-：")
        if name and "竞品资料" not in name and name not in {"竞品", "竞品信息", "竞品公开资料整理包"}:
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


def check_banned_words(article_content, banned_words=None):
    text = str(article_content or "")
    banned_words = banned_words or BANNED_WORDS
    hits = []
    cautionary_hits = []
    for values in banned_words.values():
        for phrase in values or []:
            phrase = str(phrase or "").strip()
            start = text.find(phrase) if phrase else -1
            while start >= 0:
                target = cautionary_hits if _has_cautionary_context(text, phrase, start) else hits
                if phrase not in target:
                    target.append(phrase)
                start = text.find(phrase, start + len(phrase))
    evidence = hits + [phrase for phrase in cautionary_hits if phrase not in hits]
    return _check(
        "banned_words", "code", not evidence, "block" if hits else "warn", evidence,
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
    return _check("title_brand", "code", not hits, "block", hits)


def _parent_type(brief, provenance):
    for source in (brief, provenance):
        if not isinstance(source, dict):
            continue
        value = source.get("parent_type")
        if value:
            return str(value)
        sample = source.get("sample") or {}
        if isinstance(sample, dict) and sample.get("parent_type"):
            return str(sample["parent_type"])
    return ""


def check_comparison_presence(article_content, brief, provenance, competitor_names):
    if _parent_type(brief, provenance) != "对比型":
        return _check("comparison_presence", "code", True, "block")
    text = str(article_content or "")
    hits = []
    for name in competitor_names or []:
        name = str(name or "").strip()
        if name and name in text and name not in hits:
            hits.append(name)
    return _check("comparison_presence", "code", len(hits) >= 2, "block", hits)


def check_meta_discourse(article_content):
    text = str(article_content or "")
    phrases = [
        "作为AI", "以下是", "【", "】", "占位", "补充位", "待运营补充", "本节保留结构位置",
        "竞品", "客户资料", "客户提供资料", "竞品资料", "资料包", "现有资料", "资料未提供", "资料中未提供", "资料缺失", "未提供",
    ]
    hits = [phrase for phrase in phrases if phrase in text]
    return _check("meta_discourse", "code", not hits, "block", hits)


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
                         customer_material_text="", content_upload_text=""):
    return f"""你是内容质量门禁。只输出 JSON，不要 Markdown。
检查文章中的数字和专有主张是否能回溯到简报、客户资料包或内容上传资料任一合法来源，点名拉踩或竞品不平等呈现、词表漏掉的过度承诺/最高级/标题营销，以及竞品资料中的强主张复读。
竞品强主张复读仅作低置信度提示，不能阻断入库。
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
                     competitor_markdown, recent_articles, ai_json_fn, customer_material_text="", content_upload_text=""):
    """Run deterministic checks first, then a non-blocking injected LLM review."""
    try:
        code_layer = [
            check_banned_words(article_content),
            check_title_brand(article_title, client_brand, competitor_names),
            check_comparison_presence(article_content, brief, provenance, competitor_names),
            check_meta_discourse(article_content),
            check_shingle_duplicate(article_content, recent_articles),
        ]
    except Exception as exc:  # Gate failures must never discard a generated draft.
        code_layer = [_check("quality_gate_internal", "code", False, "warn", [str(exc) or type(exc).__name__])]

    code_blocked = any(not item["passed"] and item["severity"] == "block" for item in code_layer)
    if not code_blocked:
        try:
            llm_layer = _parse_llm_checks(ai_json_fn(
                _quality_gate_prompt(
                    article_title, article_content, brief, provenance, competitor_names, competitor_markdown,
                    customer_material_text, content_upload_text,
                ),
                4000,
            ))
            llm_status = "passed"
        except Exception as exc:
            llm_layer = [_failed_llm_check(exc)]
            llm_status = "failed"
    else:
        llm_layer = []
        llm_status = "skipped"

    has_warning = any(not item["passed"] for item in code_layer + llm_layer) or llm_status == "failed"
    verdict = "blocked" if code_blocked else "warn" if has_warning else "pass"
    return {
        "passed": verdict == "pass",
        "verdict": verdict,
        "code_layer": code_layer,
        "llm_layer": llm_layer,
        "llm_layer_status": llm_status,
    }
