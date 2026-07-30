from collections import defaultdict

from services.ref_articles import canonical_article_key
from services.ref_platforms import normalize_ref_platform


def _avg(values):
    return round(sum(values) / len(values), 1) if values else 0


def build_daily_ref_stats(records, platform_names=None, platform_order=None):
    records = list(records or [])
    platform_names = platform_names or {}
    order_index = {platform: idx for idx, platform in enumerate(platform_order or [])}

    platform_cnt = defaultdict(int)
    article_cnt = defaultdict(int)
    article_info = {}
    ai_record_cnt = defaultdict(int)
    ai_article_cnt = defaultdict(lambda: defaultdict(int))
    ai_article_info = defaultdict(dict)
    total_refs = 0

    for rec in records:
        ai_platform = rec.get("source_platform", "doubao") or "doubao"
        ai_record_cnt[ai_platform] += 1
        for ref in rec.get("refs", []):
            url = ref.get("url", "")
            platform = normalize_ref_platform(ref.get("platform", ""), url)
            title = ref.get("title", "")
            position = ref.get("position", 0)
            platform_cnt[platform] += 1
            total_refs += 1
            key = canonical_article_key(title, url)
            if not key:
                continue

            article_cnt[key] += 1
            if key not in article_info:
                article_info[key] = {
                    "title": title,
                    "url": url,
                    "platform": platform,
                    "positions": [],
                    "ai_platforms": set(),
                }
            article_info[key]["positions"].append(position)
            article_info[key]["ai_platforms"].add(ai_platform)

            ai_article_cnt[ai_platform][key] += 1
            if key not in ai_article_info[ai_platform]:
                ai_article_info[ai_platform][key] = {
                    "title": title,
                    "url": url,
                    "platform": platform,
                    "positions": [],
                }
            ai_article_info[ai_platform][key]["positions"].append(position)

    platform_weights = sorted([
        {
            "platform": platform,
            "count": count,
            "pct": round(count / total_refs * 100, 1) if total_refs else 0,
        }
        for platform, count in platform_cnt.items()
    ], key=lambda x: x["count"], reverse=True)

    top_articles = sorted([
        {
            "title": info["title"],
            "url": info["url"],
            "platform": info["platform"],
            "count": article_cnt[key],
            "avg_position": _avg(info["positions"]),
            "ai_platforms": sorted(info["ai_platforms"]),
        }
        for key, info in article_info.items()
    ], key=lambda x: x["count"], reverse=True)[:20]

    top_articles_by_ai = []
    for ai_platform, counts in ai_article_cnt.items():
        articles = sorted([
            {
                "title": info["title"],
                "url": info["url"],
                "platform": info["platform"],
                "count": counts[key],
                "avg_position": _avg(info["positions"]),
                "ai_platforms": [ai_platform],
            }
            for key, info in ai_article_info[ai_platform].items()
        ], key=lambda x: x["count"], reverse=True)[:20]
        top_articles_by_ai.append({
            "source_platform": ai_platform,
            "platform_name": platform_names.get(ai_platform, ai_platform),
            "total_records": ai_record_cnt[ai_platform],
            "top_articles": articles,
        })

    default_order = len(order_index)
    top_articles_by_ai.sort(
        key=lambda item: order_index.get(item["source_platform"], default_order)
    )

    return {
        "total_records": len(records),
        "total_refs": total_refs,
        "platform_weights": platform_weights,
        "top_articles": top_articles,
        "top_articles_by_ai": top_articles_by_ai,
    }
