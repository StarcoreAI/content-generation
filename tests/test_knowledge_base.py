import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as geo_app
from services.auth import create_user
from services.knowledge_base import KnowledgeBaseService


@contextmanager
def isolated_knowledge_app():
    original = {
        "D": geo_app.D,
        "F_CLIENTS": geo_app.F_CLIENTS,
        "F_USERS": geo_app.F_USERS,
        "F_RAW_RECORDS": geo_app.F_RAW_RECORDS,
        "F_COMPETITOR_ARTICLE_BODY_HITS": geo_app.F_COMPETITOR_ARTICLE_BODY_HITS,
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
        "SECRET_KEY": geo_app.app.config.get("SECRET_KEY"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.D = tmp
        geo_app.F_CLIENTS = str(Path(tmp) / "clients.json")
        geo_app.F_USERS = str(Path(tmp) / "users.json")
        geo_app.F_RAW_RECORDS = str(Path(tmp) / "raw_records.json")
        geo_app.F_COMPETITOR_ARTICLE_BODY_HITS = str(Path(tmp) / "competitor_article_body_hits.json")
        geo_app.app.config["AUTH_DISABLED"] = False
        geo_app.app.config["SECRET_KEY"] = "knowledge-test-secret"
        try:
            yield Path(tmp)
        finally:
            for key, value in original.items():
                if key in {"AUTH_DISABLED", "SECRET_KEY"}:
                    if value is None:
                        geo_app.app.config.pop(key, None)
                    else:
                        geo_app.app.config[key] = value
                else:
                    setattr(geo_app, key, value)


class CustomerMasterTests(unittest.TestCase):
    def test_sync_builds_customer_facts_master_without_web_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text(
                "# 客户资料注入包\n\n"
                "## 品牌基础\n客户品牌为星河教育。\n\n"
                "## 产品/服务\n提供成人学历提升服务。\n\n"
                "## 优势\n有全流程节点提醒。\n",
                encoding="utf-8",
            )
            (package_dir / "latest_web_supplement.md").write_text(
                "# 客户资料联网补充\n\n"
                "## 公开背景\n2026 年报名规则以官方通知为准。\n"
                "来源 URL：https://example.com/info\n"
                "来源性质：官方科普。\n"
                "时间锚点：网页未明确。\n"
                "地区锚点：网页未明确。\n"
                "使用限制：具体报名要求以当年通知为准。\n\n"
                "## 信任\n公开页面列有办学许可信息。\n",
                encoding="utf-8",
            )

            service = KnowledgeBaseService(root / "knowledge_base")
            result = service.sync_customer_master("client-a", package_dir)

            content = result["content"]
            for heading in ("品牌与服务主体", "产品与服务", "特有方法与服务逻辑"):
                self.assertIn(f"## {heading}", content)
            self.assertNotIn("## 服务对象与适配边界", content)
            self.assertIn("客户品牌为星河教育。", content)
            self.assertNotIn("2026 年报名规则以官方通知为准。", content)
            self.assertNotIn("使用限制：具体报名要求以当年通知为准。", content)
            self.assertNotIn("[客户资料解析]", content)
            self.assertNotIn("[AI 联网补充]", content)
            self.assertNotIn("来源 URL", content)
            self.assertNotIn("来源性质", content)
            self.assertNotIn("时间锚点", content)
            self.assertNotIn("地区锚点", content)
            self.assertNotIn("https://", content)
            self.assertEqual(
                (root / "knowledge_base" / "client-a" / "customer_master.md").read_text(encoding="utf-8"),
                content,
            )

    def test_sync_omits_empty_and_operational_customer_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text(
                "# 客户资料解析\n\n"
                "## 品牌与服务主体\n客户品牌为星河教育。\n\n"
                "## 特有方法与服务逻辑\n暂无资料。\n\n"
                "## 运营备注与已确认口径\n暂无资料。\n",
                encoding="utf-8",
            )

            content = KnowledgeBaseService(root / "knowledge_base").sync_customer_master(
                "client-a", package_dir,
            )["content"]

            self.assertIn("## 品牌与服务主体", content)
            self.assertNotIn("## 特有方法与服务逻辑", content)
            self.assertNotIn("## 运营备注与已确认口径", content)

    def test_customer_facts_validation_rejects_editorial_sections(self):
        from services.knowledge_base import validate_customer_content_facts

        result = validate_customer_content_facts(
            "# 客户内容资料\n\n## 产品与服务\n\n提供服务。\n\n## 可用角度\n\n后续可写成咨询入口。"
        )

        self.assertFalse(result["usable_for_generation"])
        self.assertIn("可用角度", result["forbidden_headings"])

    def test_customer_facts_validation_requires_brand_or_product_section(self):
        from services.knowledge_base import validate_customer_content_facts

        result = validate_customer_content_facts("## 信任与可核验信息\n\n已有资质。")

        self.assertFalse(result["usable_for_generation"])

    def test_prepare_then_confirm_customer_fact_migration_does_not_write_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text(
                "# 客户内容资料\n\n## 产品与服务\n\n提供咨询服务。", encoding="utf-8",
            )
            service = KnowledgeBaseService(root / "knowledge_base")
            service.save_customer_master("client-a", "# 客户总资料\n\n## 可用角度\n\n旧策划内容。")

            preview = service.prepare_customer_fact_migration("client-a", package_dir)

            self.assertIn("提供咨询服务", preview["candidate_content"])
            self.assertIn("可用角度", preview["deletion_headings"])
            self.assertIn("旧策划内容", service.load_customer_master("client-a")["content"])
            confirmed = service.confirm_customer_fact_migration("client-a", preview["candidate_content"], package_dir)
            self.assertIn("提供咨询服务", confirmed["content"])

    def test_changed_customer_sources_incrementally_merge_without_overwriting_manual_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            source = package_dir / "latest_injection.md"
            source.write_text("# 客户资料注入包\n\n## 产品与服务\n- 旧资料。", encoding="utf-8")
            service = KnowledgeBaseService(root / "knowledge_base")
            service.sync_customer_master("client-a", package_dir)
            service.save_customer_master("client-a", "# 客户内容资料\n\n## 产品与服务\n\n- 人工确认事实。")
            source.write_text("# 客户资料注入包\n\n## 产品与服务\n- 上游新增事实。", encoding="utf-8")
            (package_dir / "latest_web_supplement.md").write_text(
                "# 客户联网事实候选\n\n## 信任与可核验信息\n\n- 联网新增事实。",
                encoding="utf-8",
            )

            merged = service.sync_customer_master("client-a", package_dir)

            self.assertFalse(merged["source_update_available"])
            self.assertIn("人工确认事实。", merged["content"])
            self.assertIn("上游新增事实。", merged["content"])
            self.assertIn("联网新增事实。", merged["content"])
            self.assertEqual(merged["merged_count"], 2)
            self.assertEqual(service.sync_customer_master("client-a", package_dir)["merged_count"], 0)

    def test_removed_customer_section_stays_suppressed_after_auto_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            source = package_dir / "latest_injection.md"
            source.write_text(
                "# 客户资料\n\n## 产品与服务\n\n- 定制服务。\n\n## 服务对象与适配边界\n\n- 面向首次咨询用户。",
                encoding="utf-8",
            )
            service = KnowledgeBaseService(root / "knowledge_base")
            initial = service.sync_customer_master("client-a", package_dir)["content"]
            service.save_customer_master("client-a", initial.replace(
                "\n\n## 服务对象与适配边界\n\n- 面向首次咨询用户。", "",
            ), removed_sections=["服务对象与适配边界"])
            source.write_text(
                "# 客户资料\n\n## 产品与服务\n\n- 定制服务。\n\n## 服务对象与适配边界\n\n- 面向首次咨询用户。\n- 关注恢复期顾虑。",
                encoding="utf-8",
            )

            merged = service.sync_customer_master("client-a", package_dir)["content"]

        self.assertNotIn("服务对象与适配边界", merged)
        self.assertNotIn("恢复期顾虑", merged)

    def test_removing_last_customer_section_stays_suppressed_after_auto_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text(
                "# 客户资料\n\n## 服务对象与适配边界\n\n- 面向首次咨询用户。",
                encoding="utf-8",
            )
            service = KnowledgeBaseService(root / "knowledge_base")
            initial = service.sync_customer_master("client-a", package_dir)["content"]
            service.save_customer_master("client-a", initial.replace(
                "\n\n## 服务对象与适配边界\n\n- 面向首次咨询用户。", "",
            ), removed_sections=["服务对象与适配边界"])

            merged = service.sync_customer_master("client-a", package_dir)["content"]

        self.assertNotIn("服务对象与适配边界", merged)


class CustomerMasterApiTests(unittest.TestCase):
    def test_generated_customer_and_competitor_web_facts_auto_merge_into_masters(self):
        with isolated_knowledge_app() as root:
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "name": "客户", "industry": "教育"}])
            material_dir = root / "material_packages" / "client-a"
            material_dir.mkdir(parents=True)
            (material_dir / "latest_injection.md").write_text(
                "# 客户资料\n\n## 产品与服务\n\n- 客户原有事实。", encoding="utf-8",
            )

            def customer_expand(*, output_dir, **_kwargs):
                (output_dir / "latest_web_supplement.md").write_text(
                    "# 客户联网事实候选\n\n## 信任与可核验信息\n\n- 客户联网新增事实。",
                    encoding="utf-8",
                )
                return {"ok": True}

            def competitor_expand(*, output_dir, **_kwargs):
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "latest_web_competitors.md").write_text(
                    "# 竞品联网资料补充包\n\n## 竞品甲\n\n- 竞品联网新增事实。",
                    encoding="utf-8",
                )
                return {"ok": True}

            with patch.object(geo_app, "get_settings", return_value={"tavily_api_key": "test"}), \
                    patch.object(geo_app, "get_tavily_api_key", return_value="test"), \
                    patch.object(geo_app, "expand_material_web_package", side_effect=customer_expand), \
                    patch.object(geo_app, "expand_competitor_web_package", side_effect=competitor_expand):
                customer_result = geo_app.run_client_material_web_expansion("client-a")
                competitor_result = geo_app.run_client_competitor_web_expansion("client-a", ["竞品甲"])

            self.assertEqual(customer_result["knowledge_merge"]["merged_count"], 1)
            self.assertEqual(competitor_result["knowledge_merge"]["merged_count"], 1)
            service = geo_app.knowledge_base_service()
            self.assertIn("客户联网新增事实。", service.load_customer_master("client-a")["content"])
            self.assertIn("竞品联网新增事实。", service.load_competitor_master("client-a")["content"])

    def test_quality_policy_edits_common_and_industry_without_client_policy(self):
        with isolated_knowledge_app():
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "other", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{
                "id": "client-a", "owner_username": "owner", "industry": "装修·昆山本地",
            }])
            owner = geo_app.app.test_client()
            other = geo_app.app.test_client()
            owner.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})
            other.post("/api/auth/login", json={"username": "other", "password": "secret-pass"})

            self.assertEqual(owner.put("/api/quality-policy/common", json={"policy": {}}).status_code, 400)
            common = {"banned_words": ["通用词"], "must_do": ["说明依据"], "must_not_do": [], "review_requirements": "检查通用口径。"}
            self.assertEqual(owner.put("/api/quality-policy/common", json={"policy": common, "confirmed_global": True}).status_code, 200)
            industry = {"banned_words": ["装修词"], "must_do": [], "must_not_do": ["承诺零增项"], "review_requirements": "检查装修口径。"}
            self.assertEqual(owner.put("/api/quality-policy/industry/client-a", json={"policy": industry}).status_code, 200)
            self.assertEqual(other.put("/api/quality-policy/industry/client-a", json={"policy": industry}).status_code, 404)

            loaded = owner.get("/api/quality-policy?client_id=client-a").get_json()
            self.assertEqual(loaded["common"]["banned_words"], ["通用词"])
            self.assertEqual(loaded["industry"]["key"], "装修")
            self.assertEqual(loaded["industry"]["policy"]["banned_words"], ["装修词"])

    def test_competitor_cli_experiment_requests_no_cache_write(self):
        from scripts.run_competitor_knowledge_experiment import run_experiment

        calls = []
        fake_app = SimpleNamespace(
            F_CLIENTS="clients.json",
            load=lambda _path, _default: [{"id": "client-a"}],
            load_client_records=lambda _client_id: [
                {"today": "2026-07-26"}, {"today": "2026-07-25"},
            ],
            competitor_knowledge_input=lambda client_id, persist_cache: calls.append(
                (client_id, persist_cache)
            ) or "# 竞品总资料\n",
        )

        result = run_experiment("client-a", fake_app)

        self.assertEqual(calls, [("client-a", False)])
        self.assertEqual(result["source_date"], "2026-07-26")
        self.assertEqual(result["content"], "# 竞品总资料\n")

    def test_competitor_preview_does_not_write_article_cache(self):
        with isolated_knowledge_app() as root:
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "brand": "客户品牌"}])
            geo_app.save(geo_app.F_RAW_RECORDS, [{
                "client_id": "client-a", "today": "2026-07-26", "refs": [
                    {"title": "高频文章", "url": "https://example.com/a"},
                ],
            }])

            geo_app.competitor_knowledge_input(
                "client-a",
                ask_text=lambda _prompt, _max_tokens: "## 竞品甲\n\n资料",
                fetch_fn=lambda _url: {"ok": True, "content": "竞品甲资料"},
                persist_cache=False,
            )

            self.assertFalse((root / "knowledge_base" / "client-a" / "competitor_article_sources.json").exists())

    def test_competitor_sync_uses_top_cited_articles_for_one_prompt(self):
        with isolated_knowledge_app():
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "brand": "客户品牌"}])
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {"client_id": "client-a", "today": "2026-07-26", "refs": [
                    {"title": "高频文章甲", "url": "https://example.com/a"},
                    {"title": "高频文章乙", "url": "https://example.com/b"},
                ], "mentioned_entities": [{"name": "竞品甲"}]},
                {"client_id": "client-a", "today": "2026-07-26", "refs": [
                    {"title": "高频文章甲", "url": "https://example.com/a"},
                ], "mentioned_entities": [{"name": "竞品甲"}]},
            ])
            calls = []

            content = geo_app.competitor_knowledge_input(
                "client-a",
                ask_text=lambda prompt, max_tokens: calls.append((prompt, max_tokens)) or "## 竞品甲\n\n提供到店试听。",
                fetch_fn=lambda url: {"ok": True, "title": "抓取标题", "content": f"{url} 中提到竞品甲。" * 100},
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], 6000)
            self.assertIn("高频文章甲", calls[0][0])
            self.assertIn("高频文章乙", calls[0][0])
            self.assertIn("提供到店试听。", content)

    def test_competitor_sync_splits_detailed_extraction_by_four_articles(self):
        with isolated_knowledge_app():
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "brand": "客户品牌"}])
            geo_app.save(geo_app.F_RAW_RECORDS, [{
                "client_id": "client-a", "today": "2026-07-26", "refs": [
                    {"title": f"文章{index}", "url": f"https://example.com/{index}"}
                    for index in range(1, 6)
                ],
            }])
            calls = []

            def ask_text(prompt, max_tokens):
                calls.append((prompt, max_tokens))
                if "文章5" in prompt:
                    return "## 竞品甲\n\n- 共同事实\n- 第二批事实"
                return "## 竞品甲\n\n- 共同事实\n- 第一批事实"

            content = geo_app.competitor_knowledge_input(
                "client-a",
                ask_text=ask_text,
                fetch_fn=lambda url: {"ok": True, "content": f"{url} 中的竞品甲资料"},
            )

            self.assertEqual(len(calls), 2)
            self.assertTrue(all(max_tokens == 6000 for _, max_tokens in calls))
            self.assertIn("文章1", calls[0][0])
            self.assertIn("文章4", calls[0][0])
            self.assertNotIn("文章5", calls[0][0])
            self.assertIn("文章5", calls[1][0])
            self.assertIn("第一批事实", content)
            self.assertIn("第二批事实", content)
            self.assertEqual(content.count("共同事实"), 1)

    def test_customer_knowledge_get_builds_master_from_parsed_source_only(self):
        with isolated_knowledge_app() as root:
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "owner_username": "owner", "brand": "客户品牌"}])
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text(
                "# 客户资料解析\n\n## 品牌基础\n解析得到的品牌资料。",
                encoding="utf-8",
            )
            (package_dir / "latest_web_supplement.md").write_text(
                "# 客户资料联网补充\n\n## 公开背景\n联网补充的公开资料。",
                encoding="utf-8",
            )
            client = geo_app.app.test_client()
            client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})

            response = client.get("/api/knowledge/customer/client-a")

            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertNotIn("citation_summary", body)
            self.assertIn("解析得到的品牌资料。", body["content"])
            self.assertNotIn("联网补充的公开资料。", body["content"])
            self.assertNotIn("[客户资料解析]", body["content"])
            self.assertNotIn("[AI 联网补充]", body["content"])

    def test_owner_can_sync_save_and_read_customer_master(self):
        with isolated_knowledge_app() as root:
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "owner_username": "owner"}])
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text(
                "# 客户资料注入包\n\n## 品牌基础\n星河教育。", encoding="utf-8"
            )
            client = geo_app.app.test_client()
            self.assertEqual(
                client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"}).status_code,
                200,
            )

            synced = client.post("/api/knowledge/customer/client-a/sync", json={})

            self.assertEqual(synced.status_code, 200)
            self.assertIn("星河教育。", synced.get_json()["content"])
            saved = client.put("/api/knowledge/customer/client-a", json={"content": "# 客户总资料\n\n人工口径"})
            self.assertEqual(saved.status_code, 200)
            loaded = client.get("/api/knowledge/customer/client-a")
            self.assertEqual(loaded.status_code, 200)
            self.assertIn("人工口径", loaded.get_json()["content"])
            self.assertIn("星河教育。", loaded.get_json()["content"])

    def test_other_operator_gets_404_for_customer_master(self):
        with isolated_knowledge_app() as root:
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "other", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "owner_username": "owner"}])
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text("# 客户资料注入包", encoding="utf-8")
            owner = geo_app.app.test_client()
            other = geo_app.app.test_client()
            owner.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})
            other.post("/api/auth/login", json={"username": "other", "password": "secret-pass"})
            self.assertEqual(owner.post("/api/knowledge/customer/client-a/sync", json={}).status_code, 200)

            response = other.get("/api/knowledge/customer/client-a")

            self.assertEqual(response.status_code, 404)

    def test_owner_can_build_competitor_master_from_daily_hits_and_upload(self):
        with isolated_knowledge_app() as root:
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "owner_username": "owner", "brand": "客户品牌"}])
            geo_app.save(geo_app.F_RAW_RECORDS, [{
                "client_id": "client-a", "today": "2026-07-26", "brand": "客户品牌",
                "mentioned_entities": [{"name": "竞品甲", "type": "品牌", "evidence": "竞品甲"}],
            }])
            geo_app.save(geo_app.F_COMPETITOR_ARTICLE_BODY_HITS, [{
                "client_id": "client-a", "date": "2026-07-26", "task_id": "", "group_id": "", "platform": "",
                "body_hits": [{"status": "matched", "title": "对比文章", "matched_entities": ["竞品甲"], "evidence": "竞品甲有到店试听。"}],
            }])
            package_dir = root / "competitor_material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_upload_competitors.md").write_text(
                "# 竞品上传资料\n\n## 竞品乙\n乙机构提供线上答疑。\n"
                "来源依据：上传资料。\n来源 URL：https://example.com/b。\n", encoding="utf-8"
            )
            (package_dir / "latest_web_competitors.md").write_text(
                "# 竞品联网扩展\n\n## 竞品丙\n丙机构公开提供免费线下体验。\n"
                "来源性质：机构官方科普。\n使用限制：以实际服务为准。", encoding="utf-8"
            )
            client = geo_app.app.test_client()
            client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})

            response = client.post("/api/knowledge/competitors/client-a/sync", json={})

            self.assertEqual(response.status_code, 200)
            content = response.get_json()["content"]
            self.assertIn("## 竞品甲", content)
            self.assertIn("竞品甲有到店试听。", content)
            self.assertIn("## 竞品乙", content)
            self.assertIn("乙机构提供线上答疑。", content)
            self.assertIn("## 竞品丙", content)
            self.assertIn("丙机构公开提供免费线下体验。", content)
            self.assertIn("使用限制：以实际服务为准。", content)
            self.assertNotIn("来源依据", content)
            self.assertNotIn("来源 URL", content)
            self.assertNotIn("来源性质", content)
            self.assertNotIn("https://", content)

    def test_daily_competitor_extraction_forwards_current_scope(self):
        with isolated_knowledge_app():
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "owner_username": "owner"}])
            captured = {}
            original = geo_app.competitor_knowledge_input
            geo_app.competitor_knowledge_input = lambda client_id, **scope: captured.update(
                {"client_id": client_id, **scope}
            ) or "# 竞品总资料\n"
            try:
                client = geo_app.app.test_client()
                client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})
                response = client.post("/api/knowledge/competitors/client-a/sync", json={
                    "date": "2026-07-26", "group_id": "group-a", "task_id": "task-a", "platform": "qwen",
                })
            finally:
                geo_app.competitor_knowledge_input = original

            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured, {
                "client_id": "client-a", "date_str": "2026-07-26", "group_id": "group-a",
                "task_id": "task-a", "platform": "qwen",
            })

    def test_competitor_knowledge_get_initializes_from_existing_materials(self):
        with isolated_knowledge_app() as root:
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "owner_username": "owner"}])
            package_dir = root / "competitor_material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_upload_competitors.md").write_text(
                "# 竞品上传资料\n\n## 竞品甲\n上传解析得到的资料。", encoding="utf-8"
            )
            (package_dir / "latest_web_competitors.md").write_text(
                "# 竞品联网扩展\n\n## 竞品乙\n联网扩展得到的资料。\n"
                "来源 URL：https://example.com/b。", encoding="utf-8"
            )
            client = geo_app.app.test_client()
            client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})

            response = client.get("/api/knowledge/competitors/client-a")

            self.assertEqual(response.status_code, 200)
            content = response.get_json()["content"]
            self.assertIn("上传解析得到的资料。", content)
            self.assertIn("联网扩展得到的资料。", content)
            self.assertNotIn("来源 URL", content)
            self.assertNotIn("https://", content)

            client.put(
                "/api/knowledge/competitors/client-a",
                json={"content": "# 竞品总资料\n\n## 竞品乙\n人工确认事实。"},
            )
            (package_dir / "latest_web_competitors.md").write_text(
                "# 竞品联网扩展\n\n## 竞品乙\n联网刷新新增事实。",
                encoding="utf-8",
            )
            refreshed = client.get("/api/knowledge/competitors/client-a")

            self.assertIn("人工确认事实。", refreshed.get_json()["content"])
            self.assertIn("联网刷新新增事实。", refreshed.get_json()["content"])

    def test_competitor_master_omits_short_placeholder_sections(self):
        with isolated_knowledge_app() as root:
            create_user(geo_app.F_USERS, "owner", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-a", "owner_username": "owner"}])
            package_dir = root / "competitor_material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            (package_dir / "latest_upload_competitors.md").write_text(
                "# 竞品上传资料\n\n## 竞品甲\n暂无可合并资料。\n\n"
                "## 竞品乙\n乙机构提供线上答疑。",
                encoding="utf-8",
            )

            client = geo_app.app.test_client()
            client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})
            response = client.get("/api/knowledge/competitors/client-a")

            content = response.get_json()["content"]
            self.assertNotIn("## 竞品甲", content)
            self.assertIn("## 竞品乙", content)


