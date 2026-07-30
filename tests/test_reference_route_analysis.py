import json
import tempfile
import unittest
from pathlib import Path


class ReferenceRouteAnalysisTests(unittest.TestCase):
    def test_valid_introduction_route_keeps_verified_evidence_and_complete_route(self):
        from services.reference_route_analysis import (
            analyze_reference_route_article,
            build_route_analysis_prompt,
        )

        excerpt = "通过分层评估松弛程度，再匹配相应的提升方案，避免把所有需求都归为同一种处理方式。"
        article = {
            "url": "https://example.com/article",
            "title": "示例文章",
            "content": "开头说明。" + excerpt + "结尾说明。",
            "support_points": ["运营已人工核对：文章有分层评估与方案匹配信息"],
        }
        bundle = {
            "query": "想做自然一点的面部提升，如何判断方案是否合适？",
            "final_entities": ["示例医生"],
        }
        prompts = []

        def fake_ai_json(prompt, max_tokens):
            prompts.append((prompt, max_tokens))
            return {
                "classification": "介绍型",
                "source_evidence": [{
                    "role": "方案适配依据",
                    "finding": "先区分需求程度，再说明方案适配关系。",
                    "excerpt": excerpt,
                }],
                "route": {
                    "name": "问题分层后的适配说明路线",
                    "parent_type": "介绍型",
                    "reader_task": "帮助读者把模糊需求转成可核验的判断条件。",
                    "steps": [
                        {
                            "purpose": "还原读者的决策困惑。",
                            "evidence_role": "问题背景",
                            "output_action": "用非承诺性的语言界定选择范围。",
                        },
                        {
                            "purpose": "给出可核验的方案适配条件。",
                            "evidence_role": "方案适配依据",
                            "output_action": "把条件与可验证信息一一对应。",
                        },
                    ],
                    "signature": "以判断条件串联解释，不用单一结论替代读者决策。",
                    "risk_notes": "不得把来源中的个案宣传改写为普遍结论。",
                },
                "library_decision": {"reason": "路线完整，且证据能回到原文核对。"},
            }

        prompt = build_route_analysis_prompt(bundle, article)
        result = analyze_reference_route_article(bundle, article, fake_ai_json)

        self.assertIn(bundle["query"], prompt)
        self.assertIn(article["title"], prompt)
        self.assertIn("source_evidence", prompt)
        self.assertIn("不要拆成开头、结尾、FAQ等零散模块", prompt)
        self.assertIn("若文章正文已经清楚说明“问题—机制—顾虑回应”的关系", prompt)
        self.assertIn("没有则不要硬凑", prompt)
        self.assertEqual(prompts[0][1], 4000)
        self.assertEqual(result["classification"], "介绍型")
        self.assertTrue(result["library_decision"]["eligible"])
        self.assertTrue(result["source_evidence"][0]["excerpt_verified"])
        self.assertEqual(result["source_evidence"][0]["excerpt"], excerpt)
        self.assertEqual(result["route"]["parent_type"], "介绍型")
        self.assertEqual(len(result["route"]["steps"]), 2)

    def test_malformed_result_is_downgraded_to_not_for_library(self):
        from services.reference_route_analysis import normalize_route_analysis_result

        result = normalize_route_analysis_result(
            {
                "classification": "对比型",
                "source_evidence": [{
                    "role": "交付依据",
                    "finding": "有数据。",
                    "excerpt": "原文中不存在的片段，不能被当作证据。",
                }],
                "route": {
                    "name": "不完整路线",
                    "parent_type": "对比型",
                    "reader_task": "帮助选择。",
                    "steps": [],
                    "signature": "缺少完整的路线步骤。",
                },
            },
            article_content="这是实际文章正文，和模型提供的片段无关。",
        )

        self.assertEqual(result["classification"], "不入库")
        self.assertFalse(result["library_decision"]["eligible"])
        self.assertIsNone(result["route"])
        self.assertEqual(result["source_evidence"], [])

    def test_manual_experiment_writes_only_normalized_analysis(self):
        from scripts.dev_reference_route_experiment import run_route_experiment

        excerpt = "清单式合同将范围、责任与验收节点写清，方便读者按同一标准检查交付过程。"
        bundle = {
            "query": "昆山哪家装修公司的交付更靠谱？",
            "articles": [{
                "url": "https://example.com/contract",
                "title": "示例装修文章",
                "content": "正文前段。" + excerpt + "正文后段。",
            }],
        }

        def fake_ai_json(prompt, max_tokens):
            return {
                "classification": "对比型",
                "source_evidence": [{
                    "role": "交付核验维度",
                    "finding": "用合同范围、责任和验收节点构成检查标准。",
                    "excerpt": excerpt,
                }],
                "route": {
                    "name": "按交付核验标准进行横向判断的路线",
                    "parent_type": "对比型",
                    "reader_task": "帮助读者在多家服务方之间做可核验的比较。",
                    "steps": [{
                        "purpose": "定义交付判断维度。",
                        "evidence_role": "交付核验维度",
                        "output_action": "按同一维度整理不同候选的可验证信息。",
                    }],
                    "signature": "先给标准，再呈现候选信息，避免用结论代替比较过程。",
                    "risk_notes": "不把营销数字当作已核实事实。",
                },
                "library_decision": {"reason": "可学习比较顺序。"},
            }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "experiment-output"
            result = run_route_experiment(bundle, output_dir, fake_ai_json)
            output_path = output_dir / "route_analysis.json"

            self.assertEqual(result["total_articles"], 1)
            self.assertEqual(result["total_eligible"], 1)
            self.assertTrue(output_path.is_file())
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(output["articles"]), 1)
            self.assertNotIn(bundle["articles"][0]["content"], output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
