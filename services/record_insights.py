from collections import defaultdict

from services.ref_articles import canonical_article_key
from services.ref_platforms import normalize_ref_platform


AI_PLATFORM_NAMES = {
    "deepseek": "DeepSeek",
    "yuanbao": "元宝",
    "qwen": "千问",
    "doubao": "豆包",
}


def _pct(part, total):
    return round(part / total * 100, 1) if total else 0


def _contains_entity(text, entity_name):
    return str(entity_name or "").strip().lower() in str(text or "").lower()


def _pick_selected_competitors(mentioned_entities):
    selected = []
    for idx in (0, 2):
        if len(mentioned_entities) > idx:
            name = mentioned_entities[idx].get("name", "")
            if name and name not in selected:
                selected.append(name)
    return selected


def _record_mentions_brand(record):
    if record.get("brand_mentioned"):
        return True
    brand = str(record.get("brand") or "").strip()
    if not brand:
        return False
    if brand in str(record.get("answer") or ""):
        return True
    for entity in record.get("mentioned_entities") or []:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        evidence = str(entity.get("evidence") or "").strip()
        if name == brand or brand in name or name in brand:
            return True
        if brand in evidence:
            return True
    return False


def _build_competitor_articles(records, top_articles, selected_competitors):
    if not selected_competitors:
        return [], []

    top_article_map = {
        canonical_article_key(article.get("title", ""), article.get("url", "")): article
        for article in top_articles[:20]
    }
    top_article_map = {key: article for key, article in top_article_map.items() if key}
    if not top_article_map:
        return [], []

    strong_candidates = {}
    weak_candidates = {}

    def ensure_candidate(bucket, key, article):
        if key not in bucket:
            bucket[key] = {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "platform": article.get("platform", ""),
                "count": article.get("count", 0),
                "ai_platforms": set(article.get("ai_platforms") or []),
                "questions": set(article.get("questions") or []),
                "related_entities": set(),
                "match_types": set(),
                "cooccurrence_count": 0,
            }
        return bucket[key]

    for key, article in top_article_map.items():
        article_text = f"{article.get('title', '')} {article.get('url', '')}"
        for entity_name in selected_competitors:
            if _contains_entity(article_text, entity_name):
                candidate = ensure_candidate(strong_candidates, key, article)
                candidate["related_entities"].add(entity_name)
                candidate["match_types"].add("标题/URL命中")

    for rec in records:
        answer = rec.get("answer", "")
        entity_names = {
            str(entity.get("name", "")).strip()
            for entity in rec.get("mentioned_entities") or []
            if isinstance(entity, dict) and str(entity.get("name", "")).strip()
        }
        matched_entities = [
            entity_name for entity_name in selected_competitors
            if entity_name in entity_names or _contains_entity(answer, entity_name)
        ]
        if not matched_entities:
            continue
        for ref in rec.get("refs") or []:
            key = canonical_article_key(ref.get("title", ""), ref.get("url", ""))
            article = top_article_map.get(key)
            if not article:
                continue
            candidate = ensure_candidate(weak_candidates, key, article)
            candidate["cooccurrence_count"] += 1
            if rec.get("source_platform"):
                candidate["ai_platforms"].add(rec.get("source_platform"))
            if rec.get("question"):
                candidate["questions"].add(rec.get("question"))
            for entity_name in matched_entities:
                candidate["related_entities"].add(entity_name)
                candidate["match_types"].add("回答共现")

    def format_candidates(candidates, include_weak_reason=False):
        result = []
        for item in candidates.values():
            match_types = sorted(
                item["match_types"],
                key=lambda x: {"标题/URL命中": 0, "正文命中": 1, "回答共现": 2}.get(x, 9),
            )
            reason_prefix = "高频引用 Top20 中与目标竞品存在"
            if include_weak_reason:
                reason_prefix = "弱关联：同一条 AI 回答提到目标竞品并引用该文章，尚未证明正文提到竞品"
            result.append({
                "title": item["title"],
                "url": item["url"],
                "platform": item["platform"],
                "count": item["count"],
                "ai_platforms": sorted(item["ai_platforms"]),
                "questions": sorted(item["questions"])[:5],
                "related_entities": sorted(item["related_entities"], key=selected_competitors.index),
                "match_types": match_types,
                "cooccurrence_count": item["cooccurrence_count"],
                "reason": reason_prefix if include_weak_reason else reason_prefix + "、".join(match_types),
            })
        result.sort(key=lambda x: (
            -x["count"],
            0 if "标题/URL命中" in x["match_types"] else 1,
            -x["cooccurrence_count"],
            x["title"],
        ))
        return result

    strong = format_candidates(strong_candidates)
    weak = format_candidates(weak_candidates, include_weak_reason=True)
    strong_keys = set(strong_candidates.keys())
    weak = [
        item for item in weak
        if canonical_article_key(item.get("title", ""), item.get("url", "")) not in strong_keys
    ]
    return strong, weak