class CustomerKnowledgeUiTests(unittest.TestCase):
    def test_customer_knowledge_page_only_uses_knowledge_api(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("navTo('knowledge'", template)
        self.assertIn('data-nav="knowledge"', template)
        self.assertIn("function openKnowledge", script)
        self.assertNotIn("客户知识库</div>", template.split('<div class="sidebar">', 1)[1].split('<div class="s-nav" onclick="navTo(\'content\'', 1)[0])
        self.assertIn('id="page-knowledge-customer"', template)
        self.assertIn('id="knowledgeCustomerSections"', template)
        self.assertIn('id="knowledgeCustomerSections" style="display:grid;grid-template-columns:1fr', template)
        self.assertNotIn('id="knowledgeCustomerContent"', template)
        self.assertIn('id="page-knowledge-quality"', template)
        self.assertIn('id="qualityCommonBanned"', template)
        self.assertNotIn('id="knowledgeCitationSummary"', template)
        self.assertIn("function loadCustomerKnowledge()", script)
        self.assertIn("function renderCustomerKnowledgeSections(", script)
        self.assertIn("function fitKnowledgeEditorHeight(", script)
        self.assertIn("function shouldHideKnowledgeSection(", script)
        self.assertNotIn("function renderKnowledgeCitationSummary(", script)
        self.assertIn("navTo('knowledge-' + section, null)", script)
        self.assertNotIn("function syncCustomerKnowledge(", script)
        self.assertIn("function saveCustomerKnowledge()", script)
        self.assertIn("移除整节", script)
        self.assertIn("card.remove()", script)
        self.assertIn("removedCustomerKnowledgeSections", script)
        self.assertIn("removed_sections", script)
        self.assertIn("/api/knowledge/customer/", script)
        page = template.split('id="page-knowledge-customer"', 1)[1].split('id="page-content"', 1)[0]
        self.assertNotIn("generateContentArticle", page)

    def test_competitor_knowledge_page_is_independent_and_sectioned_by_name(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("openKnowledge('competitors')", template)
        self.assertIn('id="page-knowledge-competitors"', template)
        self.assertIn('id="knowledgeCompetitorSections"', template)
        self.assertIn("function loadCompetitorKnowledge()", script)
        self.assertIn("function renderCompetitorKnowledgeSections(", script)
        self.assertIn("/api/knowledge/competitors/", script)
        page = template.split('id="page-knowledge-competitors"', 1)[1].split('id="page-content"', 1)[0]
        self.assertNotIn("expandCompetitorWeb", page)


class CompetitorMasterTests(unittest.TestCase):
    def test_high_frequency_sources_use_global_top_articles_and_cache_first(self):
        from services.competitor_knowledge import collect_high_frequency_article_sources

        records = [
            {"refs": [{"title": "文章甲", "url": "https://example.com/a"}, {"title": "文章乙", "url": "https://example.com/b"}]},
            {"refs": [{"title": "文章甲", "url": "https://example.com/a"}]},
            {"refs": [{"title": "文章丙", "url": "https://example.com/c"}]},
        ]
        calls = []

        sources = collect_high_frequency_article_sources(
            records,
            {"https://example.com/a": {"ok": True, "title": "缓存文章甲", "content": "甲正文" * 120}},
            lambda url: calls.append(url) or {"ok": True, "title": "抓取文章", "content": "乙正文" * 120},
            limit=2,
        )

        self.assertEqual([item["url"] for item in sources], ["https://example.com/a", "https://example.com/b"])
        self.assertEqual(sources[0]["citation_count"], 2)
        self.assertEqual(sources[0]["fetch_method"], "cache")
        self.assertEqual(calls, ["https://example.com/b"])

    def test_high_frequency_prompt_only_uses_fixed_article_sources(self):
        from services.competitor_knowledge import build_high_frequency_competitor_prompt

        prompt = build_high_frequency_competitor_prompt(
            ["竞品甲"],
            [{"title": "高频文章", "url": "https://example.com/a", "citation_count": 8, "content": "竞品甲提供到店试听。"}],
        )

        self.assertIn("累计引用次数最高的 12 篇", prompt)
        self.assertIn("只使用以下文章正文", prompt)
        self.assertIn("竞品甲提供到店试听。", prompt)
        self.assertIn("不使用外部知识", prompt)
        self.assertIn("## 真实竞品名称", prompt)
        self.assertIn("主要介绍或比较对象", prompt)
        self.assertIn("医院只是所属关系", prompt)
        self.assertIn("老师只是学校信息", prompt)

    def test_detailed_competitor_prompt_requires_an_overview_before_facts(self):
        from services.competitor_knowledge import build_high_frequency_competitor_prompt

        prompt = build_high_frequency_competitor_prompt(
            ["竞品甲"],
            [{"title": "高频文章", "url": "https://example.com/a", "content": "竞品甲提供整装服务。"}],
        )

        self.assertIn("先写 1–3 句客观概述", prompt)
        self.assertIn("概述后再用条目列出", prompt)

    def test_merging_high_frequency_output_keeps_one_section_per_competitor(self):
        from services.competitor_knowledge import merge_competitor_master_markdown

        content = merge_competitor_master_markdown(
            "## 竞品甲\n\n提供到店试听。\n\n## 竞品乙\n\n提供线上答疑。",
            "# 竞品总资料\n\n## 竞品甲\n\n已有上传资料。",
        )

        self.assertEqual(content.count("## 竞品甲"), 1)
        self.assertIn("提供到店试听。", content)
        self.assertIn("已有上传资料。", content)
        self.assertIn("## 竞品乙", content)

    def test_competitor_input_is_grouped_by_real_entity_name(self):
        from services.competitor_knowledge import build_competitor_master_input

        content = build_competitor_master_input(
            ["竞品甲", "竞品乙"],
            [{
                "status": "matched",
                "title": "本地机构对比文章",
                "url": "https://example.com/article",
                "matched_entities": ["竞品甲"],
                "evidence": "竞品甲提供周末咨询与到店试听。",
            }],
            "# 竞品上传资料\n\n## 竞品乙\n乙机构提供线上答疑服务。",
        )

        self.assertEqual(content.count("## 竞品甲"), 1)
        self.assertEqual(content.count("## 竞品乙"), 1)
        self.assertIn("竞品甲提供周末咨询与到店试听。", content)
        self.assertIn("乙机构提供线上答疑服务。", content)
        self.assertNotIn("竞品 A", content)
        self.assertNotIn("客户品牌", content)

    def test_changed_competitor_facts_incrementally_merge_without_overwriting_manual_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = KnowledgeBaseService(Path(tmp) / "knowledge_base")
            service.sync_competitor_master("client-a", "# 竞品总资料\n\n## 竞品甲\n旧资料。")
            service.save_competitor_master("client-a", "# 竞品总资料\n\n## 竞品甲\n人工确认资料。")

            merged = service.sync_competitor_master("client-a", "# 竞品总资料\n\n## 竞品甲\n上游新资料。")

            self.assertFalse(merged["source_update_available"])
            self.assertIn("人工确认资料。", merged["content"])
            self.assertIn("上游新资料。", merged["content"])
            self.assertEqual(merged["merged_count"], 1)
            self.assertEqual(service.sync_competitor_master("client-a", "# 竞品总资料\n\n## 竞品甲\n上游新资料。")["merged_count"], 0)


if __name__ == "__main__":
    unittest.main()
