import json
import tempfile
import unittest
from pathlib import Path


class ReferenceStage2Tests(unittest.TestCase):
    def test_stage2_clusters_stage1_structures_without_article_body_or_urls(self):
        from scripts.dev_reference_stage2 import run_stage2_cluster_structures

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            input_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-10"
            input_dir.mkdir(parents=True)
            (input_dir / "stage1_article_structures.json").write_text(
                json.dumps({
                    "client_id": "client-1",
                    "date": "2026-07-10",
                    "analyses": [
                        {
                            "url": "https://example.com/a",
                            "citation_count": 3,
                            "title": "A",
                            "parent_type": "对比型",
                            "opening": "先提出选择困难。",
                            "body": ["建立筛选标准。", "逐个讲多个品牌。"],
                            "ending": "给出避坑建议。",
                        },
                        {
                            "url": "https://example.com/b",
                            "citation_count": 2,
                            "title": "B",
                            "parent_type": "对比型",
                            "opening": "先提出行业乱象。",
                            "body": ["列出判断标准。", "用正反样本对比。"],
                            "ending": "提醒实地核验。",
                        },
                    ],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            prompts = []

            def fake_ai_json(prompt, max_tokens):
                prompts.append(prompt)
                return {
                    "clusters": [
                        {
                            "parent_type": "对比型",
                            "subtype_name": "避坑标准验证型",
                            "article_indexes": [1, 2],
                            "shared_structure": {
                                "opening": "先制造选择风险或行业乱象。",
                                "body": ["建立筛选标准。", "用样本逐项验证。"],
                                "ending": "给出核验或避坑建议。",
                            },
                            "prompt_text": "should be ignored",
                        }
                    ]
                }

            result = run_stage2_cluster_structures(
                client_id="client-1",
                date="2026-07-10",
                data_dir=data_dir,
                ai_json_fn=fake_ai_json,
            )

            self.assertEqual(result["clusters"], 1)
            self.assertEqual(len(prompts), 1)
            self.assertIn("子类型名", prompts[0])
            self.assertIn("article_indexes", prompts[0])
            self.assertIn("opening", prompts[0])
            self.assertIn("body", prompts[0])
            self.assertIn("ending", prompts[0])
            self.assertNotIn("https://example.com/a", prompts[0])
            self.assertNotIn("citation_count", prompts[0])
            self.assertNotIn("content", prompts[0])
            self.assertNotIn("最终生成prompt", prompts[0])

            output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(output["client_id"], "client-1")
            self.assertEqual(output["date"], "2026-07-10")
            self.assertEqual(output["total_input"], 2)
            self.assertEqual(output["clusters"][0]["subtype_name"], "避坑标准验证型")
            self.assertEqual(output["clusters"][0]["article_indexes"], [1, 2])
            self.assertNotIn("prompt_text", output["clusters"][0])


if __name__ == "__main__":
    unittest.main()
