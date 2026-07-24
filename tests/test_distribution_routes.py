import io
import os
import unittest

import app as geo_app
from services.content_generations import ContentGenerationStore
from tests.test_app_core import isolated_app_data


class DistributionRouteTests(unittest.TestCase):
    def test_order_rejects_supplier_business_error_without_creating_local_order(self):
        class FakeClient:
            def create_self_media_order(self, title, content, mid, no, saling_price):
                return {"code": 201, "msg": "余额不足"}

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            draft = geo_app.publication_store().create_draft(client_id, {
                "id": "article-a", "title": "文章标题", "content": "文章正文",
            })
            geo_app.publication_store().upsert_resources(client_id, [{
                "resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {},
            }], geo_app.now_str())
            geo_app.save(geo_app.user_settings_path("operator"), {
                "rwmeiti_secret_id": "sid", "rwmeiti_secret_key": "key",
            })
            with unittest.mock.patch.object(geo_app, "settings_username", return_value="operator"), \
                 unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=FakeClient()), \
                 unittest.mock.patch.dict(os.environ, {"GEO_PUBLIC_BASE_URL": "http://preview.example.test"}, clear=False):
                response = geo_app.app.test_client().post("/api/distribution/orders", json={
                    "client_id": client_id, "draft_id": draft["id"], "resource_id": "7",
                })

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error"], "余额不足")
            self.assertEqual(geo_app.publication_store().list_orders(client_id), [])

    def test_order_does_not_resubmit_a_draft_that_already_has_an_order(self):
        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            draft = geo_app.publication_store().create_draft(client_id, {
                "id": "article-a", "title": "文章标题", "content": "文章正文",
            })
            geo_app.publication_store().upsert_resources(client_id, [{
                "resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {},
            }], geo_app.now_str())
            existing = geo_app.publication_store().create_supplier_order(
                client_id, draft["id"], "geo-" + draft["id"], "self_media", "7", "账号A", 88,
            )

            response = geo_app.app.test_client().post("/api/distribution/orders", json={
                "client_id": client_id, "draft_id": draft["id"], "resource_id": "7",
            })

            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error"], "draft_already_has_supplier_order")
            self.assertEqual(response.get_json()["order"]["id"], existing["id"])

    def test_refresh_self_media_order_marks_published_and_saves_url(self):
        calls = []

        class FakeClient:
            def query_self_media_orders(self, order_numbers):
                calls.append(order_numbers)
                return [{"no3": "geo-order-a", "status": 2, "url": "https://example.test/published"}]

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            draft = geo_app.publication_store().create_draft(client_id, {
                "id": "article-a", "title": "文章标题", "content": "文章正文",
            })
            order = geo_app.publication_store().create_supplier_order(
                client_id, draft["id"], "geo-order-a", "self_media", "7", "账号A", 88,
            )
            geo_app.save(geo_app.user_settings_path("operator"), {
                "rwmeiti_secret_id": "sid", "rwmeiti_secret_key": "key",
            })
            with unittest.mock.patch.object(geo_app, "settings_username", return_value="operator"), \
                 unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=FakeClient()):
                response = geo_app.app.test_client().post(
                    "/api/distribution/orders/" + order["id"] + "/refresh", json={"client_id": client_id}
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(calls, [["geo-order-a"]])
            self.assertEqual(response.get_json()["order"]["status"], "published")
            self.assertEqual(response.get_json()["order"]["provider_url"], "https://example.test/published")
            self.assertEqual(geo_app.publication_store().list_publications(client_id)[0]["url"], "https://example.test/published")

    def test_refresh_news_media_order_marks_published_and_saves_url(self):
        class FakeClient:
            def query_news_media_orders(self, order_numbers):
                return [{"no3": "geo-order-a", "status": 2, "url": "https://example.test/news-published"}]

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            draft = geo_app.publication_store().create_draft(client_id, {
                "id": "article-a", "title": "文章标题", "content": "文章正文",
            })
            order = geo_app.publication_store().create_supplier_order(
                client_id, draft["id"], "geo-order-a", "news_media", "7", "媒体A", 88,
            )
            geo_app.save(geo_app.user_settings_path("operator"), {
                "rwmeiti_secret_id": "sid", "rwmeiti_secret_key": "key",
            })
            with unittest.mock.patch.object(geo_app, "settings_username", return_value="operator"), \
                 unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=FakeClient()):
                response = geo_app.app.test_client().post(
                    "/api/distribution/orders/" + order["id"] + "/refresh", json={"client_id": client_id}
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["order"]["status"], "published")
            self.assertEqual(response.get_json()["order"]["provider_url"], "https://example.test/news-published")

    def test_upload_article_creates_publish_draft_directly(self):
        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])

            uploaded = geo_app.app.test_client().post("/api/distribution/drafts/upload", data={
                "client_id": client_id,
                "files": [(io.BytesIO("外部文章标题\n\n外部文章正文".encode("utf-8")), "外部稿件.md")],
            }, content_type="multipart/form-data")

            self.assertEqual(uploaded.status_code, 200)
            draft = uploaded.get_json()["drafts"][0]
            self.assertEqual(draft["article_title"], "外部文章标题")
            self.assertEqual(draft["article_content"], "外部文章正文")
            self.assertEqual(draft["status"], "draft")

    def test_publish_resources_are_current_operators_catalog_backed_favorites(self):
        with isolated_app_data() as tmp:
            original_catalog = getattr(geo_app, "F_DISTRIBUTION_CATALOG", None)
            original_favorites = geo_app.F_DISTRIBUTION_FAVORITES
            geo_app.F_DISTRIBUTION_CATALOG = os.path.join(tmp, "distribution_catalog")
            geo_app.F_DISTRIBUTION_FAVORITES = os.path.join(tmp, "distribution_favorites")
            try:
                client_id = "client-a"
                geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
                geo_app.save(geo_app.distribution_catalog_path("operator"), [{
                    "resource_id": "7", "resource_type": "self_media", "name": "账号A", "price": 88, "status": "1", "raw": {},
                }])
                geo_app.save(geo_app.distribution_favorites_path("operator"), [{
                    "id": "favorite-a", "resource_id": "7", "resource_type": "self_media",
                }])

                with unittest.mock.patch.object(geo_app, "current_user", return_value={"username": "operator"}):
                    response = geo_app.app.test_client().get("/api/distribution/resources?client_id=" + client_id)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["resources"][0]["name"], "账号A")
            finally:
                geo_app.F_DISTRIBUTION_FAVORITES = original_favorites
                if original_catalog is None:
                    delattr(geo_app, "F_DISTRIBUTION_CATALOG")
                else:
                    geo_app.F_DISTRIBUTION_CATALOG = original_catalog

    def test_order_submits_public_http_preview_link(self):
        class FakeClient:
            def __init__(self):
                self.order = None

            def create_self_media_order(self, title, content, mid, no, saling_price):
                self.order = (title, content, mid, no, saling_price)
                return {"code": 200}

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            draft = geo_app.publication_store().create_draft(client_id, {
                "id": "article-a", "title": "文章标题", "content": "文章标题\n第一段 <重点>\n\n第二段",
            })
            geo_app.publication_store().upsert_resources(client_id, [{
                "resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {},
            }], geo_app.now_str())
            geo_app.save(geo_app.user_settings_path("operator"), {
                "rwmeiti_secret_id": "sid", "rwmeiti_secret_key": "key",
            })
            supplier = FakeClient()
            with unittest.mock.patch.object(geo_app, "settings_username", return_value="operator"), \
                 unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=supplier), \
                 unittest.mock.patch.dict(os.environ, {"GEO_PUBLIC_BASE_URL": "http://preview.example.test"}, clear=False):
                response = geo_app.app.test_client().post("/api/distribution/orders", json={
                    "client_id": client_id, "draft_id": draft["id"], "resource_id": "7",
                })

            self.assertEqual(response.status_code, 200)
            preview_url = "http://preview.example.test/public/publications/" + draft["preview_token"]
            self.assertEqual(supplier.order, (
                "文章标题", '稿件链接：<a href="' + preview_url + '">' + preview_url + "</a>", "7", "geo-" + draft["id"], 88.0,
            ))

    def test_order_submits_news_media_to_news_endpoint(self):
        class FakeClient:
            def __init__(self):
                self.news_order = None

            def create_news_media_order(self, title, content, mid, no, saling_price):
                self.news_order = (title, content, mid, no, saling_price)
                return {"code": 200}

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            draft = geo_app.publication_store().create_draft(client_id, {
                "id": "article-a", "title": "新闻标题", "content": "新闻标题\n新闻正文",
            })
            geo_app.publication_store().upsert_resources(client_id, [{
                "resource_id": "1364", "resource_type": "news_media", "name": "新闻媒体", "price": 99, "status": "1", "raw": {},
            }], geo_app.now_str())
            geo_app.save(geo_app.user_settings_path("operator"), {
                "rwmeiti_secret_id": "sid", "rwmeiti_secret_key": "key",
            })
            supplier = FakeClient()
            with unittest.mock.patch.object(geo_app, "settings_username", return_value="operator"), \
                 unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=supplier), \
                 unittest.mock.patch.dict(os.environ, {"GEO_PUBLIC_BASE_URL": "http://preview.example.test"}, clear=False):
                response = geo_app.app.test_client().post("/api/distribution/orders", json={
                    "client_id": client_id, "draft_id": draft["id"],
                    "resource_id": "1364", "resource_type": "news_media",
                })

            self.assertEqual(response.status_code, 200)
            preview_url = "http://preview.example.test/public/publications/" + draft["preview_token"]
            self.assertEqual(supplier.news_order, (
                "新闻标题", '稿件链接：<a href="' + preview_url + '">' + preview_url + "</a>", "1364", "geo-" + draft["id"], 99.0,
            ))

    def test_resource_sync_persists_fake_supplier_result(self):
        class FakeClient:
            def __init__(self):
                self.requests = []

            def list_self_media(self, page, limit, resource_id):
                self.requests.append((page, limit, resource_id))
                return [{"resource_id": resource_id, "name": "账号" + resource_id, "price": 88, "status": "1", "raw": {}}]

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            supplier = FakeClient()
            with unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=supplier, create=True):
                client = geo_app.app.test_client()
                synced = client.post("/api/distribution/resources/sync", json={"client_id": client_id, "resource_ids": ["7", "8"]})
                listed = client.get("/api/distribution/resources?client_id=" + client_id)
            self.assertEqual(synced.status_code, 200)
            self.assertEqual(synced.get_json()["count"], 2)
            self.assertEqual(supplier.requests, [(1, 5, "7"), (1, 5, "8")])
            self.assertEqual([item["resource_id"] for item in listed.get_json()["resources"]], ["7", "8"])

    def test_news_resource_sync_uses_news_media_lookup(self):
        class FakeClient:
            def list_news_media(self, page, limit, resource_id):
                self.request = (page, limit, resource_id)
                return [{"resource_id": resource_id, "resource_type": "news_media", "name": "新闻媒体", "price": 99, "status": "1", "raw": {}}]

        with isolated_app_data():
            client_id = "client-a"
            geo_app.save(geo_app.F_CLIENTS, [{"id": client_id, "name": "客户"}])
            supplier = FakeClient()
            with unittest.mock.patch.object(geo_app, "rwmeiti_client_from_env", return_value=supplier):
                client = geo_app.app.test_client()
                synced = client.post("/api/distribution/resources/sync", json={
                    "client_id": client_id,
                    "resources": [{"resource_id": "1364", "resource_type": "news_media"}],
                })
                listed = client.get("/api/distribution/resources?client_id=" + client_id)
            self.assertEqual(synced.status_code, 200)
            self.assertEqual(supplier.request, (1, 5, "1364"))
            self.assertEqual(listed.get_json()["resources"][0]["resource_type"], "news_media")
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
