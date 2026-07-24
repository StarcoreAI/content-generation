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

    def test_resources_are_replaced_by_latest_sync_for_one_client(self):
        self.store.save_resources("client-a", [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}], "2026-07-22 10:00:00")
        self.store.save_resources("client-a", [{"resource_id": "8", "name": "账号B", "price": 99, "status": "1", "raw": {}}], "2026-07-22 11:00:00")
        resources = self.store.list_resources("client-a")
        self.assertEqual([item["resource_id"] for item in resources], ["8"])

    def test_upsert_resources_keeps_previously_selected_resources(self):
        self.store.upsert_resources("client-a", [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}], "2026-07-22 10:00:00")
        self.store.upsert_resources("client-a", [{"resource_id": "8", "name": "账号B", "price": 99, "status": "1", "raw": {}}], "2026-07-22 11:00:00")

        self.assertEqual([item["resource_id"] for item in self.store.list_resources("client-a")], ["7", "8"])

    def test_resources_keep_same_id_when_their_types_differ(self):
        self.store.upsert_resources("client-a", [
            {"resource_id": "7", "resource_type": "self_media", "name": "账号A", "price": 88, "status": "1", "raw": {}},
            {"resource_id": "7", "resource_type": "news_media", "name": "媒体A", "price": 99, "status": "1", "raw": {}},
        ], "2026-07-24 10:00:00")

        self.assertEqual(self.store.get_resource("client-a", "7", "news_media")["name"], "媒体A")
        self.assertEqual(
            {(item["resource_type"], item["resource_id"]) for item in self.store.list_resources("client-a")},
            {("self_media", "7"), ("news_media", "7")},
        )

    def test_order_status_can_be_updated_and_listed(self):
        draft = self.store.create_draft("client-a", {"id": "a1", "title": "标题", "content": "正文"}, "op")
        order = self.store.create_supplier_order("client-a", draft["id"], "geo-1", "self_media", "7", "账号A", 88)
        self.store.update_supplier_order("client-a", order["id"], "completed", "https://example.com/a", "")
        self.assertEqual(self.store.list_orders("client-a")[0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
