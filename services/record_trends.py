from collections import defaultdict
from datetime import date

from services.ref_articles import canonical_article_key


def build_question_trend(records, question):
    """Build per-AI-platform daily brand-mention states for one exact question."""
    daily = {}
    for record in records or []:
        if record.get("question") != question:
            continue
        platform = record.get("source_platform") or "doubao"
        day = record.get("today") or ""
        key = (platform, day)
        if key not in daily:
            daily[key] = {"date": day, "mentioned": False, "records": 0}
        daily[key]["mentioned"] = daily[key]["mentioned"] or bool(record.get("brand_mentioned"))
        daily[key]["records"] += 1

    result = defaultdict(list)
    for (platform, _), item in daily.items():
        result[platform].append(item)
    return {
        platform: sorted(items, key=lambda item: item["date"])
        for platform, items in sorted(result.items())
    }


def build_article_pool(records, anchor_date=None):
    """Build the selected day's new and retained cited-article pool."""
    records = list(records or [])
    anchor_date = anchor_date or max((record.get("today") or "" for record in records), default="")
    if not anchor_date:
        return {"date": "", "new_entries": [], "retained": []}

    articles = {}
    for record in records:
        day = record.get("today") or ""
        platform = record.get("source_platform") or "doubao"
        for ref in record.get("refs") or []:
            if not isinstance(ref, dict):
                continue
            title = ref.get("title") or ""
            url = ref.get("url") or ""
            key = canonical_article_key(title, url)
            if not key:
                continue
            article = articles.setdefault(key, {
                "title": title,
                "url": url,
                "first_seen_date": day,
                "total_count": 0,
                "today_count": 0,
                "ai_platforms": set(),
            })
            article["first_seen_date"] = min(article["first_seen_date"], day)
            article["total_count"] += 1
            article["ai_platforms"].add(platform)
            if day == anchor_date:
                article["today_count"] += 1

    new_entries = []
    retained = []
    for article in articles.values():
        if not article["today_count"]:
            continue
        item = {
            "title": article["title"],
            "url": article["url"],
            "today_count": article["today_count"],
            "total_count": article["total_count"],
            "first_seen_date": article["first_seen_date"],
            "ai_platforms": sorted(article["ai_platforms"]),
        }
        if article["first_seen_date"] == anchor_date:
            new_entries.append(item)
        elif article["first_seen_date"] < anchor_date:
            item["retained_days"] = (date.fromisoformat(anchor_date) - date.fromisoformat(article["first_seen_date"])).days
            retained.append(item)

    new_entries.sort(key=lambda item: (-item["today_count"], item["title"]))
    retained.sort(key=lambda item: (-item["retained_days"], item["title"]))
    return {
        "date": anchor_date,
        "new_entries": new_entries[:20],
        "retained": retained[:20],
    }
