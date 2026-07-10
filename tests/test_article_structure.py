import unittest
from unittest.mock import patch

import app as geo_app
from services.article_fetcher import extract_article_text_from_html
from services.article_structure import build_article_structure_prompt, normalize_article_structure_result
from tests.test_app_core import isolated_app_data


class ArticleStructureTests(unittest.TestCase):
    def test_extract_article_text_from_html_prefers_article_paragraphs(self):
        html = """
        <html>
          <head><title>页面标题</title><meta name="description" content="页面摘要"></head>
          <body>
            <nav>导航噪声</nav>
            <article>
              <h1>西安牙齿矫正怎么选</h1>
              <p>开头先讲用户选择困难和价格顾虑。</p>
              <p>正文按照医生资质、机构正规性、复诊便利性进行对比。</p>
            </article>
            <footer>底部噪声</footer>
          </body>
        </html>
        """

        result = extract_article_text_from_html(html, "https://example.com/a")

        self.assertEqual(result["title"], "页面标题")
        self.assertEqual(result["description"], "页面摘要")
        self.assertIn("西安牙齿矫正怎么选", result["content"])
        self.assertIn("医生资质", result["content"])
        self.assertNotIn("导航噪声", result["content"])
        self.assertNotIn("底部噪声", result["content"])

    def test_extract_article_text_from_html_rejects_short_error_page(self):
        result = extract_article_text_from_html(
            "<html><head><title>Not Found</title></head><body><h1>Not Found</h1></body></html>",
            "https://example.com/missing",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "content_too_short")

    def test_normalize_article_structure_result_keeps_flexible_observation_notes(self):
        result = normalize_article_structure_result(
            {
                "argument_pattern": "pain_point_matching",
                "parent_type": "介绍型",
                "structure_notes": "这篇文章不是简单榜单，而是先列用户担心医生、价格、复诊的问题，再逐家说明谁更能解决哪类顾虑。",
                "opening_observation": "开头列出用户痛点。",
                "body_observation": "正文按痛点匹配机构。",
                "generation_implications": "后续生成可以学习这种按顾虑匹配机构的路径。",
            },
            {
                "title": "西安牙齿矫正怎么选",
                "url": "https://example.com/a",
                "platform": "搜狐",
            },
        )

        self.assertEqual(result["title"], "西安牙齿矫正怎么选")
        self.assertEqual(result["parent_type"], "介绍型")
        self.assertEqual(result["argument_pattern"], "pain_point_matching")
        self.assertIn("不是简单榜单", result["structure_notes"])
        self.assertIn("开头列出用户痛点", result["opening_observation"])
        self.assertIn("按痛点匹配机构", result["body_observation"])

    def test_normalize_article_structure_result_keeps_parent_type_to_two_top_level_classes(self):
        result = normalize_article_structure_result(
            {
                "argument_pattern": "scenario_matching",
                "parent_type": "场景匹配型",
                "generation_subtype": "病情场景匹配型",
            },
            {"title": "西安口腔机构怎么选"},
        )

        self.assertEqual(result["parent_type"], "对比型")
        self.assertEqual(result["generation_subtype"], "病情场景匹配型")

    def test_build_article_structure_prompt_asks_for_flexible_notes_not_rigid_schema(self):
        prompt = build_article_structure_prompt({
            "title": "西安牙齿矫正怎么选",
            "platform": "搜狐",
            "url": "https://example.com/a",
            "content": "正文",
        })

        self.assertIn("可以自由补充你认为重要的结构观察", prompt)
        self.assertIn("parent_type", prompt)
        self.assertIn("只能是 对比型 或 介绍型", prompt)
        self.assertIn("子类型请用更具体的中文名字", prompt)
        self.assertNotIn("父类型固定为对比型", prompt)
        self.assertIn("structure_notes", prompt)
        self.assertIn("generation_implications", prompt)
        self.assertNotIn('"content_modules": ["开头痛点", "机构对比"]', prompt)

    def test_extract_article_structure_api_returns_single_article_analysis(self):
        model_result = {
            "argument_pattern": "criteria_verification",
            "structure_notes": "开头讲选择困难，正文用资质、医生、设备、价格逐项验证。",
            "generation_implications": "适合生成标准验证型对比文章。",
        }

        with isolated_app_data(), patch.object(geo_app, "ai_json", return_value=model_result) as ai_json:
            response = geo_app.app.test_client().post(
                "/api/article_structure/extract",
                json={
                    "title": "西安口腔医院怎么选",
                    "url": "https://example.com/guide",
                    "platform": "示例平台",
                    "content": "开头讲选择困难，正文用资质、医生、设备和价格对比机构。",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["analysis"]["argument_pattern"], "criteria_verification")
        self.assertIn("资质、医生", payload["analysis"]["structure_notes"])
        self.assertIn("argument_pattern", ai_json.call_args.args[0])

    def test_extract_article_structure_api_fetches_url_when_content_missing(self):
        model_result = {
            "argument_pattern": "criteria_verification",
            "structure_notes": "先说明用户不知道怎么判断机构，再用资质和医生逐项验证。",
        }

        with (
            isolated_app_data(),
            patch.object(geo_app, "fetch_article_text", return_value={
                "ok": True,
                "title": "网页标题",
                "url": "https://example.com/guide",
                "platform": "",
                "description": "网页摘要",
                "content": "网页正文：开头讲选择困难，正文按资质和医生对比。",
            }) as fetch_article_text,
            patch.object(geo_app, "ai_json", return_value=model_result) as ai_json,
        ):
            response = geo_app.app.test_client().post(
                "/api/article_structure/extract",
                json={
                    "title": "原始标题",
                    "url": "https://example.com/guide",
                    "platform": "示例平台",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["analysis"]["title"], "原始标题")
        self.assertEqual(payload["fetched_article"]["title"], "网页标题")
        self.assertEqual(fetch_article_text.call_args.args[0], "https://example.com/guide")
        self.assertIn("网页正文", ai_json.call_args.args[0])

    def test_fetch_article_structure_api_returns_downloaded_text(self):
        with (
            isolated_app_data(),
            patch.object(geo_app, "fetch_article_text", return_value={
                "ok": True,
                "title": "网页标题",
                "url": "https://example.com/guide",
                "description": "网页摘要",
                "content": "网页正文",
            }) as fetch_article_text,
        ):
            response = geo_app.app.test_client().post(
                "/api/article_structure/fetch",
                json={"url": "https://example.com/guide"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["article"]["content"], "网页正文")
        self.assertEqual(fetch_article_text.call_args.args[0], "https://example.com/guide")

    def test_extract_article_structure_api_requires_title_or_content(self):
        with isolated_app_data():
            response = geo_app.app.test_client().post("/api/article_structure/extract", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "article_required")


if __name__ == "__main__":
    unittest.main()
