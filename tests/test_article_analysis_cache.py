import tempfile
import unittest
from pathlib import Path


class ArticleAnalysisCacheTests(unittest.TestCase):
    def test_cache_returns_saved_article_by_url(self):
        from services.article_analysis_cache import get_cached_article, put_cached_article

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.json"
            article = {"title": "文章", "content": "body one", "ok": True}
            put_cached_article(path, "https://example.com/a", article)

            self.assertEqual(get_cached_article(path, "https://example.com/a"), article)
            self.assertIsNone(get_cached_article(path, "https://example.com/b"))

    def test_cache_returns_analysis_only_for_matching_url_and_body(self):
        from services.article_analysis_cache import get_cached_analysis, put_cached_analysis

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.json"
            put_cached_analysis(path, "https://example.com/a", "body one", {"kind": "介绍型"})

            self.assertEqual(
                get_cached_analysis(path, "https://example.com/a", "body one"),
                {"kind": "介绍型"},
            )
            self.assertIsNone(get_cached_analysis(path, "https://example.com/a", "body changed"))
            self.assertIsNone(get_cached_analysis(path, "https://example.com/b", "body one"))

    def test_analysis_cache_keeps_different_queries_separate(self):
        from services.article_analysis_cache import get_cached_analysis, put_cached_analysis

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.json"
            put_cached_analysis(path, "https://example.com/a", "body", {"query": "Q1"}, scope="Q1")

            self.assertEqual(get_cached_analysis(path, "https://example.com/a", "body", scope="Q1"), {"query": "Q1"})
            self.assertIsNone(get_cached_analysis(path, "https://example.com/a", "body", scope="Q2"))

    def test_saving_changed_article_body_invalidates_prior_analysis(self):
        from services.article_analysis_cache import get_cached_analysis, put_cached_analysis, put_cached_article

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.json"
            put_cached_analysis(path, "https://example.com/a", "old body", {"query": "Q1"}, scope="Q1")
            put_cached_article(path, "https://example.com/a", {"ok": True, "content": "new body"})

            self.assertIsNone(get_cached_analysis(path, "https://example.com/a", "new body", scope="Q1"))


if __name__ == "__main__":
    unittest.main()
