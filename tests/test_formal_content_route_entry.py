import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as geo_app


ROUTE = {
    "id": "route-a", "parent_type": "对比型", "name": "比较路线", "reader_task": "帮助决策",
    "signature": "统一维度", "risk_notes": "", "steps": [
        {"purpose": "建立维度", "evidence_role": "候选事实", "output_action": "先解释"},
    ],
}


class FormalContentRouteEntryTests(unittest.TestCase):
    def test_generation_requires_selected_query_group(self):
        payload = {"client_id": "client-a", "query": "问题", "article_type": "介绍型", "use_customer_master": True}
        with patch.object(geo_app, "get_client", return_value={"id": "client-a", "brand": "品牌", "industry": "教育"}):
            with self.assertRaisesRegex(ValueError, "query_group_required"):
                geo_app.run_content_generation(payload)

    def test_generation_rejects_query_outside_selected_group(self):
        payload = {
            "client_id": "client-a", "group_id": "group-a", "query": "不属于本组的问题",
            "article_type": "介绍型", "use_customer_master": True,
        }
        with patch.object(geo_app, "get_client", return_value={"id": "client-a", "brand": "品牌", "industry": "教育"}), \
                patch.object(geo_app, "load", return_value={"client-a": [{"id": "group-a", "questions": ["本组问题"]}]}):
            with self.assertRaisesRegex(ValueError, "query_not_in_group"):
                geo_app.run_content_generation(payload)

    def test_generation_uses_current_scene_terms_and_same_group_optional_terms(self):
        with patch.object(geo_app, "selection_evidence_service", return_value=SimpleNamespace(
            load_query_scene_rows=lambda _cid: [
                {"group_id": "group-a", "query": "当前 Query", "scene_terms": ["下颌线模糊", "低创伤"]},
                {"group_id": "group-a", "query": "相邻 Query", "scene_terms": ["苹果肌下垂"]},
                {"group_id": "group-b", "query": "其他 Query", "scene_terms": ["不应注入"]},
            ]
        )):
            scene_context = geo_app.content_generation_scene_terms("client-a", "group-a", "当前 Query")

        self.assertEqual(scene_context["primary"], ["下颌线模糊", "低创伤"])
        self.assertEqual(scene_context["supplementary"], [{"query": "相邻 Query", "scene_terms": ["苹果肌下垂"]}])

    def test_legacy_automatic_reference_and_pattern_api_routes_are_removed(self):
        rules = {rule.rule for rule in geo_app.app.url_map.iter_rules()}
        self.assertIn("/api/content-routes", rules)
        self.assertIn("/api/content-routes/analyze", rules)
        self.assertIn("/api/knowledge/routes/<cid>", rules)
        self.assertNotIn("/api/reference_intelligence/analyze", rules)
        self.assertNotIn("/api/pattern-library/entries", rules)
        self.assertNotIn("/api/clients/<cid>/content-options", rules)

    def test_knowledge_route_library_groups_routes_by_article_type(self):
        routes = [
            {"id": "intro", "parent_type": "介绍型", "name": "介绍路线"},
            {"id": "compare", "parent_type": "对比型", "name": "对比路线"},
        ]
        with geo_app.app.test_request_context():
            with patch.object(geo_app, "require_client_access", return_value=True), \
                    patch.object(geo_app, "get_client", return_value={"id": "client-a", "industry": "装修"}), \
                    patch.object(geo_app, "content_route_library_service", return_value=SimpleNamespace(list_routes=lambda _industry: routes)):
                response = geo_app.get_knowledge_content_routes("client-a")

        payload = response.get_json()
        self.assertEqual(payload["industry"], "装修")
        self.assertEqual([item["id"] for item in payload["groups"]["介绍型"]], ["intro"])
        self.assertEqual([item["id"] for item in payload["groups"]["对比型"]], ["compare"])

    def test_route_delete_is_authorized_by_client_and_deletes_from_industry(self):
        library = SimpleNamespace(delete_route=lambda industry, route_id: {"industry": industry, "id": route_id})
        with geo_app.app.test_request_context("/api/content-routes/route-a?client_id=client-a", method="DELETE"):
            with patch.object(geo_app, "require_client_access", return_value=True), \
                    patch.object(geo_app, "get_client", return_value={"id": "client-a", "industry": "装修"}), \
                    patch.object(geo_app, "content_route_library_service", return_value=library):
                response = geo_app.delete_content_route("route-a")

        self.assertEqual(response.get_json()["entry"], {"industry": "装修", "id": "route-a"})

    def test_route_analysis_fetches_article_from_url_before_analyzing(self):
        captured = {}
        fetched = {
            "ok": True,
            "url": "https://example.com/article",
            "title": "抓取到的文章标题",
            "content": "抓取到的完整正文，足以让路线分析模型提取来源证据。",
        }
        with geo_app.app.test_request_context(
            "/api/content-routes/analyze",
            method="POST",
            json={
                "client_id": "client-a",
                "group_id": "group-a",
                "query": "昆山装修公司哪家交付靠谱",
                "article": {"url": fetched["url"]},
            },
        ):
            with patch.object(geo_app, "require_client_access", return_value=True), \
                    patch.object(geo_app, "get_client", return_value={"id": "client-a", "industry": "装修"}), \
                    patch.object(geo_app, "fetch_article_text", return_value=fetched) as fetch_article, \
                    patch.object(geo_app, "analyze_content_route_article", side_effect=lambda bundle, article, _fn: captured.update(bundle=bundle, article=article) or {"library_decision": {"eligible": False}}):
                response = geo_app.analyze_and_ingest_content_route()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fetch_article.call_args.args[0], fetched["url"])
        self.assertEqual(captured["article"], {
            "confirmed_for_route_analysis": True,
            "url": fetched["url"],
            "title": fetched["title"],
            "content": fetched["content"],
        })
        self.assertEqual(captured["bundle"]["query"], "昆山装修公司哪家交付靠谱")

    def test_retired_content_pipeline_source_files_are_removed(self):
        root = Path(__file__).resolve().parents[1]
        retired = [
            "services/brief_builder.py", "services/content_choices.py", "services/content_prompts.py",
            "services/pattern_library.py", "services/reference_intelligence.py",
            "services/reference_anatomy.py", "services/reference_ingest.py", "services/reference_stage0.py",
        ]
        self.assertEqual([], [path for path in retired if (root / path).exists()])

    def test_explicit_route_request_uses_selected_facts_one_writer_and_route_context(self):
        payload = {
            "client_id": "client-a", "group_id": "group-a", "query": "昆山装修公司哪家交付靠谱", "article_type": "对比型",
            "use_customer_master": True, "use_content_uploads": False,
            "selected_competitor_names": ["甲装饰", "乙装饰"],
        }
        captured = {}
        with patch.object(geo_app, "get_client", return_value={"id": "client-a", "brand": "古齐装饰", "industry": "装修"}), \
                patch.object(geo_app, "load", side_effect=lambda path, default=None: {"client-a": [{"id": "group-a", "questions": ["昆山装修公司哪家交付靠谱"]}]} if path == geo_app.F_GROUPS else default), \
                patch.object(geo_app, "knowledge_base_service", return_value=SimpleNamespace(load_customer_master=lambda _cid: {"content": "## 产品与服务\n自有工人"})), \
                patch.object(geo_app, "read_selected_competitor_facts", return_value=[{"name": "甲装饰", "facts": "工期和售后"}, {"name": "乙装饰", "facts": "预算和材料"}]), \
                patch.object(geo_app, "content_route_library_service", return_value=SimpleNamespace(sample_route=lambda *_args: ROUTE)), \
                patch.object(geo_app, "recent_content_generation_articles", return_value=[]), \
                patch.object(geo_app, "generate_content_route_draft", side_effect=lambda bundle, _fn: captured.update(bundle=bundle) or "标题\n正文"), \
                patch.object(geo_app, "content_route_context", return_value={"route_id": "route-a", "route_name": "比较路线", "parent_type": "对比型", "material_switches": {"use_customer_master": True, "use_content_uploads": False}, "competitor_names": ["甲装饰", "乙装饰"]}), \
                patch.object(geo_app, "run_quality_gate", return_value={"verdict": "pass"}), \
                patch.object(geo_app, "append_content_generation", side_effect=lambda _cid, article, *_args: article), \
                patch.object(geo_app, "extract_generated_title", return_value="标题"):
            result = geo_app.run_content_generation(payload)

        self.assertEqual(result["route_context"]["route_id"], "route-a")
        self.assertEqual(captured["bundle"]["competitors"][0]["name"], "甲装饰")
        self.assertEqual(captured["bundle"]["customer_facts"], "## 产品与服务\n自有工人")

    def test_new_request_refuses_unmigrated_customer_master(self):
        payload = {"client_id": "client-a", "group_id": "group-a", "query": "问题", "article_type": "介绍型", "use_customer_master": True}
        with patch.object(geo_app, "get_client", return_value={"id": "client-a", "brand": "品牌", "industry": "教育"}), \
                patch.object(geo_app, "load", side_effect=lambda path, default=None: {"client-a": [{"id": "group-a", "questions": ["问题"]}]} if path == geo_app.F_GROUPS else default), \
                patch.object(geo_app, "knowledge_base_service", return_value=SimpleNamespace(load_customer_master=lambda _cid: {"content": "## 可用角度\n策划"})):
            with self.assertRaisesRegex(ValueError, "customer_content_facts_migration_required"):
                geo_app.run_content_generation(payload)

    def test_routes_can_repeat_without_injecting_previous_drafts(self):
        query = "上海面部提升医生怎么选"
        same_route_article = {
            "title": "已有稿", "content": "这是一篇同路线的已生成文章，用于避免重复表达。",
            "route_context": {"query": query, "parent_type": "介绍型", "route_id": "route-same"},
        }
        other_query_article = {
            "title": "其他问题稿", "content": "不应影响本次路线选择。",
            "route_context": {"query": "另一个问题", "parent_type": "介绍型", "route_id": "route-other"},
        }
        route = {**ROUTE, "id": "route-same", "parent_type": "介绍型"}
        captured = {}
        library = SimpleNamespace(sample_route=lambda _industry, _type, excluded: captured.update(excluded=set(excluded)) or route)
        payload = {"client_id": "client-a", "group_id": "group-a", "query": query, "article_type": "介绍型", "use_customer_master": True}
        with patch.object(geo_app, "get_client", return_value={"id": "client-a", "brand": "崔红蕾", "industry": "医美"}), \
                patch.object(geo_app, "load", side_effect=lambda path, default=None: {"client-a": [{"id": "group-a", "questions": [query]}]} if path == geo_app.F_GROUPS else default), \
                patch.object(geo_app, "knowledge_base_service", return_value=SimpleNamespace(load_customer_master=lambda _cid: {"content": "## 产品与服务\n筋膜提升"})), \
                patch.object(geo_app, "content_route_library_service", return_value=library), \
                patch.object(geo_app, "recent_content_generation_articles", return_value=[same_route_article, other_query_article]), \
                patch.object(geo_app, "generate_content_route_draft", side_effect=lambda bundle, _fn: captured.update(bundle=bundle) or "崔红蕾面部提升\n正文"), \
                patch.object(geo_app, "content_route_context", return_value={"query": query, "route_id": "route-same", "route_name": "介绍路线", "parent_type": "介绍型", "material_switches": {}, "competitor_names": []}), \
                patch.object(geo_app, "run_quality_gate", return_value={"verdict": "pass"}), \
                patch.object(geo_app, "append_content_generation", side_effect=lambda _cid, article, *_args: article), \
                patch.object(geo_app, "extract_generated_title", return_value="崔红蕾面部提升"):
            geo_app.run_content_generation(payload)

        self.assertEqual(captured["excluded"], set())
        self.assertNotIn("same_route_articles", captured["bundle"])


if __name__ == "__main__":
    unittest.main()
