import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_entities import get_openai_client, read_json, select_records, write_json
from services.storage import update_json


def _clean_name(value):
    text = str(value or "").strip()
    for char in " \t\r\n，。,.、：:；;（）()[]【】<>《》\"'“”‘’":
        text = text.replace(char, "")
    return text


COMBINED_NAME_SEPARATORS = ("/", "／")


def is_combined_entity_name(value):
    text = str(value or "").strip()
    return any(separator in text for separator in COMBINED_NAME_SEPARATORS)


def split_combined_entity_name(value):
    text = str(value or "").strip()
    if not is_combined_entity_name(text):
        return [_clean_name(text)] if _clean_name(text) else []
    for separator in COMBINED_NAME_SEPARATORS[1:]:
        text = text.replace(separator, COMBINED_NAME_SEPARATORS[0])
    parts = []
    for part in text.split(COMBINED_NAME_SEPARATORS[0]):
        cleaned = _clean_name(part)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    return parts


def _extract_json_object(raw):
    text = str(raw or "").strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.I)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def is_own_brand_name(name, own_brand):
    name = _clean_name(name)
    own_brand = _clean_name(own_brand)
    if not name or not own_brand or len(own_brand) < 2:
        return False
    return name == own_brand or name in own_brand or own_brand in name


def build_deepseek_options(settings, prefix=""):
    thinking_key = f"{prefix}_thinking" if prefix else "thinking"
    reasoning_key = f"{prefix}_reasoning_effort" if prefix else "reasoning_effort"
    thinking = str(settings.get(thinking_key, "disabled")).strip().lower()
    if thinking not in {"enabled", "disabled"}:
        thinking = "disabled"
    options = {"extra_body": {"thinking": {"type": thinking}}}
    if thinking == "enabled" and settings.get(reasoning_key):
        options["reasoning_effort"] = str(settings.get(reasoning_key)).strip()
    return options


def build_candidate_extraction_prompt(record, competitor_category=""):
    question = record.get("question", "")
    platform = record.get("source_platform", "")
    answer = (record.get("answer") or "")[:6000]
    category_scope = competitor_category.strip() or "与本问题直接相关、和本客户争夺同一需求的经营主体"
    return f"""你是GEO竞品实体抽取助手。请只从这一条 AI 回答正文中抽取已经符合范围的真实经营主体。

竞品品类/服务范围：{category_scope}
AI平台：{platform}
问题：{question}

抽取目标：
- 只抽取符合范围的实体：真实门店/品牌/公司/机构，且正在提供或被回答明确描述为提供该品类服务。
- 不要输出不符合范围的实体；第二层会做最终过滤。
- 行业要按问题语境判断：如果问题是评估车载音响/汽车音响门店，只抽汽车音响公司、改装店、服务品牌，不要抽宝马、奔驰、特斯拉、车型、车企实体。
- 如果问题是黄金回收，只抽黄金回收商家、门店、公司、机构，不要抽营业执照、XRF光谱仪、上海黄金交易所大盘价、报价、手续费、克扣重量、风险点、地点、媒体平台。
- 不要抽业务概念、品类词、设备、证照、价格、风险、城市、文章平台、搜索平台。
- 只抽回答正文明确出现的名字，不要编造。
- 遇到“A/B”“A、B”“A和B”等并列推荐，必须拆成多个独立实体分别输出；不要输出 A/B 组合名。
- evidence 必须是回答里的短片段。

输出严格 JSON，不要解释。JSON 字段固定为 competitors：
{{
  "competitors": [
    {{
      "n": "实体原名",
      "e": "回答中的短证据片段",
      "b": "行业业务"
    }}
  ]
}}

AI回答正文：
{answer}
"""


