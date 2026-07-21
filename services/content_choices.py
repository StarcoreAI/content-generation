"""Stable customer content choices and per-article competitor subsets."""
import random
import re


def normalize_choice_items(value, default_source="manual"):
    values = value.splitlines() if isinstance(value, str) else value
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        item = value if isinstance(value, dict) else {"text": value}
        text = str(item.get("text") or "").strip()[:200]
        if not text or any(row["text"] == text for row in result):
            continue
        result.append({
            "text": text,
            "enabled": bool(item.get("enabled", True)),
            "source": str(item.get("source") or default_source).strip() or default_source,
        })
    return result


def active_choice_texts(value):
    return [item["text"] for item in normalize_choice_items(value) if item["enabled"]]


def choice_state(value):
    items = normalize_choice_items(value)
    if not items:
        return "missing"
    return "active" if any(item["enabled"] for item in items) else "all_disabled"


def normalize_competitor_rules(value):
    value = value if isinstance(value, dict) else {}
    result = {}
    for key in ("must_use", "banned"):
        names = value.get(key) or []
        if isinstance(names, str):
            names = re.split(r"[\n,，]+", names)
        result[key] = []
        for name in names if isinstance(names, list) else []:
            name = str(name or "").strip()
            if name and name not in result[key]:
                result[key].append(name)
    result["banned"] = [name for name in result["banned"] if name not in result["must_use"]]
    return result


def select_competitor_names(candidates, rules=None, *, rng=None, avoid_names=None, client_brand=""):
    """Keep required candidates, exclude banned ones, then fill a 2–4 institution subset."""
    rng = rng or random.Random()
    candidates = _unique(candidates)
    client_brand = str(client_brand or "").strip()
    candidates = [name for name in candidates if name != client_brand]
    rules = normalize_competitor_rules(rules)
    required = [name for name in rules["must_use"] if name in candidates]
    banned = set(rules["banned"])
    pool = [name for name in candidates if name not in required and name not in banned]
    avoid = set(avoid_names or [])
    preferred = [name for name in pool if name not in avoid]
    fallback = [name for name in pool if name in avoid]
    rng.shuffle(preferred)
    rng.shuffle(fallback)
    target = min(4, max(2, len(required)))
    return required + (preferred + fallback)[:max(0, target - len(required))]


def filter_competitor_markdown(markdown, selected_names, candidate_names):
    selected = set(selected_names or [])
    candidates = set(candidate_names or [])
    lines = str(markdown or "").splitlines()
    kept, current = [], None
    for line in lines:
        heading = _heading_name(line)
        if heading in candidates:
            current = heading
        if current in selected:
            kept.append(line)
    return "\n".join(kept).strip()


def _heading_name(line):
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", str(line or ""))
    if not match:
        return ""
    name = re.sub(r"^(?:竞品(?:名称)?\s*[:：]\s*)", "", match.group(1)).strip()
    return re.split(r"[（(]", name, maxsplit=1)[0].strip(" *#:-：")


def _unique(values):
    result = []
    for value in values or []:
        value = str(value or "").strip()
        if value and value not in result:
            result.append(value)
    return result
