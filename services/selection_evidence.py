"""Cached article surfaces used by the records-library scene-term prompt."""
import hashlib
import json
import re
from pathlib import Path

from services.article_fetcher import fetch_article_text
from services.selection_surface import MISSING, aggregate_selection_articles, extract_selection_surface, first_content_block
from services.storage import load_json, save_json


SCENE_RULE_VERSION = "2"
SCENE_ENTITY_SUFFIXES = ("教育", "培训", "机构", "学校", "医院", "公司", "门店", "诊所", "中心", "大学", "学院")


def _surface_value(value):
    value = str(value or "").strip()
    return "" if value == MISSING else value


class SelectionEvidenceService:
    def __init__(self, root_dir, fetch_article=fetch_article_text):
        self.root_dir = Path(root_dir)
        self.fetch_article = fetch_article

    def _client_dir(self, client_id):
        return self.root_dir / str(client_id)

    def _surface_path(self, client_id):
        return self._client_dir(client_id) / "article_surfaces.json"

    def _scene_path(self, client_id):
        return self._client_dir(client_id) / "query_scenes.json"

    def _load_surfaces(self, client_id):
        path = self._surface_path(client_id)
        data = load_json(path, {}) if path.exists() else {}
        return data if isinstance(data, dict) else {}

    def _article_surface(self, client_id, article, cached):
        url = str(article.get("url") or "").strip()
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        saved = cached.get(key)
        if isinstance(saved, dict) and saved.get("url") == url:
            return saved

        result = self.fetch_article(url, include_html=True, accept_metadata=True)
        surface = extract_selection_surface(result.get("html") or "")
        entry = {
            "url": url,
            "title": _surface_value(surface["title"]) or str(article.get("title") or "").strip(),
            "meta_description": _surface_value(surface["meta_description"]) or str(result.get("description") or "").strip(),
            "first_paragraph": _surface_value(surface["first_paragraph"]) or first_content_block(result.get("content") or ""),
            "fetch_ok": bool(result.get("ok")),
        }
        entry["first_paragraph"] = _surface_value(entry["first_paragraph"])[:300]
        cached[key] = entry
        return entry

    def build_group_query_evidence(self, client_id, groups, records, persist=True):
        cached = self._load_surfaces(client_id)
        units = []
        for group in groups or []:
            group_id = str(group.get("id") or "").strip()
            if not group_id:
                continue
            group_records = [record for record in records or [] if record.get("group_id") == group_id]
            for query in group.get("questions") or []:
                query = str(query or "").strip()
                if not query:
                    continue
                query_records = [record for record in group_records if (
                    str(record.get("question") or "").strip() == query and record.get("refs")
                )]
                articles = aggregate_selection_articles(query_records, top=None)[:3]
                if len(articles) < 3:
                    continue
                surfaces = [self._article_surface(client_id, article, cached) for article in articles]
                units.append({
                    "group_id": group_id,
                    "group_name": str(group.get("name") or "").strip() or "未命名问题组",
                    "query": query,
                    "articles": surfaces,
                })
        if persist:
            save_json(self._surface_path(client_id), cached)
        return units

    @staticmethod
    def _scene_key(unit):
        return f"{unit['group_id']}\n{unit['query']}"

    @staticmethod
    def _evidence_fingerprint(unit):
        text = json.dumps({
            "scene_rule_version": SCENE_RULE_VERSION,
            "query": unit["query"],
            "articles": [{
                "url": item["url"],
                "title": item["title"],
                "meta_description": item["meta_description"],
                "first_paragraph": item["first_paragraph"],
            } for item in unit["articles"]],
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean_scene_terms(terms):
        cleaned = []
        for term in terms or []:
            term = str(term or "").strip()
            compact = re.sub(r"\s+", "", term)
            entity_text = re.sub(r"[（(][^（）()]*[）)]$", "", compact)
            is_article_fact = (
                any(char.isdigit() for char in compact)
                or "app" in compact.lower()
                or any(char in compact for char in "、,，；;：:")
                or entity_text.endswith(SCENE_ENTITY_SUFFIXES)
            )
            if not term or term in cleaned or is_article_fact:
                continue
            cleaned.append(term)
        return cleaned

    @staticmethod
    def _prompt(units):
        items = []
        for unit in units:
            articles = "\n".join(
                f"- 标题：{item['title'] or '无'}\n  Meta：{item['meta_description'] or '无'}\n  首段：{item['first_paragraph'] or '无'}"
                for item in unit["articles"]
            ) or "- 无可用高引用文章表面"
            items.append(
                f"问题组 ID：{unit['group_id']}\n问题组：{unit['group_name']}\nQuery：{unit['query']}\n高引用文章表面：\n{articles}"
            )
        return """你是运营提示助手。AI 平台会根据 Query 生成检索关键词，再用这些关键词检索引用来源。根据每个 Query 与其高引用文章的标题、Meta、首段，提取文章已经写出的、能解释它为何被该 Query 检到并引用的具体场景表达，供运营判断怎样写。
请直接判断：AI 为匹配用户需求时可能实际使用的检索关键词是什么。场景词既可以是用户会自然带入提问的具体人群、症状、使用场景、决策阶段或明确顾虑，也可以是能帮助召回合适文章的具体机制、流程、服务方式或判断词。不要把客户名、竞品名、机构名单、数字、比例、市场数据、APP/平台名或文章标题/正文中的名单直接复制出来；不要做同义词扩展。
必须过滤没有实际信息的泛化词：推荐、哪个好、哪家好、怎么样、价格、排名、靠谱、对比、注意事项、怎么选。
只返回 JSON：{\"items\":[{\"group_id\":\"...\",\"query\":\"...\",\"scene_terms\":[\"...\"]}]}。每项只对应给定的同一 group_id 和 Query。

""" + "\n\n---\n\n".join(items)

    @staticmethod
    def _rows(entries, groups=None):
        allowed = None
        if groups is not None:
            allowed = {
                f"{str(group.get('id') or '').strip()}\n{str(query or '').strip()}"
                for group in groups or []
                for query in (group.get("questions") or [])
                if str(group.get("id") or "").strip() and str(query or "").strip()
            }
        rows = []
        for key, entry in entries.items():
            if allowed is not None and key not in allowed:
                continue
            if not isinstance(entry, dict):
                continue
            rows.append({
                "group_id": entry.get("group_id", ""),
                "group_name": entry.get("group_name", "未命名问题组"),
                "query": entry.get("query", ""),
                "scene_terms": list(entry.get("scene_terms") or []),
            })
        return rows

    def load_query_scene_rows(self, client_id, groups=None):
        path = self._scene_path(client_id)
        data = load_json(path, {"entries": {}}) if path.exists() else {"entries": {}}
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        return self._rows(entries, groups)

    def save_query_scene_terms(self, client_id, group_id, group_name, query, scene_terms):
        path = self._scene_path(client_id)
        data = load_json(path, {"entries": {}}) if path.exists() else {"entries": {}}
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        key = f"{str(group_id or '').strip()}\n{str(query or '').strip()}"
        current = entries.get(key)
        if not isinstance(current, dict):
            raise ValueError("scene_terms_not_found")
        updated = {
            **current,
            "group_id": str(group_id or "").strip(),
            "group_name": str(group_name or "").strip() or "未命名问题组",
            "query": str(query or "").strip(),
            "scene_terms": self._clean_scene_terms(scene_terms),
        }
        save_json(path, {"entries": {**entries, key: updated}})
        return updated

    def refresh_query_scenes(self, client_id, groups, records, ask_json, dry_run=False):
        units = self.build_group_query_evidence(client_id, groups, records, persist=not dry_run)
        scene_path = self._scene_path(client_id)
        data = load_json(scene_path, {"entries": {}}) if scene_path.exists() else {"entries": {}}
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        changed = []
        for unit in units:
            key = self._scene_key(unit)
            unit["evidence_fingerprint"] = self._evidence_fingerprint(unit)
            if entries.get(key, {}).get("evidence_fingerprint") != unit["evidence_fingerprint"]:
                changed.append(unit)

        if not changed:
            return {"rows": self._rows(entries, groups), "updated": 0, "error": "", "dry_run": dry_run}

        try:
            response = ask_json(self._prompt(changed), 4000)
        except Exception as exc:
            return {"rows": self._rows(entries, groups), "updated": 0, "error": str(exc), "dry_run": dry_run}

        items = response.get("items", []) if isinstance(response, dict) else []
        returned = {
            (str(item.get("group_id") or ""), str(item.get("query") or "")): item
            for item in items if isinstance(item, dict)
        }
        updated = 0
        next_entries = dict(entries)
        for unit in changed:
            result = returned.get((unit["group_id"], unit["query"]))
            if result is None:
                continue
            next_entries[self._scene_key(unit)] = {
                "group_id": unit["group_id"],
                "group_name": unit["group_name"],
                "query": unit["query"],
                "evidence_fingerprint": unit["evidence_fingerprint"],
                "scene_terms": self._clean_scene_terms(result.get("scene_terms")),
            }
            updated += 1
        if not dry_run:
            save_json(scene_path, {"entries": next_entries})
        return {"rows": self._rows(next_entries, groups), "updated": updated, "error": "", "dry_run": dry_run}