def build_candidate_batch_extraction_prompt(records, competitor_category=""):
    records = list(records or [])
    category_scope = competitor_category.strip() or "与本问题直接相关、和本客户争夺同一需求的经营主体"
    compact_records = [
        {
            "record_id": record.get("id"),
            "source_platform": record.get("source_platform", ""),
            "question": record.get("question", ""),
            "answer": (record.get("answer") or "")[:6000],
        }
        for record in records
    ]
    return f"""你是GEO竞品实体抽取助手。请从多条 AI 回答正文中抽取已经符合范围的真实经营主体。

竞品品类/服务范围：{category_scope}

抽取目标：
- 每条回答必须按 record_id 单独输出，不能把不同 record_id 的实体混到一起。
- 只抽取符合范围的实体：真实门店/品牌/公司/机构，且正在提供或被回答明确描述为提供该品类服务。
- 不要输出不符合范围的实体；第二层会做最终过滤。
- 如果问题是黄金回收，只抽黄金回收商家、门店、公司、机构；营业执照、XRF光谱仪、上海黄金交易所大盘价、报价、手续费、克扣重量、风险点、地点、媒体平台都不是经营主体。
- 如果问题是车载音响/汽车音响，只抽汽车音响公司、改装店、服务品牌，不要抽整车品牌、车型、车企。
- 只抽回答正文明确出现的名字，不要编造。
- 遇到“A/B”“A、B”“A和B”等并列推荐，必须拆成多个独立实体分别输出；不要输出 A/B 组合名。
- evidence 必须是对应回答里的短片段。

输出严格 JSON，不要解释。字段名必须精简，固定为 records：
{{
  "records": [
    {{
      "record_id": "原始record_id",
      "competitors": [
        {{
          "n": "实体原名",
          "e": "短证据",
          "b": "行业业务"
        }}
      ]
    }}
  ]
}}

字段含义：n=name，e=evidence且最多40字，b=行业业务或服务类型。

待处理回答：
{json.dumps(compact_records, ensure_ascii=False)}
"""


def parse_candidate_response(raw):
    payload = _extract_json_object(raw)
    items = payload.get("competitors", []) if isinstance(payload, dict) else []
    competitors = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _clean_name(item.get("name") or item.get("n"))
        if not name or name in seen:
            continue
        seen.add(name)
        business = str(item.get("business") or item.get("b") or item.get("type") or "").strip()[:40]
        competitors.append({
            "name": name,
            "canonical_name": _clean_name(item.get("canonical_name") or name),
            "type": business or "未知",
            "business": business,
            "sentiment": str(item.get("sentiment") or "neutral").strip()[:20],
            "evidence": str(item.get("evidence") or item.get("e") or "").strip()[:160],
        })
    return competitors


def parse_candidate_batch_response(raw, records):
    payload = _extract_json_object(raw)
    record_ids = [str(record.get("id") or "") for record in records or []]
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        result = {}
        for item in payload.get("records") or []:
            if not isinstance(item, dict):
                continue
            record_id = str(item.get("record_id") or "")
            result[record_id] = parse_candidate_response(json.dumps({
                "competitors": item.get("competitors") or []
            }, ensure_ascii=False))
        return result
    if len(record_ids) == 1:
        return {record_ids[0]: parse_candidate_response(raw)}
    return {}


def resolve_competitor_category(explicit_category, client_id, clients):
    if str(explicit_category or "").strip():
        return str(explicit_category).strip()
    for client in clients or []:
        if client.get("id") != client_id:
            continue
        return str(
            client.get("competitor_category")
            or client.get("category")
            or client.get("industry")
            or ""
        ).strip()
    return ""


def resolve_own_brand(client_id, clients):
    for client in clients or []:
        if client.get("id") != client_id:
            continue
        return str(client.get("brand") or client.get("name") or "").strip()
    return ""


def filter_entity_candidates(candidates, own_brand=""):
    kept = []
    rejected = []
    seen = set()
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        item = dict(candidate)
        name = _clean_name(item.get("name"))
        canonical = _clean_name(item.get("canonical_name") or name)
        if not canonical:
            rejected.append({**item, "reason": "empty_name"})
            continue
        item["name"] = name or canonical
        item["canonical_name"] = canonical
        if canonical in seen:
            rejected.append({**item, "reason": "duplicate"})
            continue
        seen.add(canonical)
        kept.append(item)
    return kept, rejected


