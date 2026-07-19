import tempfile
import unittest
from pathlib import Path


class CompetitorMaterialsTests(unittest.TestCase):
    def test_build_search_queries_uses_manual_qualifier_before_client_industry(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(
            ["第一竞品", "第二竞品"],
            {"industry": "教育"},
            qualifier="成人学历提升",
        )

        self.assertEqual(
            queries,
            [
                {"competitor": "第一竞品", "query": "第一竞品 成人学历提升"},
                {"competitor": "第二竞品", "query": "第二竞品 成人学历提升"},
            ],
        )

    def test_build_search_queries_falls_back_to_client_industry(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(["第一竞品"], {"industry": "汽车音响"}, qualifier="")

        self.assertEqual(queries, [{"competitor": "第一竞品", "query": "第一竞品 汽车音响"}])

    def test_build_search_queries_prefers_client_category_before_industry(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(
            ["第一竞品"],
            {"category": "成人学历提升", "industry": "教育"},
            qualifier="",
        )

        self.assertEqual(queries, [{"competitor": "第一竞品", "query": "第一竞品 成人学历提升"}])

    def test_build_search_queries_uses_competitor_name_without_scope(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(["第一竞品"], {}, qualifier="")

        self.assertEqual(queries, [{"competitor": "第一竞品", "query": "第一竞品"}])

    def test_analyze_upload_package_writes_markdown_with_competitor_prompt_rules(self):
        from services.competitor_materials import analyze_competitor_upload_package

        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "package"
            output_dir = Path(tmp) / "out"
            package_dir.mkdir()
            (package_dir / "competitors.txt").write_text(
                "第一竞品主打本地服务。\n第二竞品公开资料强调流程透明。",
                encoding="utf-8",
            )
            prompts = []

            def ask_text(prompt, max_tokens):
                prompts.append(prompt)
                return "# 竞品上传资料整理包\n\n## 第一竞品\n- 主打本地服务。"

            result = analyze_competitor_upload_package(
                package_dir,
                output_dir,
                ["第一竞品", "第二竞品"],
                ask_text=ask_text,
            )

        self.assertTrue(result["ok"])
        self.assertIn("第一竞品", result["markdown"])
        self.assertEqual(len(prompts), 1)
        self.assertIn("竞品名称必须使用资料中出现的真实品牌名", prompts[0])
        self.assertIn("无法确定是否同一主体时，直接分开整理，不要猜测关系", prompts[0])
        self.assertNotIn("疑似同主体", prompts[0])

    def test_expand_web_package_uses_fixed_queries_and_two_sources_per_competitor(self):
        from services.competitor_materials import expand_competitor_web_package

        calls = []
        prompts = []

        def search_fn(query):
            calls.append(query)
            name = query.split()[0]
            return [
                {"title": f"{name} 官网", "url": f"https://example.com/{name}/1", "content": f"{name} 服务介绍，公开页面包含足够正文内容。"},
                {"title": f"{name} 业务", "url": f"https://example.com/{name}/2", "content": f"{name} 业务范围，公开页面包含足够正文内容。"},
                {"title": f"{name} 多余", "url": f"https://example.com/{name}/3", "content": f"{name} 多余来源，公开页面包含足够正文内容。"},
            ]

        def ask_text(prompt, max_tokens):
            prompts.append(prompt)
            return "# 竞品联网资料补充包\n\n## 第一竞品\n- 页面介绍。"

        with tempfile.TemporaryDirectory() as tmp:
            result = expand_competitor_web_package(
                {"industry": "教育"},
                ["第一竞品", "第二竞品"],
                qualifier="成人学历提升",
                output_dir=Path(tmp),
                ask_text=ask_text,
                search_fn=search_fn,
                fetched_at="2026-07-16 12:00",
            )

        self.assertEqual(calls, ["第一竞品 成人学历提升", "第二竞品 成人学历提升"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["source_count"], 4)
        self.assertEqual([item["source_count"] for item in result["competitors"]], [2, 2])
        self.assertIn("每个竞品必须使用真实竞品名称", prompts[0])
        self.assertNotIn("生成检索词", prompts[0])


if __name__ == "__main__":
    unittest.main()
