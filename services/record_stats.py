from collections import defaultdict


def build_raw_platform_stats(records):
    records = list(records or [])
    platform_cnt = defaultdict(int)
    platform_articles = defaultdict(list)
    platform_positions = defaultdict(list)
    article_cnt = defaultdict(int)

    for rec in records:
        for ref in rec.get("refs", []):
            platform = ref.get("platform", "未知")
            url = ref.get("url", "")
            title = ref.get("title", "")
            position = ref.get("position", 0)
            platform_cnt[platform] += 1
            platform_positions[platform].append(position)
            if url:
                article_cnt[url] += 1
                platform_articles[platform].append({"title": title, "url": url})

    total = sum(platform_cnt.values()) or 1
    platform_weights = sorted([
        {
            "platform": platform,
            "count": count,
            "pct": round(count / total * 100, 1),
            "avg_position": round(sum(platform_positions[platform]) / len(platform_positions[platform]), 1),
            "sample_articles": list({a["url"]: a for a in platform_articles[platform]}.values())[:3],
        }
        for platform, count in platform_cnt.items()
    ], key=lambda x: x["count"], reverse=True)

    top_articles = []
    seen_urls = set()
    for rec in records:
        for ref in rec.get("refs", []):
            url = ref.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                top_articles.append({
                    "title": ref.get("title", ""),
                    "url": url,
                    "platform": ref.get("platform", ""),
                    "count": article_cnt[url],
                })
    top_articles = sorted(top_articles, key=lambda x: x["count"], reverse=True)[:20]

    return {
        "total_records": len(records),
        "total_refs": sum(platform_cnt.values()),
        "platform_weights": platform_weights,
        "top_articles": top_articles,
    }
