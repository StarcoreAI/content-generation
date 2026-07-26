import argparse
import re
import sys
import time
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
    group_selection_articles_by_question,
    grouped_surface_similarity,
    sample_low_frequency_selection_articles,
)
from services.storage import load_json


def default_data_dir():
    return ROOT / "data"


def _client_info(data_dir, client_id):
    for client in load_json(data_dir / "clients.json", []):
        if isinstance(client, dict) and client.get("id") == client_id:
            return (
                str(client.get("name") or client.get("brand") or "").strip(),
                str(client.get("brand") or "").strip(),
            )
    return "", ""


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


def _similarity_value(value):
    return f"{value * 100:.1f}%" if value is not None else "无可比样本"


def _render_similarity(lines, label, comparison):
    within = comparison["within"]
    cross = comparison["cross"]
    lines.extend([
        f"- {label}：",
        f"  - 同一问题内：均值 {_similarity_value(within['mean'])}；中位数 {_similarity_value(within['median'])}；{within['pair_count']} 对",
        f"  - 跨问题：均值 {_similarity_value(cross['mean'])}；中位数 {_similarity_value(cross['median'])}；{cross['pair_count']} 对",
        f"  - 均值差（组内 - 组间）：{_similarity_value(comparison['mean_difference'])}",
    ])


def _render_grouped_report(client_id, client_name, brand, run_date, date_from, date_to, top,
                           selection_mode, groups, stats, similarities):
    lines = [
        "# 高频引用文章选择层表面报告（按问题分组）",
        "",
        "## 运行参数",
        "",
        f"- 客户：{client_name or client_id}",
        f"- 客户 ID：{client_id}",
        f"- 客户品牌：{brand or MISSING}",
        f"- 日期范围：{date_from or '全部'} 至 {date_to or '全部'}",
        f"- 文章选择：{'全局高频 Top N' if selection_mode == 'high-frequency' else '最低被引次数档随机样本'}（{top} 篇）",
        f"- 运行日期：{run_date}",
        "",
        "## 结论：同一问题内 vs 跨问题相似度",
        "",
        "同一 URL 不参与与自身的比较；每一对不同文章若共同出现在至少一个问题中，计入“同一问题内”，否则计入“跨问题”。",
    ]
    _render_similarity(lines, "Meta description 相似度（字符 3-gram Jaccard）", similarities["meta"])
    _render_similarity(lines, "Title 相似度（字符 3-gram Jaccard）", similarities["title"])
    lines.extend([
        "",
        "## 汇总统计",
        "",
        f"- 高频文章数：{stats['total_articles']}",
        f"- 有 meta description：{stats['has_meta_description']}（{_percent(stats['has_meta_description'], stats['total_articles'])}）",
        f"- 标题含年份：{stats['title_has_year']}（{_percent(stats['title_has_year'], stats['total_articles'])}）",
        f"- 标题含决策词：{stats['title_has_decision_word']}（{_percent(stats['title_has_decision_word'], stats['total_articles'])}）",
        f"- 品牌出现在表面的篇数：{stats['brand_on_surface']}",
        f"- 抓取成功数：{stats['fetch_succeeded']}",
        f"- 抓取失败数：{stats['fetch_failed']}",
        f"- 抓取成功率：{_percent(stats['fetch_succeeded'], stats['total_articles'])}",
    ])
    for group in groups:
        lines.extend(["", f"## 问题：{group['question']}"])
        for index, article in enumerate(group["articles"], 1):
            surface = article.get("surface") or {}
            lines.extend([
                "",
                f"### {index}. {surface.get('title') or article.get('title') or MISSING}",
                "",
                f"- 此问题被引次数：{article['question_citation_count']}",
                f"- 出现平台：{'、'.join(article['question_ai_platforms']) or MISSING}",
                f"- 共 {article['referenced_question_count']} 个问题引用此文",
                f"- URL：{article['url'] or MISSING}",
                f"- 域名：{article_domain(article['url'])}",
                f"- 抓取状态：{article.get('fetch_status') or '失败'}",
            ])
            if article.get("fetch_error"):
                lines.append(f"- 失败原因：{article['fetch_error']}")
                continue
            features = article["features"]
            lines.extend([
                f"- 标题：{surface['title']}",
                f"- Meta description：{surface['meta_description']}",
                f"- H1：{surface['h1']}",
                f"- 首段（前 200 字）：{surface['first_paragraph'][:200]}",
                "",
                "#### 特征标记",
                "",
                f"- 标题含年份：{'是' if features['title_has_year'] else '否'}",
                f"- 标题含决策词：{'是' if features['title_has_decision_word'] else '否'}",
                f"- 标题长度：{features['title_length']}",
                f"- 品牌在标题 / meta / 首段：{'是' if features['brand_in_title'] else '否'} / {'是' if features['brand_in_meta_description'] else '否'} / {'是' if features['brand_in_first_paragraph'] else '否'}",
            ])
    return "\n".join(lines) + "\n"