def merge_body_hit_results(competitor_articles, body_hit_results, selected_competitors):
    articles_by_key = {
        canonical_article_key(article.get("title", ""), article.get("url", "")): dict(article)
        for article in competitor_articles or []
    }
    for hit in body_hit_results or []:
        if hit.get("status") != "matched" or not hit.get("matched_entities"):
            continue
        key = canonical_article_key(hit.get("title", ""), hit.get("url", ""))
        if not key:
            continue
        article = articles_by_key.get(key, {
            "title": hit.get("title", ""),
            "url": hit.get("url", ""),
            "platform": hit.get("platform", ""),
            "count": hit.get("count", 0),
            "ai_platforms": hit.get("ai_platforms", []),
            "questions": [],
            "related_entities": [],
            "match_types": [],
            "cooccurrence_count": 0,
            "reason": "",
        })
        related = set(article.get("related_entities") or [])
        for entity_name in hit.get("matched_entities") or []:
            if entity_name in selected_competitors:
                related.add(entity_name)
        article["related_entities"] = sorted(related, key=selected_competitors.index)
        match_types = set(article.get("match_types") or [])
        match_types.add("正文命中")
        article["match_types"] = sorted(
            match_types,
            key=lambda x: {"标题/URL命中": 0, "正文命中": 1, "回答共现": 2}.get(x, 9),
        )
        article["body_hit_status"] = "matched"
        article["body_evidence"] = hit.get("evidence", "")
        article["reason"] = "高频引用 Top20 中与目标竞品存在" + "、".join(article["match_types"])
        articles_by_key[key] = article

    result = list(articles_by_key.values())
    result.sort(key=lambda x: (
        -x["count"],
        0 if "标题/URL命中" in x["match_types"] else 1,
        0 if "正文命中" in x["match_types"] else 1,
        -x["cooccurrence_count"],
        x["title"],
    ))
    return result


