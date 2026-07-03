import html
import re
import socket
import ssl
import urllib.error
import urllib.request
from html.parser import HTMLParser


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data:
            self.parts.append(data)


def html_to_visible_text(content):
    parser = _VisibleTextParser()
    parser.feed(str(content or ""))
    text = html.unescape(" ".join(parser.parts))
    return re.sub(r"\s+", " ", text).strip()


def default_fetcher(url, timeout=10):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            )
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        raw = response.read(1024 * 1024)
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="ignore")


def _contains_entity(text, entity_name):
    return str(entity_name or "").strip().lower() in str(text or "").lower()


def _evidence_for(text, entity_name, radius=70):
    idx = str(text or "").lower().find(str(entity_name or "").lower())
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(entity_name) + radius)
    return text[start:end].strip()


def check_article_body_hits(articles, entity_names, fetcher=None, timeout=10):
    fetcher = fetcher or default_fetcher
    entity_names = [name for name in (entity_names or []) if str(name or "").strip()]
    results = []

    for article in articles or []:
        url = str(article.get("url", "")).strip()
        result = {
            "title": article.get("title", ""),
            "url": url,
            "platform": article.get("platform", ""),
            "count": article.get("count", 0),
            "ai_platforms": article.get("ai_platforms", []),
            "status": "skipped",
            "matched_entities": [],
            "evidence": "",
            "error": "",
        }
        if not url:
            result["error"] = "missing_url"
            results.append(result)
            continue

        try:
            content = fetcher(url, timeout=timeout)
            text = html_to_visible_text(content)
            matched = [name for name in entity_names if _contains_entity(text, name)]
            result["matched_entities"] = matched
            if matched:
                result["status"] = "matched"
                result["evidence"] = _evidence_for(text, matched[0])
            else:
                result["status"] = "not_matched"
        except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError) as exc:
            result["status"] = "fetch_failed"
            result["error"] = str(exc)
        except Exception as exc:
            result["status"] = "fetch_failed"
            result["error"] = str(exc)

        results.append(result)

    return results
