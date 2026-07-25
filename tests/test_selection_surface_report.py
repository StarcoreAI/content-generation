import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SelectionSurfaceTests(unittest.TestCase):
    def test_existing_fetcher_keeps_static_html_for_surface_extraction(self):
        from services.article_fetcher import fetch_article_text

        class Headers:
            def get_content_charset(self):
                return "utf-8"

        class Response:
            headers = Headers()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _size):
                return ("<title>标题</title><p>" + "正文内容" * 100 + "</p>").encode("utf-8")

        with patch("services.article_fetcher.urlopen", return_value=Response()):
            result = fetch_article_text("https://example.com/article", include_html=True)

        self.assertTrue(result["ok"])
        self.assertIn("<title>标题</title>", result["html"])

    def test_extract_selection_surface_uses_description_and_first_long_paragraph(self):
        from services.selection_surface import extract_selection_surface

        surface = extract_selection_surface("""
            <html><head><title>2026 购车音响推荐</title>
            <meta name="description" content="这是摘要"></head>
            <body><h1>购买指南</h1><p>太短。</p>
            <p>这是第一段足够长的正文，用于验证选择层表面提取会跳过过短的文本块，并且包含额外说明以满足四十字阈值。</p></body></html>
        """)

        self.assertEqual(surface["title"], "2026 购车音响推荐")
        self.assertEqual(surface["meta_description"], "这是摘要")
        self.assertEqual(surface["h1"], "购买指南")
        self.assertIn("第一段足够长", surface["first_paragraph"])

    def test_extract_selection_surface_falls_back_to_og_and_handles_missing_or_broken_html(self):
        from services.selection_surface import extract_selection_surface

        og_surface = extract_selection_surface(
            '<title>标题</title><meta property="og:description" content="OG 摘要"><p>这里有一段足够长的正文，即使 HTML 不完整也应当能被安全处理。'
        )
        empty_surface = extract_selection_surface("")

        self.assertEqual(og_surface["meta_description"], "OG 摘要")
        self.assertEqual(empty_surface["title"], "无")
        self.assertEqual(empty_surface["meta_description"], "无")
        self.assertEqual(empty_surface["h1"], "无")
        self.assertEqual(empty_surface["first_paragraph"], "无")

    def test_selection_features_mark_year_decision_words_and_brand_locations(self):
        from services.selection_surface import build_selection_features

        features = build_selection_features({
            "title": "2026 年哪家音响靠谱？",
            "meta_description": "品牌甲的对比说明",
            "h1": "指南",
            "first_paragraph": "这是品牌甲的首段介绍，长度足够用于测试。",
        }, "品牌甲")

        self.assertTrue(features["title_has_year"])
        self.assertTrue(features["title_has_decision_word"])
        self.assertEqual(features["title_length"], len("2026 年哪家音响靠谱？"))
        self.assertFalse(features["brand_in_title"])
        self.assertTrue(features["brand_in_meta_description"])
        self.assertTrue(features["brand_in_first_paragraph"])
        self.assertTrue(features["brand_on_surface"])

    def test_aggregate_selection_articles_dedupes_and_filters_dates_before_top_n(self):
        from services.selection_surface import aggregate_selection_articles

        records = [
            {"today": "2026-07-01", "source_platform": "doubao", "refs": [
                {"title": "文章 A", "url": "https://www.example.com/a/"},
                {"title": "文章 B", "url": "https://example.com/b"},
            ]},
            {"today": "2026-07-02", "source_platform": "deepseek", "refs": [
                {"title": "文章 A 新标题", "url": "https://example.com/a"},
            ]},
            {"today": "2026-07-03", "source_platform": "doubao", "refs": [
                {"title": "文章 C", "url": "https://example.com/c"},
            ]},
        ]

        articles = aggregate_selection_articles(
            records, date_from="2026-07-01", date_to="2026-07-02", top=1
        )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["url"], "https://www.example.com/a/")
        self.assertEqual(articles[0]["citation_count"], 2)
        self.assertEqual(articles[0]["ai_platforms"], ["deepseek", "doubao"])
        self.assertEqual(articles[0]["first_cited_date"], "2026-07-01")
        self.assertEqual(articles[0]["last_cited_date"], "2026-07-02")

    def test_question_groups_keep_per_question_counts_and_shared_article_count(self):
        from services.selection_surface import (
            aggregate_selection_articles,
            group_selection_articles_by_question,
        )

        records = [
            {"today": "2026-07-01", "question": "问题一", "source_platform": "doubao", "refs": [
                {"title": "文章 A", "url": "https://example.com/a"},
                {"title": "文章 B", "url": "https://example.com/b"},
            ]},
            {"today": "2026-07-02", "question": "问题一", "source_platform": "deepseek", "refs": [
                {"title": "文章 A", "url": "https://example.com/a"},
            ]},
            {"today": "2026-07-03", "question": "问题二", "source_platform": "doubao", "refs": [
                {"title": "文章 A", "url": "https://example.com/a"},
                {"title": "文章 C", "url": "https://example.com/c"},
            ]},
        ]

        groups = group_selection_articles_by_question(
            aggregate_selection_articles(records, top=3)
        )

        self.assertEqual([group["question"] for group in groups], ["问题一", "问题二"])
        first = groups[0]["articles"]
        self.assertEqual(first[0]["url"], "https://example.com/a")
        self.assertEqual(first[0]["question_citation_count"], 2)
        self.assertEqual(first[0]["question_ai_platforms"], ["deepseek", "doubao"])
        self.assertEqual(first[0]["referenced_question_count"], 2)
        self.assertEqual(groups[1]["articles"][0]["question_citation_count"], 1)

    def test_grouped_similarity_splits_within_and_cross_question_and_omits_same_url(self):
        from services.selection_surface import grouped_surface_similarity

        articles = [
            {"canonical_key": "url:example.com/a", "question_citations": {"问题一": 1},
             "surface": {"meta_description": "共同内容甲乙丙", "title": "共同标题甲"}},
            {"canonical_key": "url:example.com/b", "question_citations": {"问题一": 1},
             "surface": {"meta_description": "共同内容甲乙丁", "title": "共同标题乙"}},
            {"canonical_key": "url:example.com/c", "question_citations": {"问题二": 1},
             "surface": {"meta_description": "完全不同戊己庚", "title": "另一标题甲"}},
            {"canonical_key": "url:example.com/d", "question_citations": {"问题二": 1},
             "surface": {"meta_description": "完全不同戊己辛", "title": "另一标题乙"}},
            # A duplicate article from another question must merge into A, not compare with itself.
            {"canonical_key": "url:example.com/a", "question_citations": {"问题二": 1},
             "surface": {"meta_description": "共同内容甲乙丙", "title": "共同标题甲"}},
        ]

        meta = grouped_surface_similarity(articles, "meta_description")
        title = grouped_surface_similarity(articles, "title")

        self.assertEqual(meta["within"]["pair_count"], 4)
        self.assertEqual(meta["cross"]["pair_count"], 2)
        self.assertEqual(meta["within"]["pair_count"] + meta["cross"]["pair_count"], 6)
        self.assertGreater(meta["within"]["mean"], meta["cross"]["mean"])
        self.assertEqual(title["within"]["pair_count"], 4)

    def test_decision_words_include_medical_aesthetics_colloquialisms(self):
        from services.selection_surface import build_selection_features

        features = build_selection_features({
            "title": "医美机构靠谱吗，效果怎么样？",
            "meta_description": "无",
            "h1": "无",
            "first_paragraph": "无",
        }, "")

        self.assertTrue(features["title_has_decision_word"])

    def test_report_continues_after_fetch_failure_and_writes_expected_summary(self):
        from scripts.run_selection_surface_report import run_selection_surface_report

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "clients.json").write_text(json.dumps([
                {"id": "client-1", "name": "客户甲", "brand": "品牌甲"},
            ], ensure_ascii=False), encoding="utf-8")
            (data_dir / "raw_records.json").write_text(json.dumps([
                {"client_id": "client-1", "today": "2026-07-01", "question": "问题一", "source_platform": "doubao", "refs": [
                    {"title": "文章 A", "url": "https://example.com/a"},
                    {"title": "文章 B", "url": "https://example.com/b"},
                ]},
                {"client_id": "client-1", "today": "2026-07-02", "question": "问题二", "source_platform": "deepseek", "refs": [
                    {"title": "文章 A", "url": "https://example.com/a"},
                ]},
            ], ensure_ascii=False), encoding="utf-8")

            def fake_fetch(url, **_kwargs):
                if url.endswith("/b"):
                    raise RuntimeError("network unavailable")
                return {
                    "ok": True,
                    "url": url,
                    "html": """
                        <title>2026 品牌甲音响推荐</title>
                        <meta name="description" content="品牌甲的选择建议">
                        <h1>选购指南</h1>
                        <p>这是品牌甲的第一段正文，长度足够用于提取选择层表面内容。</p>
                    """,
                    "error": "",
                }

            result = run_selection_surface_report(
                client_id="client-1",
                data_dir=data_dir,
                top=2,
                fetch_fn=fake_fetch,
                run_date="2026-07-25",
                sleep_fn=lambda _seconds: None,
            )

            report = Path(result["output_path"]).read_text(encoding="utf-8")
            self.assertEqual(result["total_articles"], 2)
            self.assertEqual(result["fetch_failed"], 1)
            self.assertEqual(result["fetch_succeeded"], 1)
            self.assertIn("抓取失败数：1", report)
            self.assertIn("抓取成功率：50.0%", report)
            self.assertIn("2026 品牌甲音响推荐", report)
            self.assertIn("抓取失败", report)
            self.assertIn("品牌出现在表面的篇数：1", report)
            self.assertIn("## 问题：问题一", report)
            self.assertIn("## 问题：问题二", report)
            self.assertIn("共 2 个问题引用此文", report)
            self.assertIn("Meta description 相似度", report)
            self.assertIn("Title 相似度", report)
            self.assertTrue(result["output_path"].endswith("2026-07-25_客户甲_selection_surface.md"))


if __name__ == "__main__":
    unittest.main()