def build_record_insights(records):
    records = list(records or [])
    platform_data = defaultdict(lambda: {
        "source_platform": "",
        "platform_name": "",
        "total_records": 0,
        "total_refs": 0,
        "brand_mentions": 0,
        "zero_ref_records": 0,
        "empty_answer_records": 0,
        "ref_platform_counts": defaultdict(int),
    })
    article_data = {}
    source_data = defaultdict(lambda: {"platform": "", "count": 0, "record_ids": set()})
    entity_data = {}

    total_refs = 0
    brand_mentions = 0
    zero_ref_records = 0
    empty_answer_records = 0

    for rec in records:
        source_platform = rec.get("source_platform", "doubao") or "doubao"
        refs = rec.get("refs") or []
        record_id = rec.get("id", "")
        answer = rec.get("answer") or ""
        brand_mentioned = _record_mentions_brand(rec)

        pdata = platform_data[source_platform]
        pdata["source_platform"] = source_platform
        pdata["platform_name"] = AI_PLATFORM_NAMES.get(source_platform, source_platform)
        pdata["total_records"] += 1
        pdata["total_refs"] += len(refs)
        if brand_mentioned:
            pdata["brand_mentions"] += 1
            brand_mentions += 1
        if not refs:
            pdata["zero_ref_records"] += 1
            zero_ref_records += 1
        if not answer.strip():
            pdata["empty_answer_records"] += 1
            empty_answer_records += 1
        total_refs += len(refs)

        for ref in refs:
            title = ref.get("title", "")
            url = ref.get("url", "")
            ref_platform = normalize_ref_platform(ref.get("platform", ""), url)
            article_key = canonical_article_key(title, url)
            if article_key:
                if article_key not in article_data:
                    article_data[article_key] = {
                        "title": title,
                        "url": url,
                        "platform": ref_platform,
                        "count": 0,
                        "ai_platforms": set(),
                        "questions": set(),
                    }
                article_data[article_key]["count"] += 1
                article_data[article_key]["ai_platforms"].add(source_platform)
                if rec.get("question"):
                    article_data[article_key]["questions"].add(rec.get("question"))

            sdata = source_data[ref_platform]
            sdata["platform"] = ref_platform
            sdata["count"] += 1
            if record_id:
                sdata["record_ids"].add(record_id)
            pdata["ref_platform_counts"][ref_platform] += 1

        for entity in rec.get("mentioned_entities") or []:
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name", "")).strip()
            if not name:
                continue
            if name not in entity_data:
                entity_data[name] = {
                    "name": name,
                    "type": entity.get("type", ""),
                    "count": 0,
                    "sentiment_counts": defaultdict(int),
                    "evidence_samples": [],
                    "ai_platforms": set(),
                }
            edata = entity_data[name]
            edata["count"] += 1
            edata["sentiment_counts"][entity.get("sentiment", "neutral") or "neutral"] += 1
            if entity.get("evidence") and len(edata["evidence_samples"]) < 3:
                edata["evidence_samples"].append(entity.get("evidence"))
            edata["ai_platforms"].add(source_platform)

    ai_platforms = []
    for item in platform_data.values():
        total = item["total_records"]
        item["mention_rate"] = _pct(item["brand_mentions"], total)
        item["zero_ref_rate"] = _pct(item["zero_ref_records"], total)
        ref_total = item["total_refs"]
        item["ref_platforms"] = sorted([
            {
                "platform": platform,
                "count": count,
                "pct": _pct(count, ref_total),
            }
            for platform, count in item["ref_platform_counts"].items()
        ], key=lambda x: x["count"], reverse=True)[:12]
        del item["ref_platform_counts"]
        ai_platforms.append(item)
    ai_platforms.sort(key=lambda x: (x["total_refs"], x["total_records"]), reverse=True)

    top_articles = []
    for item in article_data.values():
        top_articles.append({
            "title": item["title"],
            "url": item["url"],
            "platform": item["platform"],
            "count": item["count"],
            "ai_platforms": sorted(item["ai_platforms"]),
            "questions": sorted(item["questions"])[:5],
        })
    top_articles.sort(key=lambda x: x["count"], reverse=True)

    top_ref_platforms = []
    for item in source_data.values():
        top_ref_platforms.append({
            "platform": item["platform"],
            "count": item["count"],
            "record_count": len(item["record_ids"]),
        })
    top_ref_platforms.sort(key=lambda x: x["count"], reverse=True)

    mentioned_entities = []
    for item in entity_data.values():
        mentioned_entities.append({
            "name": item["name"],
            "type": item["type"],
            "count": item["count"],
            "sentiment_counts": dict(item["sentiment_counts"]),
            "evidence_samples": item["evidence_samples"],
            "ai_platforms": sorted(item["ai_platforms"]),
        })
    mentioned_entities.sort(key=lambda x: x["count"], reverse=True)
    selected_competitors = _pick_selected_competitors(mentioned_entities)
    competitor_articles, weak_competitor_articles = _build_competitor_articles(
        records,
        top_articles,
        selected_competitors,
    )

    return {
        "total_records": len(records),
        "total_refs": total_refs,
        "brand_mentions": brand_mentions,
        "mention_rate": _pct(brand_mentions, len(records)),
        "zero_ref_records": zero_ref_records,
        "empty_answer_records": empty_answer_records,
        "ai_platforms": ai_platforms,
        "top_articles": top_articles[:50],
        "top_ref_platforms": top_ref_platforms[:30],
        "mentioned_entities": mentioned_entities[:50],
        "selected_competitors": selected_competitors,
        "competitor_articles": competitor_articles,
        "weak_competitor_articles": weak_competitor_articles,
    }
