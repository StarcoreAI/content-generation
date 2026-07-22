import copy
import json
import random


FAQ_PROBABILITY = 0.80
TABLE_PROBABILITY = 0.60
FREE_SLOT_PROBABILITY = 0.12
BODY_MODULE_COUNT_WEIGHTS = {0: 0.30, 1: 0.50, 2: 0.20}
MAX_FINGERPRINT_RETRIES = 3
BRIEF_MAX_TOKENS = 6000
BRIEF_LLM_MAX_ATTEMPTS = 2
GENERAL_BANS = ["包过", "保录取", "第一", "最好", "全市最低", "保证有效"]
TEMPLATE_BANS = ["随着社会的发展", "在当今社会", "毋庸置疑"]

# Extend this table when operations records a confirmed incompatibility.
MODULE_COMPATIBILITY = {
    "对比表": {"parent_types": {"对比型"}},
}
PARENT_TYPE_FIELDS = ("parent_type", "parent_types", "compatible_parent_types")
SKELETON_ID_FIELDS = ("skeleton_id", "skeleton_ids", "compatible_skeleton_ids")


def build_brief_sample(*, library, scopes, parent_type, audience_angles=None,
                       faq_questions=None, recent_combos=None, recent_endings=None,
                       avoid_skeleton_opening_pairs=None, rng=None):
    """Sample active pattern-library entries without reading other application storage."""
    rng = rng or random.Random()
    recent_combos = recent_combos if recent_combos is not None else []
    recent_endings = recent_endings if recent_endings is not None else []
    entries = _active_entries(library, scopes)
    skeletons = [
        entry for entry in entries
        if entry.get("kind") == "skeleton" and entry.get("payload", {}).get("parent_type") == parent_type
    ]
    if not skeletons:
        raise ValueError("missing_active_skeleton")
    recent = _recent_fingerprints(recent_combos)
    avoided_pairs = {
        (str(pair[0] or ""), str(pair[1] or ""))
        for pair in avoid_skeleton_opening_pairs or []
        if isinstance(pair, (tuple, list)) and len(pair) >= 2
    }
    for retry_count in range(MAX_FINGERPRINT_RETRIES + 1):
        result = _sample_once(
            entries, skeletons, parent_type, audience_angles or [], faq_questions or [],
            _latest_id(recent_endings), rng,
        )
        fingerprint = result["sampling_meta"]["fingerprint"]
        pair = _sample_pair(result)
        if fingerprint not in recent and pair not in avoided_pairs:
            result["sampling_meta"]["fingerprint_retries"] = retry_count
            result["sampling_meta"]["fingerprint_conflict"] = False
            result["sampling_meta"]["pair_retries"] = retry_count
            result["sampling_meta"]["pair_conflict"] = False
            result["recent_fingerprints"] = recent_combos
            return result
    result["sampling_meta"]["fingerprint_retries"] = MAX_FINGERPRINT_RETRIES
    result["sampling_meta"]["fingerprint_conflict"] = fingerprint in recent
    result["sampling_meta"]["pair_retries"] = MAX_FINGERPRINT_RETRIES
    result["sampling_meta"]["pair_conflict"] = pair in avoided_pairs
    result["recent_fingerprints"] = recent_combos
    return result


def _active_entries(library, scopes):
    entries = []
    seen_ids = set()
    for scope in scopes or []:
        for entry in library.list_entries(scope, status="active"):
            entry_id = entry.get("id")
            if entry_id and entry_id not in seen_ids:
                entries.append(entry)
                seen_ids.add(entry_id)
    return entries


