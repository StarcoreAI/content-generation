import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.article_fetcher import fetch_article_text
from services.records import load_client_records
from services.selection_surface import (
    MISSING,
    aggregate_selection_articles,
    article_domain,
    build_selection_features,
    extract_selection_surface,
    first_content_block,
)
from services.storage import load_json


def default_data_dir():
    return ROOT / "data"


def _client_brand(data_dir, client_id):
    for client in load_json(data_dir / "clients.json", []):
        if isinstance(client, dict) and client.get("id") == client_id:
            return str(client.get("brand") or "").strip()
    return ""


def _surface_from_fetch(fetched, article):
    html_text = str(fetched.get("html") or "")
    if html_text:
        return extract_selection_surface(html_text)
    return {
        "title": str(fetched.get("title") or article.get("title") or MISSING),
        "meta_description": str(fetched.get("description") or MISSING),
        "h1": MISSING,
        "first_paragraph": first_content_block(fetched.get("content")),
    }


def _percent(numerator, denominator):
    return f"{(numerator / denominator * 100) if denominator else 0:.1f}%"


def _render_report(client_id, brand, run_date, date_from, date_to, top, articles, stats):
    lines = [
        "# 高频引用文章选择层表面报告",
        "",
        "## 运行参数",
        "",
        f"- 客户：{client_id}",
        f"- 客户品牌：{brand or MISSING}",
        f"- 日期范围：{date_from or '全部'} 至 {date_to or '全部'}",
        f"- Top N：{top}",
        f"- 运行日期：{run_date}",
        "",
        "## 汇总统计",
        "",
        f"- 文章数：{stats['total_articles']}",
        f"- 有 meta description：{stats['has_meta_description']}（{_percent(stats['has_meta_description'], stats['total_articles'])}）",
        f"- 标题含年份：{stats['title_has_year']}（{_percent(stats['title_has_year'], stats['total_articles'])}）",
        f"- 标题含决策词：{stats['title_has_decision_word']}（{_percent(stats['title_has_decision_word'], stats['total_articles'])}）",
        f"- 品牌出现在表面的篇数：{stats['brand_on_surface']}",
        f"- 抓取失败数：{stats['fetch_failed']}",
    ]
    for index, article in enumerate(articles, 1):
        lines.extend([
            "",
            f"## {index}. {article['surface']['title'] if article.get('surface') else article['title'] or MISSING}",
            "",
            f"- 被引次数：{article['citation_count']}",
            f"- 涉及 AI 平台：{'、'.join(article['ai_platforms']) or MISSING}",
            f"- 首次/最近被引日期：{article['first_cited_date'] or MISSING} / {article['last_cited_date'] or MISSING}",
            f"- URL：{article['url'] or MISSING}",
            f"- 域名：{article_domain(article['url'])}",
        ])
        if article.get("fetch_error"):
            lines.append(f"- 抓取失败：{article['fetch_error']}")
            continue
        surface = article["surface"]
        features = article["features"]
        lines.extend([
            "",
            "### 选择层表面",
            "",
            f"- 标题：{surface['title']}",
            f"- Meta description：{surface['meta_description']}",
            f"- H1：{surface['h1']}",
            f"- 首段（前 150 字）：{surface['first_paragraph'][:150]}",
            "",
            "### 特征标记",
            "",
            f"- 标题含年份：{'是' if features['title_has_year'] else '否'}",
            f"- 标题含决策词：{'是' if features['title_has_decision_word'] else '否'}",
            f"- 标题长度：{features['title_length']}",
            f"- 品牌在标题/meta/首段：{'是' if features['brand_in_title'] else '否'} / {'是' if features['brand_in_meta_description'] else '否'} / {'是' if features['brand_in_first_paragraph'] else '否'}",
        ])
    return "\n".join(lines) + "\n"


def run_selection_surface_report(
    client_id,
    date_from=None,
    date_to=None,
    top=30,
    data_dir=None,
    fetch_fn=fetch_article_text,
    run_date=None,
):
    top = int(top)
    if top < 1:
        raise ValueError("top must be at least 1")
    data_dir = Path(data_dir or default_data_dir())
    records = load_client_records(data_dir / "raw_records.json", client_id)
    articles = aggregate_selection_articles(records, date_from=date_from, date_to=date_to, top=top)
    brand = _client_brand(data_dir, client_id)
    stats = {
        "total_articles": len(articles),
        "has_meta_description": 0,
        "title_has_year": 0,
        "title_has_decision_word": 0,
        "brand_on_surface": 0,
        "fetch_failed": 0,
    }
    for article in articles:
        try:
            fetched = fetch_fn(
                article["url"], timeout=25, max_chars=12000,
                browser_fallback=True, include_html=True,
            )
            if not isinstance(fetched, dict) or not fetched.get("ok"):
                raise RuntimeError(str((fetched or {}).get("error") or "抓取失败"))
            article["surface"] = _surface_from_fetch(fetched, article)
            article["features"] = build_selection_features(article["surface"], brand)
        except Exception as exc:
            article["fetch_error"] = str(exc) or "抓取失败"
            stats["fetch_failed"] += 1
            continue
        features = article["features"]
        stats["has_meta_description"] += article["surface"]["meta_description"] != MISSING
        stats["title_has_year"] += features["title_has_year"]
        stats["title_has_decision_word"] += features["title_has_decision_word"]
        stats["brand_on_surface"] += features["brand_on_surface"]

    run_date = run_date or date.today().isoformat()
    output_path = data_dir / "selection_surface_reports" / client_id / f"{run_date}_selection_surface.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _render_report(client_id, brand, run_date, date_from, date_to, top, articles, stats),
        encoding="utf-8",
    )
    return {**stats, "output_path": str(output_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a selection-surface report for frequently cited articles.")
    parser.add_argument("--client", required=True, dest="client_id")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    result = run_selection_surface_report(
        client_id=args.client_id,
        date_from=args.date_from,
        date_to=args.date_to,
        top=args.top,
    )
    print(f"[GEO] report: {result['output_path']}")
    print(f"[GEO] articles={result['total_articles']} fetch_failed={result['fetch_failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
