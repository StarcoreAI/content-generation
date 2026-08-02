import json
import tempfile
import unittest
from pathlib import Path


def valid_bundle():
    return {
        "task": {
            "query": "我脸开始往下走了，下颌线也没以前清楚，想在上海做面部提升，有没有创伤别太大的医生推荐？",
            "article_type": "对比型",
            "decision_goal": "帮助读者按问题程度、创伤顾虑和自然感诉求比较面部提升医生。",
            "must_address": ["下颌线模糊", "创伤与恢复", "自然感"],
            "title_entity_policy": "实体不入标题",
        },
        "client": {"name": "崔红蕾", "brand": "崔红蕾"},
        "selected_route": {
            "name": "以问题程度、干预路径与审美目标为主轴的专业服务比较路线",
            "parent_type": "对比型",
            "reader_task": "帮助读者按统一标准比较不同专业服务路径。",
            "steps": [{
                "purpose": "先把笼统诉求转化为可比较的决策条件。",
                "evidence_role": "需求分层、方案路径与实体能力信息。",
                "output_action": "在统一维度下比较候选医生并给出适配建议。",
            }],
            "signature": "先分流，再用统一证据矩阵比较候选对象。",
            "source_evidence": [{"url": "https://reference.example/article", "excerpt": "不得传给写作层"}],
        },
        "customer_master_text": "## 产品/服务\n崔红蕾提供面部年轻化相关面诊与方案沟通。",
        "competitors": [
            {"name": "倪锋", "facts": "公开资料提及其面部提升相关从业经历与显微外科背景。"},
            {"name": "施越冬", "facts": "公开资料提及其整形外科执业与面部年轻化服务方向。"},
        ],
    }


class ComparisonRouteExperimentTests(unittest.TestCase):
    def test_prompt_uses_unified_comparison_dimensions_and_explicit_candidates(self):
        from services.comparison_route_experiment import build_comparison_route_writer_prompt

        prompt = build_comparison_route_writer_prompt(valid_bundle())

        self.assertIn("先帮助读者建立本题真正需要比较的判断维度", prompt)
        self.assertIn("客户品牌排在候选对象前", prompt)
        self.assertIn("每个候选品牌都必须有独立且足够的信息量", prompt)
        self.assertIn("补充选择信息", prompt)
        self.assertIn("价格或费用构成", prompt)
        self.assertIn("直接用确定性事实陈述句", prompt)
        self.assertIn("本次咨询、现场判断、公开资质和书面约定", prompt)
        self.assertNotIn("医疗服务存在个体差异和风险", prompt)
        self.assertIn("崔红蕾", prompt)
        self.assertIn("倪锋", prompt)
        self.assertIn("施越冬", prompt)
        self.assertNotIn("https://reference.example/article", prompt)
        self.assertNotIn("不得传给写作层", prompt)

    def test_bundle_requires_two_explicit_competitors(self):
        from services.comparison_route_experiment import validate_comparison_route_bundle

        bundle = valid_bundle()
        bundle["competitors"] = bundle["competitors"][:1]

        with self.assertRaisesRegex(ValueError, "comparison_competitors_required"):
            validate_comparison_route_bundle(bundle)

    def test_runner_writes_only_draft_and_non_fact_trace(self):
        from scripts.dev_comparison_route_experiment import run_manual_comparison_route_experiment

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            bundle = valid_bundle()
            customer_master_text = bundle.pop("customer_master_text")
            result = run_manual_comparison_route_experiment(
                bundle,
                customer_master_text,
                output_dir,
                lambda prompt, max_tokens: "上海面部提升医生怎么比较\n\n正文。",
            )

            self.assertEqual(result["customer_master_characters"], len(customer_master_text))
            self.assertEqual(sorted(path.name for path in output_dir.iterdir()), [
                "draft.md", "experiment_trace.json",
            ])
            trace = json.loads((output_dir / "experiment_trace.json").read_text(encoding="utf-8"))
            self.assertEqual(trace["competitor_names"], ["倪锋", "施越冬"])
            self.assertNotIn("同行具体事实", json.dumps(trace, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