def extract_candidates_for_records(records, settings, client=None, competitor_category=""):
    client = client or get_openai_client(settings)
    model = settings.get("extraction_model") or settings.get("model") or "deepseek-v4-flash"
    batch_size = int(settings.get("extraction_batch_size") or 5)
    batch_size = max(1, batch_size)
    records = list(records or [])
    results = []

    def empty_result(record):
        return {
            "record_id": record.get("id"),
            "question": record.get("question"),
            "source_platform": record.get("source_platform"),
            "task_id": record.get("task_id", ""),
            "competitors": [],
            "rejected_competitors": [],
        }

    def apply_competitors(result, record, competitors):
        kept, rejected = filter_entity_candidates(competitors, own_brand=record.get("brand", ""))
        result["competitors"] = kept
        result["rejected_competitors"] = rejected
        return result

    def request_single(record, batch_error=""):
        result = {
            "record_id": record.get("id"),
            "question": record.get("question"),
            "source_platform": record.get("source_platform"),
            "task_id": record.get("task_id", ""),
            "competitors": [],
            "rejected_competitors": [],
        }
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": build_candidate_extraction_prompt(record, competitor_category=competitor_category)}],
                temperature=0,
                max_tokens=int(settings.get("extraction_max_tokens") or 1100),
                response_format={"type": "json_object"},
                **build_deepseek_options(settings, "extraction"),
            )
            raw = response.choices[0].message.content
            parsed = parse_candidate_response(raw)
            apply_competitors(result, record, parsed)
            result["raw"] = raw
            if batch_error:
                result["batch_error"] = batch_error
        except Exception as exc:
            result["error"] = str(exc)
            if batch_error:
                result["batch_error"] = batch_error
        return result

    total_batches = (len(records) + batch_size - 1) // batch_size if records else 0
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        current_batch = start // batch_size + 1
        if settings.get("progress"):
            print(f"第一层批量抽取 {current_batch}/{total_batches}: {len(batch)} 条", file=sys.stderr, flush=True)
        if len(batch) == 1 and batch_size == 1:
            results.append(request_single(batch[0]))
            continue
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": build_candidate_batch_extraction_prompt(batch, competitor_category=competitor_category)}],
                temperature=0,
                max_tokens=int(settings.get("extraction_max_tokens") or 3000),
                response_format={"type": "json_object"},
                **build_deepseek_options(settings, "extraction"),
            )
            raw = response.choices[0].message.content
            parsed_by_id = parse_candidate_batch_response(raw, batch)
            if len(parsed_by_id) < len(batch):
                missing = [str(record.get("id") or "") for record in batch if str(record.get("id") or "") not in parsed_by_id]
                raise ValueError(f"batch response missing record_id: {', '.join(missing)}")
            for record in batch:
                result = empty_result(record)
                apply_competitors(result, record, parsed_by_id.get(str(record.get("id") or ""), []))
                result["raw"] = raw
                results.append(result)
        except Exception as exc:
            batch_error = str(exc)
            if settings.get("progress"):
                print(f"第一层批量抽取失败，回退单条：{batch_error}", file=sys.stderr, flush=True)
            for record in batch:
                results.append(request_single(record, batch_error=batch_error))
    return results


def mentions_from_extraction_results(results):
    mentions = []
    for result in results or []:
        for item in result.get("competitors") or []:
            mentions.append({
                "record_id": result.get("record_id"),
                "question": result.get("question", ""),
                "source_platform": result.get("source_platform", "unknown") or "unknown",
                "raw_name": _clean_name(item.get("name")),
                "type": item.get("type", ""),
                "business": item.get("business", ""),
                "sentiment": item.get("sentiment", "neutral"),
                "evidence": item.get("evidence", ""),
            })
    return [item for item in mentions if item["raw_name"]]


