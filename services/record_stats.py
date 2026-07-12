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


def build_precise_diagnosis(records):
    q_data = defaultdict(lambda: {"total": 0, "mentioned": 0, "geo_sum": 0, "ref_count": 0})
    for record in records or []:
        question = record.get("question", "")
        if not question:
            continue
        q_data[question]["total"] += 1
        if record.get("brand_mentioned"):
            q_data[question]["mentioned"] += 1
        q_data[question]["geo_sum"] += record.get("geo_score", 0) or 0
        q_data[question]["ref_count"] += len(record.get("refs", []))

    result = []
    for question, data in q_data.items():
        total = data["total"]
        mention_rate = round(data["mentioned"] / total * 100, 1) if total else 0
        avg_geo = round(data["geo_sum"] / total, 1) if total else 0
        avg_refs = round(data["ref_count"] / total, 1) if total else 0
        opportunity = round((100 - mention_rate) * min(total, 10) / 10, 1)
        result.append({
            "question": question,
            "total": total,
            "mention_rate": mention_rate,
            "avg_geo": avg_geo,
            "avg_refs": avg_refs,
            "opportunity": opportunity,
        })

    result.sort(key=lambda x: x["opportunity"], reverse=True)
    return result


def filter_records_by_question(records, question_filter):
    return [record for record in records if question_filter in record.get("question", "")]


def build_precise_question_ref_stats(records):
    article_cnt = defaultdict(int)
    article_info = {}
    platform_cnt = defaultdict(int)

    for record in records or []:
        seen = set()
        for ref in record.get("refs", []):
            url = ref.get("url", "")
            title = ref.get("title", "")
            platform = ref.get("platform", "未知")
            key = url or title
            if not key:
                continue
            article_cnt[key] += 1
            if key not in article_info:
                article_info[key] = {"title": title, "url": url, "platform": platform}
            if platform not in seen:
                platform_cnt[platform] += 1
                seen.add(platform)

    top_articles = sorted([
        {
            "title": article_info[key]["title"],
            "url": article_info[key]["url"],
            "platform": article_info[key]["platform"],
            "count": article_cnt[key],
        }
        for key in article_info
    ], key=lambda x: x["count"], reverse=True)[:15]

    total_refs = sum(platform_cnt.values()) or 1
    platform_dist = sorted([
        {"platform": platform, "count": count, "pct": round(count / total_refs * 100, 1)}
        for platform, count in platform_cnt.items()
    ], key=lambda x: x["count"], reverse=True)

    return {
        "top_articles": top_articles,
        "platform_dist": platform_dist,
    }
