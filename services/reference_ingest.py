STAGE2_MAX_TOKENS = 1600
STAGE2_LLM_MAX_ATTEMPTS = 2
LIBRARY_SUMMARY_LIMIT = 300
CITABILITY_VOCABULARY = [
    {"tag": "标题含年份地域决策词", "desc": "标题带年份/地域/\"怎么选、哪家好、避坑\"类决策词"},
    {"tag": "分人群分场景建议", "desc": "按人群、预算、场景分别给建议或直接给选型结论"},
    {"tag": "免责与广告标注", "desc": "免责声明、广告标识、转载来源标注"},
    {"tag": "FAQ用用户原话提问", "desc": "FAQ 的问题用用户真实搜索原话/口语句式"},
    {"tag": "官方政策与数据锚点", "desc": "引用官方政策、考试时间、具体数字等可锚定信息"},
    {"tag": "数据来源声明", "desc": "明确说明数据/结论出处"},
    {"tag": "提示以官方渠道核验", "desc": "引导读者去官方渠道确认关键信息"},
    {"tag": "风险与规则前置提示", "desc": "把规则、风险、限制条件放在推荐之前讲"},
    {"tag": "可执行核验清单", "desc": "给出报名/付款前可逐项执行的核验动作"},
]
CONTROLLED_CITABILITY_TAGS = {item["tag"] for item in CITABILITY_VOCABULARY}


def _text(value, limit=1200):
    return str(value or "").strip()[:limit]


def _kind_label(entry):
    if entry.get("kind") == "skeleton":
        return "骨架"
    return f"段落模式({ _text(entry.get('payload', {}).get('type'), 40) or '其他' })"


def _pattern_description(item):
    payload = item.get("payload") or {}
    if item.get("kind") == "skeleton":
        sections = payload.get("sections") or []
        section_text = "；".join(_text(section, 180) for section in sections if _text(section, 180))
        return _text(f"{section_text}；{_text(payload.get('signature'), 500)}", 1000)
    return _text(payload.get("pattern"), 1000)


def _library_summary(entry):
    payload = entry.get("payload") or {}
    name = _text(entry.get("name"), 160)
    if entry.get("kind") == "skeleton":
        description = "；".join(_text(value, 120) for value in payload.get("sections") or [])
        description = f"{description}；{_text(payload.get('signature'), 300)}"
    else:
        description = _text(payload.get("pattern"), 500)
    return _text(description, max(0, LIBRARY_SUMMARY_LIMIT - len(name)))


def build_ingest_prompt(entries, items, citability_items=None):
    library_lines = [
        " | ".join([
            _text(entry.get("id"), 100),
            _kind_label(entry),
            _text(entry.get("name"), 160),
            _text(entry.get("status"), 30),
            _library_summary(entry),
        ])
        for entry in entries
        if entry.get("kind") in {"skeleton", "module"}
    ]
    item_lines = [
        " | ".join([
            _text(item.get("item_key"), 80),
            _kind_label(item),
            _text(item.get("name"), 160),
            _pattern_description(item),
        ])
        for item in items
    ]
    other_checklist_lines = [
        " | ".join([
            _text(entry.get("id"), 100),
            "清单",
            _text(entry.get("name"), 200),
            _text(entry.get("status"), 30),
            _text("；".join(entry.get("payload", {}).get("raw_labels") or []), 300),
        ])
        for entry in entries
        if entry.get("kind") == "checklist" and _text(entry.get("name")).startswith("其他:")
    ]
    citability_lines = [
        f"{item['item_key']} | 原始标签: {item['raw_label']}"
        for item in citability_items or []
    ]
    vocabulary_lines = [f"{item['tag']} | {item['desc']}" for item in CITABILITY_VOCABULARY]
    return f"""你是写法库的入库审核员。写法库按“套路”积累可复用的文章写作结构。下面给出库中现有条目的摘要，以及一批新抽取的套路。请逐条判断：每个新套路是库里已有条目的同一套路，还是新套路。

判断标准：两个套路互换品牌和事实之后能互相照做，就是同一套路；措辞不同、侧重点不同、章节数量略有增减，都不构成新套路。骨架只和骨架比，段落模式只和段落模式比。

拿不准的判新套路。（新建重复条目可以由运营合并，错误归并则无法发现。）

你只能输出 JSON，不要输出 Markdown。字段只能是：
{{
  "results": [
    {{"item_key": "输入中给出的编号", "match": "骨架/段落模式命中的库条目id；引用友好特征仅当其他类命中已有清单时填写，否则为 null", "tag": "引用友好特征必须给出词表标签或其他:原始标签；骨架/段落模式留空", "reason": "一句话判断理由"}}
  ]
}}

【引用友好特征词表】
{"\n".join(vocabulary_lines)}
判定原则：按语义归类，不要按字面；措辞不同但指同一特征的必须归入同一标签。
词表归类与库中已有条目无关：即使库是空的，也必须先为每个引用友好特征从词表中选标签，只有语义确实超出词表全部标签时才允许用 其他:。

【库中现有条目】
{"\n".join(library_lines)}

【库中已有其他类清单】
{"\n".join(other_checklist_lines)}

【新抽取的套路】
{"\n".join(item_lines)}

【新抽取的引用友好特征】
{"\n".join(citability_lines)}
"""