def mentions_from_existing_records(records):
    mentions = []
    for record in records or []:
        for entity in record.get("mentioned_entities") or []:
            if not isinstance(entity, dict):
                continue
            name = _clean_name(entity.get("name"))
            if not name:
                continue
            mentions.append({
                "record_id": record.get("id"),
                "question": record.get("question", ""),
                "source_platform": record.get("source_platform", "unknown") or "unknown",
                "raw_name": name,
                "type": entity.get("type", ""),
                "sentiment": entity.get("sentiment", "neutral"),
                "evidence": entity.get("evidence", ""),
            })
    return mentions


def build_existing_entity_summary(records):
    return build_raw_entity_summary(mentions_from_existing_records(records))


def build_raw_entity_summary(mentions):
    summary = {}
    for mention in mentions or []:
        name = _clean_name(mention.get("raw_name") or mention.get("name"))
        if not name:
            continue
        source_platform = mention.get("source_platform", "unknown") or "unknown"
        if name not in summary:
            summary[name] = {
                "name": name,
                "type": mention.get("type", ""),
                "business": mention.get("business", ""),
                "count": 0,
                "ai_platform_counts": defaultdict(int),
                "evidence_samples": [],
                "questions": [],
            }
        item = summary[name]
        item["count"] += 1
        item["ai_platform_counts"][source_platform] += 1
        evidence = str(mention.get("evidence") or "").strip()
        if evidence and evidence not in item["evidence_samples"] and len(item["evidence_samples"]) < 5:
            item["evidence_samples"].append(evidence[:160])
        question = str(mention.get("question") or "").strip()
        if question and question not in item["questions"] and len(item["questions"]) < 5:
            item["questions"].append(question)

    result = []
    for item in summary.values():
        item["ai_platform_counts"] = dict(item["ai_platform_counts"])
        result.append(item)
    result.sort(key=lambda x: (-x["count"], x["name"]))
    return result


def build_competitor_report_prompt(raw_summary, competitor_category=""):
    category_scope = competitor_category.strip() or "与本客户争夺同一需求的经营主体"
    compact = [
        {
            "raw_name": item["name"],
            "count": item.get("count", 0),
            "type": item.get("type", ""),
            "business": item.get("business", ""),
            "ai_platform_counts": item.get("ai_platform_counts", {}),
            "evidence_samples": item.get("evidence_samples", [])[:3],
            "questions": item.get("questions", [])[:3],
        }
        for item in (raw_summary or [])[:160]
    ]
    return f"""你是GEO竞品分析全局归一化助手。第一层只抽取了候选实体名、短证据和行业业务，没有做最终过滤。请一次性完成全局别名合并和过滤。

竞品品类/服务范围：{category_scope}

你的职责：
1. 统一实体名称：判断哪些 raw_name 是同一经营主体/门店/公司/品牌的别名、简称、带地域或业务后缀的写法。
2. 过滤不属于该品类服务的候选；不要输出被过滤的候选。
3. 本客户品牌如果出现在候选里，也作为经营主体保留，不要因为它是本客户而拒绝。
4. 只输出保留实体；不要输出原因、置信度、平台发现、排名或被拒绝列表。
5. 不要把不同城市、不同主体、不同品牌强行合并。
6. 遇到“A/B”“A、B”这类并列写法，不能把 A 和 B 合成一个品牌，也不能把 A/B 放进任何单个品牌的别名；应分别归到已有主体，无法判断就不输出这个并列名。
7. 银行渠道、交易所、价格/证照/设备/地点/媒体平台、只作为被回收商品出现的金饰品牌、泛称都不要输出。

输出严格 JSON，不要解释。JSON 字段固定如下：
{{
  "canonical_entities": [
    {{
      "n": "标准名称",
      "a": ["原始名1", "原始名2"]
    }}
  ]
}}

原始实体摘要：
{json.dumps(compact, ensure_ascii=False)}
"""


