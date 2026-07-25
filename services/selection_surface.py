import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from services.ref_articles import canonical_article_key


MISSING = "无"
DECISION_WORDS = ("推荐", "排名", "哪家", "怎么选", "避坑", "测评", "对比", "靠谱", "攻略")


def _clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _display(value):
    return _clean_text(value) or MISSING


class _SelectionSurfaceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._in_h1 = False
        self._title_parts = []
        self._h1_parts = []
        self._current_block = None
        self._blocks = []
        self.description = ""
        self.og_description = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "aside"}:
            self._skip_depth += 1
            return
        if tag == "meta":
            name = attrs.get("name", "").lower()
            prop = attrs.get("property", "").lower()
            if name == "description" and attrs.get("content", "").strip():
                self.description = attrs["content"]
            elif prop == "og:description" and attrs.get("content", "").strip():
                self.og_description = attrs["content"]
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
        elif tag in {"p", "li", "blockquote"} and self._current_block is None:
            self._current_block = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "aside"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag in {"p", "li", "blockquote"}:
            self._finish_block()

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)
        if self._current_block is not None:
            self._current_block.append(data)

    def _finish_block(self):
        if self._current_block is None:
            return
        text = _clean_text("".join(self._current_block))
        if text:
            self._blocks.append(text)
        self._current_block = None

    def finish(self):
        self._finish_block()


def extract_selection_surface(html_text):
    """Extract deterministic selection-layer fields from a page's HTML."""
    parser = _SelectionSurfaceParser()
    try:
        parser.feed(str(html_text or ""))
        parser.close()
    except Exception:
        pass
    parser.finish()
    paragraph = next((block for block in parser._blocks if len(block) >= 40), "")
    return {
        "title": _display("".join(parser._title_parts)),
        "meta_description": _display(parser.description or parser.og_description),
        "h1": _display("".join(parser._h1_parts)),
        "first_paragraph": _display(paragraph),
    }


def _date_in_range(value, date_from, date_to):
    if not value:
        return not date_from and not date_to
    return (not date_from or value >= date_from) and (not date_to or value <= date_to)


def aggregate_selection_articles(records, date_from=None, date_to=None, top=30):
    """Aggregate cited articles by the project's canonical article identity."""
    articles = {}
    for record_index, record in enumerate(records or []):
        if not isinstance(record, dict):
            continue
        cited_date = str(record.get("today") or "").strip()
        if not _date_in_range(cited_date, date_from, date_to):
            continue
        ai_platform = str(record.get("source_platform") or "").strip()
        for ref in record.get("refs") or []:
            if not isinstance(ref, dict):
                continue
            title = str(ref.get("title") or "").strip()
            url = str(ref.get("url") or "").strip()
            key = canonical_article_key(title, url)
            if not key:
                continue
            article = articles.setdefault(key, {
                "title": title,
                "url": url,
                "citation_count": 0,
                "ai_platforms": set(),
                "first_cited_date": cited_date,
                "last_cited_date": cited_date,
                "_index": record_index,
            })
            article["citation_count"] += 1
            if ai_platform:
                article["ai_platforms"].add(ai_platform)
            if cited_date and (not article["first_cited_date"] or cited_date < article["first_cited_date"]):
                article["first_cited_date"] = cited_date
            if cited_date and (not article["last_cited_date"] or cited_date > article["last_cited_date"]):
                article["last_cited_date"] = cited_date

    result = list(articles.values())
    result.sort(key=lambda item: (-item["citation_count"], item["_index"]))
    for article in result:
        article["ai_platforms"] = sorted(article["ai_platforms"])
        article.pop("_index", None)
    return result[:max(0, int(top or 0))]


def article_domain(url):
    return urlparse(str(url or "").strip()).hostname or MISSING


def build_selection_features(surface, brand):
    title = "" if surface.get("title") == MISSING else str(surface.get("title") or "")
    meta_description = "" if surface.get("meta_description") == MISSING else str(surface.get("meta_description") or "")
    first_paragraph = "" if surface.get("first_paragraph") == MISSING else str(surface.get("first_paragraph") or "")
    brand = str(brand or "").strip()
    return {
        "title_has_year": bool(re.search(r"20\d{2}", title)),
        "title_has_decision_word": any(word in title for word in DECISION_WORDS),
        "title_length": len(title),
        "brand_in_title": bool(brand and brand in title),
        "brand_in_meta_description": bool(brand and brand in meta_description),
        "brand_in_first_paragraph": bool(brand and brand in first_paragraph),
        "brand_on_surface": bool(brand and brand in f"{title}\n{meta_description}\n{first_paragraph}"),
    }


def first_content_block(value):
    for block in str(value or "").splitlines():
        text = _clean_text(block)
        if len(text) >= 40:
            return text
    return MISSING
