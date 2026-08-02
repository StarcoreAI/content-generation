"""Small JSON cache for model work derived from an article body."""
import hashlib
import threading

from services.storage import load_json, save_json


_cache_lock = threading.RLock()


def _body_hash(content):
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def get_cached_article(path, url):
    with _cache_lock:
        current = load_json(path, {"entries": {}})
        entries = current.get("entries", {}) if isinstance(current, dict) else {}
        entry = entries.get(str(url or "")) if isinstance(entries, dict) else None
        article = entry.get("article") if isinstance(entry, dict) else None
        return dict(article) if isinstance(article, dict) and str(article.get("content") or "").strip() else None


def put_cached_article(path, url, article):
    article = dict(article or {})
    content = str(article.get("content") or "")
    if not content.strip():
        return
    with _cache_lock:
        current = load_json(path, {"entries": {}})
        entries = current.get("entries") if isinstance(current, dict) else None
        entries = dict(entries) if isinstance(entries, dict) else {}
        previous = entries.get(str(url or "")) if isinstance(entries.get(str(url or "")), dict) else {}
        body_hash = _body_hash(content)
        analyses = previous.get("analyses", {}) if previous.get("body_hash") == body_hash else {}
        entry = {"article": article, "body_hash": body_hash, "analyses": analyses}
        entries[str(url or "")] = entry
        save_json(path, {"entries": entries})


def get_cached_analysis(path, url, content, scope=""):
    with _cache_lock:
        current = load_json(path, {"entries": {}})
        entries = current.get("entries", {}) if isinstance(current, dict) else {}
        entry = entries.get(str(url or "")) if isinstance(entries, dict) else None
        if not isinstance(entry, dict) or entry.get("body_hash") != _body_hash(content):
            return None
        analyses = entry.get("analyses", {})
        analysis = analyses.get(str(scope or "")) if isinstance(analyses, dict) else None
        return analysis if isinstance(analysis, (dict, str)) else None


def put_cached_analysis(path, url, content, analysis, scope=""):
    with _cache_lock:
        current = load_json(path, {"entries": {}})
        entries = current.get("entries") if isinstance(current, dict) else None
        entries = dict(entries) if isinstance(entries, dict) else {}
        previous = entries.get(str(url or "")) if isinstance(entries.get(str(url or "")), dict) else {}
        article = previous.get("article") if previous.get("body_hash") == _body_hash(content) else None
        analyses = previous.get("analyses") if previous.get("body_hash") == _body_hash(content) else None
        analyses = dict(analyses) if isinstance(analyses, dict) else {}
        analyses[str(scope or "")] = analysis
        entries[str(url or "")] = {"article": article, "body_hash": _body_hash(content), "analyses": analyses}
        save_json(path, {"entries": entries})
