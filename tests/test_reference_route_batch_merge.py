import unittest

from services.reference_route_batch_merge import merge_reference_route_batch


ROUTE = {
    "id": "route-existing",
    "parent_type": "介绍型",
    "name": "现有路线",
    "reader_task": "帮助读者判断",
    "signature": "先解释再落地",
    "risk_notes": "",
    "steps": [{"purpose": "说明问题", "evidence_role": "来源证据", "output_action": "展开说明"}],
}
ANALYSIS = {
    "classification": "介绍型",
    "route": {key: value for key, value in ROUTE.items() if key != "id"},
    "source": {"url": "https://example.com/a", "title": "文章 A"},
    "source_evidence": [{"role": "判断框架", "finding": "先解释判断条件", "excerpt": "这是一段可以在原文中连续找到且长度足够用于验证的来源片段。"}],
}


class ReferenceRouteBatchMergeTests(unittest.TestCase):
    def test_batch_merge_uses_a_separate_4000_token_llm_call(self):
        captured = {}

        def fake_ai_json(prompt, max_tokens):
            captured["prompt"] = prompt
            captured["max_tokens"] = max_tokens
            return {"updates": [{"action": "reinforce", "route_id": "route-existing", "analysis_indexes": [0], "reason": "结构相同"}]}

        result = merge_reference_route_batch([ANALYSIS], [ROUTE], fake_ai_json)

        self.assertEqual(4000, captured["max_tokens"])
        self.assertIn("批次", captured["prompt"])
        self.assertEqual("reinforce", result["updates"][0]["action"])
        self.assertEqual("route-existing", result["updates"][0]["route_id"])
