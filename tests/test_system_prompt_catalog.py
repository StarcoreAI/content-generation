import unittest
from pathlib import Path

import app as geo_app
from services.system_prompt_catalog import list_system_prompts


class SystemPromptCatalogTests(unittest.TestCase):
    def test_catalog_has_content_and_material_templates_with_placeholders(self):
        prompts = list_system_prompts()
        names = {item["name"] for item in prompts}
        self.assertTrue({"介绍型内容生成", "对比型内容生成", "客户资料解析"}.issubset(names))
        self.assertTrue(all(item["content"].strip() for item in prompts))
        self.assertTrue(all("真实客户名称" not in item["content"] for item in prompts))
        self.assertIn("{{客户品牌}}", next(item["content"] for item in prompts if item["name"] == "介绍型内容生成"))

    def test_read_only_api_returns_catalog_and_has_no_write_route(self):
        previous = geo_app.app.config.get("AUTH_DISABLED")
        geo_app.app.config["AUTH_DISABLED"] = True
        try:
            client = geo_app.app.test_client()
            response = client.get("/api/system-prompts")
            self.assertEqual(response.status_code, 200)
            self.assertIn("prompts", response.get_json())
            self.assertEqual(client.post("/api/system-prompts", json={}).status_code, 405)
        finally:
            geo_app.app.config["AUTH_DISABLED"] = previous

    def test_knowledge_page_has_read_only_prompt_catalog_without_download(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="page-knowledge-system-prompts"', template)
        self.assertIn("openKnowledge('system-prompts')", template)
        self.assertIn("function loadSystemPromptCatalog()", script)
        self.assertIn("/api/system-prompts", script)
        self.assertNotIn("downloadKnowledgeDocx('system-prompts')", template)
