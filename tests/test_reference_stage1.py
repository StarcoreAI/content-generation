import json
import tempfile
import unittest
from pathlib import Path


class ReferenceStage1Tests(unittest.TestCase):
    def test_stage1_analyzes_only_fetched_article_title_and_content(self):
        from scripts.dev_reference_stage1 import run_stage1_article_structure

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            input_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-10"
            input_dir.mkdir(parents=True)
            (input_dir / "fetched_articles.json").write_text(
                json.dumps({
                    "client_id": "client-1",
                    "date": "2026-07-10",
                    "articles": [
                        {
                            "ok": True,
                            "url": "https://example.com/a",
                            "platform": "toutiao",
                            "source_title": "Source A",
                            "title": "Article A",
                            "citation_count": 3,
                            "content": "Article A body " * 80,
                            "content_len": len("Article A body " * 80),
                        },
                        {
                            "ok": False,
                            "url": "https://example.com/b",
                            "title": "Article B",
                            "content": "",
                            "content_len": 0,
                        },
                    ],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            prompts = []

            def fake_ai_json(prompt, max_tokens):
                prompts.append(prompt)
                return {
                    "parent_type": "对比型",
                    "opening": "开头先提出用户选择服务方时的信息差和担忧。",
                    "body": [
                        "正文从资质、服务能力、流程和案例几个角度拆解服务方。",
                        "中段穿插不同服务方或不同选择标准的对比。",
                    ],
                    "ending": "结尾用筛选建议和避坑提醒收束。",
                    "ignored_extra": "not needed",
                }

            result = run_stage1_article_structure(
                client_id="client-1",
                date="2026-07-10",
                data_dir=data_dir,
                ai_json_fn=fake_ai_json,
            )

            self.assertEqual(result["analyzed"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(len(prompts), 1)
            self.assertIn("Article A", prompts[0])
            self.assertIn("Article A body", prompts[0])
            self.assertNotIn("https://example.com/a", prompts[0])
            self.assertNotIn("toutiao", prompts[0])
            self.assertNotIn("citation_count", prompts[0])
            self.assertIn('"opening"', prompts[0])
            self.assertIn('"body"', prompts[0])
            self.assertIn('"ending"', prompts[0])
            self.assertIn("如果是对比型", prompts[0])
            self.assertIn("如果是介绍型", prompts[0])
            self.assertIn("多个品牌", prompts[0])
            self.assertIn("也归为对比型", prompts[0])
            self.assertNotIn("structure_points", prompts[0])
            for forbidden in ["家长", "教育", "单招", "升学", "师资", "课程", "学员", "学校"]:
                self.assertNotIn(forbidden, prompts[0])

            output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(output["client_id"], "client-1")
            self.assertEqual(output["date"], "2026-07-10")
            self.assertEqual(output["total_input"], 2)
            self.assertEqual(output["total_analyzed"], 1)
            self.assertEqual(output["total_skipped"], 1)
            self.assertEqual(output["analyses"][0]["url"], "https://example.com/a")
            self.assertEqual(output["analyses"][0]["parent_type"], "对比型")
            self.assertEqual(output["analyses"][0]["opening"], "开头先提出用户选择服务方时的信息差和担忧。")
            self.assertEqual(output["analyses"][0]["body"], [
                "正文从资质、服务能力、流程和案例几个角度拆解服务方。",
                "中段穿插不同服务方或不同选择标准的对比。",
            ])
            self.assertEqual(output["analyses"][0]["ending"], "结尾用筛选建议和避坑提醒收束。")
            self.assertNotIn("structure_points", output["analyses"][0])
            self.assertNotIn("content", output["analyses"][0])


if __name__ == "__main__":
    unittest.main()
