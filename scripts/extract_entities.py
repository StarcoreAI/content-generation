import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from openai import OpenAI


VEHICLE_BRAND_WORDS = {
    "宝马", "奔驰", "奥迪", "特斯拉", "比亚迪", "极氪", "捷豹", "马自达",
    "传祺", "本田", "丰田", "大众", "日产", "理想", "蔚来", "小鹏",
}
EXCLUDED_TYPES = {"车型", "整车品牌", "汽车品牌", "车系"}


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_name(value):
    return re.sub(r"\s+", "", str(value or "")).strip("，。,.、：:；;（）()[]【】")


def brand_aliases(brand):
    name = normalize_name(brand)
    aliases = {name}
    for prefix in ("扬州", "南京", "苏州", "上海", "北京", "广州", "深圳"):
        if name.startswith(prefix) and len(name) > len(prefix):
            aliases.add(name[len(prefix):])
    if name.endswith("汽车音响") and len(name) > 4:
        aliases.add(name[:-4])
    if len(name) >= 2:
        aliases.add(name[:2])
    return {item for item in aliases if item}


def clean_json_text(raw):
    text = str(raw or "").strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.I)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return text.strip()


def parse_entity_response(raw, own_brand=""):
    payload = json.loads(clean_json_text(raw))
    raw_entities = payload.get("entities", []) if isinstance(payload, dict) else []
    aliases = brand_aliases(own_brand)
    entities = []
    seen = set()
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = normalize_name(item.get("name", ""))
        if not name or name in aliases:
            continue
        entity_type = str(item.get("type") or "未知").strip()[:20]
        if entity_type in EXCLUDED_TYPES:
            continue
        if any(word in name for word in VEHICLE_BRAND_WORDS) and "音响" not in name and "影音" not in name:
            continue
        if any(alias and (name == alias or name in alias or alias in name) for alias in aliases if len(alias) >= 2):
            continue
        if name in seen:
            continue
        seen.add(name)
        entities.append({
            "name": name,
            "type": entity_type,
            "sentiment": str(item.get("sentiment") or "neutral").strip()[:20],
            "evidence": str(item.get("evidence") or "").strip()[:120],
        })
    return entities


def build_entity_prompt(record):
    brand = record.get("brand", "")
    answer = (record.get("answer") or "")[:5000]
    return f"""你是GEO数据清洗助手。请从以下AI回答正文中抽取被推荐、被比较或被提及的门店、品牌、公司名。

要求：
- 排除本客户品牌及其简称：{brand}
- 不要抽取通用词，如汽车音响、改装店、门店、公司、商家
- 只抽取汽车音响改装门店、汽车音响服务品牌、汽车音响器材品牌
- 排除车型、整车品牌、车主车型名，例如宝马X5、特斯拉、比亚迪、极氪、捷豹XFL、马自达CX-5、传祺GS8
- 只返回正文中明确出现的实体名，不要编造
- evidence 必须是回答中的短片段
- 输出严格 JSON，不要解释

JSON格式：
{{
  "entities": [
    {{
      "name": "实体名",
      "type": "门店/品牌/公司/其他",
      "sentiment": "positive/neutral/negative",
      "evidence": "回答中的短片段"
    }}
  ]
}}

AI回答正文：
{answer}
"""


def select_records(records, client_id="", date="", task_id="", limit=0, include_existing=False):
    selected = []
    for record in records:
        if client_id and record.get("client_id") != client_id:
            continue
        if date and record.get("today") != date:
            continue
        if task_id and record.get("task_id") != task_id:
            continue
        if not include_existing and record.get("mentioned_entities"):
            continue
        if not (record.get("answer") or "").strip():
            continue
        selected.append(record)
        if limit and len(selected) >= limit:
            break
    return selected


def get_openai_client(settings):
    api_key = settings.get("api_key")
    if not api_key:
        raise RuntimeError("settings.json 中没有 api_key，无法调用 LLM 抽取")
    return OpenAI(
        api_key=api_key,
        base_url=settings.get("base_url") or "https://api.deepseek.com",
    )


def extract_for_records(records, settings, client=None):
    client = client or get_openai_client(settings)
    model = settings.get("model") or "deepseek-chat"
    results = []
    for record in records:
        result = {
            "record_id": record.get("id"),
            "question": record.get("question"),
            "source_platform": record.get("source_platform"),
            "task_id": record.get("task_id", ""),
            "entities": [],
        }
        try:
            prompt = build_entity_prompt(record)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=800,
            )
            raw = response.choices[0].message.content
            result["entities"] = parse_entity_response(raw, own_brand=record.get("brand", ""))
        except Exception as exc:
            result["error"] = str(exc)
        results.append(result)
    return results


def apply_entity_results(raw_records_path, records, results):
    by_id = {item["record_id"]: item.get("entities", []) for item in results}
    changed = 0
    for record in records:
        if record.get("id") in by_id:
            record["mentioned_entities"] = by_id[record.get("id")]
            changed += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{raw_records_path}.bak_entities_{timestamp}"
    shutil.copy2(raw_records_path, backup_path)
    write_json(raw_records_path, records)
    return {"changed": changed, "backup_path": backup_path}


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Extract mentioned brands/stores from raw record answers.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--date", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data_dir)
    raw_records_path = data_dir / "raw_records.json"
    records = read_json(raw_records_path, [])
    settings = read_json(data_dir / "settings.json", {})
    selected = select_records(
        records,
        client_id=args.client_id,
        date=args.date,
        task_id=args.task_id,
        limit=args.limit,
        include_existing=args.include_existing,
    )
    results = extract_for_records(selected, settings)
    output = {
        "dry_run": not args.apply,
        "selected": len(selected),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.apply:
        apply_result = apply_entity_results(str(raw_records_path), records, results)
        print(json.dumps({"applied": apply_result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
