import json
import tempfile
import unittest
from pathlib import Path


class ReferenceStage3Tests(unittest.TestCase):
    def test_stage3_does_not_publish_live_output_by_default(self):
        from scripts.dev_reference_stage3 import run_stage3_prompt_plugins

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            input_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-10"
            input_dir.mkdir(parents=True)
            (input_dir / "stage2_structure_clusters.json").write_text(
                json.dumps({
                    "clusters": [
                        {
                            "parent_type": "x",
                            "subtype_name": "x",
                            "article_indexes": [1],
                            "shared_structure": {},
                        }
                    ],
                }),
                encoding="utf-8",
            )

            result = run_stage3_prompt_plugins(
                client_id="client-1",
                date="2026-07-10",
                data_dir=data_dir,
                ai_json_fn=lambda prompt, max_tokens: {
                    "plugins": [
                        {
                            "cluster_index": 1,
                            "parent_type": "x",
                            "subtype_name": "x",
                            "prompt_text": "write this way",
                            "few_shot": "example",
                        }
                    ]
                },
            )

            self.assertTrue(Path(result["output_path"]).exists())
            self.assertNotIn("live_output_path", result)
            self.assertFalse((data_dir / "reference_intelligence" / "client-1" / "2026-07-10_all.json").exists())

    def test_stage3_turns_clusters_into_prompt_plugins_without_source_indexes_in_prompt(self):
        from scripts.dev_reference_stage3 import run_stage3_prompt_plugins

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            input_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-10"
            input_dir.mkdir(parents=True)
            (input_dir / "stage2_structure_clusters.json").write_text(
                json.dumps({
                    "client_id": "client-1",
                    "date": "2026-07-10",
                    "clusters": [
                        {
                            "parent_type": "对比型",
                            "subtype_name": "避坑标准验证型",
                            "article_indexes": [1, 2],
                            "shared_structure": {
                                "opening": "先制造选择风险。",
                                "body": ["建立筛选标准。", "用样本逐项验证。"],
                                "ending": "给出核验建议。",
                            },
                        }
                    ],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            (input_dir / "fetched_articles.json").write_text(
                json.dumps({
                    "articles": [
                        {
                            "title": "来源文章一",
                            "url": "https://example.com/one",
                            "platform": "不展示",
                            "citation_count": 9,
                        },
                        {
                            "title": "403 Forbidden",
                            "source_title": "来源文章二",
                            "url": "https://example.com/two",
                            "platform": "不展示",
                            "citation_count": 3,
                        },
                    ]
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            prompts = []
            max_tokens_seen = []

            def fake_ai_json(prompt, max_tokens):
                prompts.append(prompt)
                max_tokens_seen.append(max_tokens)
                return {
                    "plugins": [
                        {
                            "cluster_index": 1,
                            "parent_type": "对比型",
                            "subtype_name": "避坑标准验证型",
                            "prompt_text": "先提出用户面临的选择风险，再建立3-5条筛选标准，并用正反样本逐项验证。",
                            "few_shot": "写法示例：先写用户为什么难选；再列标准；最后给核验动作。",
                            "ignored": "not needed",
                        }
                    ]
                }

            result = run_stage3_prompt_plugins(
                client_id="client-1",
                date="2026-07-10",
                data_dir=data_dir,
                ai_json_fn=fake_ai_json,
                publish=True,
            )

            self.assertEqual(result["plugins"], 1)
            self.assertEqual(len(prompts), 1)
            self.assertLessEqual(max_tokens_seen[0], 6000)
            self.assertIn("第三阶段", prompts[0])
            self.assertIn("prompt_text", prompts[0])
            self.assertIn("few_shot", prompts[0])
            self.assertIn("简洁凝练", prompts[0])
            self.assertIn("结构完整", prompts[0])
            self.assertIn("不要追求示例插件的篇幅", prompts[0])
            self.assertIn("180-350字", prompts[0])
            self.assertIn("输出前自检", prompts[0])
            self.assertIn("允许保留当前行业", prompts[0])
            self.assertIn("可以使用 A/B/C", prompts[0])
            self.assertIn("禁止输出未核实的具体数字", prompts[0])
            self.assertIn("具体比例、价格、人数、年份、排名", prompts[0])
            self.assertIn("禁止出现具体品牌", prompts[0])
            self.assertIn("不需要强行泛化成所有行业", prompts[0])
            self.assertIn("【示例插件：攻略对比型】", prompts[0])
            self.assertIn("仅作为示例", prompts[0])
            self.assertIn("不要把示例插件作为输出结果", prompts[0])
            self.assertIn("正文采用", prompts[0])
            self.assertIn("攻略对比型展开 few-shot 示例", prompts[0])
            self.assertIn("多个服务方", prompts[0])
            self.assertIn("必须归为“对比型”", prompts[0])
            self.assertNotIn("article_indexes", prompts[0])
            self.assertNotIn("https://example.com", prompts[0])

            output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(output["client_id"], "client-1")
            self.assertEqual(output["date"], "2026-07-10")
            self.assertEqual(output["total_clusters"], 1)
            self.assertEqual(output["total_plugins"], 1)
            plugin = output["plugins"][0]
            self.assertEqual(plugin["parent_type"], "对比型")
            self.assertEqual(plugin["subtype_name"], "避坑标准验证型")
            self.assertIn("筛选标准", plugin["prompt_text"])
            self.assertIn("写法示例", plugin["few_shot"])
            self.assertEqual(plugin["source_article_indexes"], [1, 2])
            self.assertNotIn("ignored", plugin)

            live_output = json.loads(Path(result["live_output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["live_output_path"], str(data_dir / "reference_intelligence" / "client-1" / "2026-07-10_all.json"))
            self.assertEqual(live_output["client_id"], "client-1")
            self.assertEqual(live_output["date"], "2026-07-10")
            self.assertEqual(live_output["clusters"], [])
            self.assertEqual(live_output["source_articles"], [])
            self.assertEqual(live_output["plugins"][0]["parent_type"], "对比型")
            self.assertEqual(live_output["plugins"][0]["subtype_name"], "避坑标准验证型")
            self.assertIn("筛选标准", live_output["plugins"][0]["prompt_text"])
            self.assertNotIn("source_article_indexes", live_output["plugins"][0])
            self.assertEqual(live_output["plugins"][0]["source_articles"], [
                {"title": "来源文章一", "url": "https://example.com/one"},
                {"title": "来源文章二", "url": "https://example.com/two"},
            ])
            self.assertNotIn("platform", live_output["plugins"][0]["source_articles"][0])
            self.assertNotIn("citation_count", live_output["plugins"][0]["source_articles"][0])
            for forbidden in ["教育", "单招", "升学", "师资", "学员", "学校", "家长", "考生"]:
                self.assertNotIn(forbidden, prompts[0])
                self.assertNotIn(forbidden, plugin["prompt_text"])
                self.assertNotIn(forbidden, plugin["few_shot"])


if __name__ == "__main__":
    unittest.main()
