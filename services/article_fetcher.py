import html
import os
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ArticleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._tag_stack = []
        self._skip_depth = 0
        self._title_parts = []
        self._blocks = []
        self._current = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs or [])
        self._tag_stack.append(tag)
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "aside"}:
            self._skip_depth += 1
        if tag == "meta" and attrs.get("name", "").lower() == "description":
            self.description = attrs.get("content", "").strip()
        if self._skip_depth:
            return
        if tag in {"p", "h1", "h2", "h3", "li"}:
            self._current = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title" and not self.title:
            self.title = _clean_text("".join(self._title_parts))
        if self._skip_depth:
            if tag in {"script", "style", "noscript", "svg", "nav", "footer", "aside"}:
                self._skip_depth = max(0, self._skip_depth - 1)
            if self._tag_stack:
                self._tag_stack.pop()
            return
        if tag in {"p", "h1", "h2", "h3", "li"} and self._current is not None:
            text = _clean_text("".join(self._current))
            if len(text) >= 8:
                self._blocks.append(text)
            self._current = None
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self._title_parts.append(data)
        if self._current is not None:
            self._current.append(data)

    @property
    def content(self):
        return "\n".join(_dedupe_blocks(self._blocks))


def _clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _dedupe_blocks(blocks):
    result = []
    seen = set()
    for block in blocks:
        key = re.sub(r"\W+", "", block).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(block)
    return result


def extract_article_text_from_html(html_text, url="", max_chars=12000, min_chars=200):
    parser = ArticleHTMLParser()
    parser.feed(str(html_text or ""))
    content = parser.content[:max_chars]
    ok = len(content) >= min_chars
    return {
        "ok": ok,
        "url": str(url or ""),
        "title": parser.title[:200],
        "description": parser.description[:500],
        "content": content,
        "error": "" if ok else "content_too_short",
    }


def _prefer_local_playwright_cache():
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return
    browser_cache = os.path.join(local_app_data, "ms-playwright")
    if os.path.exists(browser_cache):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browser_cache


def _clean_browser_text(value, max_chars):
    lines = []
    seen = set()
    for line in str(value or "").splitlines():
        text = _clean_text(line)
        if len(text) < 2 or text in seen:
            continue
        seen.add(text)
        lines.append(text)
    return "\n".join(lines)[:max_chars]


def fetch_article_text_with_browser(url, timeout=25, max_chars=12000, min_chars=200, playwright_factory=None):
    _prefer_local_playwright_cache()
    playwright_context = None
    try:
        if playwright_factory is None:
            from playwright.sync_api import sync_playwright

            playwright_context = sync_playwright()
            p = playwright_context.__enter__()
        else:
            p = playwright_factory()
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121 Safari/537.36")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            except Exception:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            title = _clean_text(page.title())[:200]
            content = _clean_browser_text(page.locator("body").inner_text(timeout=5000), max_chars)
        finally:
            browser.close()
            if playwright_context is not None:
                playwright_context.__exit__(None, None, None)
    except Exception as exc:
        return {"ok": False, "url": url, "title": "", "description": "", "content": "", "error": str(exc), "fetch_method": "browser"}

    ok = len(content) >= min_chars
    return {
        "ok": ok,
        "url": url,
        "title": title,
        "description": "",
        "content": content,
        "error": "" if ok else "content_too_short",
        "fetch_method": "browser",
    }


def fetch_article_text(url, timeout=10, max_chars=12000, browser_fallback=False, browser_fetch_fn=None):
    url = str(url or "").strip()
    if not re.match(r"^https?://", url):
        return {"ok": False, "url": url, "title": "", "description": "", "content": "", "error": "invalid_url", "fetch_method": "static"}
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; GEOAgent/1.0; +https://localhost)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_chars * 8)
            charset = resp.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        result = {"ok": False, "url": url, "title": "", "description": "", "content": "", "error": str(exc), "fetch_method": "static"}
        if browser_fallback:
            browser_result = (browser_fetch_fn or fetch_article_text_with_browser)(url, timeout=timeout, max_chars=max_chars)
            browser_result.setdefault("static_error", result["error"])
            return browser_result
        return result
    text = raw.decode(charset, errors="ignore")
    result = extract_article_text_from_html(text, url=url, max_chars=max_chars)
    result["fetch_method"] = "static"
    if not result["ok"]:
        result["error"] = "empty_content"
        if browser_fallback:
            browser_result = (browser_fetch_fn or fetch_article_text_with_browser)(url, timeout=timeout, max_chars=max_chars)
            browser_result.setdefault("static_error", result["error"])
            return browser_result
    return result