def _sample_once(entries, skeletons, parent_type, audience_angles, faq_questions, recent_ending_id, rng):
    skeleton = rng.choice(skeletons)
    modules = [entry for entry in entries if entry.get("kind") == "module"]
    candidates = {
        "opening_module": _compatible_modules(modules, "开头", parent_type, skeleton["id"]),
        "ending_module": _compatible_modules(modules, "结尾", parent_type, skeleton["id"]),
        "faq_module": _compatible_modules(modules, "FAQ段", parent_type, skeleton["id"]),
        "table_module": _compatible_modules(modules, "对比表", parent_type, skeleton["id"]),
        "body_modules": _compatible_modules(modules, "其他", parent_type, skeleton["id"]),
    }
    free_slot = rng.choice(["opening_module", "ending_module", "body_modules"]) if rng.random() < FREE_SLOT_PROBABILITY else None
    opening = None if free_slot == "opening_module" else _choice(candidates["opening_module"], rng)
    ending, ending_retries = (None, 0) if free_slot == "ending_module" else _choose_ending(candidates["ending_module"], recent_ending_id, rng)
    faq = _choice(candidates["faq_module"], rng) if faq_questions and rng.random() < FAQ_PROBABILITY else None
    table = _choice(candidates["table_module"], rng) if rng.random() < TABLE_PROBABILITY else None
    body_count = rng.choices(
        list(BODY_MODULE_COUNT_WEIGHTS), weights=list(BODY_MODULE_COUNT_WEIGHTS.values()), k=1,
    )[0]
    body = [] if free_slot == "body_modules" else rng.sample(candidates["body_modules"], min(body_count, len(candidates["body_modules"])))
    opening_id = opening.get("id") if opening else ""
    return {
        "skeleton": _brief_entry(skeleton),
        "opening_module": _brief_entry(opening),
        "ending_module": _brief_entry(ending),
        "faq_module": _brief_entry(faq),
        "table_module": _brief_entry(table),
        "body_modules": [_brief_entry(entry) for entry in body],
        "free_slot": free_slot,
        "audience_angle": rng.choice(audience_angles) if audience_angles else "",
        "faq_questions": _faq_subset(faq_questions, rng) if faq else [],
        "competitors_passthrough": True,
        "sampling_meta": {
            "missing_slots": {slot: not bool(slot_candidates) for slot, slot_candidates in candidates.items()},
            "faq_module_reason": "faq_questions_empty" if not faq_questions else "",
            "fingerprint": f"{skeleton['id']}×{opening_id}",
            "fingerprint_retries": 0,
            "fingerprint_conflict": False,
            "pair_retries": 0,
            "pair_conflict": False,
            "ending_retries": ending_retries,
        },
    }


def _latest_id(values):
    return next((str(value or "").strip() for value in reversed(values or []) if str(value or "").strip()), "")


def _choose_ending(candidates, recent_ending_id, rng):
    if not candidates:
        return None, 0
    ending = rng.choice(candidates)
    if len(candidates) > 1 and recent_ending_id and ending.get("id") == recent_ending_id:
        return rng.choice([entry for entry in candidates if entry.get("id") != recent_ending_id]), 1
    return ending, 0


def _compatible_modules(modules, module_type, parent_type, skeleton_id):
    return [
        entry for entry in modules
        if _module_type(entry) == module_type and _is_compatible(entry, module_type, parent_type, skeleton_id)
    ]


def _module_type(entry):
    return str(entry.get("payload", {}).get("type") or "其他").strip() or "其他"


def _is_compatible(entry, module_type, parent_type, skeleton_id):
    rules = MODULE_COMPATIBILITY.get(module_type, {})
    if rules.get("parent_types") and parent_type not in rules["parent_types"]:
        return False
    payload = entry.get("payload") or {}
    for field in PARENT_TYPE_FIELDS:
        values = _values(payload.get(field))
        if values and parent_type not in values:
            return False
    for field in SKELETON_ID_FIELDS:
        values = _values(payload.get(field))
        if values and skeleton_id not in values:
            return False
    return True


def _values(value):
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    value = str(value or "").strip()
    return {value} if value else set()


def _choice(entries, rng):
    return rng.choice(entries) if entries else None


def _brief_entry(entry):
    if not entry:
        return None
    return {"id": entry["id"], "name": entry["name"], "payload": copy.deepcopy(entry.get("payload") or {})}


def _faq_subset(questions, rng):
    questions = [str(question).strip() for question in questions if str(question).strip()]
    if not questions:
        return []
    return rng.sample(questions, min(len(questions), rng.randint(3, 5)))


