import unittest

from services.query_platform_reference_intelligence import select_query_platform_articles


def _record(question, platform, *urls):
    return {
        "question": question,
        "source_platform": platform,
        "refs": [{"title": url.rsplit("/", 1)[-1], "url": url} for url in urls],
    }


class QueryPlatformReferenceIntelligenceTests(unittest.TestCase):
    def test_selects_anchor_and_weighted_article_from_exact_query_and_platform(self):
        records = [
            _record("Q1", "doubao", "https://example.com/a", "https://example.com/b", "https://example.com/c", "https://example.com/d", "https://example.com/e"),
            _record("Q1", "doubao", "https://example.com/a", "https://example.com/b", "https://example.com/c", "https://example.com/d"),
            _record("Q1", "doubao", "https://example.com/a", "https://example.com/b", "https://example.com/c"),
            _record("Q1", "doubao", "https://example.com/a", "https://example.com/b"),
            _record("Q1", "doubao", "https://example.com/a"),
            _record("Q1", "deepseek", "https://example.com/ignored-platform", "https://example.com/ignored-platform"),
            _record("Q2", "doubao", "https://example.com/ignored-query", "https://example.com/ignored-query"),
        ]

        result = select_query_platform_articles(records, "Q1", "doubao", seed=7)

        self.assertEqual("https://example.com/a", result["anchor"]["url"])
        self.assertEqual(5, result["anchor"]["citation_count"])
        self.assertEqual(
            ["https://example.com/b", "https://example.com/c", "https://example.com/d", "https://example.com/e"],
            [item["url"] for item in result["weighted_pool"]],
        )
        self.assertEqual([4, 3, 2, 1], [item["weight"] for item in result["weighted_pool"]])
        self.assertEqual(2, len(result["selected"]))
        self.assertNotIn(result["selected"][1]["url"], {"https://example.com/a", "https://example.com/ignored-platform", "https://example.com/ignored-query"})

    def test_canonical_url_variants_count_as_one_candidate(self):
        records = [
            _record("Q1", "doubao", "https://www.toutiao.com/article/7655174835676480010/?wid=1"),
            _record("Q1", "doubao", "https://m.toutiao.com/a7655174835676480010?channel="),
        ]

        result = select_query_platform_articles(records, "Q1", "doubao", seed=1)

        self.assertEqual(1, len(result["ranked"]))
        self.assertEqual(2, result["anchor"]["citation_count"])
        self.assertEqual(1, len(result["selected"]))
