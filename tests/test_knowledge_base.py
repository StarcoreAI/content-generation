import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

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
        "F_REFERENCE_INTELLIGENCE": geo_app.F_REFERENCE_INTELLIGENCE,
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
        "SECRET_KEY": geo_app.app.config.get("SECRET_KEY"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.D = tmp
        geo_app.F_CLIENTS = str(Path(tmp) / "clients.json")
        geo_app.F_USERS = str(Path(tmp) / "users.json")
        geo_app.F_RAW_RECORDS = str(Path(tmp) / "raw_records.json")
        geo_app.F_COMPETITOR_ARTICLE_BODY_HITS = str(Path(tmp) / "competitor_article_body_hits.json")
        geo_app.F_REFERENCE_INTELLIGENCE = str(Path(tmp) / "reference_intelligence")
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
    def test_sync_builds_structured_master_with_both_source_labels(self):
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
                "## 公开背景\n2026 年报名规则以官方通知为准。\n\n"
                "## 信任\n公开页面列有办学许可信息。\n",
                encoding="utf-8",
            )

            service = KnowledgeBaseService(root / "knowledge_base")
            result = service.sync_customer_master("client-a", package_dir)

            content = result["content"]
            for heading in service.CUSTOMER_SECTIONS:
                self.assertIn(f"## {heading}", content)
            self.assertIn("[客户资料解析]\n客户品牌为星河教育。", content)
            self.assertIn("[AI 联网补充]\n2026 年报名规则以官方通知为准。", content)
            self.assertEqual(
                (root / "knowledge_base" / "client-a" / "customer_master.md").read_text(encoding="utf-8"),
                content,
            )

    def test_changed_source_does_not_overwrite_manually_saved_master_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "material_packages" / "client-a"
            package_dir.mkdir(parents=True)
            source = package_dir / "latest_injection.md"
            source.write_text("# 客户资料注入包\n\n## 品牌基础\n旧资料。", encoding="utf-8")
            service = KnowledgeBaseService(root / "knowledge_base")
            service.sync_customer_master("client-a", package_dir)
            service.save_customer_master("client-a", "# 客户总资料\n\n人工确认后的口径。")
            source.write_text("# 客户资料注入包\n\n## 品牌基础\n上游新资料。", encoding="utf-8")

            pending = service.sync_customer_master("client-a", package_dir)

            self.assertTrue(pending["source_update_available"])
            self.assertEqual(pending["content"], "# 客户总资料\n\n人工确认后的口径。")
            refreshed = service.sync_customer_master("client-a", package_dir, overwrite=True)
            self.assertIn("上游新资料。", refreshed["content"])


class CustomerMasterApiTests(unittest.TestCase):
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

    def test_customer_knowledge_get_builds_master_from_parsed_and_web_sources(self):
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
            self.assertIn("[客户资料解析]", body["content"])
            self.assertIn("解析得到的品牌资料。", body["content"])
            self.assertIn("[AI 联网补充]", body["content"])
            self.assertIn("联网补充的公开资料。", body["content"])

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
            self.assertEqual(loaded.get_json()["content"], "# 客户总资料\n\n人工口径")

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
                "# 竞品上传资料\n\n## 竞品乙\n乙机构提供线上答疑。", encoding="utf-8"
            )
            (package_dir / "latest_web_competitors.md").write_text(
                "# 竞品联网扩展\n\n## 竞品丙\n丙机构公开提供免费线下体验。", encoding="utf-8"
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
        self.assertIn('id="knowledgeCustomerContent"', template)
        self.assertNotIn('id="knowledgeCitationSummary"', template)
        self.assertIn("function loadCustomerKnowledge()", script)
        self.assertNotIn("function renderKnowledgeCitationSummary(", script)
        self.assertIn("function syncCustomerKnowledge(", script)
        self.assertIn("function saveCustomerKnowledge()", script)
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

    def test_manual_competitor_master_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = KnowledgeBaseService(Path(tmp) / "knowledge_base")
            service.sync_competitor_master("client-a", "# 竞品总资料\n\n## 竞品甲\n旧资料。")
            service.save_competitor_master("client-a", "# 竞品总资料\n\n## 竞品甲\n人工确认资料。")

            pending = service.sync_competitor_master("client-a", "# 竞品总资料\n\n## 竞品甲\n上游新资料。")

            self.assertTrue(pending["source_update_available"])
            self.assertIn("人工确认资料。", pending["content"])
            replaced = service.sync_competitor_master(
                "client-a", "# 竞品总资料\n\n## 竞品甲\n上游新资料。", overwrite=True
            )
            self.assertIn("上游新资料。", replaced["content"])


if __name__ == "__main__":
    unittest.main()