def _sample_pair(sample):
    skeleton_id = str((sample.get("skeleton") or {}).get("id") or "")
    opening_id = str((sample.get("opening_module") or {}).get("id") or "")
    return skeleton_id, opening_id


def _recent_fingerprints(recent_combos):
    fingerprints = set()
    for combo in recent_combos or []:
        if isinstance(combo, str):
            fingerprints.add(combo)
        elif isinstance(combo, (tuple, list)) and len(combo) >= 2:
            fingerprints.add(f"{combo[0]}×{combo[1]}")
        elif isinstance(combo, dict):
            fingerprint = combo.get("fingerprint")
            if fingerprint:
                fingerprints.add(str(fingerprint))
            else:
                fingerprints.add(f"{combo.get('skeleton_id', '')}×{combo.get('opening_module_id', '')}")
    return fingerprints


def build_planning_brief_prompt(sample, *, customer_material_text="", content_upload_text="",
                                competitor_markdown=""):
    """Build the constrained planner prompt; all facts remain caller-provided material."""
    sample = dict(sample or {})
    skeleton = sample.get("skeleton") or {}
    sections = (skeleton.get("payload") or {}).get("sections") or []
    if not skeleton or not sections:
        raise ValueError("missing_sampled_skeleton_sections")
    slot_instructions = _slot_instructions(sample)
    faq_questions = sample.get("faq_questions") or []
    faq_rule = (
        "- FAQ 只能使用下方给出的 FAQ 问题，不得另造 FAQ 问题。"
        if faq_questions else
        "- 当前 faq_questions 为空：直接省略 FAQ 结构位，不得出现任何 FAQ 相关段落、占位说明或建议运营补充类文字。"
    )
    faq_context = f"【可用 FAQ 问题】\n{json.dumps(faq_questions, ensure_ascii=False)}\n" if faq_questions else ""
    comparison_hard_structure = """
【对比型硬结构】
- 多机构对比块必须存在：正文中间必须安排一大块“本次品牌 + 多家真实机构”的逐个介绍与对比。其他机构只取自下方机构资料中的真实名称；每家要给出定位、服务侧重、适合人群和可核验信息，为用户提供选择依据。任何骨架、任何资料状况下都不得省略，也不得替换为路径、概念或学习形式对比。
- 本次品牌第一个介绍、不强行推荐：本次品牌建议作为第一个介绍对象，本次品牌小节的字数预算不低于 500 字，写成连贯的大段陈述而非条目罗列；可用输入资料展开更深，但不得写成“本次品牌就是最好/首选”的推荐结论；其他机构必须客观完整，不拉踩。必选竞品也不得置于本次品牌之前。
- 不得使用推荐等级词汇和分档标签：禁止最推荐、首推、强烈推荐、推荐指数、第一/第二/第三梯队、按需选择、谨慎考察、星级及任何机构推荐档次。机构只能按服务模式、供给性质、业务侧重或地域覆盖等中性维度分组；组的呈现顺序不代表排名，正文必须明示这一点。
- 本次品牌可第一个介绍且篇幅更深，但与其他机构使用同样的字段框架，不得借档位、定性词或章节标题制造高下。骨架自带排名、梯队或打分语义时，保留维度权重、横向对比表和来源声明等量化外壳，分档改写为中性分组。
- 其他机构在资料允许时充分展开，目标 200-400 字；可用信息较少时才少写并列出“咨询时可确认的问题”；可减少机构数量，但多机构对比总计保底 2-3 家。不得因可用信息较少把对比对象整体换成路径或概念。
- combo_warning 只用于报告缝合困难，不是改变文章对象类型、替换多机构对比或省略该对比块的授权。
""" if (skeleton.get("payload") or {}).get("parent_type") == "对比型" else ""
    return f"""你是 GEO 内容的策划简报 LLM。只输出 JSON，不要输出 Markdown、解释或成品文章。

你的职责是把已经抽签确定的文章形状，结合输入资料，写成施工简报。不得输出可直接发布的成品句子；“要点”只能写施工指令：写什么、采用什么资料、什么口径以及资料缺口提示。给写作层的指导涉及机构时一律使用机构名称；客户/竞品是内部称谓，不得出现在成文。信息缺口只能指示省略维度或改写为读者核验动作，不得指示写“未提供”“资料缺失”“待补充”。

【输出 JSON schema】
{{
  "title_candidates": ["2-3 个标题候选"],
  "angle_statement": "人群角度贯穿全文的一句主线",
  "sections": [{{"id": 1, "功能": "", "要点": "", "引用": ["资料小节名 > 不超过40字原文短摘录"], "字数": 250, "展开来源": ["客户资料包 > 产品与服务"]}}],
  "素材池": {{"机构名称或行业公共": [{{"表述": "读者视角的一句可用事实", "来源": "资料小节名"}}]}},
  "bans": ["禁用项"],
  "dedup_hints": "针对近期组合的具体规避指令",
  "combo_warning": "可选；仅在组合确实难缝合时说明，仍必须照做"
}}

【不可违反的抽样约束】
- 骨架和模块是抽签结果，不得替换、不得弃用。sections 必须严格对应骨架 sections 的顺序和数量。
- 开头、结尾、FAQ、对比表及正文模块必须按下方抽到的 pattern 套路实例化；只有标记“自由自拟”的槽位允许自拟写法。
- 如果组合难缝合，填写 combo_warning，但仍须按抽样结果完成全部 sections。
{faq_rule}
- 人群角度必须成为 angle_statement 主线，并贯穿每节要点。
- 所有事实只能来自输入资料。资料没有的信息不得编造，必须写入对应要点的“缺口提示”。引用只能使用“资料小节名 > 原文短摘录”的形式，禁止发明 F-xx 或其他不存在的 id。
- 本次品牌的介绍或展开节必须给出“展开来源”，指向客户资料包中真实存在的小节名（可多个），并在“要点”写清展开角度；多机构对比节中每家其他机构也必须给出“展开来源”，指向竞品 Markdown 的对应机构分节。展开来源只能指向输入资料中真实存在的小节名/机构名，不得发明。
- 素材池为可选字段，是保底清单而非唯一取材通道；按“本次品牌”“各家其他机构”“行业公共”分组。本次品牌一组要尽可能穷尽与人群角度相关的可用事实，目标 8-15 条，覆盖服务、流程、资质、费用口径、地域等多个资料小节；其他机构各自列出竞品资料中的中性可用事实，资料少就少列；行业公共一组放政策、时间节点类公共事实。池内条目鼓励用足，写作层也可按“展开来源”直接取材。
- 素材池每条必须是读者视角的可直接取用直接陈述句；来源保持“资料小节名”定位格式，仅供内部溯源、不进入正文，不得出现“客户/竞品/资料包”等内部称谓。每条必须可定位到输入资料，资料没有的不得进池。
- 读者核验动作或签约前提醒类内容每节最多出现 1-2 处，不得用核验、免责类句子替代实质内容。

{comparison_hard_structure}

【抽样骨架】
{json.dumps(skeleton, ensure_ascii=False)}

【骨架 section 顺序】
{json.dumps(sections, ensure_ascii=False)}

【模块槽位】
{slot_instructions}

【人群角度】
{sample.get('audience_angle') or '未指定；不得自行假定具体人群事实'}

{faq_context}

【近期指纹与避让】
{json.dumps(sample.get('recent_fingerprints') or [], ensure_ascii=False)}

【自动 bans：必须保留或细化，不得删掉】
{_automatic_bans(sample, customer_material_text, competitor_markdown)}

【客户资料】
{customer_material_text or '无客户资料；所有缺口必须明确标注'}

【内容生产独立上传资料】
{content_upload_text or '无独立上传资料'}

【竞品 Markdown】
{competitor_markdown or '无竞品资料'}
"""


