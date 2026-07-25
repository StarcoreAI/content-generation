from collections import defaultdict
from datetime import date
import re
from urllib.parse import urlparse

from services.ref_articles import canonical_article_key


MULTI_PART_SUFFIXES = {
    "ac.uk", "co.jp", "co.uk", "com.au", "com.cn", "edu.cn", "gov.cn",
    "net.au", "net.cn", "org.au", "org.cn",
}


def source_domain(url, platform=""):
    """Return a normalized registrable domain, or the source-site label as fallback."""
    value = str(url or "").strip()
    try:
        parsed = urlparse(value if "://" in value or value.startswith("//") else f"//{value}")
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        host = ""
    if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host):
        labels = host.split(".")
        suffix = ".".join(labels[-2:])
        return ".".join(labels[-3:]) if suffix in MULTI_PART_SUFFIXES and len(labels) >= 3 else suffix
    return str(platform or "").strip()


def _iso_week(day):
    try:
        iso_year, iso_week, _ = date.fromisoformat(str(day or "")).isocalendar()
    except (TypeError, ValueError):
        return ""
    return f"{iso_year}-W{iso_week:02d}"


def build_source_trend(records):
    """Build weekly source-site shares for the latest twelve ISO weeks."""
    weekly_counts = defaultdict(lambda: defaultdict(int))
    for record in records or []:
        week = _iso_week(record.get("today"))
        if not week:
            continue
        for ref in record.get("refs") or []:
            if not isinstance(ref, dict):
                continue
            source = source_domain(ref.get("url"), ref.get("platform"))
            if source:
                weekly_counts[week][source] += 1

    weeks = sorted(weekly_counts)[-12:]
    if not weeks:
        return {"weeks": [], "series": []}

    totals = defaultdict(int)
    for week in weeks:
        for source, count in weekly_counts[week].items():
            totals[source] += count
    top_sources = [source for source, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:10]]
    other_sources = set(totals) - set(top_sources)

    def series_item(source, counts):
        return {
            "source": source,
            "total_count": sum(counts.get(week, 0) for week in weeks),
            "shares": [counts.get(week, 0) / sum(weekly_counts[week].values()) for week in weeks],
        }

    series = [series_item(source, {week: weekly_counts[week].get(source, 0) for week in weeks}) for source in top_sources]
    if other_sources:
        series.append(series_item("其他", {
            week: sum(weekly_counts[week].get(source, 0) for source in other_sources)
            for week in weeks
        }))
    return {"weeks": weeks, "series": series}


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
