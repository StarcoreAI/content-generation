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


def _valid_date(day):
    try:
        return date.fromisoformat(str(day or "")).isoformat()
    except (TypeError, ValueError):
        return ""


def build_source_trend(records):
    """Build source-site shares for the latest seven actual capture dates."""
    daily_counts = defaultdict(lambda: defaultdict(int))
    for record in records or []:
        day = _valid_date(record.get("today"))
        if not day:
            continue
        daily_counts[day]
        for ref in record.get("refs") or []:
            if not isinstance(ref, dict):
                continue
            source = source_domain(ref.get("url"), ref.get("platform"))
            if source:
                daily_counts[day][source] += 1

    dates = sorted(daily_counts)[-7:]
    if not dates:
        return {"dates": [], "series": []}

    totals = defaultdict(int)
    for day in dates:
        for source, count in daily_counts[day].items():
            totals[source] += count
    top_sources = [source for source, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:5]]
    other_sources = set(totals) - set(top_sources)

    def series_item(source, counts):
        return {
            "source": source,
            "total_count": sum(counts.get(day, 0) for day in dates),
            "shares": [
                counts.get(day, 0) / total if (total := sum(daily_counts[day].values())) else 0
                for day in dates
            ],
        }

    series = [series_item(source, {day: daily_counts[day].get(source, 0) for day in dates}) for source in top_sources]
    if other_sources:
        series.append(series_item("其他", {
            day: sum(daily_counts[day].get(source, 0) for source in other_sources)
            for day in dates
        }))
    return {"dates": dates, "series": series}


def build_group_mention_trend(records, questions, platform=""):
    """Build daily group mention rates from distinct crawl-task results."""
    questions = list(dict.fromkeys(question for question in questions or [] if question))
    selected_platform = "" if platform == "all" else (platform or "")
    states = {}
    for index, record in enumerate(records or []):
        day = _valid_date(record.get("today"))
        question = record.get("question") or ""
        source_platform = record.get("source_platform") or "doubao"
        if not day or question not in questions or (selected_platform and source_platform != selected_platform):
            continue
        task_key = record.get("task_id") or record.get("id") or f"record-{index}"
        key = (day, question, source_platform, task_key)
        states[key] = states.get(key, False) or bool(record.get("brand_mentioned"))

    dates = sorted({day for day, _, _, _ in states})[-7:]
    overall = []
    question_rows = []
    for day in dates:
        daily_states = [mentioned for (record_day, _, _, _), mentioned in states.items() if record_day == day]
        overall.append({"mentioned": sum(daily_states), "total": len(daily_states)})
    for question in questions:
        values = []
        for day in dates:
            daily_states = [
                mentioned for (record_day, record_question, _, _), mentioned in states.items()
                if record_day == day and record_question == question
            ]
            values.append({"mentioned": sum(daily_states), "total": len(daily_states)})
        question_rows.append({"question": question, "values": values})
    return {"dates": dates, "overall": overall, "questions": question_rows}


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


def build_question_article_list(records):
    """Aggregate cited articles from the records of one exact question."""
    articles = {}
    total_refs = 0
    for record in records or []:
        ai_platform = record.get("source_platform") or "doubao"
        for ref in record.get("refs") or []:
            if not isinstance(ref, dict):
                continue
            title = ref.get("title") or ""
            url = ref.get("url") or ""
            key = canonical_article_key(title, url)
            if not key:
                continue
            total_refs += 1
            article = articles.setdefault(key, {
                "title": title,
                "url": url,
                "count": 0,
                "source_platforms": set(),
                "ai_platforms": set(),
            })
            article["count"] += 1
            if ref.get("platform"):
                article["source_platforms"].add(ref["platform"])
            article["ai_platforms"].add(ai_platform)

    rows = [{
        "title": item["title"],
        "url": item["url"],
        "count": item["count"],
        "source_platforms": sorted(item["source_platforms"]),
        "ai_platforms": sorted(item["ai_platforms"]),
    } for item in articles.values()]
    rows.sort(key=lambda item: (-item["count"], item["title"], item["url"]))
    return {"total_records": len(records or []), "total_refs": total_refs, "articles": rows[:50]}


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
