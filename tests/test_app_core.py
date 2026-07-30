import json
import io
import os
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
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
        "F_COMPETITOR_ARTICLE_BODY_HITS": geo_app.F_COMPETITOR_ARTICLE_BODY_HITS,
        "F_CONTENT_GENERATIONS": getattr(geo_app, "F_CONTENT_GENERATIONS", None),
        "CONTENT_UPLOAD_FOLDER": getattr(geo_app, "CONTENT_UPLOAD_FOLDER", None),
        "F_CONTENT_MATERIALS_INDEX": getattr(geo_app, "F_CONTENT_MATERIALS_INDEX", None),
        "CONTENT_MATERIAL_CACHE_FOLDER": getattr(geo_app, "CONTENT_MATERIAL_CACHE_FOLDER", None),
        "F_CRAWL_JOBS": getattr(geo_app, "F_CRAWL_JOBS", None),
        "UPLOAD_FOLDER": getattr(geo_app, "UPLOAD_FOLDER", None),
        "F_MATERIALS_INDEX": getattr(geo_app, "F_MATERIALS_INDEX", None),
        "MATERIAL_CACHE_FOLDER": getattr(geo_app, "MATERIAL_CACHE_FOLDER", None),
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
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
        geo_app.F_COMPETITOR_ARTICLE_BODY_HITS = os.path.join(tmp, "competitor_article_body_hits.json")
        geo_app.F_CONTENT_GENERATIONS = os.path.join(tmp, "content_generations.json")
        if hasattr(geo_app, "CONTENT_UPLOAD_FOLDER"):
            geo_app.CONTENT_UPLOAD_FOLDER = os.path.join(tmp, "content_uploads")
        if hasattr(geo_app, "F_CONTENT_MATERIALS_INDEX"):
            geo_app.F_CONTENT_MATERIALS_INDEX = os.path.join(tmp, "content_materials_index.json")
        if hasattr(geo_app, "CONTENT_MATERIAL_CACHE_FOLDER"):
            geo_app.CONTENT_MATERIAL_CACHE_FOLDER = os.path.join(tmp, "content_material_cache")
        geo_app.F_CRAWL_JOBS = os.path.join(tmp, "crawl_jobs.json")
        if hasattr(geo_app, "UPLOAD_FOLDER"):
            geo_app.UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        if hasattr(geo_app, "F_MATERIALS_INDEX"):
            geo_app.F_MATERIALS_INDEX = os.path.join(tmp, "materials_index.json")
        if hasattr(geo_app, "MATERIAL_CACHE_FOLDER"):
            geo_app.MATERIAL_CACHE_FOLDER = os.path.join(tmp, "material_cache")
        geo_app.app.config["AUTH_DISABLED"] = True
        base_crawler.DATA_DIR = tmp
        try:
            yield tmp
        finally:
            if original["AUTH_DISABLED"] is None:
                geo_app.app.config.pop("AUTH_DISABLED", None)
            else:
                geo_app.app.config["AUTH_DISABLED"] = original["AUTH_DISABLED"]
            for key, value in original.items():
                if key in {"BASE_CRAWLER_DATA_DIR", "AUTH_DISABLED"}:
                    if key == "BASE_CRAWLER_DATA_DIR":
                        base_crawler.DATA_DIR = value
                    continue
                if value is None and hasattr(geo_app, key):
                    delattr(geo_app, key)
                else:
                    setattr(geo_app, key, value)


@contextmanager
def isolated_content_app_data():
    with isolated_app_data() as tmp:
        yield tmp