def generate_planning_brief(sample, *, customer_material_text="", content_upload_text="", competitor_markdown="",
                            ai_json_fn):
    prompt = build_planning_brief_prompt(
        sample,
        customer_material_text=customer_material_text,
        content_upload_text=content_upload_text,
        competitor_markdown=competitor_markdown,
    )
    for _ in range(BRIEF_LLM_MAX_ATTEMPTS):
        raw = ai_json_fn(prompt, BRIEF_MAX_TOKENS)
        if isinstance(raw, str):
            if not raw.strip():
                continue
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid_planning_brief") from exc
        if not raw:
            continue
        return validate_planning_brief(raw, sample)
    raise ValueError("empty_planning_brief_response")


def validate_planning_brief(brief, sample):
    brief = dict(brief or {})
    titles = brief.get("title_candidates")
    sections = brief.get("sections")
    expected_sections = ((sample.get("skeleton") or {}).get("payload") or {}).get("sections") or []
    if not isinstance(titles, list) or not 2 <= len(titles) <= 3 or not all(str(title).strip() for title in titles):
        raise ValueError("invalid_planning_brief")
    if not isinstance(brief.get("angle_statement"), str) or not brief["angle_statement"].strip():
        raise ValueError("invalid_planning_brief")
    if not isinstance(sections, list) or not sections or len(sections) != len(expected_sections):
        raise ValueError("invalid_planning_brief")
    for index, section in enumerate(sections, 1):
        if not isinstance(section, dict) or section.get("id") != index:
            raise ValueError("invalid_planning_brief")
        if not str(section.get("功能") or "").strip() or not str(section.get("要点") or "").strip():
            raise ValueError("invalid_planning_brief")
        if not isinstance(section.get("引用"), list) or not isinstance(section.get("字数"), int):
            raise ValueError("invalid_planning_brief")
    if not isinstance(brief.get("bans"), list) or not isinstance(brief.get("dedup_hints"), str):
        raise ValueError("invalid_planning_brief")
    if "combo_warning" in brief and not isinstance(brief["combo_warning"], str):
        raise ValueError("invalid_planning_brief")
    return brief