def _pattern_items(card):
    items = []
    skeleton = card.get("skeleton")
    if isinstance(skeleton, dict) and _text(skeleton.get("name")) and _pattern_description({"kind": "skeleton", "payload": skeleton}):
        items.append({
            "item_key": "skeleton",
            "kind": "skeleton",
            "name": _text(skeleton.get("name"), 200),
            "payload": dict(skeleton),
        })
    for index, module in enumerate(card.get("modules") or []):
        if not isinstance(module, dict) or not _text(module.get("name")) or not _text(module.get("pattern")):
            continue
        items.append({
            "item_key": f"module_{index}",
            "kind": "module",
            "name": _text(module.get("name"), 200),
            "payload": dict(module),
        })
    return items


def _citability_items(card):
    return [
        {"item_key": f"citability_{index}", "raw_label": _text(feature, 200)}
        for index, feature in enumerate(card.get("citability_features") or [])
        if _text(feature, 200)
    ]


def _source_for_card(card, groups_by_id):
    source = dict(card.get("source") or {})
    group_id = _text(source.get("group_id"), 200)
    group = dict((groups_by_id or {}).get(group_id) or {})
    primary_url = _text(source.get("url"), 2000).rstrip("/")
    members = [
        _text(url, 2000).rstrip("/")
        for url in group.get("member_urls") or []
        if _text(url, 2000).rstrip("/")
    ]
    if not primary_url and members:
        primary_url = members[0]
    return {
        "url": primary_url,
        "title": _text(source.get("title"), 300),
        "group_id": group_id,
        "published_at": _text(source.get("published_at"), 40),
        "platform": _text(source.get("platform"), 80),
        "citation_count": source.get("citation_count") or 0,
        "risk_marks": list(group.get("risk_marks") or []),
        "alias_urls": [url for url in members if url != primary_url],
    }


def _raw_results_by_key(raw):
    raw_results = raw.get("results") if isinstance(raw, dict) else []
    return {
        _text(item.get("item_key"), 80): item
        for item in raw_results or []
        if isinstance(item, dict) and _text(item.get("item_key"), 80)
    }


def _normalized_matches(raw, items, entries):
    raw_by_key = _raw_results_by_key(raw)
    entries_by_id = {entry.get("id"): entry for entry in entries}
    results = {}
    for item in items:
        response = raw_by_key.get(item["item_key"], {})
        match_id = _text(response.get("match"), 200) if isinstance(response, dict) else ""
        matched_entry = entries_by_id.get(match_id)
        if not matched_entry or matched_entry.get("kind") != item["kind"]:
            match_id = ""
        results[item["item_key"]] = {
            "match": match_id,
            "reason": _text(response.get("reason"), 500) if isinstance(response, dict) else "",
        }
    return results


def _normalize_citability_tag(value, raw_label):
    tag = _text(value, 220)
    if tag in CONTROLLED_CITABILITY_TAGS:
        return tag
    if tag.startswith("其他:"):
        suffix = _text(tag.partition(":")[2], 200) or raw_label
        return f"其他:{suffix}"
    return f"其他:{tag or raw_label}"


def _normalized_citability(raw, items, other_entries):
    raw_by_key = _raw_results_by_key(raw)
    entries_by_id = {entry.get("id"): entry for entry in other_entries}
    decisions = {}
    for item in items:
        response = raw_by_key.get(item["item_key"], {})
        tag = _normalize_citability_tag(response.get("tag") if isinstance(response, dict) else "", item["raw_label"])
        match_id = _text(response.get("match"), 200) if isinstance(response, dict) else ""
        matched_entry = entries_by_id.get(match_id)
        if not tag.startswith("其他:") or not matched_entry:
            match_id = ""
        decisions[item["item_key"]] = {
            "tag": tag,
            "match": match_id,
            "reason": _text(response.get("reason"), 500) if isinstance(response, dict) else "",
        }
    return decisions


def _call_ingest_model(ai_json_fn, prompt):
    last_error = None
    for attempt in range(1, STAGE2_LLM_MAX_ATTEMPTS + 1):
        try:
            return ai_json_fn(prompt, STAGE2_MAX_TOKENS), attempt
        except Exception as exc:
            last_error = exc
    raise last_error