def parse_competitor_report_response(raw):
    try:
        payload = _extract_json_object(raw)
    except Exception as exc:
        return {
            "canonical_entities": [],
            "competitor_rankings": [],
            "rejected_entities": [],
            "platform_findings": [],
            "alias_groups": [],
            "parse_error": str(exc),
        }
    if not isinstance(payload, dict):
        return {"canonical_entities": [], "competitor_rankings": [], "rejected_entities": [], "platform_findings": [], "alias_groups": []}
    payload.setdefault("canonical_entities", [])
    normalized = []
    for item in payload.get("canonical_entities") or []:
        if not isinstance(item, dict):
            continue
        canonical = _clean_name(item.get("canonical_name") or item.get("n"))
        if not canonical:
            continue
        aliases = item.get("aliases", item.get("a", [])) or []
        if not isinstance(aliases, list):
            aliases = [aliases]
        aliases = [
            _clean_name(alias)
            for alias in aliases
            if _clean_name(alias) and not is_combined_entity_name(alias)
        ]
        if canonical not in aliases:
            aliases.insert(0, canonical)
        normalized.append({
            "canonical_name": canonical,
            "aliases": aliases,
        })
    payload["canonical_entities"] = normalized
    payload.setdefault("competitor_rankings", [])
    payload.setdefault("rejected_entities", [])
    payload.setdefault("platform_findings", [])
    payload.setdefault("alias_groups", [])
    return payload


def request_competitor_report(raw_summary, settings, client=None, competitor_category=""):
    if not raw_summary:
        return {"canonical_entities": [], "competitor_rankings": [], "rejected_entities": [], "platform_findings": [], "alias_groups": []}
    client = client or get_openai_client(settings)
    model = settings.get("model") or "deepseek-chat"
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": build_competitor_report_prompt(raw_summary, competitor_category=competitor_category)}],
        temperature=0,
        max_tokens=int(settings.get("normalization_max_tokens") or 1600),
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    report = parse_competitor_report_response(raw)
    report["raw"] = raw
    return report


def merge_competitor_reports(reports):
    merged = {
        "canonical_entities": [],
        "competitor_rankings": [],
        "rejected_entities": [],
        "platform_findings": [],
        "alias_groups": [],
        "batches": len(reports or []),
    }
    canonical_seen = set()
    rejected_seen = set()
    finding_seen = set()
    alias_seen = set()
    parse_errors = []

    for report in reports or []:
        if report.get("parse_error"):
            parse_errors.append(report.get("parse_error"))
        for item in report.get("canonical_entities") or []:
            name = _clean_name(item.get("canonical_name"))
            if not name or name in canonical_seen:
                continue
            canonical_seen.add(name)
            merged["canonical_entities"].append(item)
        for item in report.get("rejected_entities") or []:
            name = _clean_name(item.get("name"))
            if not name or name in rejected_seen:
                continue
            rejected_seen.add(name)
            merged["rejected_entities"].append(item)
        for item in report.get("platform_findings") or []:
            key = (item.get("source_platform"), item.get("finding"))
            if key in finding_seen:
                continue
            finding_seen.add(key)
            merged["platform_findings"].append(item)
        for item in report.get("alias_groups") or []:
            key = (_clean_name(item.get("canonical_name")), tuple(sorted(_clean_name(v) for v in item.get("aliases", []) or [])))
            if key in alias_seen:
                continue
            alias_seen.add(key)
            merged["alias_groups"].append(item)
    if parse_errors:
        merged["parse_errors"] = parse_errors
    return merged


