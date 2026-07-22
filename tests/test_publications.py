import os
import tempfile
import unittest

from services.publications import PublicationStore


class PublicationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PublicationStore(os.path.join(self.tmp.name, "content.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_blocked_article_can_become_manual_draft_and_is_frozen(self):
        article = {
            "id": "a1",
            "title": "原标题",
            "content": "原正文",
            "gate_report": {"verdict": "blocked"},
        }
        draft = self.store.create_draft("client-a", article, "operator-a")
        article["content"] = "后来编辑的正文"

        saved = self.store.get_draft("client-a", draft["id"])
        self.assertEqual(saved["gate_verdict"], "blocked")
        self.assertEqual(saved["article_content"], "原正文")
        self.assertEqual(saved["status"], "draft")
        self.assertTrue(saved["preview_token"])

    def test_completion_creates_one_publication_record(self):
        draft = self.store.create_draft(
            "client-a", {"id": "a1", "title": "标题", "content": "正文"}, "operator-a"
        )
        order = self.store.create_supplier_order(
            "client-a", draft["id"], "rw-100", "self_media", "7", "账号A", 88.0
        )
        first = self.store.record_completed_publication(
            "client-a", order["id"], "账号A", "https://example.com/a", "标题", "2026-07-22 10:00:00"
        )
        second = self.store.record_completed_publication(
            "client-a", order["id"], "账号A", "https://example.com/a", "标题", "2026-07-22 10:00:00"
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_publications("client-a")), 1)

    def test_draft_marks_article_as_having_publication_state(self):
        self.assertFalse(self.store.article_has_publication_state("client-a", "a1"))
        self.store.create_draft(
            "client-a", {"id": "a1", "title": "标题", "content": "正文"}, "operator-a"
        )
        self.assertTrue(self.store.article_has_publication_state("client-a", "a1"))


if __name__ == "__main__":
    unittest.main()
