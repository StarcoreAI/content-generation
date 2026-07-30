"""Industry-scoped, evidence-backed writing routes for GEO content production."""
import copy
import hashlib
import json
import random
import re
import uuid
from datetime import datetime
from pathlib import Path


PARENT_TYPES = {"介绍型", "对比型"}
ROUTE_FIELDS = ("parent_type", "name", "reader_task", "steps", "signature", "risk_notes")
SAMPLE_FIELDS = ("id", "parent_type", "name", "reader_task", "steps", "signature", "risk_notes")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_industry_filename(industry):
    text = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(industry or "").strip())
    return text.strip("._") or "unknown"


def _normalized_url(url):
    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("source_url_required")
    return value.rstrip("/").lower()


class ContentRouteLibrary:
    def __init__(self, root_dir, now_fn=None, rng=None):
        self.root_dir = Path(root_dir)
        self.now_fn = now_fn or _now
        self.rng = rng or random

    def _path(self, industry):
        if not str(industry or "").strip():
            raise ValueError("industry_required")
        return self.root_dir / f"industry_{_safe_industry_filename(industry)}.json"

    def _load(self, industry):
        path = self._path(industry)
        if not path.exists():
            return {"industry": str(industry).strip(), "routes": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("routes"), list):
            raise ValueError("invalid_content_route_library")
        if any("status" in route for route in data["routes"]):
            for route in data["routes"]:
                route.pop("status", None)
            self._save(industry, data)
        return data

    def _save(self, industry, data):
        path = self._path(industry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _validate_route(route):
        route = dict(route or {})
        if route.get("parent_type") not in PARENT_TYPES:
            raise ValueError("invalid_parent_type")
        for field in ("name", "reader_task", "signature"):
            if not isinstance(route.get(field), str) or not route[field].strip():
                raise ValueError(f"route_{field}_required")
        if not isinstance(route.get("steps"), list) or not route["steps"]:
            raise ValueError("route_steps_required")
        steps = []
        for step in route["steps"]:
            if not isinstance(step, dict) or any(not str(step.get(key) or "").strip() for key in ("purpose", "evidence_role", "output_action")):
                raise ValueError("invalid_route_step")
            steps.append({key: str(step[key]).strip() for key in ("purpose", "evidence_role", "output_action")})
        return {
            "parent_type": route["parent_type"],
            "name": route["name"].strip(),
            "reader_task": route["reader_task"].strip(),
            "steps": steps,
            "signature": route["signature"].strip(),
            "risk_notes": str(route.get("risk_notes") or "").strip(),
        }

    @staticmethod
    def _validate_source(source):
        source = dict(source or {})
        url = _normalized_url(source.get("url"))
        title = str(source.get("title") or "").strip()
        evidence = source.get("source_evidence")
        if not title or not isinstance(evidence, list) or not evidence:
            raise ValueError("source_evidence_required")
        checked = []
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("invalid_source_evidence")
            role = str(item.get("role") or "").strip()
            finding = str(item.get("finding") or "").strip()
            excerpt = str(item.get("excerpt") or "").strip()
            length = len(re.sub(r"\s+", "", excerpt))
            if not role or not finding or not 20 <= length <= 240:
                raise ValueError("invalid_source_evidence")
            checked.append({"role": role, "finding": finding, "excerpt": excerpt})
        contexts = []
        for item in source.get("citation_contexts") if isinstance(source.get("citation_contexts"), list) else []:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()[:1000]
            ai_platform = str(item.get("ai_platform") or "").strip()[:80]
            try:
                citation_count = int(item.get("citation_count"))
            except (TypeError, ValueError):
                citation_count = 0
            if query and ai_platform and citation_count > 0:
                contexts.append({"query": query, "ai_platform": ai_platform, "citation_count": citation_count})
        return {"url": url, "title": title, "source_evidence": checked, "citation_contexts": contexts}

    def list_routes(self, industry):
        return copy.deepcopy(self._load(industry)["routes"])

    def create_route(self, industry, route, source):
        clean_route = self._validate_route(route)
        clean_source = self._validate_source(source)
        data = self._load(industry)
        now = self.now_fn()
        entry = {
            "id": f"route_{uuid.uuid4().hex}",
            "industry": str(industry).strip(),
            **clean_route,
            "sources": [clean_source],
            "evidence_count": 1,
            "created_at": now,
            "updated_at": now,
        }
        data["routes"].append(entry)
        self._save(industry, data)
        return copy.deepcopy(entry)

    def add_source(self, industry, route_id, source):
        clean_source = self._validate_source(source)
        data = self._load(industry)
        route = next((item for item in data["routes"] if item.get("id") == route_id), None)
        if route is None:
            raise ValueError("content_route_not_found")
        existing_urls = {_normalized_url(item.get("url")) for item in route.get("sources") or []}
        if clean_source["url"] in existing_urls:
            raise ValueError("duplicate_source_url")
        route.setdefault("sources", []).append(clean_source)
        route["evidence_count"] = len(route["sources"])
        route["updated_at"] = self.now_fn()
        self._save(industry, data)
        return copy.deepcopy(route)

    def add_or_merge_source(self, industry, route_id, source):
        clean_source = self._validate_source(source)
        data = self._load(industry)
        route = next((item for item in data["routes"] if item.get("id") == route_id), None)
        if route is None:
            raise ValueError("content_route_not_found")
        existing = next((item for item in route.get("sources") or [] if _normalized_url(item.get("url")) == clean_source["url"]), None)
        if existing is None:
            route.setdefault("sources", []).append(clean_source)
        else:
            evidence = existing.setdefault("source_evidence", [])
            seen = {str(item.get("excerpt") or "") for item in evidence if isinstance(item, dict)}
            evidence.extend(item for item in clean_source["source_evidence"] if item["excerpt"] not in seen)
            contexts = existing.setdefault("citation_contexts", [])
            by_key = {(str(item.get("query") or ""), str(item.get("ai_platform") or "")): item for item in contexts if isinstance(item, dict)}
            for context in clean_source["citation_contexts"]:
                key = (context["query"], context["ai_platform"])
                if key in by_key:
                    by_key[key]["citation_count"] = max(int(by_key[key].get("citation_count") or 0), context["citation_count"])
                else:
                    contexts.append(context)
        route["evidence_count"] = len(route.get("sources") or [])
        route["updated_at"] = self.now_fn()
        self._save(industry, data)
        return copy.deepcopy(route)

    def delete_route(self, industry, route_id):
        data = self._load(industry)
        routes = [item for item in data["routes"] if item.get("id") != route_id]
        if len(routes) == len(data["routes"]):
            raise ValueError("content_route_not_found")
        data["routes"] = routes
        self._save(industry, data)
        return {"id": route_id}

    def sample_route(self, industry, parent_type, excluded_route_ids=None):
        if parent_type not in PARENT_TYPES:
            raise ValueError("invalid_parent_type")
        excluded = set(excluded_route_ids or ())
        choices = [
            route for route in self._load(industry)["routes"]
            if route.get("parent_type") == parent_type and route.get("id") not in excluded
        ]
        if not choices:
            raise ValueError("missing_content_route")
        selected = self.rng.choice(choices)
        return {field: copy.deepcopy(selected.get(field)) for field in SAMPLE_FIELDS}