def simplify_competitor_report_for_output(report):
    report = report or {}
    simplified = {
        "canonical_entities": report.get("canonical_entities") or [],
    }
    if report.get("batches") is not None:
        simplified["batches"] = report.get("batches")
    if report.get("parse_errors"):
        simplified["parse_errors"] = report.get("parse_errors")
    if report.get("parse_error"):
        simplified["parse_error"] = report.get("parse_error")
    if "raw" in report:
        simplified["raw"] = report.get("raw")

    batch_reports = []
    for batch in report.get("batch_reports") or []:
        item = {
            "canonical_entities": batch.get("canonical_entities") or [],
        }
        if batch.get("parse_error"):
            item["parse_error"] = batch.get("parse_error")
        if "raw" in batch:
            item["raw"] = batch.get("raw")
        batch_reports.append(item)
    if batch_reports:
        simplified["batch_reports"] = batch_reports
    return simplified


def request_competitor_report_batched(raw_summary, settings, client=None, competitor_category="", batch_size=120):
    raw_summary = list(raw_summary or [])
    if not raw_summary:
        return {"canonical_entities": [], "competitor_rankings": [], "rejected_entities": [], "platform_findings": [], "alias_groups": []}
    reports = []
    for start in range(0, len(raw_summary), batch_size):
        if settings.get("progress"):
            current = start // batch_size + 1
            total = (len(raw_summary) + batch_size - 1) // batch_size
            print(f"第二层全局归一 {current}/{total}: {min(batch_size, len(raw_summary) - start)} 个候选", file=sys.stderr, flush=True)
        reports.append(request_competitor_report(
            raw_summary[start:start + batch_size],
            settings,
            client=client,
            competitor_category=competitor_category,
        ))
    merged = merge_competitor_reports(reports)
    merged["batch_reports"] = reports
    return merged


def accepted_raw_names(competitor_report):
    return set(canonical_alias_map(competitor_report))


def canonical_alias_map(competitor_report):
    aliases = {}
    for entity in competitor_report.get("canonical_entities", []) or []:
        canonical = _clean_name(entity.get("canonical_name"))
        if canonical:
            aliases[canonical] = canonical
        for alias in entity.get("aliases", []) or []:
            alias = _clean_name(alias)
            if alias and not is_combined_entity_name(alias):
                aliases[alias] = canonical or alias
    for group in competitor_report.get("alias_groups", []) or []:
        canonical = _clean_name(group.get("canonical_name"))
        if canonical:
            aliases[canonical] = canonical
        for alias in group.get("aliases", []) or []:
            alias = _clean_name(alias)
            if alias and not is_combined_entity_name(alias):
                aliases[alias] = canonical or alias
    return aliases


def rejected_raw_names(competitor_report):
    return {
        _clean_name(item.get("name"))
        for item in competitor_report.get("rejected_entities", []) or []
        if _clean_name(item.get("name"))
    }


def canonical_name_for(raw_name, competitor_report):
    raw_name = _clean_name(raw_name)
    return canonical_alias_map(competitor_report).get(raw_name, raw_name)


def canonical_names_for_raw(raw_name, competitor_report):
    raw_name = _clean_name(raw_name)
    aliases = canonical_alias_map(competitor_report)
    if raw_name in aliases:
        return [aliases[raw_name]]
    if is_combined_entity_name(raw_name):
        names = []
        for part in split_combined_entity_name(raw_name):
            canonical = aliases.get(part)
            if canonical and canonical not in names:
                names.append(canonical)
        return names
    if aliases:
        return []
    return [raw_name] if raw_name else []


