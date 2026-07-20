import hashlib
import re

from services.ref_articles import canonical_article_key


MIN_CONTENT_CHARS = 200
ERROR_TITLES = {"403 forbidden", "404 not found", "just a moment..."}
BLOCKED_PAGE_MARKERS = {
    "captcha",
    "verification required",
    "access denied",
    "人机验证",
    "安全验证",
    "访问被拒绝",
}


def prequalify_reference_articles(articles, similarity_threshold=0.82):
    candidates = []
    rejected = []
    for article in articles or []:
        article = dict(article or {})
        signals = structural_signals(article.get("content"))
        reasons = hard_reject_reasons(article)
        if reasons:
            rejected.append({"article": article, "reasons": reasons, "signals": signals})
        else:
            candidates.append({"article": article, "signals": signals})

    groups = _group_candidates(candidates, similarity_threshold)
    eligible = []
    group_summaries = []
    for group in groups:
        members = group["members"]
        representative = max(members, key=lambda item: (_citation_count(item["article"]), len(str(item["article"].get("content") or ""))))
        urls = [str(item["article"].get("url") or "").strip() for item in members]
        citation_count = sum(_citation_count(item["article"]) for item in members)
        eligible.append({
            "article": representative["article"],
            "group_id": group["id"],
            "group_size": len(members),
            "group_urls": urls,
            "group_citation_count": citation_count,
            "signals": representative["signals"],
        })
        group_summaries.append({
            "group_id": group["id"],
            "group_size": len(members),
            "group_urls": urls,
            "group_citation_count": citation_count,
        })
    return {"eligible": eligible, "rejected": rejected, "groups": group_summaries}


def hard_reject_reasons(article):
    if not article.get("ok"):
        return ["fetch_failed"]
    title = str(article.get("title") or article.get("source_title") or "").strip().lower()
    if title in ERROR_TITLES:
        return ["error_title"]
    content = str(article.get("content") or "").strip()
    if len(content) < MIN_CONTENT_CHARS:
        return ["content_too_short"]
    content_lower = content.lower()
    if any(marker in content_lower for marker in BLOCKED_PAGE_MARKERS):
        return ["blocked_page"]
    return []


def structural_signals(content):
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    normalized_lines = [re.sub(r"\s+", " ", line).lower() for line in lines]
    meaningful = [line for line in lines if len(line) >= 20]
    headings = [line for line in lines if re.match(r"^(#{1,6}\s+|(?:\d+|[一二三四五六七八九十]+)[、.])", line)]
    duplicate_ratio = 0.0
    if normalized_lines:
        duplicate_ratio = round(1 - len(set(normalized_lines)) / len(normalized_lines), 3)
    return {
        "content_chars": len(str(content or "").strip()),
        "meaningful_paragraphs": len(meaningful),
        "heading_count": len(headings),
        "duplicate_line_ratio": duplicate_ratio,
    }


def _group_candidates(candidates, similarity_threshold):
    groups = []
    for candidate in candidates:
        article = candidate["article"]
        article_key = canonical_article_key(article.get("title"), article.get("url"))
        shingles = _shingles(article.get("content"))
        matching_group = next((group for group in groups if _matches_group(group, article_key, shingles, similarity_threshold)), None)
        if matching_group is None:
            fingerprint = _content_fingerprint(article.get("content"))
            matching_group = {
                "id": f"group_{fingerprint}",
                "canonical_keys": set(),
                "shingles": shingles,
                "members": [],
            }
            groups.append(matching_group)
        if article_key:
            matching_group["canonical_keys"].add(article_key)
        matching_group["members"].append(candidate)
    return groups


def _matches_group(group, article_key, shingles, similarity_threshold):
    if article_key and article_key in group["canonical_keys"]:
        return True
    return _shingle_similarity(group["shingles"], shingles) >= similarity_threshold


def _shingles(content, width=5, step=3):
    text = re.sub(r"[\W_]+", "", str(content or "").lower(), flags=re.UNICODE)
    if len(text) <= width:
        return {text} if text else set()
    return {text[index:index + width] for index in range(0, len(text) - width + 1, step)}


def _shingle_similarity(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _content_fingerprint(content):
    normalized = re.sub(r"\s+", "", str(content or "").lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _citation_count(article):
    try:
        return max(0, int(article.get("citation_count") or 0))
    except (TypeError, ValueError):
        return 0
