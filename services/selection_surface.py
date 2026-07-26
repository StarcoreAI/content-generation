import html
import random
import re
from statistics import mean, median
from html.parser import HTMLParser
from urllib.parse import urlparse

from services.ref_articles import canonical_article_key


MISSING = "无"
DECISION_WORDS = (
    "推荐", "排名", "哪家", "怎么选", "避坑", "测评", "对比", "靠谱", "攻略",
    "怎么样", "好不好", "靠谱吗", "口碑", "坑不坑",
)


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
                "canonical_key": key,
                "title": title,
                "url": url,
                "citation_count": 0,
                "ai_platforms": set(),
                "question_citations": {},
                "question_ai_platforms": {},
                "first_cited_date": cited_date,
                "last_cited_date": cited_date,
                "_index": record_index,
            })
            article["citation_count"] += 1
            if ai_platform:
                article["ai_platforms"].add(ai_platform)
            question = str(record.get("question") or "").strip()
            if question:
                article["question_citations"][question] = (
                    article["question_citations"].get(question, 0) + 1
                )
                article["question_ai_platforms"].setdefault(question, set())
                if ai_platform:
                    article["question_ai_platforms"][question].add(ai_platform)
            if cited_date and (not article["first_cited_date"] or cited_date < article["first_cited_date"]):
                article["first_cited_date"] = cited_date
            if cited_date and (not article["last_cited_date"] or cited_date > article["last_cited_date"]):
                article["last_cited_date"] = cited_date

    result = list(articles.values())
    result.sort(key=lambda item: (-item["citation_count"], item["_index"]))
    for article in result:
        article["ai_platforms"] = sorted(article["ai_platforms"])
        article["question_citations"] = dict(sorted(article["question_citations"].items()))
        article["question_ai_platforms"] = {
            question: sorted(platforms)
            for question, platforms in sorted(article["question_ai_platforms"].items())
        }
        article["referenced_question_count"] = len(article["question_citations"])
        article.pop("_index", None)
    if top is None:
        return result
    return result[:max(0, int(top or 0))]


def sample_low_frequency_selection_articles(records, date_from=None, date_to=None, top=30,
                                            random_seed=None):
    """Randomly choose from the lowest cited article tier after date filtering."""
    articles = aggregate_selection_articles(
        records, date_from=date_from, date_to=date_to, top=None,
    )
    if not articles:
        return []
    lowest_count = min(article["citation_count"] for article in articles)
    candidates = [article for article in articles if article["citation_count"] == lowest_count]
    return random.Random(random_seed).sample(candidates, min(max(0, int(top or 0)), len(candidates)))


def group_selection_articles_by_question(articles):
    """Expand selected global Top-N articles into their concrete question groups."""
    groups = {}
    for article in articles or []:
        if not isinstance(article, dict):
            continue
        question_citations = article.get("question_citations") or {}
        question_platforms = article.get("question_ai_platforms") or {}
        for question, citation_count in question_citations.items():
            question = str(question or "").strip()
            if not question or not citation_count:
                continue
            grouped_article = dict(article)
            grouped_article["question_citation_count"] = int(citation_count)
            grouped_article["question_ai_platforms"] = list(question_platforms.get(question) or [])
            groups.setdefault(question, []).append(grouped_article)

    result = []
    for question, grouped_articles in groups.items():
        grouped_articles.sort(
            key=lambda item: (-item["question_citation_count"], item.get("canonical_key") or "")
        )
        result.append({"question": question, "articles": grouped_articles})
    result.sort(
        key=lambda group: (-sum(item["question_citation_count"] for item in group["articles"]), group["question"])
    )
    return result


def _char_shingles(value, size=3):
    text = re.sub(r"\s+", "", str(value or "").lower())
    if not text:
        return set()
    if len(text) < size:
        return {text}
    return {text[index:index + size] for index in range(len(text) - size + 1)}


def _jaccard_similarity(left, right):
    left_shingles = _char_shingles(left)
    right_shingles = _char_shingles(right)
    if not left_shingles or not right_shingles:
        return None
    return len(left_shingles & right_shingles) / len(left_shingles | right_shingles)


def _similarity_summary(scores):
    scores = list(scores)
    return {
        "pair_count": len(scores),
        "mean": mean(scores) if scores else None,
        "median": median(scores) if scores else None,
    }


def grouped_surface_similarity(articles, field):
    """Compare distinct article surfaces within a shared question and across questions."""
    unique_articles = {}
    for index, article in enumerate(articles or []):
        if not isinstance(article, dict):
            continue
        key = str(article.get("canonical_key") or "").strip()
        if not key:
            key = canonical_article_key(article.get("title"), article.get("url")) or f"index:{index}"
        entry = unique_articles.setdefault(key, {"questions": set(), "text": ""})
        entry["questions"].update(
            str(question).strip()
            for question in (article.get("question_citations") or {})
            if str(question).strip()
        )
        candidate = str((article.get("surface") or {}).get(field) or "").strip()
        if candidate and candidate != MISSING and not entry["text"]:
            entry["text"] = candidate

    entries = [entry for entry in unique_articles.values() if entry["questions"] and entry["text"]]
    within_scores = []
    cross_scores = []
    for left_index, left in enumerate(entries):
        for right in entries[left_index + 1:]:
            score = _jaccard_similarity(left["text"], right["text"])
            if score is None:
                continue
            if left["questions"] & right["questions"]:
                within_scores.append(score)
            else:
                cross_scores.append(score)

    within = _similarity_summary(within_scores)
    cross = _similarity_summary(cross_scores)
    return {
        "within": within,
        "cross": cross,
        "mean_difference": (
            within["mean"] - cross["mean"]
            if within["mean"] is not None and cross["mean"] is not None else None
        ),
    }


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
