import json
import os
import tempfile
import threading
import time
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
        "F_COMPETITOR_ARTICLE_BODY_HITS": geo_app.F_COMPETITOR_ARTICLE_BODY_HITS,
        "F_CONTENT_GENERATIONS": getattr(geo_app, "F_CONTENT_GENERATIONS", None),
        "F_CRAWL_JOBS": getattr(geo_app, "F_CRAWL_JOBS", None),
        "F_REFERENCE_INTELLIGENCE": getattr(geo_app, "F_REFERENCE_INTELLIGENCE", None),
        "UPLOAD_FOLDER": getattr(geo_app, "UPLOAD_FOLDER", None),
        "LOCAL_PDF_FOLDER": getattr(geo_app, "LOCAL_PDF_FOLDER", None),
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
        geo_app.F_CRAWL_JOBS = os.path.join(tmp, "crawl_jobs.json")
        geo_app.F_REFERENCE_INTELLIGENCE = os.path.join(tmp, "reference_intelligence")
        if hasattr(geo_app, "UPLOAD_FOLDER"):
            geo_app.UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        if hasattr(geo_app, "LOCAL_PDF_FOLDER"):
            geo_app.LOCAL_PDF_FOLDER = os.path.join(tmp, "pdf")
            os.makedirs(geo_app.LOCAL_PDF_FOLDER, exist_ok=True)
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


