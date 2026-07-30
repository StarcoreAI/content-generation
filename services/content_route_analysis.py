"""Analyze operator-confirmed full articles into verified evidence and industry routes."""
from services.reference_route_analysis import (
    ROUTE_ANALYSIS_MAX_TOKENS,
    build_route_analysis_prompt,
    normalize_route_analysis_result,
)


def analyze_content_route_article(bundle, article, ai_json_fn):
    """Analyze one article only after operations confirms it was actually read by a platform."""
    article = dict(article or {})
    if article.get("confirmed_for_route_analysis") is not True:
        raise ValueError("confirmed_article_required")
    if not str(article.get("url") or "").strip() or not str(article.get("content") or "").strip():
        raise ValueError("article_url_and_content_required")
    raw = ai_json_fn(build_route_analysis_prompt(bundle, article), ROUTE_ANALYSIS_MAX_TOKENS)
    result = normalize_route_analysis_result(raw, article["content"])
    return {
        "source": {"url": str(article["url"]).strip(), "title": str(article.get("title") or "").strip()},
        **result,
    }


def ingest_content_route_analysis(analysis, industry, library, existing_route_id=""):
    """Persist one eligible analysis; source consolidation is explicit, never guessed."""
    if not str(industry or "").strip():
        raise ValueError("industry_required")
    analysis = dict(analysis or {})
    if not (analysis.get("library_decision") or {}).get("eligible"):
        raise ValueError("analysis_not_eligible")
    route = analysis.get("route")
    source = {
        **dict(analysis.get("source") or {}),
        "source_evidence": list(analysis.get("source_evidence") or []),
    }
    if str(existing_route_id or "").strip():
        return library.add_source(industry, str(existing_route_id).strip(), source)
    return library.create_route(industry, route, source)
