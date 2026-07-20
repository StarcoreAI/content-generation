import json
import tempfile
import unittest
from pathlib import Path

from services.reference_anatomy import (
    analyze_article_anatomy,
    build_anatomy_prompt,
    normalize_anatomy_result,
)


class ReferenceAnatomyTests(unittest.TestCase):
    def test_prompt_uses_article_and_stage0_risks_without_source_metadata_or_brand(self):
        article = {
            "title": "Article title",
            "content": "Article body content.",
            "risk_marks": ["关键数据无来源"],
            "url": "https://example.com/article",
            "group_id": "group-1",
            "published_at": "2026-07-20",
            "platform": "example-platform",
            "citation_count": 9,
        }

        prompt = build_anatomy_prompt(article)

        self.assertIn("Article title", prompt)
        self.assertIn("Article body content.", prompt)
        self.assertIn("关键数据无来源", prompt)
        self.assertIn("宁缺毋滥", prompt)
        self.assertIn("换一个品牌、换一批事实仍然能照做", prompt)
        self.assertIn("excerpt 必须是原文逐字节选", prompt)
        self.assertIn("详细讲解多个机构、逐个介绍而非显式对比，也归为对比型", prompt)
        for forbidden in [
            "https://example.com/article",
            "group-1",
            "2026-07-20",
            "example-platform",
            "citation_count",
            "翼升学",
            "家长",
            "教育",
            "师资",
            "单招",
            "升学",
            "学员",
            "学校",
        ]:
            self.assertNotIn(forbidden, prompt)

    def test_normalize_matches_anatomy_contract_and_verifies_excerpt(self):
        excerpt = "这是原文中一段足够长度的真实示范文字，用于验证逐字节选要求没有被模型改写。"
        result = normalize_anatomy_result(
            {
                "skeleton": {
                    "name": "Observation classification",
                    "parent_type": "invalid",
                    "sections": [f"Section {index}" for index in range(10)],
                    "signature": "Neutral classification structure.",
                    "risk_notes": "Risk note.",
                },
                "modules": [
                    {
                        "type": "unknown",
                        "name": "Reusable opening",
                        "pattern": "Ask several user questions before framing the decision.",
                        "excerpt": excerpt,
                        "risk_notes": "Do not use named disparagement.",
                    },
                    {"type": "开头", "name": "Missing pattern"},
                    {"type": "结尾", "name": "Closing", "pattern": "Return to selection criteria."},
                    {"type": "FAQ段", "name": "FAQ", "pattern": "Answer recurring questions."},
                    {"type": "对比表", "name": "Table", "pattern": "Compare by user need."},
                ],
                "citability_features": ["Feature"] * 20,
            },
            article_content="Prefix " + excerpt + " suffix",
        )

        self.assertEqual(result["skeleton"]["parent_type"], "介绍型")
        self.assertEqual(len(result["skeleton"]["sections"]), 8)
        self.assertEqual(result["skeleton"]["signature"], "Neutral classification structure.")
        self.assertEqual(len(result["modules"]), 3)
        self.assertEqual(result["modules"][0]["type"], "其他")
        self.assertEqual(result["modules"][0]["excerpt"], excerpt)
        self.assertTrue(result["modules"][0]["excerpt_verified"])
        self.assertEqual(len(result["citability_features"]), 12)
        self.assertNotIn("risk_marks", result)

    def test_normalize_drops_invalid_excerpt_but_retains_its_pattern_and_risky_skeleton(self):
        result = normalize_anatomy_result(
            {
                "skeleton": {
                    "name": "Risky structure",
                    "parent_type": "对比型",
                    "sections": ["Classify options"],
                    "signature": "Includes a risky comparison mechanism.",
                    "risk_notes": "手段禁用，仅结构可参考",
                },
                "modules": [{
                    "type": "开头",
                    "name": "Opening",
                    "pattern": "Start from a decision problem.",
                    "excerpt": "too short",
                }],
            },
            article_content="Some unrelated complete article body.",
        )

        self.assertEqual(result["skeleton"]["risk_notes"], "手段禁用，仅结构可参考")
        self.assertEqual(len(result["modules"]), 1)
        self.assertEqual(result["modules"][0]["excerpt"], "")
        self.assertFalse(result["modules"][0]["excerpt_verified"])

    def test_analyze_keeps_source_metadata_outside_prompt(self):
        article = {
            "title": "Article title",
            "content": "Article body content.",
            "risk_marks": ["关键数据无来源"],
            "url": "https://example.com/article",
            "group_id": "group-1",
            "published_at": "2026-07-20",
            "platform": "example-platform",
            "citation_count": 9,
        }
        prompts = []

        def fake_ai_json(prompt, max_tokens):
            prompts.append(prompt)
            return {"modules": [{"type": "开头", "name": "Opening", "pattern": "Start with a decision problem."}]}

        card = analyze_article_anatomy(article, fake_ai_json)

        self.assertEqual(card["source"], {
            "url": "https://example.com/article",
            "title": "Article title",
            "group_id": "group-1",
            "published_at": "2026-07-20",
            "platform": "example-platform",
            "citation_count": 9,
        })
        self.assertIn("关键数据无来源", prompts[0])
        self.assertNotIn("https://example.com/article", prompts[0])

    def test_manual_runner_only_analyzes_stage0_learnable_groups_and_keeps_no_body(self):
        from scripts.dev_reference_anatomy import run_reference_anatomy

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            stage_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-20"
            stage_dir.mkdir(parents=True)
            content = "完整文章正文，包含清晰开头、正文模块和结尾。" * 30
            (stage_dir / "fetched_articles.json").write_text(json.dumps({"articles": [{
                "ok": True,
                "url": "https://example.com/learnable",
                "title": "Learnable",
                "content": content,
                "citation_count": 2,
            }]}, ensure_ascii=False), encoding="utf-8")
            (stage_dir / "stage0_filter_groups.json").write_text(json.dumps({"groups": [
                {
                    "group_id": "group-learnable",
                    "learnable": True,
                    "risk_marks": ["关键数据无来源"],
                    "representative": {"url": "https://example.com/learnable"},
                },
                {
                    "group_id": "group-skipped",
                    "learnable": False,
                    "representative": {"url": "https://example.com/skipped"},
                },
            ]}, ensure_ascii=False), encoding="utf-8")

            result = run_reference_anatomy(
                client_id="client-1",
                date="2026-07-20",
                data_dir=data_dir,
                ai_json_fn=lambda prompt, max_tokens: {
                    "skeleton": {
                        "name": "Selection guide",
                        "parent_type": "介绍型",
                        "sections": ["Frame the decision"],
                        "signature": "Neutral guide.",
                        "risk_notes": "",
                    },
                    "modules": [],
                    "citability_features": [],
                },
            )

            self.assertEqual(result["input_groups"], 2)
            self.assertEqual(result["analyzed"], 1)
            self.assertEqual(result["skipped"], 1)
            output_path = Path(result["output_path"])
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertNotIn(content, output_path.read_text(encoding="utf-8"))
            self.assertEqual(output["cards"][0]["source"]["group_id"], "group-learnable")

    def test_manual_runner_limit_counts_learnable_groups_not_rejected_groups(self):
        from scripts.dev_reference_anatomy import run_reference_anatomy

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            stage_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-20"
            stage_dir.mkdir(parents=True)
            content = "完整文章正文，包含清晰开头、正文模块和结尾。" * 30
            (stage_dir / "fetched_articles.json").write_text(json.dumps({"articles": [{
                "ok": True,
                "url": "https://example.com/learnable",
                "title": "Learnable",
                "content": content,
            }]}, ensure_ascii=False), encoding="utf-8")
            (stage_dir / "stage0_filter_groups.json").write_text(json.dumps({"groups": [
                {"group_id": "group-rejected", "learnable": False, "representative": {"url": "https://example.com/rejected"}},
                {"group_id": "group-learnable", "learnable": True, "representative": {"url": "https://example.com/learnable"}},
            ]}, ensure_ascii=False), encoding="utf-8")

            result = run_reference_anatomy(
                client_id="client-1",
                date="2026-07-20",
                data_dir=data_dir,
                limit=1,
                ai_json_fn=lambda prompt, max_tokens: {"modules": []},
            )

            self.assertEqual(result["input_groups"], 1)
            self.assertEqual(result["analyzed"], 1)

    def test_manual_runner_ledger_records_only_success_and_retries_false_or_error_groups(self):
        from scripts.dev_reference_anatomy import run_reference_anatomy

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            stage_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-20"
            stage_dir.mkdir(parents=True)
            content = "完整文章正文，包含清晰开头、正文模块和结尾。" * 30
            (stage_dir / "fetched_articles.json").write_text(json.dumps({"articles": [
                {"ok": True, "url": "https://example.com/success", "title": "Success", "content": content},
                {"ok": True, "url": "https://example.com/failure", "title": "Failure", "content": content},
            ]}, ensure_ascii=False), encoding="utf-8")
            (stage_dir / "stage0_filter_groups.json").write_text(json.dumps({"groups": [
                {"group_id": "group-false", "learnable": False, "representative": {"url": "https://example.com/false"}},
                {"group_id": "group-success", "learnable": True, "representative": {"url": "https://example.com/success"}},
                {"group_id": "group-failure", "learnable": True, "representative": {"url": "https://example.com/failure"}},
            ]}, ensure_ascii=False), encoding="utf-8")
            ledger_path = data_dir / "reference_intelligence" / "client-1" / "stage1_anatomy_ledger.json"

            def first_ai_json(prompt, max_tokens):
                if "Failure" in prompt:
                    raise RuntimeError("provider unavailable")
                return {"modules": []}

            first = run_reference_anatomy(
                client_id="client-1",
                date="2026-07-20",
                data_dir=data_dir,
                ai_json_fn=first_ai_json,
                ledger_path=ledger_path,
            )
            self.assertEqual(first["analyzed"], 1)
            self.assertEqual(first["errors"], 1)
            self.assertEqual(json.loads(ledger_path.read_text(encoding="utf-8"))["successful_urls"], [
                "https://example.com/success",
            ])

            second = run_reference_anatomy(
                client_id="client-1",
                date="2026-07-20",
                data_dir=data_dir,
                ai_json_fn=lambda prompt, max_tokens: {"modules": []},
                ledger_path=ledger_path,
            )
            self.assertEqual(second["analyzed"], 1)
            self.assertEqual(json.loads(ledger_path.read_text(encoding="utf-8"))["successful_urls"], [
                "https://example.com/success",
                "https://example.com/failure",
            ])


if __name__ == "__main__":
    unittest.main()