class CoreFunctionTests(unittest.TestCase):
    def setUp(self):
        retired = (
            "test_ai_json_records_parsing_diagnostics_in_planning_context",
            "test_save_planning_brief_diagnostic_writes_truncated_attempts",
            "test_client_choice_entries_round_trip_and_probe_groups_stay_separate",
            "test_all_disabled_choices_do_not_trigger_lazy_generation",
            "test_empty_content_choices_are_lazily_generated_persisted_and_used",
            "test_failed_lazy_choice_response_does_not_persist_or_block_generation",
            "test_generation_uses_only_selected_competitor_sections_and_records_subset",
        )
        if self._testMethodName in retired or self._testMethodName.startswith("test_content_generate_") or \
                self._testMethodName.startswith("test_content_generation_") or \
                self._testMethodName.startswith("test_content_options_"):
            self.skipTest("旧两阶段内容生产测试已由正式路线测试替代")
    def test_ai_with_settings_omits_max_tokens_when_none(self):
        captured = {}

        class FakeChoices:
            message = type("Message", (), {"content": "ok"})

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return type("Response", (), {"choices": [FakeChoices()]})

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        with patch.object(geo_app, "OpenAI", FakeOpenAI):
            result = geo_app.ai_with_settings(
                "prompt",
                max_tokens=None,
                settings={"api_key": "key", "base_url": "https://api.example.com", "model": "model-a"},
            )

        self.assertEqual(result, "ok")
        self.assertNotIn("max_tokens", captured)
        self.assertEqual(captured["model"], "model-a")

    def test_ai_with_settings_response_exposes_completion_diagnostics(self):
        class FakeChoice:
            message = type("Message", (), {"content": "  body  "})
            finish_reason = "length"

        class FakeCompletions:
            def create(self, **_kwargs):
                return type("Response", (), {"model": "actual-model", "choices": [FakeChoice()]})

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        with patch.object(geo_app, "OpenAI", FakeOpenAI):
            raw, diagnostics = geo_app.ai_with_settings_response(
                "prompt",
                settings={"api_key": "key", "base_url": "https://api.example.com", "model": "configured-model"},
            )

        self.assertEqual(raw, "body")
        self.assertEqual(diagnostics, {
            "model": "actual-model",
            "finish_reason": "length",
            "response_length": 4,
        })

    def test_ai_with_settings_response_logs_safe_start_and_finish_events(self):
        class FakeChoice:
            message = type("Message", (), {"content": "body"})
            finish_reason = "stop"

        class FakeCompletions:
            def create(self, **_kwargs):
                return type("Response", (), {"model": "actual-model", "choices": [FakeChoice()]})

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        with patch.object(geo_app, "OpenAI", FakeOpenAI), patch("builtins.print") as mock_print:
            geo_app.ai_with_settings_response(
                "private prompt content",
                max_tokens=4321,
                settings={"api_key": "top-secret", "base_url": "https://api.example.com/v1", "model": "configured-model"},
            )

        events = [
            json.loads(call.args[0].removeprefix("[model_call] "))
            for call in mock_print.call_args_list
            if call.args and str(call.args[0]).startswith("[model_call] ")
        ]
        self.assertEqual([event["event"] for event in events], ["started", "finished"])
        self.assertEqual(events[0]["model"], "configured-model")
        self.assertEqual(events[0]["base_url_host"], "api.example.com")
        self.assertEqual(events[0]["max_tokens"], 4321)
        self.assertEqual(events[0]["call_id"], events[1]["call_id"])
        self.assertGreaterEqual(events[1]["elapsed_ms"], 0)
        rendered_events = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("top-secret", rendered_events)
        self.assertNotIn("private prompt content", rendered_events)

    def test_ai_with_settings_response_logs_safe_failure_event(self):
        class FailingOpenAI:
            def __init__(self, **_kwargs):
                raise RuntimeError("upstream connection closed")

        with patch.object(geo_app, "OpenAI", FailingOpenAI), patch("builtins.print") as mock_print:
            with self.assertRaisesRegex(RuntimeError, "upstream connection closed"):
                geo_app.ai_with_settings_response(
                    "private prompt content",
                    settings={"api_key": "top-secret", "base_url": "https://api.example.com/v1", "model": "configured-model"},
                )

        events = [
            json.loads(call.args[0].removeprefix("[model_call] "))
            for call in mock_print.call_args_list
            if call.args and str(call.args[0]).startswith("[model_call] ")
        ]
        self.assertEqual([event["event"] for event in events], ["started", "failed"])
        self.assertEqual(events[1]["error_type"], "RuntimeError")
        self.assertIn("upstream connection closed", events[1]["error_message"])
        rendered_events = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("top-secret", rendered_events)
        self.assertNotIn("private prompt content", rendered_events)

    def test_ai_json_records_parsing_diagnostics_in_planning_context(self):
        class FakeChoice:
            message = type("Message", (), {"content": "{}"})
            finish_reason = "stop"

        class FakeCompletions:
            def create(self, **_kwargs):
                return type("Response", (), {"model": "actual-model", "choices": [FakeChoice()]})

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        context = {"attempts": []}
        token = geo_app.planning_brief_diagnostic_context.set(context)
        try:
            with patch.object(geo_app, "OpenAI", FakeOpenAI), \
                    patch.object(geo_app, "get_settings", return_value={
                        "api_key": "key", "base_url": "https://api.example.com", "model": "configured-model",
                    }):
                self.assertEqual(geo_app.ai_json("prompt"), {})
        finally:
            geo_app.planning_brief_diagnostic_context.reset(token)

        self.assertEqual(context["attempts"], [{
            "status": "parsed",
            "model": "actual-model",
            "finish_reason": "stop",
            "response_length": 2,
            "response_preview": "{}",
        }])

    def test_save_planning_brief_diagnostic_writes_truncated_attempts(self):
        with isolated_app_data() as tmp:
            geo_app.save_planning_brief_diagnostic(
                "client-1",
                "batch-1",
                {"attempts": [{"response_preview": "x" * 1500}]},
            )

            path = os.path.join(tmp, "content_generation_diagnostics", "client-1", "latest_planning_brief.json")
            data = geo_app.load(path, {})

        self.assertEqual(data["run_id"], "batch-1")
        self.assertEqual(data["records"][0]["attempts"][0]["response_preview"], "x" * 1200)

    def test_uid_is_unique_when_clock_timestamp_repeats(self):
        class FixedDatetime:
            @staticmethod
            def now():
                from datetime import datetime
                return datetime(2026, 7, 9, 11, 30, 0, 123456)

        with patch.object(geo_app, "datetime", FixedDatetime):
            ids = [geo_app.uid() for _ in range(3)]

        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(item.startswith("20260709113000123456") for item in ids))

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
            self.assertTrue(geo_app.should_use_node_crawler("kimi"))

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

    def test_content_generate_uses_content_materials_history_and_stores_newest_first(self):
        with isolated_content_app_data():
            cid = "client-1"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "苏韵汽车音响"}])
            material_dir = os.path.join(geo_app.UPLOAD_FOLDER, cid)
            os.makedirs(material_dir, exist_ok=True)
            with open(os.path.join(material_dir, "brand.txt"), "w", encoding="utf-8") as f:
                f.write("品牌资料：苏韵主营汽车音响改装。")
            with open(os.path.join(material_dir, "case.md"), "w", encoding="utf-8") as f:
                f.write("案例资料：扬州车主升级DSP和隔音。")

            client = geo_app.app.test_client()
            customer_upload = client.post(
                f"/api/materials/{cid}/upload",
                data={
                    "file": [
                        (
                            io.BytesIO(b"CUSTOMER_ONLY_PROFILE_SHOULD_NOT_APPEAR has enough text."),
                            "customer-profile.txt",
                        )
                    ]
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(customer_upload.status_code, 200)
            content_upload = client.post(
                f"/api/content/materials/{cid}/upload",
                data={
                    "file": [
                        (
                            io.BytesIO("CONTENT_ONLY_BRAND_CONTEXT: 苏韵主营汽车音响改装。".encode("utf-8")),
                            "content-brand.txt",
                        ),
                        (
                            io.BytesIO("CONTENT_ONLY_CASE_DETAIL: 扬州车主升级DSP和隔音。".encode("utf-8")),
                            "content-case.md",
                        ),
                    ]
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(content_upload.status_code, 200)
            self.assertEqual(len(content_upload.get_json()["materials"]), 2)
            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "第一版文章" if len(captured_messages) == 1 else "第二版文章"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                first = client.post(
                    "/api/content/generate", json={"client_id": cid},
                )
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.get_json()["article"]["content"], "第一版文章")

                second = client.post(
                    "/api/content/generate", json={"client_id": cid},
                )
                self.assertEqual(second.status_code, 200)
                self.assertEqual(second.get_json()["article"]["content"], "第二版文章")

            prompt_payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertIn("CONTENT_ONLY_BRAND_CONTEXT", prompt_payload)
            self.assertIn("CONTENT_ONLY_CASE_DETAIL", prompt_payload)
            self.assertNotIn("CUSTOMER_ONLY_PROFILE_SHOULD_NOT_APPEAR", prompt_payload)
            self.assertIn("苏韵主营汽车音响改装", prompt_payload)
            self.assertIn("扬州车主升级DSP和隔音", prompt_payload)
            self.assertNotIn("写一篇面向扬州车主的宣传文章", prompt_payload)

            second_payload = json.dumps(captured_messages[1], ensure_ascii=False)
            self.assertNotIn("第一版文章", second_payload)
            self.assertNotIn("第二版加强施工流程和真实感", second_payload)

            listing = client.get(f"/api/content/generations?client_id={cid}")
            self.assertEqual(listing.status_code, 200)
            articles = listing.get_json()["articles"]
            self.assertEqual([a["content"] for a in articles], ["第二版文章", "第一版文章"])
            self.assertEqual(articles[0]["material_count"], 2)
            self.assertEqual(articles[0]["model"], "deepseek-chat")

    def test_content_generate_records_configured_model(self):
        with isolated_content_app_data():
            cid = "client-model"
            geo_app.save(geo_app.F_SETTINGS, {
                "api_key": "test-key",
                "base_url": "https://api.example.com",
                "model": "deepseek-v4-pro",
            })
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Yishengxue"}])

            def fake_deepseek_pro(messages, max_tokens=6000):
                return "Generated article"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate",
                    json={"client_id": cid, "opinion": "write a test article"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["article"]["model"], "deepseek-v4-pro")

    def test_content_generate_respects_content_material_use_toggle(self):
        with isolated_content_app_data():
            cid = "client-material-toggle"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Yishengxue"}])
            client = geo_app.app.test_client()
            uploaded = client.post(
                f"/api/content/materials/{cid}/upload",
                data={
                    "file": [
                        (io.BytesIO(b"USED_CONTENT_MARKER should be visible to generation."), "used.txt"),
                        (io.BytesIO(b"UNUSED_CONTENT_MARKER should not be visible to generation."), "unused.txt"),
                    ]
                },
                content_type="multipart/form-data",
            )

            self.assertEqual(uploaded.status_code, 200)
            materials = uploaded.get_json()["materials"]

            toggled = client.post(
                f"/api/content/materials/{cid}/{materials[1]['id']}/confirm",
                json={"confirmed": False},
            )
            self.assertEqual(toggled.status_code, 200)

            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "Generated article"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = client.post(
                    "/api/content/generate",
                    json={"client_id": cid, "opinion": "write a test article"},
                )

            self.assertEqual(response.status_code, 200)
            payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertIn("USED_CONTENT_MARKER", payload)
            self.assertNotIn("UNUSED_CONTENT_MARKER", payload)
            self.assertEqual(response.get_json()["article"]["material_count"], 1)

    def test_content_generate_uses_selected_customer_material_packages(self):
        with isolated_content_app_data():
            cid = "client-package-toggle"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Yishengxue"}])
            output_dir = geo_app.material_package_output_dir(cid)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "latest_injection.md").write_text(
                "# 客户资料注入包\nPACKAGE_INJECTION_MARKER",
                encoding="utf-8",
            )
            (output_dir / "latest_web_supplement.md").write_text(
                "# 联网扩展资料\nPACKAGE_WEB_MARKER",
                encoding="utf-8",
            )

            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "Generated article"

            client = geo_app.app.test_client()
            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                included = client.post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "opinion": "write with packages",
                        "use_material_package": True,
                        "use_material_web_supplement": True,
                    },
                )
                skipped = client.post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "opinion": "write without packages",
                        "use_material_package": False,
                        "use_material_web_supplement": False,
                    },
                )

            self.assertEqual(included.status_code, 200)
            self.assertEqual(skipped.status_code, 200)
            included_payload = json.dumps(captured_messages[0], ensure_ascii=False)
            skipped_payload = json.dumps(captured_messages[1], ensure_ascii=False)
            self.assertIn("PACKAGE_INJECTION_MARKER", included_payload)
            self.assertIn("PACKAGE_WEB_MARKER", included_payload)
            self.assertNotIn("PACKAGE_INJECTION_MARKER", skipped_payload)
            self.assertNotIn("PACKAGE_WEB_MARKER", skipped_payload)
            self.assertEqual(included.get_json()["article"]["material_count"], 2)
            self.assertEqual(skipped.get_json()["article"]["material_count"], 0)

    def test_client_choice_entries_round_trip_and_probe_groups_stay_separate(self):
        with isolated_app_data():
            cid = "client-angles"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌"}])
            geo_app.save(geo_app.F_GROUPS, {cid: [
                {"id": "g1", "questions": ["问题一", "问题二"]},
                {"id": "g2", "questions": ["问题二", "问题三"]},
            ]})
            client = geo_app.app.test_client()
            response = client.put(f"/api/clients/{cid}", json={"audience_angles": ["异地在职者", "时间紧张者", "异地在职者"]})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["client"]["audience_angles"], [
                {"text": "异地在职者", "enabled": True, "source": "manual"},
                {"text": "时间紧张者", "enabled": True, "source": "manual"},
            ])
            self.assertEqual(geo_app.load_client_faq_questions(cid), [])
            self.assertEqual(geo_app.load_probe_group_questions(cid), ["问题一", "问题二", "问题三"])

    def test_empty_content_choices_are_lazily_generated_persisted_and_used(self):
        with isolated_content_app_data():
            cid = "client-lazy-choices"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "education"}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": "g1", "questions": ["哪家靠谱", "怎么报名"]}]})
            lazy_response = {
                "audience_angles": ["异地在职者带着时间安排顾虑在问"],
                "faq_questions": ["怎么判断机构是否靠谱"],
            }
            with patch.object(geo_app, "ai_json", return_value=lazy_response) as ai_json, \
                    patch.object(geo_app, "run_quality_gate", return_value={"verdict": "pass"}), \
                    patch.object(geo_app, "ai_deepseek_pro", return_value="正常文章"):
                article = geo_app.run_content_generation({"client_id": cid})

            client = geo_app.get_client(cid)
            self.assertEqual("ai", client["audience_angles"][0]["source"])
            self.assertTrue(client["audience_angles"][0]["enabled"])
            self.assertEqual("怎么判断机构是否靠谱", client["faq_questions"][0]["text"])
            self.assertEqual("异地在职者带着时间安排顾虑在问", article["provenance"]["audience_angle"])
            self.assertGreaterEqual(ai_json.call_args.args[1], 4000)
            self.assertIn("哪家靠谱", ai_json.call_args.args[0])

    def test_all_disabled_choices_do_not_trigger_lazy_generation(self):
        with isolated_content_app_data():
            cid = "client-disabled-choices"
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": cid, "name": "客户", "brand": "品牌",
                "audience_angles": [{"text": "已停用角度", "enabled": False, "source": "manual"}],
                "faq_questions": [{"text": "已停用问题", "enabled": False, "source": "manual"}],
            }])
            with patch.object(geo_app, "ai_json") as ai_json, \
                    patch.object(geo_app, "run_quality_gate", return_value={"verdict": "pass"}), \
                    patch.object(geo_app, "ai_deepseek_pro", return_value="正常文章"):
                article = geo_app.run_content_generation({"client_id": cid})

            ai_json.assert_not_called()
            self.assertEqual("", article["provenance"]["audience_angle"])
            self.assertEqual([], article["provenance"]["faq_questions"])

    def test_generation_uses_only_selected_competitor_sections_and_records_subset(self):
        with isolated_content_app_data():
            cid = "client-competitor-choices"
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": cid, "name": "客户", "brand": "品牌",
                "audience_angles": [{"text": "读者顾虑", "enabled": True, "source": "manual"}],
                "faq_questions": [{"text": "怎么核验", "enabled": True, "source": "manual"}],
                "competitor_rules": {"must_use": ["乙机构"], "banned": ["丙机构"]},
            }])
            sources = {"customer_material_text": "客户资料", "content_upload_text": "", "files": [],
                       "competitor_markdown": "## 甲机构\n甲资料\n## 乙机构\n乙资料\n## 丙机构\n丙资料\n## 丁机构\n丁资料"}
            captured = []
            def brief(sample, **kwargs):
                captured.append(kwargs["competitor_markdown"])
                return valid_brief()
            with patch.object(geo_app, "read_content_generation_sources", return_value=sources), \
                    patch.object(geo_app, "generate_planning_brief", side_effect=brief), \
                    patch.object(geo_app, "run_quality_gate", return_value={"verdict": "pass"}), \
                    patch.object(geo_app, "ai_deepseek_pro", return_value="正常文章"):
                article = geo_app.run_content_generation({"client_id": cid})

            self.assertIn("乙机构", article["provenance"]["competitor_names"])
            self.assertNotIn("丙机构", article["provenance"]["competitor_names"])
            self.assertIn("## 乙机构", captured[0])
            self.assertNotIn("## 丙机构", captured[0])

    def test_failed_lazy_choice_response_does_not_persist_or_block_generation(self):
        with isolated_content_app_data():
            cid = "client-lazy-failure"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌"}])
            with patch.object(geo_app, "ai_json", side_effect=ValueError("bad_json")), \
                    patch.object(geo_app, "run_quality_gate", return_value={"verdict": "pass"}), \
                    patch.object(geo_app, "ai_deepseek_pro", return_value="正常文章"):
                article = geo_app.run_content_generation({"client_id": cid})

            self.assertNotIn("audience_angles", geo_app.get_client(cid))
            self.assertNotIn("faq_questions", geo_app.get_client(cid))
            self.assertEqual("", article["provenance"]["audience_angle"])

    def test_content_options_endpoint_returns_live_competitor_candidates(self):
        with isolated_content_app_data():
            cid = "client-options"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌"}])
            source_dir = geo_app.competitor_package_output_dir(cid)
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "latest_web_competitors.md").write_text(
                "# 竞品联网资料补充包\n\n## 甲机构\n资料\n\n### 价格线索\n资料\n\n## 乙机构\n资料\n\n### 服务与售后线索\n资料",
                encoding="utf-8",
            )

            response = geo_app.app.test_client().get(f"/api/clients/{cid}/content-options")

            self.assertEqual(200, response.status_code)
            self.assertEqual(["甲机构", "乙机构"], response.get_json()["competitor_candidates"])

    def test_content_generate_persists_brief_and_matching_provenance(self):
        with isolated_content_app_data():
            cid = "client-new-chain"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "education", "audience_angles": ["异地在职者"], "faq_questions": ["问题一", "问题二", "问题三"]}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": "g1", "questions": ["问题一", "问题二", "问题三"]}]})
            client = geo_app.app.test_client()
            with patch("services.brief_builder.FREE_SLOT_PROBABILITY", 0), \
                    patch("services.brief_builder.FAQ_PROBABILITY", 1), \
                    patch.object(geo_app, "generate_planning_brief", return_value=valid_brief()), \
                    patch.object(geo_app, "ai_deepseek_pro", return_value="生成文章"):
                response = client.post("/api/content/generate", json={"client_id": cid, "opinion": "按资料写", "article_type": "对比型"})

            self.assertEqual(response.status_code, 200)
            article = response.get_json()["article"]
            self.assertEqual(article["brief"], valid_brief())
            self.assertTrue(article["provenance"]["entries"]["skeleton"]["id"])
            self.assertTrue(article["provenance"]["entries"]["opening_module"]["id"])
            self.assertEqual(article["provenance"]["audience_angle"], "异地在职者")
            self.assertEqual(set(article["provenance"]["faq_questions"]), {"问题一", "问题二", "问题三"})

    def test_content_generation_passes_only_supported_arguments_to_brief_builder(self):
        with isolated_content_app_data():
            cid = "client-brief-signature"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "education"}])

            def strict_brief(sample, *, customer_material_text, content_upload_text, competitor_markdown, ai_json_fn):
                return valid_brief()

            with patch.object(geo_app, "generate_planning_brief", side_effect=strict_brief), \
                    patch.object(geo_app, "run_quality_gate", return_value={"verdict": "pass"}), \
                    patch.object(geo_app, "ai_deepseek_pro", return_value="生成文章"):
                article = geo_app.run_content_generation({"client_id": cid, "article_type": "对比型"})

            self.assertEqual("生成文章", article["content"])

    def test_content_generation_shared_entry_reads_configured_faq_questions(self):
        with isolated_content_app_data():
            cid = "client-shared-entry"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "education", "faq_questions": ["问题一", "问题二", "问题三"]}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": "g1", "questions": ["问题一", "问题二", "问题三"]}]})
            with patch("services.brief_builder.FREE_SLOT_PROBABILITY", 0), \
                    patch("services.brief_builder.FAQ_PROBABILITY", 1), \
                    patch.object(geo_app, "ai_deepseek_pro", return_value="生成文章"):
                result = geo_app.run_content_generation({
                    "client_id": cid,
                    "opinion": "按资料写",
                    "article_type": "对比型",
                })

            self.assertEqual(set(result["provenance"]["faq_questions"]), {"问题一", "问题二", "问题三"})
            self.assertEqual(set(result["sampling"]["faq_questions"]), {"问题一", "问题二", "问题三"})
            self.assertEqual(geo_app.load_content_session(cid)["articles"][0]["id"], result["id"])

    def test_content_generate_brief_or_writer_failure_leaves_no_article(self):
        with isolated_content_app_data():
            cid = "client-no-partial"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "education"}])
            client = geo_app.app.test_client()
            with patch.object(geo_app, "generate_planning_brief", side_effect=ValueError("brief_failed")):
                failed_brief = client.post("/api/content/generate", json={"client_id": cid, "opinion": "按资料写"})
            with patch.object(geo_app, "generate_planning_brief", return_value=valid_brief()), \
                    patch.object(geo_app, "ai_deepseek_pro", side_effect=["", ""]):
                failed_writer = client.post("/api/content/generate", json={"client_id": cid, "opinion": "按资料写"})

            self.assertEqual(failed_brief.status_code, 500)
            self.assertEqual(failed_writer.status_code, 500)
            self.assertEqual(geo_app.load_content_session(cid)["articles"], [])

    def test_content_generate_keeps_full_selected_material_packages(self):
        with isolated_content_app_data():
            cid = "client-full-material-packages"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Yishengxue"}])
            output_dir = geo_app.material_package_output_dir(cid)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "latest_injection.md").write_text("A" * 7000, encoding="utf-8")
            (output_dir / "latest_web_supplement.md").write_text(
                "B" * 7000 + "WEB_PACKAGE_TAIL_MARKER",
                encoding="utf-8",
            )

            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "Generated article"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate",
                    json={"client_id": cid, "opinion": "write a test article"},
                )

            self.assertEqual(response.status_code, 200)
            payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertIn("WEB_PACKAGE_TAIL_MARKER", payload)

    def test_content_generate_persists_to_sqlite_history_store(self):
        with isolated_content_app_data():
            cid = "client-sqlite"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Yishengxue"}])

            with patch.object(geo_app, "ai_deepseek_pro", return_value="SQLite article", create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate", json={"client_id": cid},
                )

            db_path = os.path.splitext(geo_app.F_CONTENT_GENERATIONS)[0] + ".sqlite3"
            self.assertEqual(response.status_code, 200)
            self.assertTrue(os.path.exists(db_path))
            self.assertFalse(os.path.exists(geo_app.F_CONTENT_GENERATIONS))
            self.assertEqual(
                [item["content"] for item in geo_app.load_content_session(cid)["articles"]],
                ["SQLite article"],
            )
            self.assertNotIn("operator_opinion", response.get_json()["article"])

    def test_content_generation_persists_optional_batch_id_without_subtype(self):
        with isolated_content_app_data():
            cid = "client-batch-id"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Brand"}])
            with patch.object(geo_app, "ai_deepseek_pro", return_value="Neutral title\nNeutral body"), \
                    patch.object(geo_app, "ai_json", return_value={"checks": []}):
                article = geo_app.run_content_generation({"client_id": cid}, batch_id="batch-1")

            self.assertEqual("batch-1", article["batch_id"])
            self.assertNotIn("article_subtype", article)
            self.assertEqual("batch-1", geo_app.load_content_session(cid)["articles"][0]["batch_id"])

    def test_content_generate_batch_validates_count_and_queues_allowed_counts(self):
        with isolated_content_app_data():
            cid = "client-batch-route"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Brand"}])
            client = geo_app.app.test_client()
            for count in (0, 2, 4, 6, 11):
                response = client.post("/api/content/generate_batch", json={"client_id": cid, "count": count})
                self.assertEqual(400, response.status_code)
            with patch.object(geo_app, "queue_content_batch_generation_job", side_effect=lambda payload, count, created_by="": {
                "job_id": "job-1", "batch_id": "batch-1", "client_id": cid, "count": count,
                "status": "queued", "cancel_requested": False, "items": [],
            }) as queued:
                for count in (1, 3, 5):
                    response = client.post("/api/content/generate_batch", json={"client_id": cid, "count": count})
                    self.assertEqual(200, response.status_code)
                    self.assertEqual(count, response.get_json()["job"]["count"])
                self.assertEqual(3, queued.call_count)

    def test_content_generate_persists_quality_gate_report(self):
        with isolated_content_app_data():
            cid = "client-gate-report"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Yishengxue"}])
            with patch.object(geo_app, "ai_deepseek_pro", return_value="Neutral title\nNeutral body"), \
                    patch.object(geo_app, "ai_json", return_value={"checks": []}) as gate_llm:
                response = geo_app.app.test_client().post(
                    "/api/content/generate", json={"client_id": cid, "opinion": "write a neutral article", "article_type": "介绍型"},
                )

            self.assertEqual(response.status_code, 200)
            article = response.get_json()["article"]
            self.assertTrue(article["gate_report"])
            self.assertEqual(article["gate_report"]["llm_layer_status"], "passed")
            self.assertGreaterEqual(gate_llm.call_args.args[1], 4000)
            self.assertEqual(geo_app.load_content_session(cid)["articles"][0]["gate_report"], article["gate_report"])

    def test_content_generate_persists_brand_title_as_warning(self):
        with isolated_content_app_data():
            cid = "client-gate-blocked"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "翼升学", "brand": "翼升学"}])
            with patch.object(geo_app, "ai_deepseek_pro", return_value="翼升学服务介绍\n正文"), \
                    patch.object(geo_app, "ai_json", return_value={"checks": []}):
                response = geo_app.app.test_client().post(
                    "/api/content/generate", json={"client_id": cid, "opinion": "写介绍", "article_type": "介绍型"},
                )

            self.assertEqual(response.status_code, 200)
            article = response.get_json()["article"]
            self.assertNotIn("generation_status", article)
            self.assertEqual(article["gate_report"]["verdict"], "warn")
            self.assertEqual(len(geo_app.load_content_session(cid)["articles"]), 1)

    def test_quality_gate_competitor_names_skips_generic_markdown_header(self):
        names = geo_app.quality_gate_competitor_names(
            "# 竞品公开资料整理包\n## 翼程教育\n### 基本信息\n### 业务范围\n## 河北尚学教育\n### 服务规模与覆盖\n"
        )
        self.assertEqual(names, ["翼程教育", "河北尚学教育"])

    def test_content_generation_manual_edit_and_ai_revision_keep_version_chain(self):
        with isolated_content_app_data():
            cid = "client-content-revision"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Brand"}])
            geo_app.append_content_generation(
                cid,
                {
                    "id": "root-article", "title": "Original title", "content": "Original title\nOriginal body",
                    "operator_opinion": "Original request", "model": "deepseek-chat", "article_type": "介绍型",
                    "created_at": "2026-07-21 10:00:00", "brief": valid_brief(), "provenance": {"parent_type": "介绍型"},
                    "gate_report": {"verdict": "blocked", "code_layer": [{"check_id": "title_brand", "passed": False}]},
                },
                {"role": "user", "content": "Original request", "created_at": "2026-07-21 10:00:00"},
                {"role": "assistant", "content": "Original title\nOriginal body", "created_at": "2026-07-21 10:00:00", "article_id": "root-article"},
            )
            client = geo_app.app.test_client()
            with patch.object(geo_app, "content_article_gate_report", side_effect=AssertionError("manual_must_not_gate")), \
                    patch.object(geo_app, "run_quality_gate", side_effect=AssertionError("manual_must_not_gate")):
                edited = client.put(
                    f"/api/content/generations/root-article?client_id={cid}",
                    json={"content": "Edited title\nEdited body"},
                )
            self.assertEqual(edited.status_code, 200)
            edited_article = edited.get_json()["article"]
            self.assertEqual(edited_article["title"], "Edited title")
            self.assertEqual(edited_article["generation_status"], "人工已编辑")
            self.assertEqual(edited_article["gate_report"]["verdict"], "blocked")

            captured = []
            def fake_writer(messages, max_tokens=6000):
                captured.append(messages)
                return "Revised title\nRevised body"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_writer), \
                    patch.object(geo_app, "ai_json", return_value={"checks": []}):
                revised = client.post(
                    f"/api/content/generations/root-article/ai_modify?client_id={cid}",
                    json={"instruction": "Add a practical example"},
                )

            self.assertEqual(revised.status_code, 200)
            article = revised.get_json()["article"]
            self.assertEqual(article["parent_id"], "root-article")
            self.assertEqual(article["root_id"], "root-article")
            self.assertEqual(article["modify_instruction"], "Add a practical example")
            prompt = json.dumps(captured[0], ensure_ascii=False)
            self.assertIn("Edited body", prompt)
            self.assertIn("Add a practical example", prompt)

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_writer), \
                    patch.object(geo_app, "ai_json", return_value={"checks": []}):
                second = client.post(
                    f"/api/content/generations/{article['id']}/ai_modify?client_id={cid}",
                    json={"instruction": "Shorten the ending"},
                )

            self.assertEqual(second.status_code, 200)
            self.assertIn("Add a practical example", json.dumps(captured[1], ensure_ascii=False))
            self.assertEqual(len(geo_app.load_content_session(cid)["articles"]), 3)

    def test_content_generation_manual_edit_returns_json_error_when_store_fails(self):
        with isolated_content_app_data():
            cid = "client-manual-error"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Brand"}])
            geo_app.append_content_generation(
                cid,
                {"id": "article-1", "title": "Old", "content": "Old\nBody", "created_at": "2026-07-21 10:00:00"},
                {}, {},
            )
            with patch.object(geo_app.ContentGenerationStore, "update_article_content", side_effect=RuntimeError("store_failed")):
                response = geo_app.app.test_client().put(
                    f"/api/content/generations/article-1?client_id={cid}",
                    json={"content": "New\nBody"},
                )

            self.assertEqual(500, response.status_code)
            self.assertEqual("store_failed", response.get_json()["error"])

    def test_content_generate_drops_legacy_sample_metadata(self):
        with isolated_content_app_data():
            cid = "client-1"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "苏韵汽车音响"}])
            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "参考样例生成文章"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "opinion": "按这些样例仿写",
                        "sample_links": ["https://example.com/sample-a"],
                        "selected_articles": [
                            {
                                "title": "汽车音响改装Top20样例",
                                "url": "https://example.com/top20",
                                "platform": "懂车帝",
                                "count": 6,
                            }
                        ],
                    },
                )

            self.assertEqual(response.status_code, 200)
            prompt_payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertNotIn("https://example.com/sample-a", prompt_payload)
            self.assertNotIn("汽车音响改装Top20样例", prompt_payload)
            article = response.get_json()["article"]
            self.assertNotIn("sample_link_count", article)
            self.assertNotIn("selected_article_count", article)
            self.assertNotIn("sample_links", article)
            self.assertNotIn("selected_articles", article)

    def test_content_generate_uses_explicit_article_type(self):
        with isolated_content_app_data():
            cid = "client-article-type"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "河北翼升学", "brand": "翼升学"}])
            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "介绍型文章"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "opinion": "写一篇成人学历提升服务文章",
                        "article_type": "介绍型",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertNotIn("文章类型：介绍型", payload)
            self.assertEqual(response.get_json()["article"]["article_type"], "介绍型")

    def test_content_generate_history_is_isolated_by_article_type_but_listing_is_combined(self):
        with isolated_content_app_data():
            cid = "client-history-type"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "河北翼升学", "brand": "翼升学"}])
            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "对比型旧文章" if len(captured_messages) == 1 else "介绍型新文章"

            client = geo_app.app.test_client()
            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                first = client.post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "article_type": "对比型",
                    },
                )
                second = client.post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "article_type": "介绍型",
                    },
                )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            second_payload = json.dumps(captured_messages[1], ensure_ascii=False)
            self.assertNotIn("写一篇介绍型文章", second_payload)
            self.assertNotIn("对比型旧文章", second_payload)
            self.assertNotIn("写一篇对比型文章", second_payload)

            listing = client.get(f"/api/content/generations?client_id={cid}")
            self.assertEqual(listing.status_code, 200)
            articles = listing.get_json()["articles"]
            self.assertEqual([a["content"] for a in articles], ["介绍型新文章", "对比型旧文章"])

    def test_content_generate_history_is_isolated_by_selected_day(self):
        with isolated_content_app_data():
            cid = "client-history-day"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "河北翼升学", "brand": "翼升学"}])
            geo_app.append_content_generation(
                cid,
                {
                    "id": "old-article",
                    "title": "旧文章",
                    "content": "昨天的对比型旧文章",
                    "operator_opinion": "昨天的运营意见",
                    "model": "deepseek-chat",
                    "material_count": 0,
                    "sample_link_count": 0,
                    "selected_article_count": 0,
                    "sample_links": [],
                    "selected_articles": [],
                    "created_at": "2026-07-06 10:00",
                    "article_type": "对比型",
                },
                {"role": "user", "content": "昨天的运营意见", "created_at": "2026-07-06 10:00"},
                {"role": "assistant", "content": "昨天的对比型旧文章", "created_at": "2026-07-06 10:00", "article_id": "old-article"},
            )
            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "今天的新文章"

            client = geo_app.app.test_client()
            with patch.object(geo_app, "now_str", return_value="2026-07-07 09:00"), \
                    patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = client.post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "article_type": "对比型",
                        "history_date": "2026-07-07",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertNotIn("今天重新生成一篇对比型文章", payload)
            self.assertNotIn("昨天的运营意见", payload)
            self.assertNotIn("昨天的对比型旧文章", payload)

            today_listing = client.get(f"/api/content/generations?client_id={cid}&date=2026-07-07")
            old_listing = client.get(f"/api/content/generations?client_id={cid}&date=2026-07-06")
            self.assertEqual([a["content"] for a in today_listing.get_json()["articles"]], ["今天的新文章"])
            self.assertEqual([a["content"] for a in old_listing.get_json()["articles"]], ["昨天的对比型旧文章"])

    def test_content_generation_can_be_deleted(self):
        with isolated_app_data():
            cid = "client-delete-content"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Brand"}])
            geo_app.append_content_generation(
                cid,
                {
                    "id": "article-delete",
                    "title": "待删除",
                    "content": "删除我",
                    "operator_opinion": "删除测试",
                    "model": "deepseek-chat",
                    "material_count": 0,
                    "sample_link_count": 0,
                    "selected_article_count": 0,
                    "sample_links": [],
                    "selected_articles": [],
                    "created_at": "2026-07-07 10:00",
                    "article_type": "对比型",
                },
                {"role": "user", "content": "删除测试", "created_at": "2026-07-07 10:00"},
                {"role": "assistant", "content": "删除我", "created_at": "2026-07-07 10:00", "article_id": "article-delete"},
            )

            client = geo_app.app.test_client()
            response = client.delete(f"/api/content/generations/article-delete?client_id={cid}&date=2026-07-07")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["articles"], [])
            self.assertEqual(geo_app.load_content_session(cid, history_date="2026-07-07")["messages"], [])

    @unittest.skip("Step E replaces legacy writer templates with planning briefs")
    def test_content_generation_system_prompt_starts_with_default_geo_rules(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "客户", "brand": "测试品牌"},
            {"text": "客户资料PDF：测试品牌只提供本地安装服务。", "files": ["profile.pdf"]},
            [],
            "生成一篇本地服务文章",
        )

        self.assertEqual(messages[0]["role"], "system")
        system_prompt = messages[0]["content"]
        self.assertTrue(system_prompt.startswith("【默认 GEO 内容生成规则】"))
        self.assertIn("有本地用户决策价值", system_prompt)
        self.assertIn("客观攻略或行业测评", system_prompt)
        self.assertIn("帮助用户理解怎么选", system_prompt)
        self.assertIn("在合适位置客观介绍客户品牌", system_prompt)
        self.assertIn("文章主体必须服从运营指定的文章类型", system_prompt)
        self.assertNotIn("标题优先包含城市/区域、项目/服务和用户决策词", system_prompt)
        self.assertIn("客户事实只能来自客户资料和运营意见", system_prompt)
        self.assertIn("样例文章只能作为写法参考", system_prompt)
        self.assertIn("不要编造案例、资质、价格、地址、设备、评价或承诺", system_prompt)

    @unittest.skip("Step E replaces legacy writer templates with planning briefs")
    def test_content_generation_defaults_to_comparison_type_prompt(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "河北翼升学", "brand": "翼升学"},
            {"text": "客户资料PDF：翼升学提供成人学历提升服务。", "files": ["profile.pdf"]},
            [],
            "请参考高频引用文章生成一篇西安成人学历提升内容",
            selected_articles=[
                {
                    "title": "河北成人学历提升机构全攻略（2026最新）",
                    "url": "https://m.sohu.com/a/1046143123_122828553/",
                    "platform": "搜狐",
                    "count": 8,
                }
            ],
        )

        payload = json.dumps(messages, ensure_ascii=False)
        self.assertIn("文章类型：对比型", payload)
        self.assertIn("标题必须严格模仿高引用文章标题", payload)
        self.assertIn("全攻略", payload)
        self.assertIn("最权威、最有公信力", payload)
        self.assertIn("放在最开头", payload)
        self.assertIn("客户品牌事实必须严格以客户资料为准", payload)
        self.assertIn("非客户机构类型和行业对比", payload)
        self.assertIn("可以参考高质量引用文章和通用行业认知展开", payload)
        self.assertIn("【文章子类型：攻略对比型】", payload)
        self.assertIn("【攻略对比型展开 few-shot 示例】", payload)
        self.assertIn("参考这种展开方式", payload)
        self.assertIn("一、A类：权威背书强，适合复杂需求", payload)
        self.assertIn("A类本身要先展开", payload)
        self.assertIn("A1代表对象", payload)
        self.assertIn("资历/公信力", payload)
        self.assertIn("地址/覆盖", payload)
        self.assertIn("价格区间", payload)
        self.assertIn("优势", payload)
        self.assertIn("劣势", payload)
        self.assertIn("适合人群", payload)
        self.assertIn("A2代表对象", payload)
        self.assertIn("展开方式参考A1", payload)
        self.assertIn("A3代表对象", payload)
        self.assertIn("二、B类", payload)
        self.assertIn("三、C类", payload)
        self.assertIn("和A类的区别", payload)
        self.assertIn("样例文章不能覆盖这里的攻略对比型展开结构", payload)
        self.assertIn("如果一个类别下出现多个代表对象", payload)
        self.assertIn("不能合并写在一行“代表机构”里", payload)
        self.assertIn("每个主要类别下至少展开2个代表对象或细分方向", payload)
        self.assertIn("A1/B1/C1只是示例标签", payload)
        self.assertIn("正文里不要输出A1、A2、B1、C1这类标签", payload)
        self.assertNotIn("不要这样写", payload)
        self.assertIn("当前运营意见和文章类型要求优先于历史文章", payload)
        self.assertIn("每个被对比的主要类别或对象都要独立成小标题或独立段落", payload)
        self.assertIn("少量攻略型开头 + 大量分类对比", payload)
        self.assertIn("主体分类对比必须充分展开", payload)
        self.assertIn("不能只有一个对比对象", payload)
        self.assertIn("客户品牌只需要在合适类别中客观出现", payload)
        self.assertIn("不能为了推荐而拔高分类或改变真实市场定位", payload)
        self.assertIn("最权威类别只放真实属于该层级的对象", payload)
        self.assertIn("如果更适合民营专科连锁、正规私立连锁、服务便利型机构等类别", payload)
        self.assertIn("只要用户理解客户品牌适合哪些需求，就算完成品牌露出", payload)
        self.assertIn("竞品名称禁止使用示例中的 A/B/C 或 A1/A2/A3 替代", payload)
        self.assertIn("必须出现真实的竞品名称", payload)
        self.assertIn("不能拉踩其他竞品", payload)
        self.assertIn("让用户了解其他竞品的优点", payload)
        self.assertIn("客户品牌放在最前面", payload)
        self.assertIn("文章结构必须优先服从文章类型要求和运营意见", payload)
        self.assertIn("信息密度和表达方式", payload)
        self.assertNotIn("不要写成单一品牌介绍稿", payload)
        self.assertNotIn("可仿照样例文章的结构和表达", payload)
        self.assertNotIn("文章结构、表达方式和信息组织", payload)
        self.assertNotIn("严禁为了凑字段编造", payload)
        self.assertNotIn("每类推荐包含", payload)
        self.assertNotIn("每个主要分类下都要出现多个可比较对象、机构类型或选择方向", payload)
        self.assertNotIn("复诊便利性", payload)
        self.assertNotIn("快速匹配", payload)
        self.assertNotIn("避坑", payload)

    @unittest.skip("Step E moves article-shape requirements to planning briefs")
    def test_content_generation_intro_type_requires_brand_title_and_brand_body(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "河北翼升学", "brand": "翼升学"},
            {"text": "客户资料PDF：翼升学提供成人学历提升服务。", "files": ["profile.pdf"]},
            [],
            "请写一篇翼升学成人学历提升服务介绍",
            article_type="介绍型",
        )

        payload = json.dumps(messages, ensure_ascii=False)
        self.assertIn("文章类型：介绍型", payload)
        self.assertIn("标题必须包含品牌名：翼升学", payload)
        self.assertIn("少量攻略型开头 + 大量品牌结构化介绍", payload)
        self.assertIn("开头必须先写目标用户在该业务场景里的真实痛点和决策难点", payload)
        self.assertIn("用户痛点/顾虑 -> 品牌如何解决 -> 资料中的证据支撑", payload)
        self.assertIn("目标是解释品牌适合哪些用户、能解决哪些选择顾虑", payload)
        self.assertIn("不要默认用户已经决定选择该品牌", payload)
        self.assertIn("资历、资质、团队、流程、设备、服务记录等只能作为证据", payload)
        self.assertIn("不要一上来写品牌履历", payload)
        self.assertIn("不能写成硬广", payload)
        self.assertIn("避免营销口号", payload)
        self.assertIn("不要写成医院榜单、第三方排名或多机构对比", payload)

    @unittest.skip("Step E moves article-shape requirements to planning briefs")
    def test_content_generation_does_not_parse_article_type_from_opinion(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "河北翼升学", "brand": "翼升学"},
            {"text": "客户资料PDF：翼升学提供成人学历提升服务。", "files": ["profile.pdf"]},
            [],
            "运营备注里写了介绍型三个字，但没有选择按钮参数",
        )

        payload = json.dumps(messages, ensure_ascii=False)
        self.assertIn("文章类型：对比型", payload)
        self.assertNotIn("标题必须包含品牌名：翼升学", payload)

    def test_retired_frontend_modules_do_not_expose_backend_routes(self):
        retired_routes = {
            "/api/intel/analyze",
            "/api/intel/records",
            "/api/intel/platform_report",
            "/api/intel/ai_report",
            "/api/platforms",
            "/api/platforms/<pid>",
            "/api/platforms/ai_fill",
            "/api/articles",
            "/api/articles/generate",
            "/api/articles/batch",
            "/api/articles/<aid>/status",
            "/api/articles/<aid>",
            "/api/articles/<aid>/format",
            "/api/content/gen_topics",
            "/api/stats/overview",
            "/api/stats/export",
            "/api/doubao/login",
            "/api/doubao/check_login",
            "/api/doubao/crawl",
            "/api/doubao/daily",
            "/api/doubao/daily_list",
            "/api/doubao/daily_analyze",
            "/api/doubao/progress/<session_id>",
            "/api/crawl/daily",
            "/api/crawl/daily_list",
            "/api/crawl/daily_analyze",
            "/api/settings/rawpath",
            "/api/platform/compare",
            "/api/agent/checklist",
            "/api/agent/chat",
            "/api/agent/summary",
            "/api/precise/diagnosis",
            "/api/precise/question_refs",
            "/api/precise/generate",
            "/api/raw_records/deep_analyze",
            "/api/daily/deep_analyze",
        }
        active_routes = {str(rule.rule) for rule in geo_app.app.url_map.iter_rules()}

        self.assertTrue(retired_routes.isdisjoint(active_routes))
        self.assertIn("/api/content/generate", active_routes)
        self.assertIn("/api/platform/crawl", active_routes)

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

    def test_save_raw_record_persists_crawl_task_metadata(self):
        with isolated_app_data():
            geo_app.save_raw_record(
                client_id="client-1",
                group_id="group-1",
                brand="测试品牌",
                question="测试问题",
                round_num=1,
                answer="测试品牌可以考虑。",
                search_keywords=[],
                refs=[],
                analysis={"brand_mentioned": True, "geo_score": 20, "main_ref": {}},
                source_platform="qwen",
                task_id="task-1",
                run_id="run-1",
                task_report="data/tasks/task-1.json",
                crawler_engine="node",
            )

            records = geo_app.load(geo_app.F_RAW_RECORDS, [])
            self.assertEqual(records[0]["task_id"], "task-1")
            self.assertEqual(records[0]["run_id"], "run-1")
            self.assertEqual(records[0]["task_report"], "data/tasks/task-1.json")
            self.assertEqual(records[0]["crawler_engine"], "node")

            loaded = geo_app.load_client_records("client-1", task_id="task-1")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["question"], "测试问题")

    def test_save_raw_record_raises_when_main_raw_store_write_fails(self):
        with isolated_app_data():
            with patch("services.storage.save_json", return_value=False):
                with self.assertRaises(RuntimeError):
                    geo_app.save_raw_record(
                        client_id="client-1",
                        group_id="group-1",
                        brand="测试品牌",
                        question="测试问题",
                        round_num=1,
                        answer="测试品牌可以考虑。",
                        search_keywords=[],
                        refs=[],
                        analysis={"brand_mentioned": True, "geo_score": 20, "main_ref": {}},
                        source_platform="deepseek",
                        task_id="task-1",
                    )


    def test_auto_normalize_task_entities_only_updates_current_task_missing_entities(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "brand": "Brand", "industry": "Industry"}
            ])
            geo_app.save(geo_app.F_SETTINGS, {"api_key": "test-key"})
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {
                    "id": "raw-current",
                    "client_id": "client-1",
                    "today": "2026-07-03",
                    "task_id": "task-1",
                    "answer": "answer",
                    "mentioned_entities": [],
                },
                {
                    "id": "raw-existing",
                    "client_id": "client-1",
                    "today": "2026-07-03",
                    "task_id": "task-1",
                    "answer": "answer",
                    "mentioned_entities": [{"name": "Existing"}],
                },
                {
                    "id": "raw-other-task",
                    "client_id": "client-1",
                    "today": "2026-07-03",
                    "task_id": "task-2",
                    "answer": "answer",
                    "mentioned_entities": [],
                },
            ])
            fake_body = {
                "mode": "extract_missing",
                "selected_records": 1,
                "own_brand": "Brand",
                "raw_entity_summary": [],
                "competitor_report": {
                    "canonical_entities": [
                        {"canonical_name": "Entity", "aliases": ["RawEntity"]}
                    ]
                },
                "final_competitor_summary": [],
                "results": [
                    {
                        "record_id": "raw-current",
                        "competitors": [
                            {"name": "RawEntity", "type": "Industry", "sentiment": "neutral", "evidence": "RawEntity"}
                        ],
                    }
                ],
            }

            with patch("scripts.normalize_entities.build_extract_missing_report", return_value=fake_body):
                result = geo_app.auto_normalize_task_entities(
                    client_id="client-1",
                    date_str="2026-07-03",
                    task_id="task-1",
                )

            records = {item["id"]: item for item in geo_app.load(geo_app.F_RAW_RECORDS, [])}
            self.assertTrue(result["ok"])
            self.assertEqual(result["changed"], 1)
            self.assertEqual(records["raw-current"]["mentioned_entities"][0]["name"], "Entity")
            self.assertEqual(records["raw-existing"]["mentioned_entities"], [{"name": "Existing"}])
            self.assertEqual(records["raw-other-task"]["mentioned_entities"], [])
            self.assertTrue(os.path.exists(result["report_path"]))


