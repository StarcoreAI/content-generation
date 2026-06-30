import json
import os
import tempfile
import unittest
from contextlib import contextmanager

import app as geo_app
import base_crawler


@contextmanager
def isolated_app_data():
    original = {
        "D": geo_app.D,
        "F_CLIENTS": geo_app.F_CLIENTS,
        "F_PROBES": geo_app.F_PROBES,
        "F_RECORDS": geo_app.F_RECORDS,
        "F_PLATFORMS": geo_app.F_PLATFORMS,
        "F_ARTICLES": geo_app.F_ARTICLES,
        "F_SETTINGS": geo_app.F_SETTINGS,
        "F_GROUPS": geo_app.F_GROUPS,
        "F_RAW_RECORDS": geo_app.F_RAW_RECORDS,
        "BASE_CRAWLER_DATA_DIR": base_crawler.DATA_DIR,
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.D = tmp
        geo_app.F_CLIENTS = os.path.join(tmp, "clients.json")
        geo_app.F_PROBES = os.path.join(tmp, "probes.json")
        geo_app.F_RECORDS = os.path.join(tmp, "records.json")
        geo_app.F_PLATFORMS = os.path.join(tmp, "platforms.json")
        geo_app.F_ARTICLES = os.path.join(tmp, "articles.json")
        geo_app.F_SETTINGS = os.path.join(tmp, "settings.json")
        geo_app.F_GROUPS = os.path.join(tmp, "probe_groups.json")
        geo_app.F_RAW_RECORDS = os.path.join(tmp, "raw_records.json")
        base_crawler.DATA_DIR = tmp
        try:
            yield tmp
        finally:
            for key, value in original.items():
                if key == "BASE_CRAWLER_DATA_DIR":
                    base_crawler.DATA_DIR = value
                else:
                    setattr(geo_app, key, value)


class CoreFunctionTests(unittest.TestCase):
    def test_calc_geo_score_requires_brand_in_answer(self):
        score = geo_app.calc_geo_score(
            "测试品牌",
            "哪家好？",
            "这里没有目标品牌。",
            [{"title": "测试品牌案例", "url": "https://example.com"}],
            {"brand_rank": 1, "brand_sentiment": "positive"},
        )
        self.assertEqual(score, 0)

    def test_calc_geo_score_uses_rank_refs_and_sentiment(self):
        score = geo_app.calc_geo_score(
            "测试品牌",
            "哪家好？",
            "测试品牌是一家可选公司。",
            [{"title": "测试品牌案例", "url": "https://example.com"}],
            {"brand_rank": 1, "brand_sentiment": "positive"},
        )
        self.assertEqual(score, 70)

    def test_save_and_load_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.json")
            geo_app.save(path, {"name": "测试", "items": [1, 2]})
            self.assertEqual(
                geo_app.load(path, {}),
                {"name": "测试", "items": [1, 2]},
            )

    def test_basic_brand_analysis_without_api_marks_pending(self):
        analysis = geo_app.basic_brand_analysis_without_api(
            "测试品牌",
            "哪家好？",
            "测试品牌可以考虑。它在本地服务、交付流程和案例资料方面都有明确说明，适合作为候选。",
            [{"title": "测试文章", "platform": "示例平台", "url": "https://example.com"}],
        )
        self.assertTrue(analysis["brand_mentioned"])
        self.assertEqual(analysis["analysis_status"], "pending_api")
        self.assertEqual(analysis["analysis_mode"], "basic_no_api_key")
        self.assertGreaterEqual(analysis["geo_score"], 20)


class FlaskApiTests(unittest.TestCase):
    def setUp(self):
        geo_app.app.config["TESTING"] = True
        self.client = geo_app.app.test_client()

    def test_health_does_not_require_api_key(self):
        with isolated_app_data():
            response = self.client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["has_api_key"])
            self.assertEqual(payload["clients_count"], 0)
            self.assertEqual(payload["version"], geo_app.APP_VERSION)

    def test_settings_save_hides_api_key_on_read(self):
        with isolated_app_data():
            response = self.client.post(
                "/api/settings",
                json={
                    "api_key": "secret-key",
                    "base_url": "https://api.example.com",
                    "model": "test-model",
                    "preset": "custom",
                },
            )
            self.assertEqual(response.status_code, 200)

            read_response = self.client.get("/api/settings")
            payload = read_response.get_json()
            self.assertTrue(payload["has_key"])
            self.assertNotIn("api_key", payload)
            self.assertEqual(payload["base_url"], "https://api.example.com")
            self.assertEqual(payload["model"], "test-model")

    def test_platform_list_shape(self):
        with isolated_app_data():
            response = self.client.get("/api/platform/list")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            platform_ids = {item["id"] for item in payload}
            self.assertEqual(platform_ids, {"doubao", "deepseek", "yuanbao", "qwen"})
            self.assertTrue(all("logged_in" in item for item in payload))
            self.assertTrue(all("status" in item for item in payload))
            self.assertTrue(all("state_file_exists" in item for item in payload))

    def test_platform_check_login_distinguishes_saved_state_from_verified_login(self):
        with isolated_app_data() as tmp:
            geo_app.save(
                os.path.join(tmp, "qwen_state.json"),
                {
                    "cookies": [
                        {"name": "session", "value": "abc", "domain": ".qianwen.com", "path": "/"}
                    ],
                    "origins": [],
                },
            )

            response = self.client.get("/api/platform/check_login?platform=qwen")
            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["state_file_exists"])
            self.assertEqual(payload["status"], "unknown")
            self.assertFalse(payload["logged_in"])

            base_crawler.mark_login_status("qwen", "ok", "登录状态已保存")
            verified = self.client.get("/api/platform/check_login?platform=qwen").get_json()
            self.assertEqual(verified["status"], "ok")
            self.assertTrue(verified["logged_in"])

            base_crawler.mark_login_status("qwen", "expired", "登录状态已过期，请重新登录")
            expired = self.client.get("/api/platform/check_login?platform=qwen").get_json()
            self.assertEqual(expired["status"], "expired")
            self.assertFalse(expired["logged_in"])

    def test_group_create_update_delete_flow(self):
        cid = "client-1"
        with isolated_app_data():
            create_response = self.client.post(
                f"/api/groups/{cid}",
                json={"name": "问题组", "description": "初始", "questions": ["问题1"]},
            )
            self.assertEqual(create_response.status_code, 200)
            gid = create_response.get_json()["group"]["id"]

            update_response = self.client.put(
                f"/api/groups/{cid}/{gid}",
                json={"name": "新问题组", "questions": ["问题1", "问题2"]},
            )
            self.assertEqual(update_response.status_code, 200)

            groups = self.client.get(f"/api/groups/{cid}").get_json()
            self.assertEqual(groups[0]["name"], "新问题组")
            self.assertEqual(groups[0]["questions"], ["问题1", "问题2"])

            delete_response = self.client.delete(f"/api/groups/{cid}/{gid}")
            self.assertEqual(delete_response.status_code, 200)
            self.assertEqual(self.client.get(f"/api/groups/{cid}").get_json(), [])

    def test_delete_client_removes_related_local_data(self):
        cid = "client-1"
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌"}])
            geo_app.save(geo_app.F_PROBES, {cid: [{"q": "问题"}]})
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": "g1", "questions": ["问题"]}]})
            geo_app.save(geo_app.F_RECORDS, [{"id": "r1", "client_id": cid}, {"id": "r2", "client_id": "other"}])
            geo_app.save(geo_app.F_RAW_RECORDS, [{"id": "raw1", "client_id": cid}])
            geo_app.save(geo_app.F_ARTICLES, [{"id": "a1", "client_id": cid}])

            response = self.client.delete(f"/api/clients/{cid}")
            self.assertEqual(response.status_code, 200)

            self.assertEqual(geo_app.load(geo_app.F_CLIENTS, []), [])
            self.assertEqual(geo_app.load(geo_app.F_PROBES, {}), {})
            self.assertEqual(geo_app.load(geo_app.F_GROUPS, {}), {})
            self.assertEqual(geo_app.load(geo_app.F_RECORDS, []), [{"id": "r2", "client_id": "other"}])
            self.assertEqual(geo_app.load(geo_app.F_RAW_RECORDS, []), [])
            self.assertEqual(geo_app.load(geo_app.F_ARTICLES, []), [])

    def test_crawl_without_login_returns_need_login_before_crawling(self):
        with isolated_app_data() as tmp:
            response = self.client.post(
                "/api/platform/crawl",
                json={
                    "client_id": "client-1",
                    "brand": "测试品牌",
                    "questions": ["测试问题"],
                    "platform": "qwen",
                    "repeat_count": 1,
                    "parallel": 1,
                },
            )

            self.assertEqual(response.status_code, 401)
            payload = response.get_json()
            self.assertEqual(payload["error"], "need_login")
            self.assertFalse(payload["has_api_key"])

    def test_crawl_with_unverified_saved_state_returns_cookie_expired_before_crawling(self):
        with isolated_app_data() as tmp:
            geo_app.save(
                os.path.join(tmp, "qwen_state.json"),
                {
                    "cookies": [
                        {"name": "session", "value": "abc", "domain": ".qianwen.com", "path": "/"}
                    ],
                    "origins": [],
                },
            )

            response = self.client.post(
                "/api/platform/crawl",
                json={
                    "client_id": "client-1",
                    "brand": "测试品牌",
                    "questions": ["测试问题"],
                    "platform": "qwen",
                    "repeat_count": 1,
                    "parallel": 1,
                },
            )

            self.assertEqual(response.status_code, 401)
            payload = response.get_json()
            self.assertEqual(payload["error"], "cookie_expired")
            self.assertEqual(payload["login_status"], "unknown")
            self.assertTrue(payload["state_file_exists"])


if __name__ == "__main__":
    unittest.main()