def build_final_competitor_summary(mentions, competitor_report, own_brand=""):
    grouped = {}
    accepted = accepted_raw_names(competitor_report)
    rejected = rejected_raw_names(competitor_report)
    for mention in mentions or []:
        raw_name = _clean_name(mention.get("raw_name"))
        if not raw_name:
            continue
        if raw_name in rejected:
            continue
        canonicals = canonical_names_for_raw(raw_name, competitor_report)
        if accepted and not canonicals:
            continue
        source_platform = mention.get("source_platform", "unknown") or "unknown"
        for canonical in canonicals:
            if canonical not in grouped:
                grouped[canonical] = {
                    "name": canonical,
                    "aliases": set(),
                    "mention_count": 0,
                    "ai_platform_counts": defaultdict(int),
                    "evidence_samples": [],
                    "record_ids": set(),
                    "is_own_brand": is_own_brand_name(canonical, own_brand),
                }
            item = grouped[canonical]
            if is_own_brand_name(raw_name, own_brand):
                item["is_own_brand"] = True
            if raw_name != canonical and not is_combined_entity_name(raw_name):
                item["aliases"].add(raw_name)
            item["mention_count"] += 1
            item["ai_platform_counts"][source_platform] += 1
            if mention.get("record_id"):
                item["record_ids"].add(mention.get("record_id"))
            evidence = str(mention.get("evidence") or "").strip()
            if evidence and evidence not in item["evidence_samples"] and len(item["evidence_samples"]) < 5:
                item["evidence_samples"].append(evidence[:160])

    result = []
    for item in grouped.values():
        item["aliases"] = sorted(item["aliases"])
        item["ai_platform_counts"] = dict(item["ai_platform_counts"])
        item["record_count"] = len(item["record_ids"])
        del item["record_ids"]
        result.append(item)
    result.sort(key=lambda x: (-x["mention_count"], x["name"]))
    return result


def build_extract_missing_report(records, settings, limit=0, use_llm=True, competitor_category="", own_brand=""):
    selected = records[:limit] if limit else list(records)
    if use_llm:
        extraction_results = extract_candidates_for_records(
            selected,
            settings,
            competitor_category=competitor_category,
        )
    else:
        extraction_results = []
    mentions = mentions_from_extraction_results(extraction_results)
    raw_summary = build_raw_entity_summary(mentions)
    competitor_report = (
        request_competitor_report_batched(raw_summary, settings, competitor_category=competitor_category)
        if use_llm and raw_summary
        else {"canonical_entities": [], "competitor_rankings": [], "rejected_entities": [], "platform_findings": [], "alias_groups": []}
    )
    final_summary = build_final_competitor_summary(mentions, competitor_report, own_brand=own_brand)
    return {
        "mode": "extract_missing",
        "selected_records": len(selected),
        "own_brand": own_brand,
        "raw_entity_summary": raw_summary,
        "competitor_report": simplify_competitor_report_for_output(competitor_report),
        "final_competitor_summary": final_summary,
        "results": extraction_results,
    }


def build_normalize_existing_report(records, settings, use_llm=True, competitor_category="", own_brand=""):
    mentions = mentions_from_existing_records(records)
    raw_summary = build_raw_entity_summary(mentions)
    competitor_report = (
        request_competitor_report_batched(raw_summary, settings, competitor_category=competitor_category)
        if use_llm and raw_summary
        else {"canonical_entities": [], "competitor_rankings": [], "rejected_entities": [], "platform_findings": [], "alias_groups": []}
    )
    final_summary = build_final_competitor_summary(mentions, competitor_report, own_brand=own_brand)
    return {
        "mode": "normalize_existing",
        "selected_records": len(records),
        "own_brand": own_brand,
        "raw_unique_entities": len(raw_summary),
        "raw_entity_summary": raw_summary,
        "competitor_report": simplify_competitor_report_for_output(competitor_report),
        "final_competitor_summary": final_summary,
    }


def entities_for_result(result, competitor_report):
    entities = []
    seen = set()
    for item in result.get("competitors") or []:
        raw_name = _clean_name(item.get("name") or item.get("canonical_name"))
        if not raw_name:
            continue
        for canonical in canonical_names_for_raw(raw_name, competitor_report):
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            entities.append({
                "name": canonical,
                "type": str(item.get("type") or item.get("business") or "").strip()[:40],
                "sentiment": str(item.get("sentiment") or "neutral").strip()[:20],
                "evidence": str(item.get("evidence") or "").strip()[:160],
            })
    return entities