class FlaskApiTests(unittest.TestCase):
    def setUp(self):
        if self._testMethodName.startswith("test_pattern_library_") or \
                self._testMethodName.startswith("test_reference_intelligence_"):
            self.skipTest("旧写法库和自动引用情报接口已删除")
        geo_app.app.config["TESTING"] = True
        self._auth_disabled = geo_app.app.config.get("AUTH_DISABLED")
        geo_app.app.config["AUTH_DISABLED"] = True
        self.client = geo_app.app.test_client()

    def tearDown(self):
        if self._auth_disabled is None:
            geo_app.app.config.pop("AUTH_DISABLED", None)
        else:
            geo_app.app.config["AUTH_DISABLED"] = self._auth_disabled

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

    def test_settings_save_hides_tavily_api_key_on_read(self):
        with isolated_app_data():
            response = self.client.post(
                "/api/settings",
                json={
                    "api_key": "secret-key",
                    "base_url": "https://api.example.com",
                    "model": "test-model",
                    "preset": "custom",
                    "tavily_api_key": "tvly-secret",
                },
            )
            self.assertEqual(response.status_code, 200)
            saved = geo_app.load(geo_app.F_SETTINGS, {})
            self.assertEqual(saved["tavily_api_key"], "tvly-secret")

            read_response = self.client.get("/api/settings")
            payload = read_response.get_json()
            self.assertTrue(payload["has_tavily_key"])
            self.assertNotIn("api_key", payload)
            self.assertNotIn("tavily_api_key", payload)

    def test_material_web_expand_requires_existing_injection(self):
        with isolated_app_data():
            response = self.client.post("/api/materials/client-1/expand-web", json={})

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.get_json()["error"], "material_injection_not_found")

    def test_material_web_expand_requires_tavily_key(self):
        with isolated_app_data():
            cid = "client-1"
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": cid,
                "name": "翼升学（河北省）科技有限公司",
                "brand": "翼升学",
                "industry": "成人学历提升",
                "goal": "GEO宣传",
            }])
            output_dir = geo_app.material_package_output_dir(cid)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "latest_injection.md").write_text("# 客户资料注入包\n翼升学资料", encoding="utf-8")

            with patch.dict(os.environ, {"TAVILY_API_KEY": ""}):
                response = self.client.post(f"/api/materials/{cid}/expand-web", json={})

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error"], "missing_tavily_api_key")

    def test_material_web_expand_saves_markdown(self):
        with isolated_app_data():
            cid = "client-1"
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": cid,
                "name": "翼升学（河北省）科技有限公司",
                "brand": "翼升学",
                "industry": "成人学历提升",
                "goal": "GEO宣传",
            }])
            geo_app.save(geo_app.F_SETTINGS, {
                "api_key": "llm-key",
                "base_url": "https://api.example.com",
                "model": "test-model",
            })
            output_dir = geo_app.material_package_output_dir(cid)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "latest_injection.md").write_text("# 客户资料注入包\n翼升学资料", encoding="utf-8")

            fake_result = {
                "ok": True,
                "queries": ["翼升学 成人学历提升"],
                "source_count": 1,
                "sources": [{"title": "来源", "url": "https://example.com", "content": "正文"}],
                "markdown": "# 联网扩展资料包\n\n## 来源列表\n- https://example.com",
                "path": str(output_dir / "latest_web_supplement.md"),
            }
            with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}), \
                    patch.object(geo_app, "expand_material_web_package", return_value=fake_result, create=True) as expand:
                response = self.client.post(f"/api/materials/{cid}/expand-web", json={})

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["markdown"], fake_result["markdown"])
            expand.assert_called_once()
            self.assertEqual(expand.call_args.kwargs["client"]["brand"], "翼升学")
            self.assertIn("翼升学资料", expand.call_args.kwargs["injection_markdown"])

    def test_material_web_expand_uses_saved_tavily_key_when_env_missing(self):
        with isolated_app_data():
            cid = "client-1"
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": cid,
                "name": "Client",
                "brand": "Brand",
                "industry": "Industry",
                "goal": "GEO",
            }])
            geo_app.save(geo_app.F_SETTINGS, {
                "api_key": "llm-key",
                "base_url": "https://api.example.com",
                "model": "test-model",
                "tavily_api_key": "tvly-from-settings",
            })
            output_dir = geo_app.material_package_output_dir(cid)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "latest_injection.md").write_text("# Injection\nBrand material", encoding="utf-8")
            tavily_keys = []

            def fake_ai(_prompt, _max_tokens, _settings=None):
                return "Brand useful proof" if not tavily_keys else "# Web supplement\n- https://example.com/a"

            def fake_tavily(_query, api_key):
                tavily_keys.append(api_key)
                return [{
                    "title": "Useful source",
                    "url": "https://example.com/a",
                    "content": "Brand has a useful public source with enough body text for filtering.",
                }]

            with patch.dict(os.environ, {"TAVILY_API_KEY": ""}), \
                    patch.object(geo_app, "ai_with_settings", side_effect=fake_ai), \
                    patch.object(geo_app, "tavily_search", side_effect=fake_tavily):
                response = self.client.post(f"/api/materials/{cid}/expand-web", json={})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(tavily_keys, ["tvly-from-settings"])
            self.assertIn("Web supplement", response.get_json()["markdown"])

    def test_download_material_web_supplement(self):
        with isolated_app_data():
            cid = "client-1"
            output_dir = geo_app.material_package_output_dir(cid)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "latest_web_supplement.md").write_text("# 联网扩展资料包\n", encoding="utf-8")

            response = self.client.get(f"/api/materials/{cid}/web-supplement.md")

            self.assertEqual(response.status_code, 200)
            self.assertIn("联网扩展资料包", response.get_data(as_text=True))
            response.close()

    def test_client_contract_platforms_can_be_created_and_updated(self):
        with isolated_app_data():
            response = self.client.post(
                "/api/clients",
                json={
                    "name": "客户A",
                    "brand": "品牌A",
                    "industry": "汽车音响",
                    "goal": "提升提及率",
                    "contract_platforms": ["qwen", "doubao", "bad"],
                },
            )
            self.assertEqual(response.status_code, 200)
            client = response.get_json()["client"]
            self.assertEqual(client["contract_platforms"], ["qwen", "doubao"])

            update_response = self.client.put(
                f"/api/clients/{client['id']}",
                json={"contract_platforms": ["deepseek", "kimi", "yuanbao"]},
            )
            self.assertEqual(update_response.status_code, 200)

            clients = self.client.get("/api/clients").get_json()
            self.assertEqual(clients[0]["contract_platforms"], ["deepseek", "yuanbao", "kimi"])

    def test_platform_list_shape(self):
        with isolated_app_data():
            response = self.client.get("/api/platform/list")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            platform_ids = {item["id"] for item in payload}
            self.assertEqual(platform_ids, {"doubao", "deepseek", "yuanbao", "qwen", "kimi"})
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

    def test_raw_record_endpoints_filter_by_task_id(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "crawl_time": "2026-07-02 10:00",
                        "source_platform": "qwen",
                        "task_id": "task-1",
                        "question": "任务一问题",
                        "answer": "测试品牌被提到",
                        "refs": [{"title": "文章A", "url": "https://a.example", "platform": "搜狐", "position": 1}],
                        "ref_count": 1,
                        "brand_mentioned": True,
                        "geo_score": 20,
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "crawl_time": "2026-07-02 11:00",
                        "source_platform": "qwen",
                        "task_id": "task-2",
                        "question": "任务二问题",
                        "answer": "另一条回答",
                        "refs": [{"title": "文章B", "url": "https://b.example", "platform": "知乎", "position": 1}],
                        "ref_count": 1,
                        "brand_mentioned": False,
                        "geo_score": 0,
                    },
                ],
            )

            records_response = self.client.get(
                "/api/raw_records?client_id=client-1&task_id=task-1"
            )
            stats_response = self.client.get(
                "/api/raw_records/platform_stats?client_id=client-1&task_id=task-1"
            )
            daily_response = self.client.get(
                f"/api/daily/records?client_id=client-1&date={geo_app.today_str()}&task_id=task-1"
            )
            daily_stats_response = self.client.get(
                f"/api/daily/ref_stats?client_id=client-1&date={geo_app.today_str()}&task_id=task-1"
            )

            self.assertEqual(records_response.status_code, 200)
            self.assertEqual([r["id"] for r in records_response.get_json()], ["raw-1"])
            self.assertEqual(stats_response.get_json()["total_records"], 1)
            self.assertEqual(stats_response.get_json()["top_articles"][0]["title"], "文章A")
            self.assertEqual([r["id"] for r in daily_response.get_json()], ["raw-1"])
            self.assertEqual(daily_stats_response.get_json()["total_records"], 1)
            self.assertEqual(daily_stats_response.get_json()["top_articles"][0]["title"], "文章A")

    def test_daily_ref_stats_counts_ref_items_and_article_ai_platforms(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "deepseek",
                        "question": "q1",
                        "answer": "a1",
                        "refs": [
                            {"title": "Shared Article", "url": "https://shared.example", "platform": "Sohu", "position": 1},
                            {"title": "Other Article", "url": "https://other.example", "platform": "Sohu", "position": 2},
                        ],
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                        "question": "q2",
                        "answer": "a2",
                        "refs": [
                            {"title": "Shared Article", "url": "https://shared.example", "platform": "Sohu", "position": 1},
                        ],
                    },
                    {
                        "id": "raw-3",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "doubao",
                        "question": "q3",
                        "answer": "a3",
                        "refs": [
                            {"title": "Zhihu Article", "url": "https://zhihu.example", "platform": "Zhihu", "position": 1},
                        ],
                    },
                ],
            )

            response = self.client.get(
                f"/api/daily/ref_stats?client_id=client-1&date={geo_app.today_str()}"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["total_refs"], 4)
            self.assertEqual(payload["platform_weights"][0]["platform"], "Sohu")
            self.assertEqual(payload["platform_weights"][0]["count"], 3)
            self.assertEqual(payload["platform_weights"][0]["pct"], 75.0)
            self.assertEqual(sum(p["count"] for p in payload["platform_weights"]), payload["total_refs"])
            self.assertEqual(payload["top_articles"][0]["title"], "Shared Article")
            self.assertEqual(payload["top_articles"][0]["count"], 2)
            self.assertEqual(payload["top_articles"][0]["ai_platforms"], ["deepseek", "qwen"])

    def test_daily_ref_stats_groups_top_articles_by_ai_platform_with_limit(self):
        with isolated_app_data():
            deepseek_refs = [
                {
                    "title": f"DeepSeek Article {i:02d}",
                    "url": f"https://deepseek.example/{i}",
                    "platform": "Sohu",
                    "position": i + 1,
                }
                for i in range(21)
            ]
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "deepseek",
                        "question": "q1",
                        "answer": "a1",
                        "refs": deepseek_refs,
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                        "question": "q2",
                        "answer": "a2",
                        "refs": [
                            {
                                "title": "Qwen Article",
                                "url": "https://qwen.example/article",
                                "platform": "Zhihu",
                                "position": 1,
                            }
                        ],
                    },
                ],
            )

            response = self.client.get(
                f"/api/daily/ref_stats?client_id=client-1&date={geo_app.today_str()}"
            )

            payload = response.get_json()
            grouped = {
                item["source_platform"]: item["top_articles"]
                for item in payload["top_articles_by_ai"]
            }
            self.assertEqual(len(grouped["deepseek"]), 20)
            self.assertEqual(grouped["deepseek"][0]["title"], "DeepSeek Article 00")
            self.assertEqual(grouped["deepseek"][-1]["title"], "DeepSeek Article 19")
            self.assertEqual(len(grouped["qwen"]), 1)
            self.assertEqual(grouped["qwen"][0]["title"], "Qwen Article")
            self.assertEqual(grouped["qwen"][0]["url"], "https://qwen.example/article")
            self.assertEqual(grouped["qwen"][0]["platform"], "Zhihu")
            self.assertEqual(grouped["qwen"][0]["count"], 1)
            self.assertEqual(grouped["qwen"][0]["avg_position"], 1.0)
            self.assertEqual(grouped["qwen"][0]["ai_platforms"], ["qwen"])

    def test_daily_ref_stats_merges_same_article_url_variants_across_ai(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "deepseek",
                        "question": "q1",
                        "answer": "a1",
                        "refs": [
                            {
                                "title": "Gold Guide - Toutiao",
                                "url": "https://www.toutiao.com/article/7655174835676480010/?wid=1782389372799",
                                "platform": "Toutiao",
                                "position": 1,
                            }
                        ],
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-1",
                        "today": geo_app.today_str(),
                        "source_platform": "yuanbao",
                        "question": "q2",
                        "answer": "a2",
                        "refs": [
                            {
                                "title": "Gold Guide: Toutiao",
                                "url": "https://www.toutiao.com/a7655174835676480010?channel=",
                                "platform": "Toutiao",
                                "position": 1,
                            }
                        ],
                    },
                ],
            )

            response = self.client.get(
                f"/api/daily/ref_stats?client_id=client-1&date={geo_app.today_str()}"
            )

            payload = response.get_json()
            self.assertEqual(len(payload["top_articles"]), 1)
            self.assertEqual(payload["top_articles"][0]["count"], 2)
            self.assertEqual(payload["top_articles"][0]["ai_platforms"], ["deepseek", "yuanbao"])

    def test_daily_ref_stats_marks_top_articles_with_competitor_body_hits(self):
        with isolated_app_data():
            date = geo_app.today_str()
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "today": date,
                        "source_platform": "qwen",
                        "question": "q1",
                        "answer": "第一竞品和第三竞品被提到",
                        "refs": [
                            {"title": "命中文章", "url": "https://hit.example", "platform": "示例", "position": 1},
                            {"title": "未命中文章", "url": "https://miss.example", "platform": "示例", "position": 2},
                            {"title": "失败文章", "url": "https://fail.example", "platform": "示例", "position": 3},
                        ],
                        "mentioned_entities": [
                            {"name": "第一竞品", "evidence": "第一竞品"},
                            {"name": "第二竞品", "evidence": "第二竞品"},
                            {"name": "第三竞品", "evidence": "第三竞品"},
                        ],
                    }
                ],
            )
            geo_app.save(
                geo_app.F_COMPETITOR_ARTICLE_BODY_HITS,
                [
                    {
                        "client_id": "client-1",
                        "date": date,
                        "task_id": "",
                        "group_id": "",
                        "platform": "",
                        "body_hits": [
                            {
                                "status": "matched",
                                "title": "命中文章",
                                "url": "https://hit.example",
                                "matched_entities": ["第一竞品"],
                            },
                            {
                                "status": "not_matched",
                                "title": "未命中文章",
                                "url": "https://miss.example",
                            },
                            {
                                "status": "fetch_failed",
                                "title": "失败文章",
                                "url": "https://fail.example",
                                "error": "timeout",
                            },
                        ],
                    }
                ],
            )

            response = self.client.get(
                f"/api/daily/ref_stats?client_id=client-1&date={date}"
            )

            payload = response.get_json()
            by_title = {item["title"]: item for item in payload["top_articles"]}
            self.assertEqual(by_title["命中文章"]["competitor_match_status"], "matched")
            self.assertEqual(by_title["命中文章"]["competitor_matched_entities"], ["第一竞品"])
            self.assertEqual(by_title["未命中文章"]["competitor_match_status"], "not_matched")
            self.assertEqual(by_title["失败文章"]["competitor_match_status"], "unconfirmed")
            grouped_qwen = next(
                item for item in payload["top_articles_by_ai"] if item["source_platform"] == "qwen"
            )
            grouped_by_title = {item["title"]: item for item in grouped_qwen["top_articles"]}
            self.assertEqual(grouped_by_title["命中文章"]["competitor_match_status"], "matched")

    def test_daily_insights_filters_by_task_id(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "crawl_time": "2026-07-02 10:00",
                        "source_platform": "qwen",
                        "task_id": "task-1",
                        "question": "任务一问题",
                        "answer": "测试品牌和竞品汽车音响都被提到",
                        "refs": [{"title": "文章A", "url": "https://a.example", "platform": "搜狐", "position": 1}],
                        "ref_count": 1,
                        "brand_mentioned": True,
                        "geo_score": 20,
                        "mentioned_entities": [{"name": "竞品汽车音响", "type": "门店", "sentiment": "positive", "evidence": "竞品汽车音响"}],
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "crawl_time": "2026-07-02 11:00",
                        "source_platform": "doubao",
                        "task_id": "task-2",
                        "question": "任务二问题",
                        "answer": "另一条回答",
                        "refs": [{"title": "文章B", "url": "https://b.example", "platform": "知乎", "position": 1}],
                        "ref_count": 1,
                        "brand_mentioned": False,
                        "geo_score": 0,
                    },
                ],
            )

            response = self.client.get(
                f"/api/daily/insights?client_id=client-1&date={geo_app.today_str()}&task_id=task-1"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["insights"]["total_records"], 1)
            self.assertEqual(payload["insights"]["ai_platforms"][0]["source_platform"], "qwen")
            self.assertEqual(payload["insights"]["top_articles"][0]["title"], "文章A")
            self.assertEqual(payload["insights"]["mentioned_entities"][0]["name"], "竞品汽车音响")

    def test_daily_insights_uses_client_contract_platforms_for_all_platform_visibility(self):
        with isolated_app_data():
            date = geo_app.today_str()
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "today": date,
                        "source_platform": "qwen",
                        "answer": "回答",
                        "refs": [{"title": "文章A", "url": "https://a.example", "platform": "搜狐"}],
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-2",
                        "today": date,
                        "source_platform": "qwen",
                        "answer": "回答",
                        "refs": [{"title": "文章B", "url": "https://b.example", "platform": "知乎"}],
                    },
                ],
            )
            geo_app.save(
                geo_app.F_CLIENTS,
                [
                    {"id": "client-1", "name": "单平台客户", "contract_platforms": ["qwen"]},
                    {"id": "client-2", "name": "多平台客户", "contract_platforms": ["qwen", "doubao"]},
                ],
            )

            single = self.client.get(f"/api/daily/insights?client_id=client-1&date={date}").get_json()
            multi = self.client.get(f"/api/daily/insights?client_id=client-2&date={date}").get_json()

            self.assertEqual(single["insights"]["ai_platforms"][0]["source_platform"], "qwen")
            self.assertEqual(multi["insights"]["ai_platforms"][0]["source_platform"], "all")
            self.assertEqual(multi["insights"]["ai_platforms"][0]["platform_name"], "全部平台")

    def test_daily_insights_does_not_return_competitor_article_section_payload(self):
        with isolated_app_data():
            date = geo_app.today_str()
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": date,
                        "source_platform": "qwen",
                        "task_id": "task-1",
                        "question": "任务一问题",
                        "answer": "第一竞品和第三竞品都被提到",
                        "brand": "测试品牌",
                        "refs": [
                            {
                                "title": "高频文章A",
                                "url": "https://a.example/article",
                                "platform": "示例平台",
                                "position": 1,
                            }
                        ],
                        "mentioned_entities": [
                            {"name": "第一竞品", "type": "门店", "evidence": "第一竞品"},
                            {"name": "第二竞品", "type": "门店", "evidence": "第二竞品"},
                            {"name": "第三竞品", "type": "门店", "evidence": "第三竞品"},
                        ],
                    }
                ],
            )
            geo_app.save(
                geo_app.F_COMPETITOR_ARTICLE_BODY_HITS,
                [
                    {
                        "client_id": "client-1",
                        "date": date,
                        "task_id": "",
                        "group_id": "",
                        "platform": "",
                        "generated_at": "2026-07-03 13:28:08",
                        "body_hits": [
                            {
                                "status": "matched",
                                "title": "高频文章A",
                                "url": "https://a.example/article",
                                "platform": "示例平台",
                                "count": 1,
                                "ai_platforms": ["qwen"],
                                "matched_entities": ["第一竞品"],
                                "evidence": "正文里提到第一竞品",
                            }
                        ],
                    }
                ],
            )

            response = self.client.get(
                f"/api/daily/insights?client_id=client-1&date={date}"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertNotIn("competitor_articles", payload["insights"])
            self.assertNotIn("weak_competitor_articles", payload["insights"])
            self.assertNotIn("selected_competitors", payload["insights"])
            self.assertNotIn("body_hit_report", payload["insights"])

    def test_daily_insights_filters_current_and_historical_own_brand_entities(self):
        with isolated_app_data():
            date = geo_app.today_str()
            geo_app.save(
                geo_app.F_CLIENTS,
                [
                    {"id": "client-1", "name": "河北翼升学", "brand": "翼升学"},
                ],
            )
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-1",
                        "client_id": "client-1",
                        "today": date,
                        "source_platform": "qwen",
                        "brand": "河北翼升学",
                        "brand_mentioned": False,
                        "answer": "翼升学和竞品A被提到。",
                        "refs": [],
                        "mentioned_entities": [
                            {"name": "翼升学", "type": "品牌", "evidence": "翼升学"},
                            {"name": "竞品A", "type": "品牌", "evidence": "竞品A"},
                        ],
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-1",
                        "today": date,
                        "source_platform": "deepseek",
                        "brand": "河北翼升学",
                        "brand_mentioned": True,
                        "answer": "河北翼升学被提到。",
                        "refs": [],
                        "mentioned_entities": [
                            {"name": "河北翼升学", "type": "门店", "evidence": "河北翼升学"},
                        ],
                    },
                ],
            )

            response = self.client.get(f"/api/daily/insights?client_id=client-1&date={date}")

            self.assertEqual(response.status_code, 200)
            insights = response.get_json()["insights"]
            self.assertEqual(insights["brand_mentions"], 2)
            self.assertEqual([item["name"] for item in insights["mentioned_entities"]], ["竞品A"])

    def test_delete_daily_entity_removes_name_within_filtered_scope(self):
        with isolated_app_data():
            geo_app.save(
                geo_app.F_RAW_RECORDS,
                [
                    {
                        "id": "raw-current-1",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                        "task_id": "task-1",
                        "mentioned_entities": [
                            {"name": "Bad Entity", "evidence": "bad"},
                            {"name": "Good Entity", "evidence": "good"},
                        ],
                    },
                    {
                        "id": "raw-current-2",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                        "task_id": "task-1",
                        "mentioned_entities": [{"name": "Bad Entity", "evidence": "bad again"}],
                    },
                    {
                        "id": "raw-other-task",
                        "client_id": "client-1",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                        "task_id": "task-2",
                        "mentioned_entities": [{"name": "Bad Entity", "evidence": "keep"}],
                    },
                    {
                        "id": "raw-other-client",
                        "client_id": "client-2",
                        "group_id": "group-1",
                        "today": geo_app.today_str(),
                        "source_platform": "qwen",
                        "task_id": "task-1",
                        "mentioned_entities": [{"name": "Bad Entity", "evidence": "keep"}],
                    },
                ],
            )

            response = self.client.post(
                "/api/daily/entities/delete",
                json={
                    "client_id": "client-1",
                    "date": geo_app.today_str(),
                    "platform": "qwen",
                    "group_id": "group-1",
                    "task_id": "task-1",
                    "name": "Bad Entity",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["removed"], 2)
            self.assertEqual(payload["records_changed"], 2)
            records = {r["id"]: r for r in geo_app.load(geo_app.F_RAW_RECORDS, [])}
            self.assertEqual(records["raw-current-1"]["mentioned_entities"], [{"name": "Good Entity", "evidence": "good"}])
            self.assertEqual(records["raw-current-2"]["mentioned_entities"], [])
            self.assertEqual(records["raw-other-task"]["mentioned_entities"][0]["name"], "Bad Entity")
            self.assertEqual(records["raw-other-client"]["mentioned_entities"][0]["name"], "Bad Entity")

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

    def test_crawl_rejects_when_same_platform_lock_is_busy(self):
        lock = geo_app.get_crawl_platform_lock("qwen")
        acquired = lock.acquire(blocking=False)
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
            lock.release()

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["error"], "crawl_busy")
        self.assertEqual(payload["platform"], "qwen")

    def test_crawl_allows_different_platform_while_other_platform_is_busy(self):
        lock = geo_app.get_crawl_platform_lock("deepseek")
        acquired = lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            with patch.object(geo_app, "platform_crawl_impl") as impl:
                impl.side_effect = lambda: geo_app.jsonify({"ok": True})
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
            lock.release()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_crawl_job_create_claim_and_result_flow(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])
            geo_app.save(geo_app.F_GROUPS, {
                "client-1": [
                    {
                        "id": "group-1",
                        "name": "核心问题",
                        "questions": ["问题一", "问题二"],
                    }
                ]
            })

            create_response = self.client.post("/api/crawl_jobs", json={
                "client_id": "client-1",
                "group_id": "group-1",
                "platform": "qwen",
                "repeat_count": 2,
            })

            self.assertEqual(create_response.status_code, 200)
            created = create_response.get_json()
            self.assertTrue(created["ok"])
            self.assertEqual(created["job"]["status"], "pending")
            self.assertEqual(created["job"]["brand"], "测试品牌")
            self.assertEqual(created["job"]["questions"], ["问题一", "问题二"])
            self.assertEqual(created["job"]["repeat_count"], 2)

            claim_response = self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-1&platform=qwen")
            self.assertEqual(claim_response.status_code, 200)
            claimed = claim_response.get_json()
            self.assertTrue(claimed["ok"])
            self.assertEqual(claimed["job"]["id"], created["job"]["id"])
            self.assertEqual(claimed["job"]["status"], "running")
            self.assertEqual(claimed["job"]["assigned_to"], "ops-laptop-1")

            empty_claim = self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-2&platform=qwen")
            self.assertEqual(empty_claim.status_code, 200)
            self.assertFalse(empty_claim.get_json()["job"])

            result_response = self.client.post(f"/api/crawl_jobs/{created['job']['id']}/result", json={
                "status": "completed",
                "summary": {"total": 2, "success": 2},
                "results": [
                    {
                        "question": "问题一",
                        "answer": "测试品牌被提到",
                        "refs": [{"title": "引用文章", "url": "https://example.com/a"}],
                        "cookies": [{"name": "session", "value": "secret"}],
                    }
                ],
                "storage_state": {"cookies": [{"name": "session", "value": "secret"}]},
                "password": "secret",
            })

            self.assertEqual(result_response.status_code, 200)
            finished = result_response.get_json()["job"]
            self.assertEqual(finished["status"], "completed")
            self.assertEqual(finished["result_summary"], {"total": 2, "success": 2})
            self.assertEqual(finished["persisted_records"], 1)
            self.assertEqual(finished["persisted_errors"], 0)
            self.assertEqual(finished["persist_result"]["saved"], 1)
            self.assertEqual(finished["result_payload"]["results"][0]["question"], "问题一")
            serialized = json.dumps(finished, ensure_ascii=False)
            self.assertNotIn("secret", serialized)
            self.assertNotIn("storage_state", serialized)
            self.assertNotIn("cookies", serialized)

            raw_records = geo_app.load(geo_app.F_RAW_RECORDS, [])
            self.assertEqual(len(raw_records), 1)
            self.assertEqual(raw_records[0]["client_id"], "client-1")
            self.assertEqual(raw_records[0]["group_id"], "group-1")
            self.assertEqual(raw_records[0]["brand"], "测试品牌")
            self.assertEqual(raw_records[0]["question"], "问题一")
            self.assertEqual(raw_records[0]["answer"], "测试品牌被提到")
            self.assertEqual(raw_records[0]["source_platform"], "qwen")
            self.assertEqual(raw_records[0]["crawler_engine"], "local_worker_node")

    def test_crawl_job_create_sets_expiry_and_batch_id(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])

            with patch.object(geo_app, "now_str", return_value="2026-07-14 10:00"):
                response = self.client.post("/api/crawl_jobs", json={
                    "client_id": "client-1",
                    "platform": "qwen",
                    "questions": ["问题一"],
                    "batch_id": "batch-123",
                })

            self.assertEqual(response.status_code, 200)
            job = response.get_json()["job"]
            self.assertEqual(job["batch_id"], "batch-123")
            self.assertEqual(job["expires_at"], "2026-07-14 10:02")

    def test_crawl_job_pending_expiry_skips_stale_job(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-old", "name": "旧客户", "brand": "旧品牌"},
                {"id": "client-new", "name": "新客户", "brand": "新品牌"},
            ])
            with patch.object(geo_app, "now_str", return_value="2026-07-14 10:00"):
                old_response = self.client.post("/api/crawl_jobs", json={
                    "client_id": "client-old",
                    "platform": "doubao",
                    "questions": ["旧问题"],
                })
            with patch.object(geo_app, "now_str", return_value="2026-07-14 10:03"):
                new_response = self.client.post("/api/crawl_jobs", json={
                    "client_id": "client-new",
                    "platform": "doubao",
                    "questions": ["新问题"],
                })
                claim_response = self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop&platform=doubao")

            self.assertEqual(claim_response.status_code, 200)
            claimed = claim_response.get_json()["job"]
            self.assertEqual(claimed["id"], new_response.get_json()["job"]["id"])
            self.assertEqual(claimed["client_id"], "client-new")
            jobs = geo_app.load(geo_app.F_CRAWL_JOBS, [])
            old_job = next(job for job in jobs if job["id"] == old_response.get_json()["job"]["id"])
            self.assertEqual(old_job["status"], "expired")

    def test_crawl_job_pending_expiry_keeps_fresh_job(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])
            with patch.object(geo_app, "now_str", return_value="2026-07-14 10:00"):
                create_response = self.client.post("/api/crawl_jobs", json={
                    "client_id": "client-1",
                    "platform": "qwen",
                    "questions": ["问题一"],
                })
            with patch.object(geo_app, "now_str", return_value="2026-07-14 10:01"):
                claim_response = self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop&platform=qwen")

            self.assertEqual(claim_response.status_code, 200)
            self.assertEqual(claim_response.get_json()["job"]["id"], create_response.get_json()["job"]["id"])

    def test_crawl_job_result_does_not_queue_entity_normalize_automatically(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])
            create_response = self.client.post("/api/crawl_jobs", json={
                "client_id": "client-1",
                "platform": "qwen",
                "questions": ["问题一"],
            })
            job_id = create_response.get_json()["job"]["id"]
            self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-1&platform=qwen")

            with patch.object(
                geo_app,
                "queue_entity_normalize_task",
                return_value={"ok": True, "status": "queued", "queued": True},
            ) as queue_entities:
                result_response = self.client.post(f"/api/crawl_jobs/{job_id}/result", json={
                    "status": "completed",
                    "summary": {"total": 1, "success": 1},
                    "results": [
                        {"ok": True, "question": "问题一", "answer": "测试品牌被提到", "refs": []}
                    ],
                })

            self.assertEqual(result_response.status_code, 200)
            payload = result_response.get_json()
            self.assertNotIn("entity_normalize", payload["persisted"])
            queue_entities.assert_not_called()

    def test_daily_entities_generate_queues_current_scope(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])
            queued_result = {"ok": True, "status": "queued", "queued": True}
            with patch.object(geo_app, "queue_entity_normalize_task", return_value=queued_result) as queue_entities:
                response = self.client.post("/api/daily/entities/generate", json={
                    "client_id": "client-1",
                    "date": "2026-07-13",
                    "group_id": "group-1",
                    "platform": "qwen",
                    "task_id": "task-1",
                })

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["entity_normalize"], queued_result)
            self.assertEqual(payload["scope_task_id"], "task-1")
            self.assertTrue(os.path.basename(payload["task_report"]).startswith("2026-07-13_"))
            queue_entities.assert_called_once()
            args, kwargs = queue_entities.call_args
            self.assertEqual(args[:3], ("client-1", "2026-07-13", "task-1"))
            self.assertEqual(args[3], payload["task_report"])
            self.assertEqual(kwargs, {"username": "", "group_id": "group-1", "platform": "qwen"})

            report = geo_app.load(payload["task_report"], {})
            self.assertEqual(report["client_id"], "client-1")
            self.assertEqual(report["date"], "2026-07-13")
            self.assertEqual(report["scope_task_id"], "task-1")
            self.assertEqual(report["group_id"], "group-1")
            self.assertEqual(report["source_platform"], "qwen")
            self.assertEqual(report["entity_normalize"], queued_result)

    def test_cloud_can_create_login_job_for_local_worker(self):
        with isolated_app_data():
            create_response = self.client.post("/api/crawl_jobs/login", json={"platform": "qwen"})

            self.assertEqual(create_response.status_code, 200)
            created = create_response.get_json()
            self.assertTrue(created["ok"])
            self.assertEqual(created["job"]["job_type"], "login")
            self.assertEqual(created["job"]["platform"], "qwen")
            self.assertEqual(created["job"]["questions"], [])

            claim_response = self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-1&platform=qwen")
            self.assertEqual(claim_response.status_code, 200)
            claimed = claim_response.get_json()["job"]
            self.assertEqual(claimed["id"], created["job"]["id"])
            self.assertEqual(claimed["job_type"], "login")
            self.assertEqual(claimed["assigned_to"], "ops-laptop-1")

            result_response = self.client.post(f"/api/crawl_jobs/{created['job']['id']}/result", json={
                "status": "completed",
                "summary": {"total": 1, "success": 1},
                "results": [],
            })

            self.assertEqual(result_response.status_code, 200)
            finished = result_response.get_json()
            self.assertEqual(finished["job"]["status"], "completed")
            self.assertTrue(finished["persisted"]["skipped"])
            self.assertEqual(geo_app.load(geo_app.F_RAW_RECORDS, []), [])

    def test_crawl_job_result_does_not_duplicate_raw_records(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])
            create_response = self.client.post("/api/crawl_jobs", json={
                "client_id": "client-1",
                "platform": "qwen",
                "questions": ["问题一"],
                "repeat_count": 1,
            })
            job_id = create_response.get_json()["job"]["id"]
            self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-1&platform=qwen")

            payload = {
                "status": "completed",
                "summary": {"total": 1, "success": 1},
                "results": [
                    {"ok": True, "question": "问题一", "answer": "测试品牌被提到", "refs": []}
                ],
            }
            first_response = self.client.post(f"/api/crawl_jobs/{job_id}/result", json=payload)
            second_response = self.client.post(f"/api/crawl_jobs/{job_id}/result", json=payload)

            self.assertEqual(first_response.status_code, 200)
            self.assertEqual(second_response.status_code, 200)
            raw_records = geo_app.load(geo_app.F_RAW_RECORDS, [])
            self.assertEqual(len(raw_records), 1)
            self.assertEqual(second_response.get_json()["persisted"]["reason"], "already_persisted")

    def test_crawl_job_cancel_pending_prevents_claim(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])
            create_response = self.client.post("/api/crawl_jobs", json={
                "client_id": "client-1",
                "platform": "qwen",
                "questions": ["问题一"],
            })
            job_id = create_response.get_json()["job"]["id"]

            cancel_response = self.client.post(f"/api/crawl_jobs/{job_id}/cancel")
            claim_response = self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-1&platform=qwen")

            self.assertEqual(cancel_response.status_code, 200)
            self.assertEqual(cancel_response.get_json()["job"]["status"], "canceled")
            self.assertIsNone(claim_response.get_json()["job"])

    def test_canceled_crawl_job_result_does_not_persist_raw_records(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])
            create_response = self.client.post("/api/crawl_jobs", json={
                "client_id": "client-1",
                "platform": "qwen",
                "questions": ["问题一"],
            })
            job_id = create_response.get_json()["job"]["id"]
            self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-1&platform=qwen")
            self.client.post(f"/api/crawl_jobs/{job_id}/cancel")

            result_response = self.client.post(f"/api/crawl_jobs/{job_id}/result", json={
                "status": "completed",
                "summary": {"total": 1, "success": 1},
                "results": [
                    {"ok": True, "question": "问题一", "answer": "测试品牌被提到", "refs": []}
                ],
            })

            self.assertEqual(result_response.status_code, 200)
            self.assertEqual(result_response.get_json()["job"]["status"], "canceled")
            self.assertEqual(result_response.get_json()["persisted"]["reason"], "job_not_completed")
            self.assertEqual(geo_app.load(geo_app.F_RAW_RECORDS, []), [])

    def test_kimi_crawl_job_result_persists_raw_records(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "client-1", "name": "测试客户", "brand": "测试品牌"}
            ])

            create_response = self.client.post("/api/crawl_jobs", json={
                "client_id": "client-1",
                "platform": "kimi",
                "questions": ["问题一"],
            })
            self.assertEqual(create_response.status_code, 200)
            job_id = create_response.get_json()["job"]["id"]

            claim_response = self.client.get("/api/crawl_jobs/next?worker_id=ops-laptop-1&platform=kimi")
            self.assertEqual(claim_response.status_code, 200)
            self.assertEqual(claim_response.get_json()["job"]["platform"], "kimi")

            result_response = self.client.post(f"/api/crawl_jobs/{job_id}/result", json={
                "status": "completed",
                "summary": {"total": 1, "success": 1},
                "results": [
                    {"ok": True, "question": "问题一", "answer": "测试品牌被 Kimi 提到", "refs": []}
                ],
            })

            self.assertEqual(result_response.status_code, 200)
            raw_records = geo_app.load(geo_app.F_RAW_RECORDS, [])
            self.assertEqual(len(raw_records), 1)
            self.assertEqual(raw_records[0]["source_platform"], "kimi")

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

                with patch("services.node_crawler_bridge.run_node_crawler", side_effect=fake_run_node_crawler), \
                        patch.object(geo_app, "queue_entity_normalize_task") as queue_entities, \
                        patch.object(geo_app, "auto_normalize_task_entities") as auto_entities:
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
                queue_entities.assert_not_called()
                auto_entities.assert_not_called()
                self.assertNotIn("entity_normalize", payload)

                records = geo_app.load(geo_app.F_RAW_RECORDS, [])
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["source_platform"], "qwen")
                self.assertEqual(records[0]["question"], "测试问题")
                self.assertEqual(records[0]["refs"][0]["platform"], "搜狐")

                report = geo_app.load(payload["task_report"], {})
                self.assertEqual(report["crawler_engine"], "node")
                self.assertEqual(report["node_output_dir"], calls[0]["kwargs"]["output_dir"])
                self.assertEqual(report["status"], "completed")
                self.assertNotIn("entity_normalize", report)
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

    def test_crawl_saves_raw_record_when_ai_analysis_retries_then_falls_back(self):
        old_value = os.environ.get("GEO_NODE_CRAWLER_PLATFORMS")
        try:
            with isolated_app_data() as tmp:
                os.environ["GEO_NODE_CRAWLER_PLATFORMS"] = "qwen"
                geo_app.save(geo_app.F_SETTINGS, {"api_key": "test-key"})
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
                                "answer": "测试品牌可以作为候选之一，适合本地服务评估。",
                                "refs": [
                                    {
                                        "title": "测试品牌参考文章",
                                        "url": "https://example.com/ref",
                                        "platform": "示例平台",
                                    }
                                ],
                                "error": "",
                            }
                        ],
                    }

                with patch("services.node_crawler_bridge.run_node_crawler", side_effect=fake_run_node_crawler), \
                        patch.object(geo_app, "analyze_brand_intel", side_effect=ValueError("Invalid control character")) as analyze, \
                        patch.object(geo_app, "queue_entity_normalize_task", return_value={"ok": True, "status": "queued", "queued": True}):
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
                self.assertEqual(payload["analyzed"], 1)
                self.assertEqual(payload["errors"], 0)
                self.assertEqual(analyze.call_count, 3)

                raw_records = geo_app.load(geo_app.F_RAW_RECORDS, [])
                self.assertEqual(len(raw_records), 1)
                self.assertEqual(raw_records[0]["question"], "测试问题")
                self.assertTrue(raw_records[0]["brand_mentioned"])
                self.assertEqual(raw_records[0]["analysis"]["analysis_status"], "fallback_basic")
                self.assertEqual(raw_records[0]["analysis"]["analysis_mode"], "api_failed_basic")

                report = geo_app.load(payload["task_report"], {})
                self.assertEqual(report["status"], "completed")
                self.assertEqual(report["analysis_errors"], [])
                self.assertEqual(len(report["analysis_fallbacks"]), 1)
                self.assertEqual(report["analysis_fallbacks"][0]["attempts"], 3)
                self.assertEqual(report["success"][0]["analysis_status"], "fallback_basic")
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

    def test_retired_reference_endpoint_returns_404(self):
        with isolated_app_data():
            response = geo_app.app.test_client().get("/api/reference_intelligence/plugins?client_id=c1")
            self.assertEqual(response.status_code, 404)
    def test_pattern_library_scopes_and_entries_include_latest_ingest_summary(self):
        with isolated_app_data() as tmp:
            library = geo_app.PatternLibrary(os.path.join(tmp, "pattern_library"))
            entry = library.create_candidate(
                "industry:成人教育",
                "skeleton",
                "观察分类型",
                {"sections": ["先按服务类型分组"], "signature": "中性比较", "risk_notes": ""},
                {
                    "url": "https://example.com/article",
                    "title": "示例文章",
                    "citation_count": 3,
                    "risk_marks": ["AI 生成痕迹明显"],
                },
            )
            global_entry = library.create_candidate(
                "global",
                "module",
                "答案前置型开头",
                {"type": "开头", "pattern": "先给答案"},
                {"url": "seed://OP-G02", "title": "答案前置型开头 | seed"},
            )
            report_path = os.path.join(
                geo_app.F_REFERENCE_INTELLIGENCE,
                "c1",
                "2026-07-17",
                "stage2_ingest_report.json",
            )
            geo_app.save(report_path, {
                "client_id": "c1",
                "date": "2026-07-17",
                "total_cards": 8,
                "items": [{"action": "created"}, {"action": "matched"}],
                "errors": [],
            })

            scopes_response = self.client.get("/api/pattern-library/scopes")
            self.assertEqual(scopes_response.status_code, 200)
            self.assertEqual(scopes_response.get_json()["scopes"], [
                {"scope": "global", "entry_count": 1},
                {"scope": "industry:成人教育", "entry_count": 1}
            ])

            entries_response = self.client.get("/api/pattern-library/entries?scope=industry:成人教育")
            self.assertEqual(entries_response.status_code, 200)
            payload = entries_response.get_json()
            self.assertEqual(payload["scope"], "industry:成人教育")
            self.assertEqual(payload["entries"][0]["id"], entry["id"])
            self.assertEqual(payload["recent_ingest"], {
                "client_id": "c1",
                "date": "2026-07-17",
                "cards": 8,
                "created": 1,
                "matched": 1,
                "errors": 0,
            })

            global_entries_response = self.client.get("/api/pattern-library/entries?scope=global")
            self.assertEqual(global_entries_response.status_code, 200)
            self.assertEqual(global_entries_response.get_json()["entries"][0]["id"], global_entry["id"])

            retired = self.client.post("/api/pattern-library/status", json={
                "scope": "global", "entry_id": global_entry["id"], "status": "retired",
            })
            self.assertEqual(retired.status_code, 200)
            self.assertEqual(retired.get_json()["entry"]["status"], "retired")

    def test_pattern_library_status_update_rejects_invalid_and_missing_entries(self):
        with isolated_app_data() as tmp:
            library = geo_app.PatternLibrary(os.path.join(tmp, "pattern_library"))
            entry = library.create_candidate(
                "industry:成人教育",
                "module",
                "痛点连问型",
                {"type": "开头", "pattern": "用问题进入主题", "excerpt": "示例摘录"},
                {"url": "https://example.com/article", "title": "示例文章"},
            )

            updated = self.client.post("/api/pattern-library/status", json={
                "scope": "industry:成人教育",
                "entry_id": entry["id"],
                "status": "active",
            })
            self.assertEqual(updated.status_code, 200)
            self.assertTrue(updated.get_json()["ok"])
            self.assertEqual(updated.get_json()["entry"]["status"], "active")

            invalid_status = self.client.post("/api/pattern-library/status", json={
                "scope": "industry:成人教育",
                "entry_id": entry["id"],
                "status": "invalid",
            })
            self.assertEqual(invalid_status.status_code, 400)

            missing_entry = self.client.post("/api/pattern-library/status", json={
                "scope": "industry:成人教育",
                "entry_id": "missing",
                "status": "retired",
            })
            self.assertEqual(missing_entry.status_code, 400)

    def test_reference_intelligence_analyze_starts_background_stage_job(self):
        with isolated_app_data():
            with patch.object(geo_app, "queue_reference_analysis_job", return_value={
                "ok": True,
                "job_id": "job-1",
                "status": "running",
                "progress": 3,
            }) as queue_job:
                response = geo_app.app.test_client().post("/api/reference_intelligence/analyze", json={
                    "client_id": "c1",
                    "date": "2026-07-08",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["job_id"], "job-1")
            self.assertEqual(data["status"], "running")
            self.assertEqual(data["progress"], 3)
            self.assertNotIn("plugins", data)
            queue_job.assert_called_once()
            self.assertEqual(queue_job.call_args.kwargs["client_id"], "c1")
            self.assertEqual(queue_job.call_args.kwargs["date_str"], "2026-07-08")

    def test_reference_intelligence_analyze_status_and_cancel_endpoints(self):
        with isolated_app_data():
            job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "")

            status_response = geo_app.app.test_client().get(f"/api/reference_intelligence/analyze_status?job_id={job_id}")
            self.assertEqual(status_response.status_code, 200)
            self.assertEqual(status_response.get_json()["job_id"], job_id)

            cancel_response = geo_app.app.test_client().post("/api/reference_intelligence/analyze_cancel", json={
                "job_id": job_id,
            })
            self.assertEqual(cancel_response.status_code, 200)
            self.assertEqual(cancel_response.get_json()["status"], "canceled")

            missing_response = geo_app.app.test_client().get("/api/reference_intelligence/analyze_status?job_id=missing")
            self.assertEqual(missing_response.status_code, 404)

    def test_reference_intelligence_queue_reuses_running_job_for_same_scope(self):
        with isolated_app_data():
            with geo_app.reference_analysis_jobs_guard:
                geo_app.reference_analysis_jobs.clear()
            job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "", username="u1")
            geo_app.update_reference_analysis_job(job_id, status="running", progress=40)

            with patch.object(geo_app.threading, "Thread") as thread_cls:
                result = geo_app.queue_reference_analysis_job("c1", "2026-07-08", "", username="u2")

            self.assertEqual(result["job_id"], job_id)
            self.assertEqual(result["progress"], 40)
            thread_cls.assert_not_called()

    def test_reference_intelligence_job_writes_new_stage_artifacts_and_industry_scope(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": "c1", "name": "Client", "brand": "Brand", "industry": "Training",
            }])
            geo_app.save(geo_app.F_RAW_RECORDS, [{
                "id": "r1", "client_id": "c1", "today": "2026-07-08", "refs": [
                    {"title": "Article", "url": "https://example.com/a", "position": 1},
                ],
            }])
            responses = [
                {"learnable": True, "reason": "complete article"},
                {"skeleton": None, "modules": [], "citability_features": []},
            ]
            job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "")
            geo_app.run_reference_analysis_job(
                job_id,
                client_id="c1",
                date_str="2026-07-08",
                fetch_fn=lambda url, **kwargs: {
                    "ok": True, "title": "Article", "content": "complete article body " * 30,
                    "fetch_method": "test",
                },
                ai_json_fn=lambda prompt, max_tokens: responses.pop(0),
            )

            stage_dir = os.path.join(geo_app.F_REFERENCE_INTELLIGENCE, "c1", "2026-07-08")
            self.assertEqual(geo_app.get_reference_analysis_job(job_id)["status"], "completed")
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage0_filter_groups.json")))
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage1_anatomy_cards.json")))
            report = geo_app.load(os.path.join(stage_dir, "stage2_ingest_report.json"), {})
            self.assertEqual(report["scope"], "industry:Training")
            self.assertFalse(os.path.exists(os.path.join(stage_dir, "stage3_prompt_plugins.json")))

    def test_reference_intelligence_job_cancels_between_new_stages(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [{"id": "c1", "brand": "Brand", "industry": ""}])
            geo_app.save(geo_app.F_RAW_RECORDS, [{
                "id": "r1", "client_id": "c1", "today": "2026-07-08", "refs": [
                    {"title": "Article", "url": "https://example.com/a", "position": 1},
                ],
            }])
            job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "")

            def cancel_after_stage0(prompt, max_tokens):
                geo_app.cancel_reference_analysis_job(job_id)
                return {"learnable": True}

            geo_app.run_reference_analysis_job(
                job_id,
                client_id="c1",
                date_str="2026-07-08",
                fetch_fn=lambda url, **kwargs: {
                    "ok": True, "title": "Article", "content": "complete article body " * 30,
                },
                ai_json_fn=cancel_after_stage0,
            )

            stage_dir = os.path.join(geo_app.F_REFERENCE_INTELLIGENCE, "c1", "2026-07-08")
            self.assertEqual(geo_app.get_reference_analysis_job(job_id)["status"], "canceled")
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage0_filter_groups.json")))
            self.assertFalse(os.path.exists(os.path.join(stage_dir, "stage1_anatomy_cards.json")))

    def test_reference_intelligence_background_job_runs_new_stage_pipeline(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_CLIENTS, [{"id": "c1", "brand": "", "industry": "成人教育"}])
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {
                    "id": "r1",
                    "client_id": "c1",
                    "today": "2026-07-08",
                    "source_platform": "deepseek",
                    "question": "学历提升机构怎么选？",
                    "refs": [
                        {"title": "河北学历提升机构选择攻略", "url": "https://example.com/a", "platform": "媒体", "position": 1}
                    ],
                }
            ])
            ai_results = [
                {
                    "article_type": "对比型",
                    "learnable": True,
                    "reason": "文章结构完整。",
                    "promoted_entity": "",
                    "risk_marks": [],
                },
                {
                    "skeleton": None,
                    "modules": [],
                    "citability_features": [],
                },
            ]

            def fake_fetch(url, **kwargs):
                return {
                    "ok": True,
                    "title": "河北学历提升机构选择攻略",
                    "description": "",
                    "content": "这是一篇足够长的文章正文。" * 30,
                    "fetch_method": "test",
                }

            job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "")
            geo_app.run_reference_analysis_job(
                job_id,
                client_id="c1",
                date_str="2026-07-08",
                task_id="",
                username="",
                fetch_fn=fake_fetch,
                ai_json_fn=lambda prompt, max_tokens: ai_results.pop(0),
            )

            status = geo_app.get_reference_analysis_job(job_id)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["progress"], 100)

            stage_dir = os.path.join(geo_app.F_REFERENCE_INTELLIGENCE, "c1", "2026-07-08")
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "fetched_articles.json")))
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage0_filter_groups.json")))
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage1_anatomy_cards.json")))
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage2_ingest_report.json")))
            self.assertFalse(os.path.exists(os.path.join(stage_dir, "stage3_prompt_plugins.json")))

    def test_reference_intelligence_fetch_reuses_cache_and_backfills_candidates(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {
                    "id": "r1",
                    "client_id": "c1",
                    "today": "2026-07-08",
                    "source_platform": "deepseek",
                    "question": "服务机构怎么选？",
                    "refs": [
                        {"title": "缓存成功文章", "url": "https://example.com/a", "position": 1},
                        {"title": "当前失败文章", "url": "https://example.com/b", "position": 2},
                        {"title": "补抓成功文章", "url": "https://example.com/c", "position": 3},
                    ],
                }
            ])
            stage_dir = geo_app.reference_stage_dir("c1", "2026-07-08")
            geo_app.save(os.path.join(stage_dir, "fetched_articles.json"), {
                "articles": [
                    {
                        "url": "https://example.com/a",
                        "ok": True,
                        "title": "缓存成功文章",
                        "description": "",
                        "content": "缓存正文" * 120,
                        "content_len": 480,
                        "fetch_method": "browser",
                    }
                ]
            })
            fetched_urls = []

            def fake_fetch(url, **kwargs):
                fetched_urls.append(url)
                if url.endswith("/b"):
                    return {
                        "ok": False,
                        "title": "当前失败文章",
                        "content": "",
                        "error": "content_too_short",
                        "fetch_method": "browser",
                    }
                return {
                    "ok": True,
                    "title": "补抓成功文章",
                    "description": "",
                    "content": "补抓正文" * 120,
                    "error": "",
                    "fetch_method": "browser",
                }

            ai_results = [
                {"parent_type": "对比型", "opening": "缓存开头", "body": ["缓存结构"], "ending": "缓存结尾"},
                {"parent_type": "对比型", "opening": "补抓开头", "body": ["补抓结构"], "ending": "补抓结尾"},
                {
                    "clusters": [
                        {
                            "parent_type": "对比型",
                            "subtype_name": "补抓合并型",
                            "article_indexes": [1, 2],
                            "shared_structure": {"opening": "开头", "body": ["正文"], "ending": "结尾"},
                        }
                    ]
                },
                {
                    "plugins": [
                        {
                            "cluster_index": 1,
                            "parent_type": "对比型",
                            "subtype_name": "补抓合并型",
                            "prompt_text": "按补抓后的结构写。",
                            "few_shot": "示例正文。",
                        }
                    ]
                },
            ]

            job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "")
            geo_app.run_reference_analysis_job(
                job_id,
                client_id="c1",
                date_str="2026-07-08",
                task_id="",
                username="",
                fetch_fn=fake_fetch,
                ai_json_fn=lambda prompt, max_tokens: ai_results.pop(0),
                limit=2,
                candidate_limit=3,
            )

            self.assertEqual(set(fetched_urls), {"https://example.com/b", "https://example.com/c"})
            fetched = geo_app.load(os.path.join(stage_dir, "fetched_articles.json"), {})
            self.assertEqual(fetched["total"], 3)
            self.assertEqual(fetched["fetched_ok"], 2)
            self.assertEqual(fetched["fetched_failed"], 1)
            self.assertEqual(fetched["articles"][0]["fetch_method"], "cache")
            self.assertEqual([item["url"] for item in fetched["articles"]], [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
            ])

            stage1 = geo_app.load(os.path.join(stage_dir, "stage1_anatomy_cards.json"), {})
            self.assertIn("cards", stage1)
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage2_ingest_report.json")))

    def test_reference_intelligence_fetches_uncached_candidates_in_parallel(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {
                    "id": "r1",
                    "client_id": "c1",
                    "today": "2026-07-08",
                    "source_platform": "deepseek",
                    "question": "服务机构怎么选？",
                    "refs": [
                        {"title": "文章A", "url": "https://example.com/a"},
                        {"title": "文章B", "url": "https://example.com/b"},
                        {"title": "文章C", "url": "https://example.com/c"},
                        {"title": "文章D", "url": "https://example.com/d"},
                    ],
                }
            ])
            active = 0
            max_active = 0
            lock = threading.Lock()

            def fake_fetch(url, **kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.05)
                with lock:
                    active -= 1
                return {
                    "ok": True,
                    "title": url.rsplit("/", 1)[-1],
                    "description": "",
                    "content": "并行正文" * 120,
                    "error": "",
                    "fetch_method": "browser",
                }

            ai_results = [
                {"parent_type": "对比型", "opening": "开头", "body": ["结构"], "ending": "结尾"},
                {"parent_type": "对比型", "opening": "开头", "body": ["结构"], "ending": "结尾"},
                {"parent_type": "对比型", "opening": "开头", "body": ["结构"], "ending": "结尾"},
                {"parent_type": "对比型", "opening": "开头", "body": ["结构"], "ending": "结尾"},
                {
                    "clusters": [
                        {
                            "parent_type": "对比型",
                            "subtype_name": "并行抓取型",
                            "article_indexes": [1, 2, 3, 4],
                            "shared_structure": {"opening": "开头", "body": ["正文"], "ending": "结尾"},
                        }
                    ]
                },
                {
                    "plugins": [
                        {
                            "cluster_index": 1,
                            "parent_type": "对比型",
                            "subtype_name": "并行抓取型",
                            "prompt_text": "按并行抓取后的结构写。",
                            "few_shot": "示例正文。",
                        }
                    ]
                },
            ]

            job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "")
            geo_app.run_reference_analysis_job(
                job_id,
                client_id="c1",
                date_str="2026-07-08",
                fetch_fn=fake_fetch,
                ai_json_fn=lambda prompt, max_tokens: ai_results.pop(0),
                limit=4,
                candidate_limit=4,
            )

            self.assertGreaterEqual(max_active, 2)
            fetched = geo_app.load(os.path.join(geo_app.reference_stage_dir("c1", "2026-07-08"), "fetched_articles.json"), {})
            self.assertEqual([item["url"] for item in fetched["articles"]], [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
                "https://example.com/d",
            ])

    def test_reference_intelligence_progress_anchors_match_parallel_pipeline(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {
                    "id": "r1",
                    "client_id": "c1",
                    "today": "2026-07-08",
                    "source_platform": "deepseek",
                    "question": "服务机构怎么选？",
                    "refs": [
                        {"title": "文章A", "url": "https://example.com/a"},
                        {"title": "文章B", "url": "https://example.com/b"},
                    ],
                }
            ])
            progresses = []
            original_update = geo_app.update_reference_analysis_job

            def record_update(job_id, **fields):
                if "progress" in fields:
                    progresses.append(fields["progress"])
                return original_update(job_id, **fields)

            ai_results = [
                {"parent_type": "对比型", "opening": "开头", "body": ["结构"], "ending": "结尾"},
                {"parent_type": "对比型", "opening": "开头", "body": ["结构"], "ending": "结尾"},
                {
                    "clusters": [
                        {
                            "parent_type": "对比型",
                            "subtype_name": "进度锚点型",
                            "article_indexes": [1, 2],
                            "shared_structure": {"opening": "开头", "body": ["正文"], "ending": "结尾"},
                        }
                    ]
                },
                {
                    "plugins": [
                        {
                            "cluster_index": 1,
                            "parent_type": "对比型",
                            "subtype_name": "进度锚点型",
                            "prompt_text": "按结构写。",
                            "few_shot": "示例正文。",
                        }
                    ]
                },
            ]

            with patch.object(geo_app, "update_reference_analysis_job", side_effect=record_update):
                job_id = geo_app.create_reference_analysis_job("c1", "2026-07-08", "")
                geo_app.run_reference_analysis_job(
                    job_id,
                    client_id="c1",
                    date_str="2026-07-08",
                    fetch_fn=lambda url, **kwargs: {
                        "ok": True,
                        "title": url.rsplit("/", 1)[-1],
                        "description": "",
                        "content": "正文" * 120,
                        "error": "",
                        "fetch_method": "browser",
                    },
                    ai_json_fn=lambda prompt, max_tokens: ai_results.pop(0),
                    limit=2,
                    candidate_limit=2,
                )

            self.assertIn(30, progresses)
            self.assertIn(80, progresses)
            self.assertIn(78, progresses)
            self.assertIn(98, progresses)
            self.assertNotIn(76, progresses)

    def test_daily_entity_status_reads_latest_task_report(self):
        with isolated_app_data() as tmp:
            report_dir = os.path.join(tmp, "tasks")
            os.makedirs(report_dir, exist_ok=True)
            geo_app.save(os.path.join(report_dir, "2026-07-08_old.json"), {
                "client_id": "c1",
                "date": "2026-07-08",
                "task_id": "old",
                "entity_normalize": {"status": "queued"},
            })
            geo_app.save(os.path.join(report_dir, "2026-07-08_new.json"), {
                "client_id": "c1",
                "date": "2026-07-08",
                "task_id": "new",
                "created_at": "2026-07-08 15:00",
                "entity_normalize": {"ok": True, "changed": 2},
                "entity_normalize_finished_at": "2026-07-08 15:03",
            })

            response = geo_app.app.test_client().get("/api/daily/entity_status?client_id=c1&date=2026-07-08")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["task_id"], "new")
            self.assertEqual(data["changed"], 2)


if __name__ == "__main__":
    unittest.main()
