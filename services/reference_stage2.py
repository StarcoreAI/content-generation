def _text(value, limit=800):
    return str(value or "").strip()[:limit]


def _list_text(value, limit=12):
    if not isinstance(value, list):
        value = [value] if value else []
    result = []
    for item in value:
        text = _text(item, 500)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _indexes(value):
    result = []
    for item in value if isinstance(value, list) else []:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def build_stage2_prompt(analyses):
    items = []
    for index, item in enumerate(analyses, 1):
        items.append({
            "index": index,
            "parent_type": _text(item.get("parent_type"), 20),
            "opening": _text(item.get("opening"), 700),
            "body": _list_text(item.get("body"), limit=10),
            "ending": _text(item.get("ending"), 700),
        })
    return f"""你是 GEO 引用文章写法聚类分析员。请阅读这些单篇文章结构，把相似写法合并成少量结构簇，并给每个簇命名一个子类型名。

只做阶段2：合并相似写法 + 命名子类型。不要写第三阶段的可插入内容生成指令。

你只能输出 JSON，不要输出 Markdown。字段只能是：
{{
  "clusters": [
    {{
      "parent_type": "对比型/介绍型",
      "subtype_name": "具体中文子类型名",
      "article_indexes": [1, 2],
      "shared_structure": {{
        "opening": "这些文章共同的开头写法",
        "body": ["这些文章共同的正文模块"],
        "ending": "这些文章共同的结尾写法"
      }}
    }}
  ]
}}

规则：
- parent_type 必须是“对比型”或“介绍型”，优先沿用输入文章的父类型。
- subtype_name 要具体，不要只写“对比型”或“介绍型”。
- article_indexes 只能使用输入里的 index。
- shared_structure 只总结共同结构，不要生成最终文案。
- 相似文章可以合并；明显不同的写法不要硬合并。

【阶段1结构列表】
{items}
"""


def normalize_stage2_result(raw):
    raw = raw if isinstance(raw, dict) else {}
    clusters = []
    for item in raw.get("clusters") if isinstance(raw.get("clusters"), list) else []:
        item = item if isinstance(item, dict) else {}
        parent_type = _text(item.get("parent_type"), 20)
        if parent_type not in {"对比型", "介绍型"}:
            parent_type = "介绍型"
        shared = item.get("shared_structure") if isinstance(item.get("shared_structure"), dict) else {}
        clusters.append({
            "parent_type": parent_type,
            "subtype_name": _text(item.get("subtype_name"), 80),
            "article_indexes": _indexes(item.get("article_indexes")),
            "shared_structure": {
                "opening": _text(shared.get("opening"), 1000),
                "body": _list_text(shared.get("body"), limit=12),
                "ending": _text(shared.get("ending"), 1000),
            },
        })
    return {"clusters": clusters}


def analyze_stage2_clusters(analyses, ai_json_fn):
    prompt = build_stage2_prompt(analyses)
    raw = ai_json_fn(prompt, 2400)
    return normalize_stage2_result(raw)
