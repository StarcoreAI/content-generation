import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

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
    def test_build_node_output_dir_returns_absolute_path_for_relative_data_dir(self):
        path = geo_app.build_node_output_dir("data", "task-1", "qwen")
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(path.endswith(os.path.join("data", "tasks", "node", "task-1", "qwen")))

    def test_should_use_node_crawler_env_flag(self):
        old_value = os.environ.get("GEO_NODE_CRAWLER_PLATFORMS")
        try:
            os.environ.pop("GEO_NODE_CRAWLER_PLATFORMS", None)
            self.assertTrue(geo_app.should_use_node_crawler("doubao"))
            self.assertTrue(geo_app.should_use_node_crawler("deepseek"))
            self.assertTrue(geo_app.should_use_node_crawler("yuanbao"))
            self.assertTrue(geo_app.should_use_node_crawler("qwen"))

            os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "none"
            self.assertFalse(geo_app.should_use_node_crawler("doubao"))
            self.assertFalse(geo_app.should_use_node_crawler("qwen"))

            os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "doubao, qwen"
            self.assertTrue(geo_app.should_use_node_crawler("doubao"))
            self.assertTrue(geo_app.should_use_node_crawler("qwen"))
            self.assertFalse(geo_app.should_use_node_crawler("deepseek"))

            os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "all"
            self.assertTrue(geo_app.should_use_node_crawler("yuanbao"))
        finally:
            if old_value is None:
                os.environ.pop("GEO_NODE_CRAWLER_PLATFORMS", None)
            else:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = old_value

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

    def test_calibrate_analysis_uses_full_brand_mention_from_answer(self):
        analysis = geo_app.calibrate_analysis_brand_mention(
            "苏韵汽车音响",
            "扬州汽车音响改装升级哪家好",
            "第三个可以看苏韵汽车音响，调音比较细。",
            [{"title": "苏韵汽车音响案例", "url": "https://example.com"}],
            {
                "brand_mentioned": False,
                "brand_rank": 3,
                "brand_sentiment": "positive",
                "brand_snippet": "",
            },
        )

        self.assertTrue(analysis["brand_mentioned"])
        self.assertIn("苏韵汽车音响", analysis["brand_snippet"])
        self.assertGreater(analysis["geo_score"], 0)

    def test_save_raw_record_uses_analysis_mention_flag_and_writes_daily_archive(self):
        with isolated_app_data() as tmp:
            record_id = geo_app.save_raw_record(
                client_id="client-1",
                group_id="group-1",
                brand="苏韵汽车音响",
                question="扬州汽车音响改装哪家好？",
                round_num=1,
                answer="苏州有不少汽车音响案例，但这里没有完整品牌名。",
                search_keywords=[],
                refs=[{"title": "汽车音响改装指南", "url": "https://example.com", "platform": "示例"}],
                analysis={
                    "brand_mentioned": False,
                    "geo_score": 0,
                    "main_ref": {"platform": "示例"},
                },
                source_platform="deepseek",
            )

            records = geo_app.load(geo_app.F_RAW_RECORDS, [])
            self.assertEqual(records[0]["id"], record_id)
            self.assertFalse(records[0]["brand_mentioned"])
            self.assertEqual(records[0]["source_platform"], "deepseek")

            loaded = geo_app.load_client_records("client-1", group_id="group-1", platform="deepseek")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["question"], "扬州汽车音响改装哪家好？")

            all_platform_records = geo_app.load_client_records("client-1", group_id="group-1", platform="all")
            self.assertEqual(len(all_platform_records), 1)

            day_file = os.path.join(tmp, "raw", "client-1", f"{geo_app.today_str()}.json")
            self.assertTrue(os.path.exists(day_file))


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
            self.assertIn("task_id", payload)
            self.assertTrue(os.path.exists(payload["task_report"]))
            report = geo_app.load(payload["task_report"], {})
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["error"], "need_login")
            self.assertEqual(report["brand"], "测试品牌")
            self.assertEqual(report["questions"], ["测试问题"])

    def test_crawl_uses_group_questions_without_legacy_probe_fallback(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_GROUPS,
                {
                    "client-1": [
                        {
                            "id": "group-1",
                            "name": "手动问题组",
                            "description": "",
                            "questions": ["手动问题1", "手动问题2"],
                        }
                    ]
                },
            )
            geo_app.save(geo_app.F_PROBES, {"client-1": [{"q": "旧问题库问题"}]})

            response = self.client.post(
                "/api/platform/crawl",
                json={
                    "client_id": "client-1",
                    "brand": "测试品牌",
                    "group_id": "group-1",
                    "platform": "qwen",
                    "repeat_count": 1,
                    "parallel": 1,
                },
            )

            self.assertEqual(response.status_code, 401)
            report = geo_app.load(response.get_json()["task_report"], {})
            self.assertEqual(report["questions"], ["手动问题1", "手动问题2"])

    def test_crawl_rejects_missing_group_questions(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_PROBES, {"client-1": [{"q": "旧问题库问题"}]})

            response = self.client.post(
                "/api/platform/crawl",
                json={
                    "client_id": "client-1",
                    "brand": "测试品牌",
                    "platform": "qwen",
                    "repeat_count": 1,
                    "parallel": 1,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("问题组", response.get_json()["error"])

    def test_platform_neutral_daily_list_alias(self):
        with isolated_app_data():
            geo_app.save_daily_raw(
                "client-1",
                "测试品牌",
                "测试问题",
                "测试回答",
                [],
                {"geo_score": 0, "main_ref": {}},
            )

            new_response = self.client.get("/api/crawl/daily_list?client_id=client-1")
            old_response = self.client.get("/api/doubao/daily_list?client_id=client-1")

            self.assertEqual(new_response.status_code, 200)
            self.assertEqual(new_response.get_json(), old_response.get_json())
            self.assertEqual(new_response.get_json()["dates"], [geo_app.today_str()])

    def test_clear_daily_records_respects_source_platform(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-ds",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "deepseek",
                    },
                    {
                        "id": "raw-qwen",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                    },
                ],
            )

            response = self.client.post(
                "/api/daily/records/clear",
                json={"client_id": "client-1", "date": geo_app.today_str(), "platform": "deepseek"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["deleted"], 1)
            self.assertEqual(
                geo_app.load(geo_app.F_RAW_RECORDS, []),
                [
                    {
                        "id": "raw-qwen",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                    }
                ],
            )

    def test_clear_daily_records_all_platforms(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-ds",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "deepseek",
                    },
                    {
                        "id": "raw-qwen",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                    },
                    {
                        "id": "raw-other-client",
                        "client_id": "client-2",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                    },
                ],
            )

            response = self.client.post(
                "/api/daily/records/clear",
                json={"client_id": "client-1", "date": geo_app.today_str(), "platform": "all"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["deleted"], 2)
            self.assertEqual(
                geo_app.load(geo_app.F_RAW_RECORDS, []),
                [
                    {
                        "id": "raw-other-client",
                        "client_id": "client-2",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                    }
                ],
            )

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
            self.assertIn("task_id", payload)
            self.assertTrue(os.path.exists(payload["task_report"]))
            report = geo_app.load(payload["task_report"], {})
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["error"], "cookie_expired")

    def test_crawl_rejects_when_global_lock_is_busy(self):
        acquired = geo_app.crawl_run_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
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
        finally:
            geo_app.crawl_run_lock.release()

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["error"], "crawl_busy")
        self.assertIn("已有爬取任务进行中", payload["message"])

    def test_crawl_uses_node_bridge_when_platform_flag_enabled(self):
        old_value = os.environ.get("GEO_NODE_CRAWLER_PLATFORMS")
        try:
            with isolated_app_data() as tmp:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "qwen"
                geo_app.save(
                    os.path.join(tmp, "qwen_state.json"),
                    {
                        "cookies": [
                            {"name": "session", "value": "abc", "domain": ".qianwen.com", "path": "/"}
                        ],
                        "origins": [],
                    },
                )
                base_crawler.mark_login_status("qwen", "ok", "登录状态已保存")

                calls = []

                def fake_run_node_crawler(platform, questions, **kwargs):
                    calls.append({"platform": platform, "questions": questions, "kwargs": kwargs})
                    return {
                        "ok": True,
                        "platform": platform,
                        "total": len(questions),
                        "success": len(questions),
                        "results": [
                            {
                                "ok": True,
                                "question": questions[0],
                                "answer": "测试品牌可以作为候选之一，具体需要结合实际评估。",
                                "refs": [
                                    {
                                        "title": "测试品牌参考文章",
                                        "url": "https://www.sohu.com/a/123",
                                        "platform": "搜狐",
                                    }
                                ],
                                "error": "",
                            }
                        ],
                    }

                with patch("services.node_crawler_bridge.run_node_crawler", side_effect=fake_run_node_crawler):
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

                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["crawler_engine"], "node")
                self.assertEqual(calls[0]["platform"], "qwen")
                self.assertEqual(calls[0]["questions"], ["测试问题"])
                self.assertIn("output_dir", calls[0]["kwargs"])
                self.assertTrue(os.path.isabs(calls[0]["kwargs"]["output_dir"]))
                self.assertTrue(calls[0]["kwargs"]["output_dir"].endswith(os.path.join("tasks", "node", payload["task_id"], "qwen")))

                records = geo_app.load(geo_app.F_RAW_RECORDS, [])
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["source_platform"], "qwen")
                self.assertEqual(records[0]["question"], "测试问题")
                self.assertEqual(records[0]["refs"][0]["platform"], "搜狐")

                report = geo_app.load(payload["task_report"], {})
                self.assertEqual(report["crawler_engine"], "node")
                self.assertEqual(report["node_output_dir"], calls[0]["kwargs"]["output_dir"])
                self.assertEqual(report["status"], "completed")
        finally:
            if old_value is None:
                os.environ.pop("GEO_NODE_CRAWLER_PLATFORMS", None)
            else:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = old_value

    def test_crawl_summary_uses_full_answer_for_brand_mention(self):
        old_value = os.environ.get("GEO_NODE_CRAWLER_PLATFORMS")
        brand = "\u6d4b\u8bd5\u54c1\u724c"
        question = "\u6d4b\u8bd5\u95ee\u9898"
        answer = ("x" * 850) + brand + "\u5728\u7b54\u6848\u540e\u6bb5\u88ab\u63d0\u5230"
        try:
            with isolated_app_data() as tmp:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "qwen"
                geo_app.save(
                    os.path.join(tmp, "qwen_state.json"),
                    {
                        "cookies": [
                            {"name": "session", "value": "abc", "domain": ".qianwen.com", "path": "/"}
                        ],
                        "origins": [],
                    },
                )
                base_crawler.mark_login_status("qwen", "ok", "\u767b\u5f55\u72b6\u6001\u5df2\u4fdd\u5b58")

                def fake_run_node_crawler(platform, questions, **kwargs):
                    return {
                        "ok": True,
                        "platform": platform,
                        "total": 1,
                        "success": 1,
                        "results": [
                            {
                                "ok": True,
                                "question": questions[0],
                                "answer": answer,
                                "refs": [],
                                "error": "",
                            }
                        ],
                    }

                with patch("services.node_crawler_bridge.run_node_crawler", side_effect=fake_run_node_crawler):
                    response = self.client.post(
                        "/api/platform/crawl",
                        json={
                            "client_id": "client-1",
                            "brand": brand,
                            "questions": [question],
                            "platform": "qwen",
                            "repeat_count": 1,
                            "parallel": 1,
                        },
                    )

                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertTrue(payload["results"][0]["brand_mentioned"])

                report = geo_app.load(payload["task_report"], {})
                self.assertTrue(report["success"][0]["brand_mentioned"])
                self.assertEqual(report["batch_summary"]["mentioned_count"], 1)

                raw_records = geo_app.load(geo_app.F_RAW_RECORDS, [])
                self.assertEqual(len(raw_records), 1)
                self.assertTrue(raw_records[0]["brand_mentioned"])
        finally:
            if old_value is None:
                os.environ.pop("GEO_NODE_CRAWLER_PLATFORMS", None)
            else:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = old_value

    def test_node_bridge_need_login_marks_platform_expired(self):
        old_value = os.environ.get("GEO_NODE_CRAWLER_PLATFORMS")
        try:
            with isolated_app_data() as tmp:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "doubao"
                geo_app.save(
                    os.path.join(tmp, "doubao_state.json"),
                    {
                        "cookies": [
                            {"name": "session", "value": "abc", "domain": ".doubao.com", "path": "/"}
                        ],
                        "origins": [],
                    },
                )
                base_crawler.mark_login_status("doubao", "ok", "登录状态已保存")

                from services.node_crawler_bridge import NodeCrawlerBridgeError

                with patch(
                    "services.node_crawler_bridge.run_node_crawler",
                    side_effect=NodeCrawlerBridgeError("Node crawler failed: need_login: login action detected"),
                ):
                    response = self.client.post(
                        "/api/platform/crawl",
                        json={
                            "client_id": "client-1",
                            "brand": "测试品牌",
                            "questions": ["测试问题"],
                            "platform": "doubao",
                            "repeat_count": 1,
                            "parallel": 1,
                        },
                    )

                self.assertEqual(response.status_code, 401)
                payload = response.get_json()
                self.assertEqual(payload["error"], "cookie_expired")
                self.assertIn("task_report", payload)

                status = base_crawler.get_platform_login_status("doubao")
                self.assertFalse(status["logged_in"])
                self.assertEqual(status["status"], "expired")
        finally:
            if old_value is None:
                os.environ.pop("GEO_NODE_CRAWLER_PLATFORMS", None)
            else:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = old_value

    def test_node_bridge_verification_required_returns_rate_limited(self):
        old_value = os.environ.get("GEO_NODE_CRAWLER_PLATFORMS")
        try:
            with isolated_app_data() as tmp:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "doubao"
                geo_app.save(
                    os.path.join(tmp, "doubao_state.json"),
                    {
                        "cookies": [
                            {"name": "session", "value": "abc", "domain": ".doubao.com", "path": "/"}
                        ],
                        "origins": [],
                    },
                )
                base_crawler.mark_login_status("doubao", "ok", "登录状态已保存")

                from services.node_crawler_bridge import NodeCrawlerBridgeError

                with patch(
                    "services.node_crawler_bridge.run_node_crawler",
                    side_effect=NodeCrawlerBridgeError(
                        "Node crawler failed: doubao verification_required: rate limited"
                    ),
                ):
                    response = self.client.post(
                        "/api/platform/crawl",
                        json={
                            "client_id": "client-1",
                            "brand": "测试品牌",
                            "questions": ["测试问题"],
                            "platform": "doubao",
                            "repeat_count": 1,
                            "parallel": 1,
                        },
                    )

                self.assertEqual(response.status_code, 429)
                payload = response.get_json()
                self.assertEqual(payload["error"], "verification_required")
                self.assertIn("task_report", payload)

                status = base_crawler.get_platform_login_status("doubao")
                self.assertFalse(status["logged_in"])
                self.assertEqual(status["status"], "expired")
        finally:
            if old_value is None:
                os.environ.pop("GEO_NODE_CRAWLER_PLATFORMS", None)
            else:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = old_value


if __name__ == "__main__":
    unittest.main()
