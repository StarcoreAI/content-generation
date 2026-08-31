import re
from collections import defaultdict

from services.ref_articles import canonical_article_key
from services.ref_platforms import normalize_ref_platform


AI_PLATFORM_NAMES = {
    "deepseek": "DeepSeek",
    "yuanbao": "元宝",
    "qwen": "千问",
    "wenxin": "文心一言",
    "kimi": "Kimi",
    "doubao": "豆包",
}


def _pct(part, total):
    return round(part / total * 100, 1) if total else 0


def _contains_entity(text, entity_name):
    return str(entity_name or "").strip().lower() in str(text or "").lower()


def _normalize_name(value):
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _own_brand_names(records, own_brand="", own_client_name=""):
    names = []
    for value in [own_brand, own_client_name, *[rec.get("brand", "") for rec in records]]:
        name = _normalize_name(value)
        if len(name) >= 2 and name not in names:
            names.append(name)
    return names


def _is_own_brand_entity(name, own_brand_names):
    normalized = _normalize_name(name)
    if len(normalized) < 2:
        return False
    return any(
        re.search(re.escape(brand_name), normalized) or re.search(re.escape(normalized), brand_name)
        for brand_name in own_brand_names
    )


def _mentions_own_brand(text, own_brand_names):
    normalized = _normalize_name(text)
    if not normalized:
        return False
    return any(brand_name in normalized for brand_name in own_brand_names)


def select_article_match_entities(mentioned_entities):
    selected = []
    for idx in (0, 2):
        if len(mentioned_entities) > idx:
            name = mentioned_entities[idx].get("name", "")
            if name and name not in selected:
                selected.append(name)
    return selected


def _record_mentions_brand(record, own_brand_names=None):
    if record.get("brand_mentioned"):
        return True
    own_brand_names = own_brand_names or _own_brand_names([record])
    if _mentions_own_brand(record.get("answer", ""), own_brand_names):
        return True
    for entity in record.get("mentioned_entities") or []:
        if not isinstance(entity, dict):
            continue
        if _is_own_brand_entity(entity.get("name", ""), own_brand_names):
            return True
        if _mentions_own_brand(entity.get("evidence", ""), own_brand_names):
            return True
    return False


def build_record_insights(records, configured_platforms=None, own_brand="", own_client_name=""):
    records = list(records or [])
    own_brand_names = _own_brand_names(
        records,
        own_brand=own_brand,
        own_client_name=own_client_name,
    )
    configured_platforms = [
        str(platform or "").strip()
        for platform in (configured_platforms or [])
        if str(platform or "").strip()
    ]
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
        brand_mentioned = _record_mentions_brand(rec, own_brand_names)

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
            if _is_own_brand_entity(name, own_brand_names):
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

    actual_platform_count = len(platform_data)
    show_all_platform = bool(records) and (
        actual_platform_count > 1 or len(configured_platforms) > 1
    )
    if show_all_platform:
        all_ref_platforms = sorted([
            {
                "platform": item["platform"],
                "count": item["count"],
                "pct": _pct(item["count"], total_refs),
            }
            for item in source_data.values()
        ], key=lambda x: x["count"], reverse=True)[:12]
        ai_platforms.insert(0, {
            "source_platform": "all",
            "platform_name": "全部平台",
            "total_records": len(records),
            "total_refs": total_refs,
            "brand_mentions": brand_mentions,
            "zero_ref_records": zero_ref_records,
            "empty_answer_records": empty_answer_records,
            "mention_rate": _pct(brand_mentions, len(records)),
            "zero_ref_rate": _pct(zero_ref_records, len(records)),
            "ref_platforms": all_ref_platforms,
        })

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
    }