class CoreFunctionTests(unittest.TestCase):
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

    def test_content_generate_uses_all_materials_history_and_stores_newest_first(self):
        with isolated_app_data():
            cid = "client-1"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "苏韵汽车音响"}])
            material_dir = os.path.join(geo_app.UPLOAD_FOLDER, cid)
            os.makedirs(material_dir, exist_ok=True)
            with open(os.path.join(material_dir, "brand.txt"), "w", encoding="utf-8") as f:
                f.write("品牌资料：苏韵主营汽车音响改装。")
            with open(os.path.join(material_dir, "case.md"), "w", encoding="utf-8") as f:
                f.write("案例资料：扬州车主升级DSP和隔音。")

            client = geo_app.app.test_client()
            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "第一版文章" if len(captured_messages) == 1 else "第二版文章"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                first = client.post(
                    "/api/content/generate",
                    json={"client_id": cid, "opinion": "写一篇面向扬州车主的宣传文章"},
                )
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.get_json()["article"]["content"], "第一版文章")

                second = client.post(
                    "/api/content/generate",
                    json={"client_id": cid, "opinion": "第二版加强施工流程和真实感"},
                )
                self.assertEqual(second.status_code, 200)
                self.assertEqual(second.get_json()["article"]["content"], "第二版文章")

            prompt_payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertIn("苏韵主营汽车音响改装", prompt_payload)
            self.assertIn("扬州车主升级DSP和隔音", prompt_payload)
            self.assertIn("写一篇面向扬州车主的宣传文章", prompt_payload)

            second_payload = json.dumps(captured_messages[1], ensure_ascii=False)
            self.assertIn("第一版文章", second_payload)
            self.assertIn("第二版加强施工流程和真实感", second_payload)

            listing = client.get(f"/api/content/generations?client_id={cid}")
            self.assertEqual(listing.status_code, 200)
            articles = listing.get_json()["articles"]
            self.assertEqual([a["content"] for a in articles], ["第二版文章", "第一版文章"])
            self.assertEqual(articles[0]["model"], "deepseek-chat")

    def test_content_generate_records_configured_model(self):
        with isolated_app_data():
            cid = "client-model"
            geo_app.save(geo_app.F_SETTINGS, {
                "api_key": "test-key",
                "base_url": "https://api.example.com",
                "model": "deepseek-v4-pro",
            })
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Rabbit Dental"}])

            def fake_deepseek_pro(messages, max_tokens=6000):
                return "Generated article"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate",
                    json={"client_id": cid, "opinion": "write a test article"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["article"]["model"], "deepseek-v4-pro")

    def test_content_generate_persists_to_sqlite_history_store(self):
        with isolated_app_data():
            cid = "client-sqlite"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "Client", "brand": "Rabbit Dental"}])

            with patch.object(geo_app, "ai_deepseek_pro", return_value="SQLite article", create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate",
                    json={"client_id": cid, "opinion": "write a sqlite-backed article"},
                )

            db_path = os.path.splitext(geo_app.F_CONTENT_GENERATIONS)[0] + ".sqlite3"
            self.assertEqual(response.status_code, 200)
            self.assertTrue(os.path.exists(db_path))
            self.assertFalse(os.path.exists(geo_app.F_CONTENT_GENERATIONS))
            self.assertEqual(
                [item["content"] for item in geo_app.load_content_session(cid)["articles"]],
                ["SQLite article"],
            )

    def test_content_generate_includes_sample_links_and_selected_top_articles(self):
        with isolated_app_data():
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
            self.assertIn("https://example.com/sample-a", prompt_payload)
            self.assertIn("汽车音响改装Top20样例", prompt_payload)
            self.assertIn("懂车帝", prompt_payload)
            article = response.get_json()["article"]
            self.assertEqual(article["sample_link_count"], 1)
            self.assertEqual(article["selected_article_count"], 1)

    def test_content_generate_uses_explicit_article_type(self):
        with isolated_app_data():
            cid = "client-article-type"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "西安兔博士口腔", "brand": "兔博士"}])
            captured_messages = []

            def fake_deepseek_pro(messages, max_tokens=6000):
                captured_messages.append(messages)
                return "介绍型文章"

            with patch.object(geo_app, "ai_deepseek_pro", side_effect=fake_deepseek_pro, create=True):
                response = geo_app.app.test_client().post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "opinion": "写一篇牙齿矫正服务文章",
                        "article_type": "介绍型",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertIn("文章类型：介绍型", payload)
            self.assertIn("标题必须包含品牌名：兔博士", payload)

    def test_content_generate_history_is_isolated_by_article_type_but_listing_is_combined(self):
        with isolated_app_data():
            cid = "client-history-type"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "西安兔博士口腔", "brand": "兔博士"}])
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
                        "opinion": "写一篇对比型文章",
                        "article_type": "对比型",
                    },
                )
                second = client.post(
                    "/api/content/generate",
                    json={
                        "client_id": cid,
                        "opinion": "写一篇介绍型文章",
                        "article_type": "介绍型",
                    },
                )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            second_payload = json.dumps(captured_messages[1], ensure_ascii=False)
            self.assertIn("写一篇介绍型文章", second_payload)
            self.assertNotIn("对比型旧文章", second_payload)
            self.assertNotIn("写一篇对比型文章", second_payload)

            listing = client.get(f"/api/content/generations?client_id={cid}")
            self.assertEqual(listing.status_code, 200)
            articles = listing.get_json()["articles"]
            self.assertEqual([a["content"] for a in articles], ["介绍型新文章", "对比型旧文章"])

    def test_content_generate_history_is_isolated_by_selected_day(self):
        with isolated_app_data():
            cid = "client-history-day"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "西安兔博士口腔", "brand": "兔博士"}])
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
                        "opinion": "今天重新生成一篇对比型文章",
                        "article_type": "对比型",
                        "history_date": "2026-07-07",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = json.dumps(captured_messages[0], ensure_ascii=False)
            self.assertIn("今天重新生成一篇对比型文章", payload)
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

    def test_content_generation_material_bundle_uses_confirmed_fact_cards(self):
        with isolated_app_data():
            cid = "client-1"
            local_file = os.path.join(geo_app.LOCAL_PDF_FOLDER, "doctor.txt")
            with open(local_file, "w", encoding="utf-8") as f:
                f.write(
                    "兔博士口腔成立于2003年。\n"
                    "李璞医生，隐适美认证医师，从事正畸专科13年。\n"
                    "擅长儿童牙齿矫正、种植牙、根管治疗。\n"
                    "禁止写保证治愈、全市第一、最低价。\n"
                )
            service = geo_app.material_service()
            material = service.import_local_material(cid, "doctor.txt")
            service.parse_material(cid, material["id"])
            service.confirm_material(cid, material["id"], True)

            bundle = geo_app.read_material_bundle(cid)
            messages = geo_app.build_content_generation_messages(
                {"id": cid, "name": "兔博士口腔", "brand": "兔博士口腔"},
                bundle,
                [],
                "写一篇正畸科普文章",
            )

            payload = json.dumps(messages, ensure_ascii=False)
            self.assertIn("【客户事实卡】", payload)
            self.assertIn("李璞", payload)
            self.assertIn("医疗内容需避免效果承诺", payload)
            self.assertIn("保证治愈", payload)
            self.assertIn("资料状态：已确认", payload)

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

    def test_content_generation_defaults_to_comparison_type_prompt(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "西安兔博士口腔", "brand": "兔博士"},
            {"text": "客户资料PDF：兔博士口腔提供牙齿矫正服务。", "files": ["profile.pdf"]},
            [],
            "请参考高频引用文章生成一篇西安牙齿矫正内容",
            selected_articles=[
                {
                    "title": "西安牙齿矫正医院全攻略（2026最新）",
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

    def test_content_generation_can_insert_reference_plugin_subtype(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "西安兔博士口腔", "brand": "兔博士"},
            {"text": "客户资料PDF：兔博士口腔提供牙齿矫正服务。", "files": ["profile.pdf"]},
            [],
            "请参考引用情报插件写一篇内容",
            article_type="对比型",
            article_subtype="本地机构筛选标准型",
            article_subtype_plugin={
                "subtype_name": "本地机构筛选标准型",
                "prompt_text": "先按机构类型和适合人群拆解。",
                "few_shot": "用户问怎么选时，先写选择困难，再按本地老牌机构和连锁标准化机构展开。",
            },
        )

        payload = json.dumps(messages, ensure_ascii=False)
        self.assertIn("【文章子类型：本地机构筛选标准型】", payload)
        self.assertIn("先按机构类型和适合人群拆解。", payload)
        self.assertIn("用户问怎么选时，先写选择困难", payload)
        self.assertNotIn("【攻略对比型展开 few-shot 示例】", payload)

    def test_content_generation_can_insert_reference_plugin_subtype_for_intro_type(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "西安兔博士口腔", "brand": "兔博士"},
            {"text": "客户资料PDF：兔博士口腔提供牙齿矫正服务。", "files": ["profile.pdf"]},
            [],
            "请参考引用情报插件写一篇品牌介绍",
            article_type="介绍型",
            article_subtype="痛点回应介绍型",
            article_subtype_plugin={
                "parent_type": "介绍型",
                "subtype_name": "痛点回应介绍型",
                "prompt_text": "先写用户顾虑，再用品牌资料逐项回应。",
                "few_shot": "用户担心服务是否正规时，先写选择顾虑，再按流程、团队和售后说明品牌如何回应。",
            },
        )

        payload = json.dumps(messages, ensure_ascii=False)
        self.assertIn("文章类型：介绍型", payload)
        self.assertIn("【文章子类型：痛点回应介绍型】", payload)
        self.assertIn("先写用户顾虑，再用品牌资料逐项回应。", payload)
        self.assertIn("用户担心服务是否正规时", payload)

    def test_content_generation_intro_type_requires_brand_title_and_brand_body(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "西安兔博士口腔", "brand": "兔博士"},
            {"text": "客户资料PDF：兔博士口腔提供牙齿矫正服务。", "files": ["profile.pdf"]},
            [],
            "请写一篇兔博士口腔牙齿矫正服务介绍",
            article_type="介绍型",
        )

        payload = json.dumps(messages, ensure_ascii=False)
        self.assertIn("文章类型：介绍型", payload)
        self.assertIn("标题必须包含品牌名：兔博士", payload)
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

    def test_content_generation_does_not_parse_article_type_from_opinion(self):
        messages = geo_app.build_content_generation_messages(
            {"id": "client-1", "name": "西安兔博士口腔", "brand": "兔博士"},
            {"text": "客户资料PDF：兔博士口腔提供牙齿矫正服务。", "files": ["profile.pdf"]},
            [],
            "运营备注里写了介绍型三个字，但没有选择按钮参数",
        )

        payload = json.dumps(messages, ensure_ascii=False)
        self.assertIn("文章类型：对比型", payload)
        self.assertNotIn("标题必须包含品牌名：兔博士", payload)

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
                for i in range(13)
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
            self.assertEqual(len(grouped["deepseek"]), 12)
            self.assertEqual(grouped["deepseek"][0]["title"], "DeepSeek Article 00")
            self.assertEqual(grouped["deepseek"][-1]["title"], "DeepSeek Article 11")
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
                    {"id": "client-1", "name": "西安兔博士口腔", "brand": "兔博士"},
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
                        "brand": "西安兔博士口腔",
                        "brand_mentioned": False,
                        "answer": "兔博士口腔和竞品A被提到。",
                        "refs": [],
                        "mentioned_entities": [
                            {"name": "兔博士口腔", "type": "品牌", "evidence": "兔博士口腔"},
                            {"name": "竞品A", "type": "品牌", "evidence": "竞品A"},
                        ],
                    },
                    {
                        "id": "raw-2",
                        "client_id": "client-1",
                        "today": date,
                        "source_platform": "deepseek",
                        "brand": "西安兔博士口腔",
                        "brand_mentioned": True,
                        "answer": "西安兔博士口腔被提到。",
                        "refs": [],
                        "mentioned_entities": [
                            {"name": "西安兔博士口腔", "type": "门店", "evidence": "西安兔博士口腔"},
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

                queued_result = {
                    "ok": True,
                    "status": "queued",
                    "queued": True,
                }
                with patch("services.node_crawler_bridge.run_node_crawler", side_effect=fake_run_node_crawler), \
                        patch.object(geo_app, "queue_entity_normalize_task", return_value=queued_result) as queue_entities, \
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
                queue_entities.assert_called_once()
                queue_args = queue_entities.call_args.args
                self.assertEqual(queue_args[:3], ("client-1", geo_app.today_str(), payload["task_id"]))
                self.assertEqual(queue_args[3], payload["task_report"])
                auto_entities.assert_not_called()
                self.assertEqual(payload["entity_normalize"], queued_result)

                records = geo_app.load(geo_app.F_RAW_RECORDS, [])
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["source_platform"], "qwen")
                self.assertEqual(records[0]["question"], "测试问题")
                self.assertEqual(records[0]["refs"][0]["platform"], "搜狐")

                report = geo_app.load(payload["task_report"], {})
                self.assertEqual(report["crawler_engine"], "node")
                self.assertEqual(report["node_output_dir"], calls[0]["kwargs"]["output_dir"])
                self.assertEqual(report["status"], "completed")
                self.assertEqual(report["entity_normalize"], queued_result)
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

    def test_reference_intelligence_plugins_can_be_saved_and_loaded(self):
        with isolated_app_data():
            client = geo_app.app.test_client()
            payload = {
                "client_id": "c1",
                "date": "2026-07-08",
                "task_id": "task-1",
                "clusters": [
                    {
                        "cluster_name": "需求场景匹配型",
                        "structure_actions": ["先按用户需求场景拆分"],
                        "abstract_rules": ["具体机构名改写成机构类型"],
                    }
                ],
                "plugins": [
                    {
                        "parent_type": "介绍型",
                        "subtype_name": "需求场景匹配型",
                        "prompt_text": "先按用户需求场景拆分。",
                        "few_shot": "用户问预算时，先列选择标准。",
                        "source_articles": [
                            {
                                "title": "来源文章",
                                "url": "https://example.com/source",
                                "platform": "不展示",
                                "citation_count": 5,
                            }
                        ],
                    }
                ],
            }

            response = client.post("/api/reference_intelligence/plugins", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["ok"])

            response = client.get("/api/reference_intelligence/plugins?client_id=c1&date=2026-07-08&task_id=task-1")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["clusters"][0]["cluster_name"], "需求场景匹配型")
            self.assertEqual(data["plugins"][0]["parent_type"], "介绍型")
            self.assertEqual(data["plugins"][0]["subtype_name"], "需求场景匹配型")
            self.assertEqual(data["plugins"][0]["prompt_text"], "先按用户需求场景拆分。")
            self.assertEqual(data["plugins"][0]["few_shot"], "用户问预算时，先列选择标准。")
            self.assertEqual(data["plugins"][0]["source_articles"], [
                {"title": "来源文章", "url": "https://example.com/source"}
            ])
            self.assertNotIn("platform", data["plugins"][0]["source_articles"][0])
            self.assertNotIn("citation_count", data["plugins"][0]["source_articles"][0])

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

    def test_reference_intelligence_background_job_runs_new_stage_pipeline(self):
        with isolated_app_data():
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {
                    "id": "r1",
                    "client_id": "c1",
                    "today": "2026-07-08",
                    "source_platform": "deepseek",
                    "question": "口腔门店怎么选？",
                    "refs": [
                        {"title": "西安口腔门店选择攻略", "url": "https://example.com/a", "platform": "媒体", "position": 1}
                    ],
                }
            ])
            ai_results = [
                {
                    "parent_type": "对比型",
                    "opening": "先写用户选择困难。",
                    "body": ["再按机构类型分层对比。"],
                    "ending": "最后给选择建议。",
                },
                {
                    "clusters": [
                        {
                            "parent_type": "对比型",
                            "subtype_name": "本地机构筛选标准型",
                            "article_indexes": [1],
                            "shared_structure": {
                                "opening": "先写用户选择困难。",
                                "body": ["再按机构类型分层对比。"],
                                "ending": "最后给选择建议。",
                            },
                        }
                    ]
                },
                {
                    "plugins": [
                        {
                            "cluster_index": 1,
                            "parent_type": "对比型",
                            "subtype_name": "本地机构筛选标准型",
                            "prompt_text": "先按机构类型和适合人群拆解。",
                            "few_shot": "用户问题场景：某地用户不知道怎么选服务机构。",
                        }
                    ]
                },
            ]

            def fake_fetch(url, **kwargs):
                return {
                    "ok": True,
                    "title": "西安口腔门店选择攻略",
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

            loaded = geo_app.app.test_client().get("/api/reference_intelligence/plugins?client_id=c1&date=2026-07-08").get_json()
            self.assertEqual(loaded["clusters"], [])
            self.assertEqual(loaded["plugins"][0]["parent_type"], "对比型")
            self.assertEqual(loaded["plugins"][0]["prompt_text"], "先按机构类型和适合人群拆解。")
            self.assertEqual(loaded["plugins"][0]["source_articles"], [
                {"title": "西安口腔门店选择攻略", "url": "https://example.com/a"}
            ])

            stage_dir = os.path.join(geo_app.F_REFERENCE_INTELLIGENCE, "c1", "2026-07-08")
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "fetched_articles.json")))
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage1_article_structures.json")))
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage2_structure_clusters.json")))
            self.assertTrue(os.path.exists(os.path.join(stage_dir, "stage3_prompt_plugins.json")))

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

            stage1 = geo_app.load(os.path.join(stage_dir, "stage1_article_structures.json"), {})
            self.assertEqual(stage1["total_analyzed"], 2)
            loaded = geo_app.app.test_client().get("/api/reference_intelligence/plugins?client_id=c1&date=2026-07-08").get_json()
            self.assertEqual(loaded["plugins"][0]["source_articles"], [
                {"title": "缓存成功文章", "url": "https://example.com/a"},
                {"title": "补抓成功文章", "url": "https://example.com/c"},
            ])

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
            self.assertIn(88, progresses)
            self.assertNotIn(76, progresses)

    def test_reference_intelligence_prompt_requires_detailed_few_shot_like_comparison_prompt(self):
        prompt = geo_app.build_reference_plugin_prompt([
            {
                "cluster_name": "本地机构筛选标准型",
                "article_pattern": "按机构类型和适合人群拆解。",
                "structure_actions": ["先写选择困难", "再按机构类型分层"],
                "abstract_rules": ["具体机构名改写成机构类型"],
            }
        ])

        self.assertIn("few_shot", prompt)
        self.assertIn("parent_type", prompt)
        self.assertIn("对比型", prompt)
        self.assertIn("介绍型", prompt)
        self.assertIn("参考对比型展开 few-shot 示例的详细程度", prompt)
        self.assertIn("【示例插件：攻略对比型】", prompt)
        self.assertIn("仅作为示例", prompt)
        self.assertIn("不要把示例插件作为输出结果", prompt)
        self.assertIn("多个服务方", prompt)
        self.assertIn("必须归为“对比型”", prompt)
        self.assertIn("正文采用", prompt)
        self.assertIn("3-5", prompt)
        self.assertIn("500-900字", prompt)
        self.assertIn("用户问题场景", prompt)
        self.assertIn("可直接模仿的正文片段", prompt)
        self.assertIn("不能只写一句方法说明", prompt)
        self.assertIn("权威背书强，适合复杂需求", prompt)
        self.assertIn("把A类/B类/C类和A1/A2/A3替换成当前行业里的真实机构类型", prompt)
        self.assertIn("禁止出现具体机构名", prompt)
        self.assertIn("具体文章名", prompt)
        self.assertIn("本地老牌机构", prompt)

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
