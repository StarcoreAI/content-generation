"""Separate LLM decision for merging one reference-analysis batch into writing routes."""
import json


MERGE_MAX_TOKENS = 4000
VALID_ACTIONS = {"create", "reinforce", "discard"}


def merge_reference_route_batch(analyses, existing_routes, ai_json_fn):
    analyses = [dict(item or {}) for item in analyses or []]
    existing_routes = [dict(item or {}) for item in existing_routes or []]
    if not analyses:
        return {"updates": []}
    parent_types = {str(item.get("classification") or "") for item in analyses}
    if len(parent_types) != 1 or parent_types - {"介绍型", "对比型"}:
        raise ValueError("batch_parent_type_required")
    parent_type = parent_types.pop()
    routes = [item for item in existing_routes if item.get("parent_type") == parent_type]
    raw = ai_json_fn(build_batch_merge_prompt(analyses, routes, parent_type), MERGE_MAX_TOKENS)
    return normalize_batch_merge_result(raw, analyses, routes, parent_type)


def build_batch_merge_prompt(analyses, existing_routes, parent_type):
    article_payload = []
    for index, item in enumerate(analyses):
        article_payload.append({
            "analysis_index": index,
            "source_query": item.get("source_query"),
            "source": item.get("source"),
            "source_evidence": item.get("source_evidence"),
            "proposed_route": item.get("route"),
        })
    route_payload = [{
        "id": route.get("id"), "name": route.get("name"), "reader_task": route.get("reader_task"),
        "steps": route.get("steps"), "signature": route.get("signature"), "risk_notes": route.get("risk_notes"),
    } for route in existing_routes]
    return f"""你是 GEO 行业写法库的批次合并审核员。只输出 JSON，不要 Markdown。
本次仅处理“{parent_type}”文章。逐篇引用情报分析已经完成；你的唯一任务是判断这些分析应强化已有路线、新建路线，还是仅作为重复证据丢弃。不要重新分析文章，不要讨论 AI 平台内部机制。

输出 schema：
{{"updates":[{{
  "action":"create|reinforce|discard",
  "analysis_indexes":[0],
  "route_id":"仅 reinforce 时填写已有路线 ID",
  "route":{{"name":"仅 create 时填写完整路线","parent_type":"{parent_type}","reader_task":"","steps":[{{"purpose":"","evidence_role":"","output_action":""}}],"signature":"","risk_notes":""}},
  "reason":"简短说明"
}}]}}

规则：
1. 先去掉具体 Query、实体、地名、数字和来源事实，再判断两种写法能否自然写成同一篇文章。若只是标题或措辞不同，读者仍会感觉是同一路写法，则合并。若场景不同，读者的关注点、材料组织或读后动作会感到明显差异，则不合并，可 create。
2. 同一批多个来源若支撑同一路线，放进同一个 reinforce 或 create 的 analysis_indexes。
3. reinforce 只能使用下方给出的已有 route_id，且不要改写已有路线本体；系统只会追加来源证据。
4. 每个 analysis_index 至多出现一次；无法形成稳定可复用路线时用 discard。
5. route 必须是可跨客户复用的抽象组织方式，不得含具体 Query、实体、地名、数字或来源文章事实。

【本批逐篇分析】
{json.dumps(article_payload, ensure_ascii=False, indent=2)}
【当前同类型写法库】
{json.dumps(route_payload, ensure_ascii=False, indent=2)}
"""


def normalize_batch_merge_result(raw, analyses, existing_routes, parent_type):
    raw = raw if isinstance(raw, dict) else {}
    existing_ids = {str(item.get("id") or "") for item in existing_routes}
    used, updates = set(), []
    for item in raw.get("updates") if isinstance(raw.get("updates"), list) else []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        indexes = _indexes(item.get("analysis_indexes"), len(analyses), used)
        if action not in VALID_ACTIONS or not indexes:
            continue
        update = {"action": action, "analysis_indexes": indexes, "reason": str(item.get("reason") or "").strip()[:500]}
        if action == "reinforce":
            route_id = str(item.get("route_id") or "").strip()
            if route_id not in existing_ids:
                continue
            update["route_id"] = route_id
        elif action == "create":
            route = _route(item.get("route"), parent_type)
            if not route:
                continue
            update["route"] = route
        updates.append(update)
        used.update(indexes)
    return {"updates": updates}


def _indexes(value, count, used):
    result = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, int) and 0 <= item < count and item not in used and item not in result:
            result.append(item)
    return result


def _route(value, parent_type):
    value = value if isinstance(value, dict) else {}
    if value.get("parent_type") != parent_type:
        return None
    fields = {key: str(value.get(key) or "").strip() for key in ("name", "reader_task", "signature")}
    if not all(fields.values()):
        return None
    steps = []
    for step in value.get("steps") if isinstance(value.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        clean = {key: str(step.get(key) or "").strip() for key in ("purpose", "evidence_role", "output_action")}
        if all(clean.values()):
            steps.append(clean)
    if not steps:
        return None
    return {"parent_type": parent_type, **fields, "steps": steps[:8], "risk_notes": str(value.get("risk_notes") or "").strip()}
