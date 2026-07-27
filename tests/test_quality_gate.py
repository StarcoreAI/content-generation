import json
import tempfile
import unittest
from pathlib import Path

from services.quality_gate import (
    check_banned_words,
    check_meta_discourse,
    check_title_brand,
    default_quality_policy,
    effective_quality_policy,
    load_banned_words,
    load_quality_policy,
    run_quality_gate,
)


class QualityGateTests(unittest.TestCase):
    def test_default_policy_keeps_industry_words_out_of_common_editor(self):
        policy = default_quality_policy()

        self.assertNotIn("保证录取", policy["common"]["banned_words"])
        self.assertIn("保证录取", policy["industries"]["education"]["banned_words"])
        self.assertNotIn("治愈", policy["common"]["banned_words"])
        self.assertIn("治愈", policy["industries"]["medical"]["banned_words"])

    def test_loaded_policy_moves_legacy_industry_words_out_of_common(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(json.dumps({"common": {"banned_words": ["通用词", "保证录取", "治愈"]}}, ensure_ascii=False), encoding="utf-8")

            policy = load_quality_policy(path)

            self.assertEqual(["通用词"], policy["common"]["banned_words"])
            self.assertIn("保证录取", policy["industries"]["education"]["banned_words"])
            self.assertIn("治愈", policy["industries"]["medical"]["banned_words"])

    def test_banned_words_block_and_clean_text_passes(self):
        self.assertFalse(check_banned_words("报名即可包过")['passed'])
        self.assertTrue(check_banned_words("请结合自身情况核验资料")['passed'])

    def test_banned_words_match_phrases_not_common_words(self):
        result = check_banned_words("第一步是准备资料，最好的方式是核验")
        self.assertTrue(result['passed'])
        self.assertIn("全国第一", check_banned_words("宣称全国第一")['evidence'])
        self.assertIn("第一梯队", check_banned_words("翼升学属于第一梯队")['evidence'])

    def test_banned_words_cautionary_context_warns_and_still_runs_llm_review(self):
        check = check_banned_words("不要相信包过承诺")
        self.assertFalse(check["passed"])
        self.assertEqual("warn", check["severity"])
        self.assertTrue(check["cautionary_context"])
        report = run_quality_gate(
            "中性标题", "不要相信包过承诺", {"parent_type": "介绍型"}, {},
            client_brand="翼升学", competitor_names=[], competitor_markdown="", recent_articles=[],
            ai_json_fn=lambda prompt, max_tokens: {"checks": []},
        )
        self.assertEqual("warn", report["verdict"])
        self.assertEqual("passed", report["llm_layer_status"])

    def test_promotional_banned_words_only_warn_and_still_run_llm_review(self):
        for text in ("我们承诺包过", "报名即可包过"):
            with self.subTest(text=text):
                check = check_banned_words(text)
                self.assertFalse(check["passed"])
                self.assertEqual("warn", check["severity"])
                self.assertFalse(check.get("cautionary_context"))
                report = run_quality_gate(
                    "中性标题", text, {}, {}, client_brand="", competitor_names=[],
                    competitor_markdown="", recent_articles=[],
                    ai_json_fn=lambda _prompt, _max_tokens: {"checks": []},
                )
                self.assertEqual("passed", report["llm_layer_status"])
                self.assertEqual("warn", report["verdict"])

    def test_effective_policy_merges_common_and_matching_industry_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            policy = load_quality_policy(path)
            policy["common"]["banned_words"] = ["通用词"]
            policy["industries"]["装修"] = {
                "banned_words": ["行业词"],
                "must_do": ["说明价格依据"],
                "must_not_do": ["承诺零增项"],
                "review_requirements": "检查报价表述。",
            }

            effective = effective_quality_policy(policy, "装修·昆山本地")

            self.assertEqual(effective["banned_words"], ["通用词", "行业词"])
            self.assertIn("说明价格依据", effective["must_do"])
            self.assertIn("承诺零增项", effective["must_not_do"])
            self.assertIn("检查报价表述", effective["review_requirements"])

    def test_industry_banned_words_are_limited_to_the_matching_industry(self):
        self.assertFalse(check_banned_words("治疗后100%有效", industry="医疗")["passed"])
        self.assertTrue(check_banned_words("治疗后100%有效", industry="教育")["passed"])
        self.assertFalse(check_banned_words("保证录取", industry="education")["passed"])
        self.assertFalse(check_banned_words("稳赚不赔", industry="金融")["passed"])
        self.assertTrue(check_banned_words("第一步是核验，最好的方式是比较", industry="医疗")["passed"])

    def test_llm_prompt_includes_customer_and_uploaded_material_as_traceable_sources(self):
        prompts = []
        run_quality_gate(
            "中性标题", "翼升学（河北省）科技有限公司提供服务", {"parent_type": "介绍型"}, {},
            client_brand="翼升学", competitor_names=[], competitor_markdown="", recent_articles=[],
            customer_material_text="客户资料：翼升学（河北省）科技有限公司",
            content_upload_text="上传资料：服务流程说明",
            ai_json_fn=lambda prompt, max_tokens: prompts.append(prompt) or {"checks": []},
        )
        self.assertIn("合法可回溯来源", prompts[0])
        self.assertIn("翼升学（河北省）科技有限公司", prompts[0])
        self.assertIn("服务流程说明", prompts[0])

    def test_external_banned_words_are_merged_and_missing_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "banned_words.json"
            path.write_text(json.dumps({"custom": ["自定义违禁"]}, ensure_ascii=False), encoding="utf-8")
            words = load_banned_words(path)
            self.assertIn("包过", words["overpromise"])
            self.assertIn("自定义违禁", words["custom"])
            self.assertTrue(check_banned_words("自定义违禁", words)['passed'] is False)
            self.assertIn("包过", load_banned_words(Path(tmp) / "missing.json")["overpromise"])

    def test_title_brand_check_blocks_client_brand_only_in_title(self):
        self.assertFalse(check_title_brand("翼升学服务介绍", "翼升学", [])['passed'])
        self.assertTrue(check_title_brand("成人学历服务介绍", "翼升学", [])['passed'])

    def test_comparison_coverage_does_not_create_a_code_gate(self):
        report = run_quality_gate(
            "中性标题", "翼升学提供咨询服务", {"parent_type": "对比型"}, {},
            client_brand="翼升学", competitor_names=["华图教育", "中公教育"],
            competitor_markdown="", recent_articles=[],
            ai_json_fn=lambda prompt, max_tokens: {"checks": []},
        )
        self.assertEqual("pass", report["verdict"])
        self.assertNotIn("comparison_presence", [item["check_id"] for item in report["code_layer"]])

    def test_meta_discourse_blocks_internal_placeholder(self):
        self.assertFalse(check_meta_discourse("本节保留结构位置")['passed'])

    def test_meta_discourse_blocks_internal_workflow_terms_but_not_reader_facing_institution_name(self):
        blocked = check_meta_discourse("该竞品未提供价格区间")
        self.assertFalse(blocked["passed"])
        self.assertIn("竞品", blocked["evidence"])
        self.assertTrue(check_meta_discourse("某机构价格区间以官网为准")["passed"])

    def test_llm_json_is_added_to_report(self):
        report = run_quality_gate(
            "中性标题", "正文没有问题", {"parent_type": "介绍型"}, {},
            client_brand="翼升学", competitor_names=[], competitor_markdown="", recent_articles=[],
            ai_json_fn=lambda prompt, max_tokens: {
                "checks": [{"check_id": "fact_traceability", "passed": True, "evidence": []}]
            },
        )
        self.assertEqual(report["llm_layer_status"], "passed")
        self.assertEqual(report["llm_layer"][0]["check_id"], "fact_traceability")

    def test_llm_empty_or_bad_json_fails_open(self):
        for response in ("", "not-json"):
            with self.subTest(response=response):
                report = run_quality_gate(
                    "中性标题", "正文没有问题", {"parent_type": "介绍型"}, {},
                    client_brand="翼升学", competitor_names=[], competitor_markdown="", recent_articles=[],
                    ai_json_fn=lambda prompt, max_tokens, response=response: response,
                )
                self.assertEqual(report["llm_layer_status"], "failed")
                self.assertEqual(report["verdict"], "warn")

    def test_llm_flags_competitor_claim_as_low_confidence(self):
        report = run_quality_gate(
            "中性标题", "翼程 95% 通过率", {"parent_type": "介绍型"}, {},
            client_brand="翼升学", competitor_names=["翼程"], competitor_markdown="翼程：95% 通过率", recent_articles=[],
            ai_json_fn=lambda prompt, max_tokens: json.dumps({"checks": [{
                "check_id": "competitor_claim_repetition", "passed": False,
                "evidence": ["翼程 95% 通过率"],
            }]}, ensure_ascii=False),
        )
        check = report["llm_layer"][0]
        self.assertFalse(check["passed"])
        self.assertTrue(check["low_confidence"])

    def test_llm_untraceable_number_is_reported(self):
        report = run_quality_gate(
            "中性标题", "服务覆盖95个城市", {"parent_type": "介绍型"}, {},
            client_brand="翼升学", competitor_names=[], competitor_markdown="", recent_articles=[],
            ai_json_fn=lambda prompt, max_tokens: {"checks": [{
                "check_id": "fact_traceability", "passed": False, "evidence": ["95个城市"],
            }]},
        )
        self.assertFalse(report["llm_layer"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
