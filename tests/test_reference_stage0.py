import json
import tempfile
import unittest
from pathlib import Path

from services.reference_stage0 import (
    analyze_stage0_groups,
    build_stage0_prompt,
    derive_sponsor,
    group_reference_articles,
    normalize_stage0_result,
)


def article(url, title, content, citation_count=0, **extra):
    return {
        "ok": True,
        "url": url,
        "title": title,
        "content": content,
        "citation_count": citation_count,
        **extra,
    }


class ReferenceStage0Tests(unittest.TestCase):
    def test_manual_runner_reads_fetched_articles_and_keeps_stage0_result(self):
        from scripts.dev_reference_stage0 import run_stage0_filter

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            stage_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-20"
            stage_dir.mkdir(parents=True)
            (stage_dir / "fetched_articles.json").write_text(json.dumps({
                "articles": [article(
                    "https://example.com/article",
                    "Article",
                    "完整文章正文，包含开头、正文模块和结尾。" * 60,
                )],
            }, ensure_ascii=False), encoding="utf-8")

            result = run_stage0_filter(
                client_id="client-1",
                client_brand="翼升学",
                date="2026-07-20",
                data_dir=data_dir,
                ai_json_fn=lambda prompt, max_tokens: {
                    "article_type": "介绍型",
                    "learnable": True,
                    "reason": "结构完整，可复用",
                    "promoted_entity": "翼升学",
                    "risk_marks": [],
                },
            )

            self.assertEqual(result["input"], 1)
            self.assertEqual(result["groups"], 1)
            self.assertEqual(result["errors"], 0)
            output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(output["groups"][0]["sponsor"], "self")

    def test_groups_syndicated_bodies_and_uses_longest_representative(self):
        shared = "完整文章正文，包含开头、多个正文模块和结尾。" * 40
        result = group_reference_articles([
            article("https://one.example.com/a", "A", shared, 9),
            article("https://two.example.com/b", "B", shared + "补充说明。", 1),
            article("https://three.example.com/c", "C", "另一篇完整文章。" * 100),
        ])

        self.assertEqual(len(result["groups"]), 2)
        syndicated = next(group for group in result["groups"] if group["syndication_count"] == 2)
        self.assertEqual(syndicated["representative"]["url"], "https://two.example.com/b")
        self.assertEqual(syndicated["member_urls"], [
            "https://one.example.com/a",
            "https://two.example.com/b",
        ])
        self.assertTrue(syndicated["group_id"].startswith("group_"))

    def test_groups_syndicated_versions_with_tail_noise_and_missing_sections(self):
        sections = [f"section-{index:02d}-" + chr(0x4E00 + index) * 80 for index in range(20)]
        shorter = "".join(sections[:6] + sections[8:18])
        longer = "".join(sections + ["site-footer-" + "杂" * 800])
        result = group_reference_articles([
            article("https://one.example.com/article", "One", shorter),
            article("https://two.example.com/article", "Two", longer),
        ])

        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["syndication_count"], 2)
        self.assertEqual(result["groups"][0]["representative"]["url"], "https://two.example.com/article")

    def test_does_not_group_different_articles_from_the_same_industry(self):
        result = group_reference_articles([
            article("https://one.example.com/a", "A", "机构选择指南" + "甲" * 500),
            article("https://two.example.com/b", "B", "机构选择指南" + "乙" * 500),
        ])

        self.assertEqual(len(result["groups"]), 2)
        self.assertTrue(all(group["syndication_count"] == 1 for group in result["groups"]))

    def test_excludes_fetch_residues_before_grouping(self):
        result = group_reference_articles([
            article("https://example.com/403", "403 Forbidden", "正文" * 200),
            article("https://example.com/cloudflare", "Just a moment...", "正文" * 200),
            article("https://example.com/good", "Good", "完整正文" * 200),
        ])

        self.assertEqual([item["url"] for item in result["excluded"]], [
            "https://example.com/403",
            "https://example.com/cloudflare",
        ])
        self.assertEqual(len(result["groups"]), 1)

    def test_prompt_contains_rules_and_never_client_brand(self):
        prompt = build_stage0_prompt({
            "url": "https://example.com/article",
            "title": "Article title",
            "content": "正文" * 7000,
        }, 3)

        self.assertIn("https://example.com/article", prompt)
        self.assertIn("【一稿多发铺站数】3", prompt)
        self.assertIn("换品牌换事实仍可照做", prompt)
        self.assertIn("风险手段也不影响 learnable", prompt)
        self.assertIn("实质性决策支架", prompt)
        self.assertIn("可逐项问出口的核验清单", prompt)
        self.assertIn("只要有任一实质性支架，即使采用统一维度逐家展开", prompt)
        self.assertIn("有实质性决策支架的照常判 true", prompt)
        self.assertIn("介绍型文章的可学判据", prompt)
        self.assertIn("完整且有辨识度的叙事结构", prompt)
        self.assertIn("纯卖点和资质堆叠、无叙事推进的仍判 false", prompt)
        self.assertNotIn("无论罗列多整齐，统一模板不是可学套路", prompt)
        self.assertIn("拿不准时判 false", prompt)
        self.assertNotIn("翼升学", prompt)
        self.assertNotIn("正文" * 7000, prompt)

    def test_decision_support_and_plain_roster_regression_fixtures(self):
        decision_support = (
            "统一维度对比多个方案。先按预算、时间和目标分流，再列出可逐项问出口的核验清单。"
            "选择步骤是先确认资质，再比较服务边界，最后预约试听。FAQ 回答退费、排课和适配人群。"
        ) * 12
        plain_roster = (
            "机构甲：环境好、服务好、课程多。机构乙：环境好、服务好、课程多。"
            "机构丙：环境好、服务好、课程多。机构丁：环境好、服务好、课程多。"
        ) * 16

        def fake_ai_json(prompt, max_tokens):
            self.assertIn("实质性决策支架", prompt)
            if "Decision support fixture" in prompt:
                return {"article_type": "对比型", "learnable": True}
            return {"article_type": "对比型", "learnable": False}

        with tempfile.TemporaryDirectory() as tmp:
            result = analyze_stage0_groups(
                [
                    article("https://example.com/decision", "Decision support fixture", decision_support),
                    article("https://example.com/roster", "Plain roster fixture", plain_roster),
                ],
                client_brand="翼升学",
                ai_json_fn=fake_ai_json,
                stage_dir=tmp,
            )

        by_title = {item["representative"]["title"]: item for item in result["groups"]}
        self.assertTrue(by_title["Decision support fixture"]["learnable"])
        self.assertFalse(by_title["Plain roster fixture"]["learnable"])

    def test_normalize_requires_literal_true_and_closed_article_type(self):
        result = normalize_stage0_result({
            "article_type": "未知类型",
            "learnable": 1,
            "reason": "判定理由",
            "promoted_entity": "品牌甲",
            "risk_marks": ["风险一", "", 3],
        })

        self.assertEqual(result["article_type"], "其他")
        self.assertFalse(result["learnable"])
        self.assertEqual(result["reason"], "判定理由")
        self.assertEqual(result["promoted_entity"], "品牌甲")
        self.assertEqual(result["risk_marks"], ["风险一", "3"])

    def test_fail_open_only_for_llm_exception_and_persists_metadata_without_body(self):
        good_content = "完整文章正文，包含开头、正文模块和结尾。" * 60
        other_content = "另一篇完整文章正文，包含独立结构。" * 70

        def fake_ai_json(prompt, max_tokens):
            if "First" in prompt:
                raise RuntimeError("provider unavailable")
            return {
                "article_type": "介绍型",
                "learnable": False,
                "reason": "目录页，无法学习结构",
                "promoted_entity": "其他品牌",
                "risk_marks": ["关键数据无来源"],
            }

        with tempfile.TemporaryDirectory() as tmp:
            result = analyze_stage0_groups(
                [
                    article("https://example.com/first", "First", good_content),
                    article("https://example.com/second", "Second", other_content),
                ],
                client_brand="翼升学",
                ai_json_fn=fake_ai_json,
                stage_dir=tmp,
                client_id="client-1",
                date="2026-07-20",
            )

            self.assertEqual(len(result["groups"]), 2)
            failed = next(item for item in result["groups"] if item["representative"]["title"] == "First")
            rejected = next(item for item in result["groups"] if item["representative"]["title"] == "Second")
            self.assertTrue(failed["learnable"])
            self.assertTrue(failed["llm_error"])
            self.assertFalse(rejected["learnable"])
            self.assertEqual(rejected["reason"], "目录页，无法学习结构")
            self.assertEqual(rejected["sponsor"], "other")

            output_path = Path(tmp) / "stage0_filter_groups.json"
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(output, result)
            self.assertNotIn(good_content, output_path.read_text(encoding="utf-8"))

    def test_derives_sponsor_by_bidirectional_brand_containment(self):
        self.assertEqual(derive_sponsor("翼升学留学", "翼升学"), "self")
        self.assertEqual(derive_sponsor("其他品牌", "翼升学"), "other")
        self.assertEqual(derive_sponsor("", "翼升学"), "")


if __name__ == "__main__":
    unittest.main()