def apply_competitor_report_results(raw_records_path, records, report):
    raw_records_path = Path(raw_records_path)
    competitor_report = report.get("competitor_report") or {}
    by_id = {
        str(item.get("record_id") or ""): entities_for_result(item, competitor_report)
        for item in report.get("results") or []
        if item.get("record_id")
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{raw_records_path}.bak_entities_{timestamp}"

    def apply_to_latest(latest_records):
        changed = 0
        for record in latest_records:
            record_id = str(record.get("id") or "")
            if record_id in by_id:
                record["mentioned_entities"] = by_id[record_id]
                changed += 1
        if raw_records_path.exists():
            shutil.copy2(raw_records_path, backup_path)
        return latest_records, {"changed": changed, "backup_path": backup_path}

    return update_json(raw_records_path, records, apply_to_latest)


def write_report(report_dir, client_id, report):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(report_dir) / f"entity_normalize_{client_id or 'all'}_{timestamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, report)
    return str(path)


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Competitor extraction and normalization reports.", allow_abbrev=False)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--date", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--competitor-category", default="")
    parser.add_argument("--extract-missing", action="store_true")
    parser.add_argument("--normalize-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-report", default="")
    parser.add_argument("--skip-llm", action="store_true")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data_dir)
    raw_records_path = data_dir / "raw_records.json"
    if args.apply_report:
        records = read_json(raw_records_path, [])
        report = read_json(Path(args.apply_report), {})
        apply_result = apply_competitor_report_results(raw_records_path, records, report)
        print(f"实体入库完成：更新 {apply_result['changed']} 条记录，备份：{apply_result['backup_path']}")
        return 0
    if not args.extract_missing and not args.normalize_existing:
        raise SystemExit("必须指定 --extract-missing 或 --normalize-existing")
    if args.extract_missing and args.normalize_existing:
        raise SystemExit("--extract-missing 和 --normalize-existing 不能同时使用")
    if args.apply and args.normalize_existing:
        raise SystemExit("--apply 当前只支持 --extract-missing")
    if not args.dry_run and not args.apply:
        raise SystemExit("必须指定 --dry-run 或 --apply")

    records = read_json(raw_records_path, [])
    settings = read_json(data_dir / "settings.json", {})
    settings = {**settings, "progress": True}
    clients = read_json(data_dir / "clients.json", [])
    competitor_category = resolve_competitor_category(
        args.competitor_category,
        args.client_id,
        clients,
    )
    own_brand = resolve_own_brand(args.client_id, clients)
    selected = select_records(
        records,
        client_id=args.client_id,
        date=args.date,
        task_id=args.task_id,
        limit=args.limit if args.extract_missing else 0,
        include_existing=args.normalize_existing,
    )

    if args.extract_missing:
        report_body = build_extract_missing_report(
            selected,
            settings,
            limit=args.limit,
            use_llm=not args.skip_llm,
            competitor_category=competitor_category,
            own_brand=own_brand,
        )
    else:
        report_body = build_normalize_existing_report(
            selected,
            settings,
            use_llm=not args.skip_llm,
            competitor_category=competitor_category,
            own_brand=own_brand,
        )

    report = {
        "dry_run": bool(args.dry_run and not args.apply),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "client_id": args.client_id,
        "date": args.date,
        "task_id": args.task_id,
        "competitor_category": competitor_category,
        "own_brand": own_brand,
        "data_written": False,
        **report_body,
    }
    if args.apply:
        apply_result = apply_competitor_report_results(raw_records_path, records, report)
        report["data_written"] = True
        report["apply_result"] = apply_result
    report_path = write_report(args.report_dir, args.client_id, report)
    if args.apply:
        print(f"实体入库完成：更新 {report['apply_result']['changed']} 条记录，报告：{report_path}，备份：{report['apply_result']['backup_path']}")
    else:
        print(f"dry-run 报告已生成：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
