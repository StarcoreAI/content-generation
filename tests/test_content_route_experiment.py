import json
import tempfile
import unittest
from pathlib import Path


def valid_bundle():
    return {
        "task": {
            "query": "我脸开始往下走了，下颌线也没以前清楚，想在上海做面部提升，有没有创伤别太大的医生推荐？",
            "article_type": "介绍型",
            "decision_goal": "帮助读者理解面诊前应怎样判断医生与方案是否匹配。",
            "must_address": ["创伤顾虑", "下颌线模糊", "自然感"],
            "title_entity_policy": "实体不入标题",
        },
        "client": {"name": "崔红蕾", "brand": "崔红蕾"},
        "selected_route": {
            "name": "问题分层与方案匹配路线",
            "parent_type": "介绍型",
            "reader_task": "帮助读者理解自身困扰与方案评估的关系。",
            "steps": [{
                "purpose": "先定位读者困扰。",
                "evidence_role": "问题与方案匹配信息",
                "output_action": "把困扰转成面诊前可讨论的判断维度。",
            }],
            "signature": "先解释判断逻辑，再连接实体资料。",
            "risk_notes": "不把个体结果写成承诺。",
            "source_evidence": [{"url": "https://reference.example/article", "excerpt": "不得传给写作层"}],
        },
        "customer_master_text": """# 客户总资料

## 品牌基础

崔红蕾的服务方向包括面部年轻化沟通与整体轮廓评估。

## 产品/服务

客户自述：双韧焕颜提升以面部天然韧带作为力学支点，通过发际线内微针眼进行操作。
资料描述的关注区域包括下颌缘韧带和中面部组织状态。

## 公开背景

资料主体为崔红蕾个人履历，实际适应证、风险和恢复情况以面诊为准。
""",
    }


class ContentRouteExperimentTests(unittest.TestCase):
    def test_direct_prompt_uses_customer_master_as_primary_content(self):
        from services.content_route_experiment import build_content_route_writer_prompt

        prompt = build_content_route_writer_prompt(valid_bundle())

        self.assertIn("客户总资料是文章主体", prompt)
        self.assertIn("Query 只决定读者进入这条主线的切口", prompt)
        self.assertIn("写法库脉络只决定组织方式", prompt)
        self.assertIn("允许使用通用知识补足解释与过渡", prompt)
        self.assertIn("客户特有优势和差异化必须成为正文主干", prompt)
        self.assertIn("不凭空写成独家、唯一、最好或市场领先", prompt)
        self.assertIn("不要写“客户资料显示”“竞品资料显示”", prompt)
        self.assertIn("先在开头和主体前半段用客户专属事实建立主线", prompt)
        self.assertIn("双韧焕颜提升", prompt)
        self.assertNotIn("https://reference.example/article", prompt)
        self.assertNotIn("不得传给写作层", prompt)

    def test_run_uses_one_writer_call_without_brief_stage(self):
        from services.content_route_experiment import WRITER_MAX_TOKENS, run_content_route_experiment

        calls = []

        def fake_writer_ai(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return "下颌线模糊又担心创伤，怎样了解面部提升方向\n\n正文。"

        result = run_content_route_experiment(valid_bundle(), fake_writer_ai)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], WRITER_MAX_TOKENS)
        self.assertNotIn("brief", result)
        self.assertTrue(result["draft"])

    def test_runner_writes_only_single_stage_experiment_outputs(self):
        from scripts.dev_content_route_experiment import run_manual_content_route_experiment

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            bundle = valid_bundle()
            customer_master_text = bundle.pop("customer_master_text")
            result = run_manual_content_route_experiment(
                bundle,
                customer_master_text,
                output_dir,
                lambda prompt, max_tokens: "标题\n\n正文。",
            )

            self.assertEqual(result["customer_master_characters"], len(customer_master_text))
            self.assertEqual(sorted(path.name for path in output_dir.iterdir()), [
                "draft.md", "experiment_trace.json",
            ])
            trace = json.loads((output_dir / "experiment_trace.json").read_text(encoding="utf-8"))
            self.assertEqual(trace["customer_master_characters"], len(customer_master_text))
            self.assertNotIn(customer_master_text[:100], json.dumps(trace, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