def _slot_instructions(sample):
    labels = {
        "opening_module": "开头",
        "ending_module": "结尾",
        "faq_module": "FAQ",
        "table_module": "对比表",
        "body_modules": "正文模式",
    }
    lines = []
    for key, label in labels.items():
        if key == "faq_module" and not sample.get("faq_questions"):
            continue
        if sample.get("free_slot") == key:
            lines.append(f"- {label}：自由自拟（唯一允许自拟写法的位置）")
            continue
        value = sample.get(key)
        if key == "body_modules":
            value = value or []
            lines.append(f"- {label}：{json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"- {label}：{json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines)


def _automatic_bans(sample, customer_material_text, competitor_markdown):
    lines = [f"- 通用禁用词：{'、'.join(GENERAL_BANS)}", f"- 模板句禁令：{'、'.join(TEMPLATE_BANS)}"]
    material_context = _risk_lines(customer_material_text, ("限制使用", "合规", "风险", "禁止", "不得"))
    if material_context:
        lines.append("- 客户资料风险/限制使用：" + " | ".join(material_context))
    competitor_context = _risk_lines(competitor_markdown, ("宣传主张", "强主张", "通过率", "第一", "唯一", "最好", "排名"))
    if competitor_context:
        lines.append("- 竞品宣传主张（LLM 识别，置信度低）：" + " | ".join(competitor_context))
    for entry in _sampled_entries(sample):
        risk_notes = str((entry.get("payload") or {}).get("risk_notes") or "").strip()
        if "手段禁用" in risk_notes:
            lines.append(f"- 抽中条目风险（手段禁用）：{risk_notes}")
    return "\n".join(lines)


def _risk_lines(text, keywords):
    return [line.strip()[:300] for line in str(text or "").splitlines() if any(word in line for word in keywords)][:12]


def _sampled_entries(sample):
    entries = [sample.get(key) for key in ("skeleton", "opening_module", "ending_module", "faq_module", "table_module")]
    entries.extend(sample.get("body_modules") or [])
    return [entry for entry in entries if isinstance(entry, dict)]