def _report_item(card_index, source, item, action, entry, reason, before):
    return {
        "card_index": card_index,
        "group_id": source["group_id"],
        "item_key": item["item_key"],
        "kind": item["kind"],
        "name": item["name"],
        "action": action,
        "entry_id": entry["id"],
        "reason": reason,
        "evidence_count_before": before,
        "evidence_count_after": entry["evidence_count"],
    }


def _append_raw_label(library, scope, entry_id, raw_label):
    from services.storage import update_json

    def append_label(store):
        store = library._normalize_store(store, scope)
        entry = library._find_entry(store, entry_id)
        payload = dict(entry.get("payload") or {})
        labels = [_text(label, 200) for label in payload.get("raw_labels") or [] if _text(label, 200)]
        if raw_label not in labels:
            labels.append(raw_label)
        payload["raw_labels"] = labels
        entry["payload"] = payload
        entry["updated_at"] = library.now_fn()
        return store, entry

    return update_json(library._scope_path(scope), library._empty_store(scope), append_label)


def _ingest_features(card_index, items, decisions, source, library, scope, report_items):
    for item in items:
        decision = decisions[item["item_key"]]
        tag = decision["tag"]
        if decision["match"]:
            existing = next(entry for entry in library.list_entries(scope) if entry.get("id") == decision["match"])
        elif tag in CONTROLLED_CITABILITY_TAGS:
            existing = next(
                (entry for entry in library.list_entries(scope)
                 if entry.get("kind") == "checklist" and entry.get("name") == tag),
                None,
            )
        else:
            existing = None
        if existing:
            before = existing["evidence_count"]
            entry = library.add_evidence(scope, existing["id"], source)
            entry = _append_raw_label(library, scope, entry["id"], item["raw_label"])
            action = "matched"
        else:
            before = 0
            entry = library.create_candidate(
                scope, "checklist", tag,
                {"feature": tag, "raw_labels": [item["raw_label"]]},
                source,
            )
            action = "created"
        report_items.append(_report_item(
            card_index,
            source,
            {"item_key": item["item_key"], "kind": "checklist", "name": tag},
            action,
            entry,
            decision["reason"] or "引用友好特征归并",
            before,
        ))


def ingest_anatomy_cards(cards, *, library, scope, groups_by_id, ai_json_fn):
    report_items = []
    errors = []
    llm_calls = 0
    for card_index, card in enumerate(cards or []):
        if not isinstance(card, dict):
            continue
        source = _source_for_card(card, groups_by_id)
        if not source["url"]:
            errors.append({"card_index": card_index, "error": "missing_source_url"})
            continue
        items = _pattern_items(card)
        citability_items = _citability_items(card)
        entries = library.list_entries(scope)
        comparable_entries = [entry for entry in entries if entry.get("kind") in {"skeleton", "module"}]
        other_entries = [
            entry for entry in entries
            if entry.get("kind") == "checklist" and _text(entry.get("name")).startswith("其他:")
        ]
        matches = {item["item_key"]: {"match": "", "reason": "库为空，直接建候选"} for item in items}
        citability = {
            item["item_key"]: {"tag": f"其他:{item['raw_label']}", "match": "", "reason": "LLM 未调用，按其他类建候选"}
            for item in citability_items
        }
        if citability_items or (items and comparable_entries):
            try:
                raw_result, attempts = _call_ingest_model(
                    ai_json_fn,
                    build_ingest_prompt(comparable_entries + other_entries, items, citability_items),
                )
                llm_calls += attempts
                matches = _normalized_matches(
                    raw_result,
                    items,
                    comparable_entries,
                )
                citability = _normalized_citability(raw_result, citability_items, other_entries)
            except Exception as exc:
                llm_calls += STAGE2_LLM_MAX_ATTEMPTS
                errors.append({"card_index": card_index, "group_id": source["group_id"], "error": str(exc)})
                matches = {item["item_key"]: {"match": "", "reason": "LLM 比对失败，按新套路建候选"} for item in items}
                citability = {
                    item["item_key"]: {"tag": f"其他:{item['raw_label']}", "match": "", "reason": "LLM 比对失败，按其他类建候选"}
                    for item in citability_items
                }

        for item in items:
            decision = matches[item["item_key"]]
            if decision["match"]:
                existing = next(entry for entry in comparable_entries if entry["id"] == decision["match"])
                before = existing["evidence_count"]
                entry = library.add_evidence(scope, existing["id"], source, payload_update=item["payload"])
                action = "matched"
            else:
                before = 0
                entry = library.create_candidate(scope, item["kind"], item["name"], item["payload"], source)
                action = "created"
            report_items.append(_report_item(card_index, source, item, action, entry, decision["reason"], before))
        _ingest_features(card_index, citability_items, citability, source, library, scope, report_items)

    return {
        "scope": scope,
        "total_cards": len([card for card in cards or [] if isinstance(card, dict)]),
        "total_items": len(report_items),
        "llm_calls": llm_calls,
        "items": report_items,
        "errors": errors,
    }
