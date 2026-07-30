from services.material_filter import format_unit_metadata


DEFAULT_REDUCER_RULES = """You are trimming retained customer material for later GEO article generation.
Your job is to decide which original lines should be deleted, not to rewrite or summarize the material.
Keep only customer-specific facts that can later be stated directly in an article: brand basics, products and services, customer-specific methods or service logic, supported fit boundaries, price and fee wording, and trust credentials.
For original brand, person, case, service, or technical material, preserve concrete details and representative original expressions that support those facts.
Keep original price ranges and fee wording only; do not calculate or complete missing prices. Keep qualifications, honors, cases, team or organization facts only when they describe this customer.
Delete strategy notes, usable angles, writing directions, templates, FAQs, generic user questions, customer-service scripts, scene words, example queries, and generic industry background.
Delete generic public education about policy, compliance, risks, recovery, market trends, or legal guidance unless it is a concrete fact about this customer's own service.
Delete source labels, search hints, pending-verification notes, internal execution notes, handoff notes, placeholders, blank fields, competitor notes, unrelated examples, duplicated statements, and generic praise without facts.
Delete unsupported strong claims, guarantees, rankings, success rates, absolute statements, and third-party catalogs that add no customer-specific facts.
For any unit that is only a third-party catalog, price list, item list, schedule, or low-level listing without customer-specific facts, delete all lines.
Do not use external knowledge. Do not write an article. Do not invent facts."""


def _numbered_lines(text):
    lines = str(text or "").strip().splitlines()
    return "\n".join(f"[{index:03d}] {line}" for index, line in enumerate(lines, 1))


def _build_reducer_prompt(units, question):
    blocks = []
    for unit in units:
        blocks.append(
            "=== Material Unit ===\n"
            f"{format_unit_metadata(unit)}\n"
            "Numbered material text:\n"
            f"{_numbered_lines(unit.get('text'))}"
        )

    return (
        "You are the second-stage Material Reducer. Review all retained units together, "
        "deduplicate facts across the package, and return only line ranges to delete.\n\n"
        f"Rules:\n{question}\n\n"
        "Return only one JSON object in this exact shape:\n"
        '{"results":[{"unit_id":"original ID","delete_unit":false,"delete_ranges":[{"start":1,"end":2}]}]}\n'
        "Every input unit_id must appear exactly once. Do not create or rewrite IDs. "
        "Use delete_unit true when the whole unit should be removed. "
        "Use an empty delete_ranges list when no lines should be deleted. "
        "Line numbers are 1-based and inclusive. Do not return rewritten text.\n\n"
        + "\n\n".join(blocks)
    )


def _apply_delete_ranges(text, delete_ranges):
    lines = str(text or "").strip().splitlines()
    deleted = set()
    for delete_range in delete_ranges:
        if not isinstance(delete_range, dict):
            raise ValueError("each delete range must be an object")
        start = delete_range.get("start")
        end = delete_range.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("delete range start and end must be integers")
        if start < 1 or end < start or end > len(lines):
            raise ValueError(f"invalid delete range: {start}-{end}")
        deleted.update(range(start, end + 1))
    return "\n".join(
        line for index, line in enumerate(lines, 1) if index not in deleted
    ).strip()


def _parse_reducer_results(payload, units):
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("material reducer response must contain a results list")

    unit_ids = [str(unit.get("unit_id") or "").strip() for unit in units]
    expected = set(unit_ids)
    unit_by_id = {str(unit.get("unit_id") or "").strip(): unit for unit in units}
    results = {}
    for item in payload["results"]:
        if not isinstance(item, dict):
            raise ValueError("each reducer result must be an object")
        unit_id = str(item.get("unit_id") or "").strip()
        if unit_id not in expected:
            raise ValueError(f"unknown reducer unit_id: {unit_id}")
        if unit_id in results:
            raise ValueError(f"duplicate reducer unit_id: {unit_id}")
        if item.get("delete_unit") is True:
            reduced_text = ""
        else:
            delete_ranges = item.get("delete_ranges") or []
            if not isinstance(delete_ranges, list):
                raise ValueError(f"delete_ranges must be a list for {unit_id}")
            reduced_text = _apply_delete_ranges(unit_by_id[unit_id].get("text"), delete_ranges)
        results[unit_id] = {
            "unit_id": unit_id,
            "reduced_text": reduced_text,
        }

    missing = [unit_id for unit_id in unit_ids if unit_id not in results]
    if missing:
        raise ValueError("missing reducer results: " + ", ".join(missing))
    return [results[unit_id] for unit_id in unit_ids]


def reduce_material_units(units, ask_json, question=None, max_tokens=8192):
    if ask_json is None:
        raise ValueError("ask_json is required")
    question = str(question or DEFAULT_REDUCER_RULES).strip()
    if not question:
        raise ValueError("question is required")

    unit_ids = []
    selected = []
    seen = set()
    for unit in units:
        unit_id = str(unit.get("unit_id") or "").strip()
        if not unit_id:
            raise ValueError("unit_id is required")
        if unit_id in seen:
            raise ValueError(f"duplicate input unit_id: {unit_id}")
        seen.add(unit_id)
        unit_ids.append(unit_id)
        selected.append(unit)

    if not selected:
        return []

    prompt = _build_reducer_prompt(selected, question)
    payload = ask_json(prompt, max_tokens=max_tokens)
    return _parse_reducer_results(payload, selected)
