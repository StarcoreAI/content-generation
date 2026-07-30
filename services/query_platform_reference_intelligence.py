"""Query × single-AI-platform citation candidate selection."""
import random

from services.ref_articles import canonical_article_key


def select_query_platform_articles(records, query, ai_platform, seed):
    """Keep the top cited article, then draw one weighted candidate from ranks 2-5."""
    query = str(query or "").strip()
    ai_platform = str(ai_platform or "").strip()
    if not query:
        raise ValueError("query_required")
    if not ai_platform:
        raise ValueError("ai_platform_required")
    grouped = {}
    for record in records or []:
        if str(record.get("question") or "").strip() != query:
            continue
        if str(record.get("source_platform") or "").strip() != ai_platform:
            continue
        for ref in record.get("refs") or []:
            if not isinstance(ref, dict):
                continue
            title = str(ref.get("title") or "").strip()
            url = str(ref.get("url") or "").strip()
            key = canonical_article_key(title, url)
            if not key:
                continue
            item = grouped.setdefault(key, {
                "canonical_key": key,
                "title": title or url,
                "url": url,
                "citation_count": 0,
            })
            item["citation_count"] += 1
    ranked = sorted(grouped.values(), key=lambda item: (-item["citation_count"], item["url"], item["title"]))
    anchor = dict(ranked[0]) if ranked else None
    weighted_pool = [dict(item, weight=item["citation_count"]) for item in ranked[1:5]]
    selected = [dict(anchor, selection="anchor", rank=1)] if anchor else []
    if weighted_pool:
        picked = random.Random(int(seed)).choices(
            weighted_pool,
            weights=[item["weight"] for item in weighted_pool],
            k=1,
        )[0]
        selected.append(dict(picked, selection="weighted_random", rank=ranked.index(next(
            item for item in ranked if item["canonical_key"] == picked["canonical_key"]
        )) + 1))
    return {
        "query": query,
        "ai_platform": ai_platform,
        "seed": int(seed),
        "ranked": [dict(item, rank=index) for index, item in enumerate(ranked, 1)],
        "anchor": anchor,
        "weighted_pool": weighted_pool,
        "selected": selected,
    }
