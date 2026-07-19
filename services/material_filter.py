import hashlib
import re
import unicodedata


MODEL_FILTER_STATUSES = frozenset(
    {"core", "representative", "redundant", "irrelevant", "reference_only"}
)
KEPT_STATUSES = frozenset({"core", "representative"})

DEFAULT_FILTER_RULES = """基于整个资料包，判断每个资料单元是否值得进入整理后的默认客户资料包。

保留包含可复用客户自身信息的单元，例如可核验事实、服务或产品、核心参数、对外服务流程、业务边界、合规要求、资质、适用对象、价格表达和第一方证据。
过滤没有客户自身有效信息的单元，例如空内容、格式噪声、通用模板、占位内容、无关第三方资料、普通内部执行记录、只有宣传形容词而没有事实依据的内容，以及只适合作为独立查询库的低层级明细。

整理后的客户资料包会按八个方向组织，因此包含下列任一方向的资料单元都应优先保留：
1. 品牌基础：主体名称、正规性、成立时间与背景、所在地与覆盖范围、业务范围。
2. 产品与服务：提供什么、怎么交付、服务流程和深度、售后与长期服务能力。
3. 核心优势：差异点、支撑差异点的事实、流程、资源、机制；不要把口号当优势。
4. 目标人群与需求痛点：谁在用、解决什么问题、决策顾虑、典型使用场景；可保留明确标注为推断或待确认的线索。
5. 价格与费用表达：资料原有的价格区间、费用构成、费用表达口径。
6. 信任凭证：资质、荣誉、案例、用户评价、第三方背书，以及出处性质。
7. 合规风险表述：绝对化用语、效果承诺、无法证实的数字、包过/第一/保证类表述；这些内容要保留为风险线索，不要洗成事实。
8. 行业公共背景：资料中已有的政策、时间节点、公共数据、官方规则。
资料没有的，不要编造；但如果资料单元明确指出缺失信息、待补证据、检索方向或需客户确认，应保留，供最终资料包登记到“缺口与检索提示”。

必须在整个资料包范围内比较重复性：
- 内容近似相同的单元只保留信息更完整、表达更清晰的一份。
- 同一数据集拆分出的多个结构相似单元属于一个重复组。优先保留汇总单元；没有汇总单元时，最多保留 6 个有代表性的明细单元。
- 输入中的 same_source_unit_count 和“同源多单元组”是强分组信号；同一 source_path 下用途和结构相近的表格单元不得分别全部标为 core。
- 同一用途但信息并不完全相同的案例、示例或说明也属于一个重复组，优先覆盖不同信息维度，最多保留 6 个代表。
- 每个重复组最多保留 6 个是硬性上限。组内细节不同不能作为全部保留的理由；未选中的明细资料应判为 redundant 或 reference_only。
- 只有包含客户全局关键事实、业务边界或合规风险的独有单元可以脱离重复组单独保留，普通行项差异不属于这个例外。
- “拿不准时保留”只适用于不属于重复组的单元；重复组内拿不准时仍须选出最多 6 个代表。

这里只决定整个资料单元的去留，不裁剪段落，不改写事实，不补充外部信息。"""

_MIDDLE_MARKER = "\n...[中部节选]...\n"
_TAIL_MARKER = "\n...[结尾节选]...\n"


def format_unit_metadata(unit, same_source_unit_count=1):
    text = str(unit.get("text") or "")
    fields = [
        ("unit_id", unit.get("unit_id")),
        ("path", unit.get("path")),
        ("kind", unit.get("kind")),
        ("extract_status", unit.get("extract_status")),
        ("sheet_name", unit.get("sheet_name")),
        ("row_count", unit.get("row_count")),
        ("column_count", unit.get("column_count")),
        ("完整字符数", len(text)),
    ]
    if same_source_unit_count > 1:
        fields.append(("same_source_unit_count", same_source_unit_count))
    columns = unit.get("columns")
    if columns:
        fields.append(("columns", " | ".join(str(item) for item in columns)))
    return "\n".join(
        f"{key}: {value}" for key, value in fields if value not in (None, "", [])
    )


