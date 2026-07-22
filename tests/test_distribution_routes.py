import os
import unittest

import app as geo_app
from services.content_generations import ContentGenerationStore
from tests.test_app_core import isolated_app_data


class DistributionRouteTests(unittest.TestCase):
    def test_resource_sync_persists_fake_supplier_result(self):
        class FakeClient:
            def list_self_media(self, page, limit):
                return [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}] if page == 1 else []

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            with unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=FakeClient(), create=True):
                client = geo_app.app.test_client()
                synced = client.post("/api/distribution/resources/sync", json={"client_id": client_id})
                listed = client.get("/api/distribution/resources?client_id=" + client_id)
            self.assertEqual(synced.status_code, 200)
            self.assertEqual(listed.get_json()["resources"][0]["name"], "账号A")
    def test_create_draft_accepts_blocked_article_and_preview_uses_token(self):
        with isolated_app_data() as tmp:
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            store = ContentGenerationStore(os.path.join(tmp, "content_generations.sqlite3"))
            store.append_generation(
                client_id,
                {
                    "id": "article-a", "title": "冻结标题", "content": "冻结正文",
                    "created_at": "2026-07-22 10:00:00", "gate_report": {"verdict": "blocked"},
                },
                {"role": "user", "content": "生成请求"},
                {"role": "assistant", "content": "冻结正文", "article_id": "article-a"},
            )

            client = geo_app.app.test_client()
            created = client.post(
                "/api/distribution/drafts", json={"client_id": client_id, "article_id": "article-a"}
            )

            self.assertEqual(created.status_code, 200)
            draft = created.get_json()["draft"]
            self.assertEqual(draft["gate_verdict"], "blocked")
            preview = client.get("/public/publications/" + draft["preview_token"])
            self.assertEqual(preview.status_code, 200)
            self.assertIn("冻结正文", preview.get_data(as_text=True))
            self.assertEqual(preview.headers["X-Robots-Tag"], "noindex, nofollow")

            listing = client.get("/api/distribution/drafts?client_id=" + client_id)
            self.assertEqual(listing.status_code, 200)
            self.assertEqual([item["id"] for item in listing.get_json()["drafts"]], [draft["id"]])

            deleted = client.delete(
                "/api/content/generations/article-a?client_id=" + client_id
            )
            self.assertEqual(deleted.status_code, 409)
            self.assertEqual(deleted.get_json()["error"], "article_has_publication_state")


if __name__ == "__main__":
    unittest.main()
