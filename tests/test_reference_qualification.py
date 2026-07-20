import unittest

from services.reference_qualification import prequalify_reference_articles


def article(url, title, content, citation_count=0, **extra):
    return {
        "ok": True,
        "url": url,
        "title": title,
        "content": content,
        "citation_count": citation_count,
        **extra,
    }


class ReferenceQualificationTests(unittest.TestCase):
    def test_hard_rejects_failed_short_error_and_blocked_pages(self):
        result = prequalify_reference_articles([
            {"ok": False, "url": "https://example.com/failed", "error": "timeout"},
            article("https://example.com/short", "Short", "too short"),
            article("https://example.com/error", "403 Forbidden", "x" * 300),
            article("https://example.com/blocked", "Page", "人机验证" * 100),
        ])

        self.assertEqual(result["eligible"], [])
        self.assertEqual(
            [item["reasons"] for item in result["rejected"]],
            [["fetch_failed"], ["content_too_short"], ["error_title"], ["blocked_page"]],
        )

    def test_groups_same_body_and_keeps_one_representative_with_aggregate_citations(self):
        shared_body = "# Heading\n" + ("Shared article body with enough detail.\n" * 12)
        other_body = "# Different heading\n" + ("Different article body with enough detail.\n" * 12)
        result = prequalify_reference_articles([
            article("https://one.example.com/article-a", "Article A", shared_body, 2),
            article("https://two.example.com/article-b", "Article B", shared_body, 3),
            article("https://example.com/article-c", "Article C", other_body, 1),
        ])

        self.assertEqual(len(result["eligible"]), 2)
        self.assertEqual(len(result["groups"]), 2)
        shared = next(item for item in result["eligible"] if item["group_size"] == 2)
        self.assertEqual(shared["article"]["url"], "https://two.example.com/article-b")
        self.assertEqual(shared["group_citation_count"], 5)
        self.assertEqual(shared["group_urls"], [
            "https://one.example.com/article-a",
            "https://two.example.com/article-b",
        ])
        self.assertTrue(shared["group_id"].startswith("group_"))

    def test_records_structural_signals_without_rejecting_a_complete_article(self):
        content = "# First heading\n" + ("First paragraph has enough text to count.\n" * 3) + "## Second heading\n" + ("Second paragraph has enough text to count.\n" * 3)
        result = prequalify_reference_articles([
            article("https://example.com/article", "Article", content, 1),
        ])

        eligible = result["eligible"][0]
        self.assertGreaterEqual(eligible["signals"]["content_chars"], 200)
        self.assertGreaterEqual(eligible["signals"]["meaningful_paragraphs"], 2)
        self.assertEqual(eligible["signals"]["heading_count"], 2)
        self.assertIn("duplicate_line_ratio", eligible["signals"])