def sample_unit_text(unit, max_chars=1800):
    """Return a bounded head/middle/tail preview for package-level comparison."""
    text = str(unit.get("text") or "").strip()
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return text

    marker_chars = len(_MIDDLE_MARKER) + len(_TAIL_MARKER)
    if max_chars <= marker_chars + 12:
        return text[:max_chars]

    available = max_chars - marker_chars
    head_chars = available // 2
    middle_chars = available // 4
    tail_chars = available - head_chars - middle_chars
    middle_start = max(0, (len(text) - middle_chars) // 2)
    return (
        text[:head_chars]
        + _MIDDLE_MARKER
        + text[middle_start : middle_start + middle_chars]
        + _TAIL_MARKER
        + text[-tail_chars:]
    )


def _normalized_text_hash(text):
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = re.sub(r"\s+", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _prepare_units(units):
    readable = []
    candidates = []
    deterministic = {}
    first_by_hash = {}
    seen_ids = set()

    for unit in units:
        unit_id = str(unit.get("unit_id") or "").strip()
        text = str(unit.get("text") or "").strip()
        if not text:
            continue
        if not unit_id:
            raise ValueError("unit_id is required")
        if unit_id in seen_ids:
            raise ValueError(f"duplicate input unit_id: {unit_id}")
        seen_ids.add(unit_id)
        readable.append(unit)

        if unit.get("extract_status") == "needs_conversion" or unit.get("kind") == "legacy_office":
            deterministic[unit_id] = {
                "unit_id": unit_id,
                "status": "needs_conversion",
            }
            continue

        digest = _normalized_text_hash(text)
        duplicate_of = first_by_hash.get(digest)
        if duplicate_of:
            deterministic[unit_id] = {
                "unit_id": unit_id,
                "status": "exact_duplicate",
                "duplicate_of": duplicate_of,
            }
            continue

        first_by_hash[digest] = unit_id
        candidates.append(unit)

    return readable, candidates, deterministic


def _build_package_prompt(candidates, question, preview_chars):
    source_groups = {}
    for unit in candidates:
        source_path = str(unit.get("path") or unit.get("unit_id") or "").strip()
        source_groups.setdefault(source_path, []).append(str(unit.get("unit_id") or "").strip())

    group_lines = [
        f"- source_path: {source_path}\n  unit_ids: {' | '.join(unit_ids)}"
        for source_path, unit_ids in source_groups.items()
        if len(unit_ids) > 1
    ]
    group_section = "同源多单元组：\n" + ("\n".join(group_lines) if group_lines else "无")

    blocks = []
    for unit in candidates:
        source_path = str(unit.get("path") or unit.get("unit_id") or "").strip()
        blocks.append(
            "=== 资料单元 ===\n"
            f"{format_unit_metadata(unit, len(source_groups[source_path]))}\n"
            "资料节选：\n"
            f"{sample_unit_text(unit, max_chars=preview_chars)}"
        )

    return (
        "你是客户资料一级筛选 Worker。下面一次提供同一个资料包中的全部候选单元。"
        "请先比较整个资料包，再逐个决定是否保留；不要孤立判断单个文件。\n\n"
        f"判断规则：\n{question}\n\n"
        f"{group_section}\n\n"
        "必须只返回一个 JSON 对象，格式为：\n"
        '{"results":[{"unit_id":"原始 ID","status":"core"}]}\n'
        "results 必须覆盖下面每个资料单元且每个 ID 只出现一次；不得创造或改写 ID。"
        "status 只能是 core、representative、redundant、irrelevant 或 reference_only。"
        "core 和 representative 表示保留，其余状态表示不进入默认资料包。\n\n"
        + "\n\n".join(blocks)
    )


def _parse_model_decisions(payload, candidate_ids):
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("package filter response must contain a results list")

    expected = set(candidate_ids)
    decisions = {}
    for item in payload["results"]:
        if not isinstance(item, dict):
            raise ValueError("each filter decision must be an object")
        unit_id = str(item.get("unit_id") or "").strip()
        if unit_id not in expected:
            raise ValueError(f"unknown filter decision unit_id: {unit_id}")
        if unit_id in decisions:
            raise ValueError(f"duplicate filter decision unit_id: {unit_id}")
        status = str(item.get("status") or "").strip()
        if status not in MODEL_FILTER_STATUSES:
            raise ValueError(f"unknown filter status for {unit_id}: {status}")
        decisions[unit_id] = {"unit_id": unit_id, "status": status}

    missing = [unit_id for unit_id in candidate_ids if unit_id not in decisions]
    if missing:
        raise ValueError("missing filter decisions: " + ", ".join(missing))
    return decisions


def filter_material_units(
    units,
    ask_json,
    question=None,
    max_tokens=4096,
    preview_chars=1800,
):
    if ask_json is None:
        raise ValueError("ask_json is required")
    question = str(question or DEFAULT_FILTER_RULES).strip()
    if not question:
        raise ValueError("question is required")

    readable, candidates, deterministic = _prepare_units(units)
    if len(readable) < 3:
        return [
            deterministic.get(str(unit["unit_id"]).strip())
            or {"unit_id": str(unit["unit_id"]).strip(), "status": "core"}
            for unit in readable
        ]

    model_decisions = {}
    if candidates:
        prompt = _build_package_prompt(candidates, question, preview_chars)
        payload = ask_json(prompt, max_tokens=max_tokens)
        candidate_ids = [str(unit["unit_id"]).strip() for unit in candidates]
        model_decisions = _parse_model_decisions(payload, candidate_ids)

    return [
        deterministic.get(str(unit["unit_id"]).strip())
        or model_decisions[str(unit["unit_id"]).strip()]
        for unit in readable
    ]