def _safe_filename_part(value):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or "")).strip(". ")


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
    sleep_fn=time.sleep,
    selection_mode="high-frequency",
    random_seed=None,
):
    top = int(top)
    if top < 1:
        raise ValueError("top must be at least 1")
    data_dir = Path(data_dir or default_data_dir())
    records = load_client_records(data_dir / "raw_records.json", client_id)
    if selection_mode == "high-frequency":
        articles = aggregate_selection_articles(records, date_from=date_from, date_to=date_to, top=top)
    elif selection_mode == "low-frequency-random":
        articles = sample_low_frequency_selection_articles(
            records, date_from=date_from, date_to=date_to, top=top, random_seed=random_seed,
        )
    else:
        raise ValueError("selection_mode must be high-frequency or low-frequency-random")
    client_name, brand = _client_info(data_dir, client_id)
    stats = {
        "total_articles": len(articles),
        "has_meta_description": 0,
        "title_has_year": 0,
        "title_has_decision_word": 0,
        "brand_on_surface": 0,
        "fetch_succeeded": 0,
        "fetch_failed": 0,
    }
    for index, article in enumerate(articles):
        if index:
            sleep_fn(1)
        try:
            fetched = fetch_fn(
                article["url"], timeout=25, max_chars=12000,
                browser_fallback=True, include_html=True, accept_metadata=True,
            )
            if not isinstance(fetched, dict) or not fetched.get("ok"):
                raise RuntimeError(str((fetched or {}).get("error") or "抓取失败"))
            article["surface"] = _surface_from_fetch(fetched, article)
            article["features"] = build_selection_features(article["surface"], brand)
            fetch_method = str(fetched.get("fetch_method") or "unknown")
            charset = str(fetched.get("charset") or "").strip()
            article["fetch_status"] = f"成功（{fetch_method}{'；' + charset if charset else ''}）"
            stats["fetch_succeeded"] += 1
        except Exception as exc:
            article["fetch_error"] = str(exc) or "抓取失败"
            article["fetch_status"] = "失败"
            stats["fetch_failed"] += 1
            continue
        features = article["features"]
        stats["has_meta_description"] += article["surface"]["meta_description"] != MISSING
        stats["title_has_year"] += features["title_has_year"]
        stats["title_has_decision_word"] += features["title_has_decision_word"]
        stats["brand_on_surface"] += features["brand_on_surface"]

    run_date = run_date or date.today().isoformat()
    groups = group_selection_articles_by_question(articles)
    similarities = {
        "meta": grouped_surface_similarity(articles, "meta_description"),
        "title": grouped_surface_similarity(articles, "title"),
    }
    output_name = _safe_filename_part(client_name or client_id) or client_id
    mode_suffix = "" if selection_mode == "high-frequency" else "_low_frequency_random"
    output_path = data_dir / "selection_surface_reports" / client_id / f"{run_date}_{output_name}{mode_suffix}_selection_surface.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _render_grouped_report(
            client_id, client_name, brand, run_date, date_from, date_to, top, selection_mode,
            groups, stats, similarities,
        ),
        encoding="utf-8",
    )
    return {**stats, "selection_mode": selection_mode, "output_path": str(output_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a selection-surface report for frequently cited articles.")
    parser.add_argument("--client", required=True, dest="client_id")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument(
        "--selection-mode", choices=("high-frequency", "low-frequency-random"),
        default="high-frequency",
    )
    parser.add_argument("--random-seed", type=int)
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    result = run_selection_surface_report(
        client_id=args.client_id,
        date_from=args.date_from,
        date_to=args.date_to,
        top=args.top,
        selection_mode=args.selection_mode,
        random_seed=args.random_seed,
    )
    print(f"[GEO] report: {result['output_path']}")
    print(f"[GEO] articles={result['total_articles']} fetch_failed={result['fetch_failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
