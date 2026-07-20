import re
import time
import uuid
from pathlib import Path

from services.storage import load_json, update_json


VALID_KINDS = {"skeleton", "module", "checklist"}
VALID_STATUSES = {"candidate", "active", "retired"}
AUTO_PROMOTION_BLOCKING_RISKS = {"AI 生成痕迹明显", "冒充口吻"}


class PatternLibrary:
    def __init__(self, root_dir, now_fn=None):
        self.root_dir = Path(root_dir)
        self.now_fn = now_fn or (lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def list_entries(self, scope, status=None):
        if status is not None:
            self._validate_status(status)
        entries = self._load_store(scope)["entries"]
        return [entry for entry in entries if status is None or entry["status"] == status]

    def create_candidate(self, scope, kind, name, payload, source):
        if kind not in VALID_KINDS:
            raise ValueError("invalid_pattern_kind")
        name = str(name or "").strip()
        if not name:
            raise ValueError("missing_pattern_name")
        normalized_source = self._normalize_source(source)
        now = self.now_fn()
        entry = {
            "id": f"{kind}_{uuid.uuid4().hex}",
            "kind": kind,
            "name": name,
            "status": "candidate",
            "payload": self._normalize_payload(kind, payload),
            "sources": [normalized_source],
            "evidence_count": 1,
            "created_at": now,
            "updated_at": now,
        }

        def add_entry(store):
            store = self._normalize_store(store, scope)
            store["entries"].append(entry)
            return store, entry

        return update_json(self._scope_path(scope), self._empty_store(scope), add_entry)

    def add_evidence(self, scope, entry_id, source, payload_update=None):
        normalized_source = self._normalize_source(source)

        def add_source(store):
            store = self._normalize_store(store, scope)
            entry = self._find_entry(store, entry_id)
            source_urls = {
                url
                for item in entry["sources"]
                for url in self._source_urls(item)
            }
            is_new_source = not (source_urls & set(self._source_urls(normalized_source)))
            if is_new_source:
                entry["sources"].append(normalized_source)
                entry["evidence_count"] = len(entry["sources"])
                if entry["status"] == "candidate" and self._promotable_evidence_count(entry) >= 2:
                    entry["status"] = "active"
            if payload_update:
                entry["payload"] = self._merge_payload(entry["kind"], entry.get("payload"), payload_update)
            if is_new_source or payload_update:
                entry["updated_at"] = self.now_fn()
            return store, entry

        return update_json(self._scope_path(scope), self._empty_store(scope), add_source)

    def set_status(self, scope, entry_id, status):
        self._validate_status(status)

        def update_status(store):
            store = self._normalize_store(store, scope)
            entry = self._find_entry(store, entry_id)
            entry["status"] = status
            entry["updated_at"] = self.now_fn()
            return store, entry

        return update_json(self._scope_path(scope), self._empty_store(scope), update_status)

    def _load_store(self, scope):
        return self._normalize_store(load_json(self._scope_path(scope), self._empty_store(scope)), scope)

    def _scope_path(self, scope):
        kind, value = self._split_scope(scope)
        filename = kind if not value else f"{kind}_{self._safe_scope_value(value)}"
        return self.root_dir / f"{filename}.json"

    @staticmethod
    def _split_scope(scope):
        scope = str(scope or "").strip()
        if scope == "global":
            return "global", ""
        kind, separator, value = scope.partition(":")
        if kind not in {"industry", "client"} or not separator or not value.strip():
            raise ValueError("invalid_pattern_scope")
        return kind, value.strip()

    @staticmethod
    def _safe_scope_value(value):
        value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
        if not value:
            raise ValueError("invalid_pattern_scope")
        return value

    @staticmethod
    def _normalize_source(source):
        source = dict(source or {})
        url = str(source.get("url") or "").strip().rstrip("/")
        if not url:
            raise ValueError("missing_pattern_source_url")
        normalized = {
            "url": url,
            "title": str(source.get("title") or "").strip(),
            "group_id": str(source.get("group_id") or "").strip()[:200],
            "published_at": str(source.get("published_at") or "").strip()[:40],
            "platform": str(source.get("platform") or "").strip()[:80],
        }
        try:
            citation_count = int(source.get("citation_count") or 0)
        except (TypeError, ValueError):
            citation_count = 0
        normalized["citation_count"] = max(0, citation_count)
        risk_marks = source.get("risk_marks")
        normalized["risk_marks"] = [
            str(mark).strip()[:80]
            for mark in risk_marks if str(mark).strip()
        ][:12] if isinstance(risk_marks, list) else []
        aliases = source.get("alias_urls")
        if aliases is None:
            aliases = source.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        normalized["alias_urls"] = []
        for alias in aliases:
            alias = str(alias or "").strip().rstrip("/")
            if alias and alias != url and alias not in normalized["alias_urls"]:
                normalized["alias_urls"].append(alias)
        normalized["alias_urls"] = normalized["alias_urls"][:30]
        return normalized

    @staticmethod
    def _source_urls(source):
        urls = [str(source.get("url") or "").strip().rstrip("/")]
        urls.extend(str(url or "").strip().rstrip("/") for url in source.get("alias_urls") or [])
        return {url for url in urls if url}

    @classmethod
    def _normalize_payload(cls, kind, payload):
        payload = dict(payload or {})
        if kind != "module":
            return payload
        examples = cls._examples(payload)
        if examples:
            payload["excerpts"] = examples
            payload["excerpt"] = examples[0]["excerpt"]
            payload["excerpt_verified"] = examples[0]["excerpt_verified"]
        return payload

    @classmethod
    def _merge_payload(cls, kind, existing, update):
        payload = dict(existing or {})
        update = dict(update or {})
        current_risk = str(payload.get("risk_notes") or "").strip()
        incoming_risk = str(update.get("risk_notes") or "").strip()
        if incoming_risk and incoming_risk not in current_risk:
            payload["risk_notes"] = "\n".join(part for part in [current_risk, incoming_risk] if part)

        if kind != "module":
            return payload
        examples = cls._examples(payload)
        excerpt = str(update.get("excerpt") or "").strip()
        if excerpt:
            incoming = {"excerpt": excerpt, "excerpt_verified": update.get("excerpt_verified") is True}
            if incoming not in examples:
                if incoming["excerpt_verified"] and examples and not examples[0]["excerpt_verified"]:
                    examples[0] = incoming
                elif len(examples) < 3:
                    examples.append(incoming)
        if examples:
            payload["excerpts"] = examples[:3]
            payload["excerpt"] = examples[0]["excerpt"]
            payload["excerpt_verified"] = examples[0]["excerpt_verified"]
        return payload

    @staticmethod
    def _examples(payload):
        examples = []
        for item in payload.get("excerpts") or []:
            if isinstance(item, dict):
                excerpt = str(item.get("excerpt") or "").strip()
                if excerpt:
                    examples.append({"excerpt": excerpt, "excerpt_verified": item.get("excerpt_verified") is True})
        if not examples:
            excerpt = str(payload.get("excerpt") or "").strip()
            if excerpt:
                examples.append({"excerpt": excerpt, "excerpt_verified": payload.get("excerpt_verified") is True})
        return examples[:3]

    @staticmethod
    def _promotable_evidence_count(entry):
        return sum(
            1
            for source in entry.get("sources") or []
            if not (set(source.get("risk_marks") or []) & AUTO_PROMOTION_BLOCKING_RISKS)
        )

    @staticmethod
    def _empty_store(scope):
        return {"schema_version": 1, "scope": scope, "entries": []}

    def _normalize_store(self, store, scope):
        store = dict(store or {})
        entries = store.get("entries")
        return {
            "schema_version": 1,
            "scope": scope,
            "entries": entries if isinstance(entries, list) else [],
        }

    @staticmethod
    def _find_entry(store, entry_id):
        for entry in store["entries"]:
            if entry.get("id") == entry_id:
                return entry
        raise KeyError(entry_id)

    @staticmethod
    def _validate_status(status):
        if status not in VALID_STATUSES:
            raise ValueError("invalid_pattern_status")
