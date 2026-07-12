from collections import defaultdict


def build_raw_deep_analysis_context(records):
    records = list(records or [])
    platform_cnt = defaultdict(int)
    for rec in records:
        for ref in rec.get("refs", []):
            platform_cnt[ref.get("platform", "未知")] += 1

    total_refs = sum(platform_cnt.values()) or 1
    platform_weights = [
        {"platform": platform, "count": count, "pct": round(count / total_refs * 100, 1)}
        for platform, count in sorted(platform_cnt.items(), key=lambda x: x[1], reverse=True)[:6]
    ]
    mentioned = [record for record in records if record.get("brand_mentioned")]
    avg_score = round(sum(record.get("geo_score", 0) for record in records) / len(records), 1) if records else 0

    sample_refs = []
    seen = set()
    for rec in records:
        for ref in rec.get("refs", [])[:3]:
            title = ref.get("title", "")
            if title and title not in seen:
                seen.add(title)
                sample_refs.append(f"【{ref.get('platform', '')}】{title}")
            if len(sample_refs) >= 15:
                break
        if len(sample_refs) >= 15:
            break

    return {
        "platform_weights": platform_weights,
        "mentioned": mentioned,
        "avg_score": avg_score,
        "sample_refs": sample_refs,
    }


def extract_content_instruction(report):
    if "CONTENT_INSTRUCTION_START" not in report or "CONTENT_INSTRUCTION_END" not in report:
        return ""
    start = report.find("CONTENT_INSTRUCTION_START") + len("CONTENT_INSTRUCTION_START")
    end = report.find("CONTENT_INSTRUCTION_END")
    return report[start:end].strip()


def build_daily_deep_analysis_context(records):
    records = list(records or [])
    platform_data = defaultdict(lambda: {
        "articles": [],
        "count": 0,
        "positions": [],
        "brand_mentioned": 0,
        "total": 0,
    })

    for rec in records:
        brand_mentioned = rec.get("brand_mentioned", False)
        for ref in rec.get("refs", []):
            platform = ref.get("platform", "未知")
            url = ref.get("url", "")
            title = ref.get("title", "")
            position = ref.get("position", 0)
            platform_data[platform]["count"] += 1
            platform_data[platform]["positions"].append(position)
            platform_data[platform]["total"] += 1
            if brand_mentioned:
                platform_data[platform]["brand_mentioned"] += 1

            key = url or title
            existing = [
                article for article in platform_data[platform]["articles"]
                if (article["url"] or article["title"]) == key
            ]
            if existing:
                existing[0]["count"] += 1
            else:
                platform_data[platform]["articles"].append({
                    "title": title,
                    "url": url,
                    "platform": platform,
                    "count": 1,
                    "position": position,
                })

    total_refs = sum(data["count"] for data in platform_data.values()) or 1
    total_records = len(records)
    platform_stats = []
    for platform, data in platform_data.items():
        top_articles = sorted(data["articles"], key=lambda x: x["count"], reverse=True)[:5]
        avg_position = round(sum(data["positions"]) / len(data["positions"]), 1) if data["positions"] else 0
        weight_pct = round(data["count"] / total_refs * 100, 1)
        mention_rate = round(data["brand_mentioned"] / max(data["total"], 1) * 100, 1)
        platform_stats.append({
            "platform": platform,
            "count": data["count"],
            "weight_pct": weight_pct,
            "avg_position": avg_position,
            "mention_rate": mention_rate,
            "top_articles": top_articles,
            "is_emerging": data["count"] >= 2 and avg_position <= 5,
        })
    platform_stats.sort(key=lambda x: x["count"], reverse=True)
    top8_platforms = platform_stats[:8]

    mentioned = [record for record in records if record.get("brand_mentioned")]
    mention_rate = round(len(mentioned) / total_records * 100, 1) if total_records else 0
    avg_score = round(sum(record.get("geo_score", 0) for record in records) / total_records, 1) if total_records else 0

    parts = []
    for platform in top8_platforms:
        article = platform["top_articles"][0]["title"][:30] if platform["top_articles"] else "无"
        parts.append(
            "【" + platform["platform"] + "】权重" + str(platform["weight_pct"]) +
            "% | 平均排名第" + str(platform["avg_position"]) +
            "位 | 品牌提及率" + str(platform["mention_rate"]) +
            "% | 高频文章：" + article
        )
    emerging = [platform for platform in platform_stats if platform.get("is_emerging")]

    return {
        "total_refs": total_refs,
        "total_records": total_records,
        "platform_stats": platform_stats,
        "top8_platforms": top8_platforms,
        "mentioned": mentioned,
        "mention_rate": mention_rate,
        "avg_score": avg_score,
        "emerging": emerging,
        "emerging_str": "、".join([platform["platform"] for platform in emerging]) if emerging else "暂无",
        "platform_summary": chr(10).join(parts),
    }
