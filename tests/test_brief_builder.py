import random
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.brief_builder import (
    build_brief_sample,
    build_planning_brief_prompt,
    generate_planning_brief,
    validate_planning_brief,
)
from services.pattern_library import PatternLibrary


def add_entry(library, scope, kind, name, payload, status="active"):
    entry = library.create_candidate(scope, kind, name, payload, {"url": f"https://example.com/{kind}/{name}"})
    return library.set_status(scope, entry["id"], status) if status != "candidate" else entry


def make_library(root):
    library = PatternLibrary(root, now_fn=lambda: "2026-07-20 12:00:00")
    entries = {
        "comparison": add_entry(library, "industry:education", "skeleton", "Comparison", {"parent_type": "对比型", "sections": ["开头功能", "正文功能"]}),
        "intro": add_entry(library, "industry:education", "skeleton", "Introduction", {"parent_type": "介绍型", "sections": ["开头功能", "品牌功能"]}),
        "candidate": add_entry(library, "industry:education", "skeleton", "Candidate", {"parent_type": "对比型"}, "candidate"),
        "opening_a": add_entry(library, "global", "module", "Opening A", {"type": "开头", "pattern": "A"}),
        "opening_b": add_entry(library, "global", "module", "Opening B", {"type": "开头", "pattern": "B"}),
        "ending": add_entry(library, "global", "module", "Ending", {"type": "结尾", "pattern": "end"}),
        "ending_b": add_entry(library, "global", "module", "Ending B", {"type": "结尾", "pattern": "end b"}),
        "faq": add_entry(library, "global", "module", "FAQ", {"type": "FAQ段", "pattern": "faq"}),
        "table": add_entry(library, "global", "module", "Table", {"type": "对比表", "pattern": "table"}),
        "body_a": add_entry(library, "industry:education", "module", "Body A", {"type": "其他", "pattern": "body a"}),
        "body_b": add_entry(library, "industry:education", "module", "Body B", {"type": "其他", "pattern": "body b"}),
        "body_c": add_entry(library, "industry:education", "module", "Body C", {"type": "其他", "pattern": "body c"}),
        "candidate_module": add_entry(library, "global", "module", "Candidate opening", {"type": "开头", "pattern": "no"}, "candidate"),
    }
    return library, entries


class BriefBuilderTests(unittest.TestCase):
    def sample(self, library, **kwargs):
        options = {
            "library": library,
            "scopes": ["industry:education", "global"],
            "parent_type": "对比型",
            "audience_angles": ["异地在职者", "时间紧张者"],
            "faq_questions": ["问题一", "问题二", "问题三", "问题四", "问题五"],
            "recent_combos": [],
            "recent_endings": [],
            "rng": random.Random(7),
        }
        options.update(kwargs)
        return build_brief_sample(**options)

    def test_uses_only_active_entries_and_parent_type_compatible_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, entries = make_library(Path(tmp))
            with patch("services.brief_builder.FAQ_PROBABILITY", 1), patch("services.brief_builder.TABLE_PROBABILITY", 1), patch("services.brief_builder.FREE_SLOT_PROBABILITY", 0):
                result = self.sample(library, parent_type="介绍型")

            self.assertEqual(result["skeleton"]["id"], entries["intro"]["id"])
            self.assertIsNone(result["table_module"])
            selected_ids = {
                item["id"] for item in [
                    result["skeleton"], result["opening_module"], result["ending_module"], result["faq_module"],
                ] if item
            } | {item["id"] for item in result["body_modules"]}
            self.assertNotIn(entries["candidate"]["id"], selected_ids)
            self.assertNotIn(entries["candidate_module"]["id"], selected_ids)
            self.assertEqual(result["skeleton"]["payload"]["parent_type"], "介绍型")

    def test_free_slot_is_marked_without_claiming_a_missing_library_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            with patch("services.brief_builder.FREE_SLOT_PROBABILITY", 1):
                result = self.sample(library)

            self.assertIn(result["free_slot"], {"opening_module", "ending_module", "body_modules"})
            self.assertFalse(result["sampling_meta"]["missing_slots"][result["free_slot"]])

    def test_missing_module_slots_are_empty_without_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp))
            add_entry(library, "global", "skeleton", "Only skeleton", {"parent_type": "对比型"})

            result = build_brief_sample(
                library=library, scopes=["global"], parent_type="对比型",
                audience_angles=[], faq_questions=[], recent_combos=[], rng=random.Random(1),
            )

            self.assertIsNone(result["opening_module"])
            self.assertTrue(result["sampling_meta"]["missing_slots"]["opening_module"])
            self.assertTrue(result["sampling_meta"]["missing_slots"]["body_modules"])

    def test_empty_faq_question_list_skips_faq_module_with_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            with patch("services.brief_builder.FAQ_PROBABILITY", 1):
                result = self.sample(library, faq_questions=[])

            self.assertIsNone(result["faq_module"])
            self.assertEqual(result["faq_questions"], [])
            self.assertEqual(result["sampling_meta"]["faq_module_reason"], "faq_questions_empty")

    def test_empty_faq_questions_omit_faq_from_planning_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            sample = self.sample(library, faq_questions=[])
            calls = []
            brief = generate_planning_brief(
                sample,
                ai_json_fn=lambda prompt, _tokens: calls.append(prompt) or {
                    "title_candidates": ["标题一", "标题二"], "angle_statement": "主线",
                    "sections": [
                        {"id": 1, "功能": "开头", "要点": "施工指令", "引用": [], "字数": 200},
                        {"id": 2, "功能": "正文", "要点": "施工指令", "引用": [], "字数": 500},
                    ], "bans": [], "dedup_hints": "避让",
                },
            )

            self.assertIn("不得出现任何 FAQ 相关段落、占位说明或建议运营补充", calls[0])
            self.assertNotIn("FAQ", " ".join(section["功能"] + section["要点"] for section in brief["sections"]))

    def test_comparison_prompt_keeps_client_before_must_use_competitors(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            prompt = build_planning_brief_prompt(self.sample(library))

        self.assertIn("必选竞品也不得置于本次品牌之前", prompt)

    def test_planning_prompt_defines_reader_facing_material_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            prompt = build_planning_brief_prompt(self.sample(library))

        self.assertIn('"素材池"', prompt)
        self.assertIn('"表述": "读者视角的一句可用事实"', prompt)
        self.assertIn('"来源": "资料小节名"', prompt)
        self.assertIn("目标 8-15 条", prompt)
        self.assertIn("行业公共", prompt)
        self.assertIn("不得出现“客户/竞品/资料包”等内部称谓", prompt)
        self.assertIn("直接陈述句", prompt)
        self.assertIn("保底清单", prompt)
        self.assertNotIn("每条必须是读者视角的可直接取用表述，用机构名称及“其官网介绍”“公开页面显示”等说法", prompt)
        self.assertIn("每条必须可定位到输入资料", prompt)

    def test_planning_prompt_guides_expansion_and_limits_disclaimer_density(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            prompt = build_planning_brief_prompt(self.sample(library))

        self.assertIn('"展开来源"', prompt)
        self.assertIn("只能指向输入资料中真实存在的小节名/机构名", prompt)
        self.assertIn("写成连贯的大段陈述而非条目罗列", prompt)
        self.assertIn("其他机构在资料允许时充分展开", prompt)
        self.assertIn("不用于限制成文篇幅", prompt)
        self.assertNotIn("500 字", prompt)
        self.assertNotIn("200-400 字", prompt)
        self.assertIn("每节最多出现 1-2 处", prompt)

    def test_planning_prompt_uses_geo_promotion_points_and_background_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            prompt = build_planning_brief_prompt(self.sample(library))

        self.assertIn("GEO 宣传点", prompt)
        self.assertIn("主题一句话 + 对应展开来源 + 展开角度", prompt)
        self.assertIn("禁止写成可直接抄进正文的成品句", prompt)
        self.assertIn("只写时间或政策锚点式短段", prompt)
        self.assertNotIn("200 字", prompt)
        self.assertIn("行业公共背景", prompt)
        self.assertIn("不得作为品牌节的展开来源", prompt)

    def test_validate_planning_brief_accepts_sections_with_or_without_expansion_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            sample = self.sample(library)

        base_brief = {
            "title_candidates": ["标题一", "标题二"],
            "angle_statement": "主线",
            "sections": [
                {"id": 1, "功能": "开头", "要点": "施工", "引用": [], "字数": 200},
                {"id": 2, "功能": "正文", "要点": "施工", "引用": [], "字数": 500},
            ],
            "bans": [],
            "dedup_hints": "避让",
        }
        with_sources = {
            **base_brief,
            "sections": [
                {**base_brief["sections"][0], "展开来源": ["客户资料包 > 产品与服务"]},
                {**base_brief["sections"][1], "展开来源": ["竞品资料 > 翼程教育"]},
            ],
        }

        self.assertEqual(validate_planning_brief(base_brief, sample), base_brief)
        self.assertEqual(validate_planning_brief(with_sources, sample), with_sources)

    def test_recent_ending_is_avoided_once_when_alternative_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, entries = make_library(Path(tmp))
            with patch("services.brief_builder.FREE_SLOT_PROBABILITY", 0):
                results = [self.sample(library, recent_endings=[entries["ending"]["id"]], rng=random.Random(seed)) for seed in range(100)]

            retried = next(item for item in results if item["sampling_meta"]["ending_retries"] == 1)
            self.assertEqual(retried["ending_module"]["id"], entries["ending_b"]["id"])

    def test_single_recent_ending_remains_selectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp))
            add_entry(library, "global", "skeleton", "Skeleton", {"parent_type": "对比型", "sections": ["段"]})
            ending = add_entry(library, "global", "module", "Only ending", {"type": "结尾", "pattern": "end"})
            result = build_brief_sample(
                library=library, scopes=["global"], parent_type="对比型",
                audience_angles=[], faq_questions=[], recent_combos=[], recent_endings=[ending["id"]], rng=random.Random(1),
            )

            self.assertEqual(result["ending_module"]["id"], ending["id"])
            self.assertEqual(result["sampling_meta"]["ending_retries"], 0)

    def test_recent_fingerprint_retries_then_marks_persistent_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp))
            skeleton = add_entry(library, "global", "skeleton", "Only skeleton", {"parent_type": "对比型"})
            opening = add_entry(library, "global", "module", "Only opening", {"type": "开头", "pattern": "open"})
            with patch("services.brief_builder.FREE_SLOT_PROBABILITY", 0):
                result = build_brief_sample(
                    library=library, scopes=["global"], parent_type="对比型",
                    audience_angles=[], faq_questions=[], recent_combos=[f"{skeleton['id']}×{opening['id']}"], rng=random.Random(1),
                )

            self.assertEqual(result["sampling_meta"]["fingerprint_retries"], 3)
            self.assertTrue(result["sampling_meta"]["fingerprint_conflict"])

    def test_avoid_skeleton_opening_pair_retries_before_returning_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            repeated = {
                "skeleton": {"id": "s-1"}, "opening_module": {"id": "o-1"},
                "sampling_meta": {"fingerprint": "s-1×o-1"},
            }
            replacement = {
                "skeleton": {"id": "s-1"}, "opening_module": {"id": "o-2"},
                "sampling_meta": {"fingerprint": "s-1×o-2"},
            }
            with patch("services.brief_builder._sample_once", side_effect=[repeated, replacement]):
                result = build_brief_sample(
                    library=library, scopes=["industry:education", "global"], parent_type="对比型",
                    audience_angles=[], faq_questions=[], recent_combos=[],
                    avoid_skeleton_opening_pairs=[("s-1", "o-1")], rng=random.Random(1),
                )

            self.assertEqual("o-2", result["opening_module"]["id"])
            self.assertEqual(1, result["sampling_meta"]["pair_retries"])
            self.assertFalse(result["sampling_meta"]["pair_conflict"])

    def test_pair_avoidance_exhaustion_returns_conflict_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            repeated = {
                "skeleton": {"id": "s-1"}, "opening_module": {"id": "o-1"},
                "sampling_meta": {"fingerprint": "s-1×o-1"},
            }
            with patch("services.brief_builder._sample_once", return_value=repeated):
                result = build_brief_sample(
                    library=library, scopes=["industry:education", "global"], parent_type="对比型",
                    audience_angles=[], faq_questions=[], recent_combos=[],
                    avoid_skeleton_opening_pairs=[("s-1", "o-1")], rng=random.Random(1),
                )

            self.assertEqual("o-1", result["opening_module"]["id"])
            self.assertEqual(3, result["sampling_meta"]["pair_retries"])
            self.assertTrue(result["sampling_meta"]["pair_conflict"])

    def test_seeded_sampling_matches_probability_and_fingerprint_avoidance_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, entries = make_library(Path(tmp))
            rng = random.Random(20260720)
            results = [self.sample(library, rng=rng) for _ in range(1000)]
            faq_rate = sum(item["faq_module"] is not None for item in results) / len(results)
            table_rate = sum(item["table_module"] is not None for item in results) / len(results)
            free_rate = sum(item["free_slot"] is not None for item in results) / len(results)
            body_counts = [len(item["body_modules"]) for item in results]
            self.assertTrue(.75 <= faq_rate <= .85)
            self.assertTrue(.55 <= table_rate <= .65)
            self.assertTrue(.09 <= free_rate <= .15)
            self.assertTrue(.25 <= body_counts.count(0) / 1000 <= .35)
            self.assertTrue(.45 <= body_counts.count(1) / 1000 <= .55)
            self.assertTrue(.15 <= body_counts.count(2) / 1000 <= .25)

            fingerprint = f"{entries['comparison']['id']}×{entries['opening_a']['id']}"
            baseline = [self.sample(library, rng=random.Random(seed))["sampling_meta"]["fingerprint"] for seed in range(1000)]
            avoided = [
                self.sample(library, rng=random.Random(seed), recent_combos=[fingerprint])["sampling_meta"]
                for seed in range(1000)
            ]
            self.assertGreater(baseline.count(fingerprint), 100)
            self.assertLess(sum(item["fingerprint"] == fingerprint for item in avoided), baseline.count(fingerprint) / 3)
            self.assertTrue(any(item["fingerprint_retries"] for item in avoided))

    def test_generates_valid_brief_with_fixed_shape_and_bans_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            sample = self.sample(library)
            calls = []

            def fake_ai_json(prompt, max_tokens):
                calls.append((prompt, max_tokens))
                return {
                    "title_candidates": ["标题一", "标题二"],
                    "angle_statement": "以异地在职者为主线",
                    "sections": [
                        {"id": 1, "功能": "开头功能", "要点": "引用资料", "引用": ["客户资料 > 事实"], "字数": 200},
                        {"id": 2, "功能": "正文功能", "要点": "补充资料", "引用": ["客户资料 > 服务"], "字数": 600},
                    ],
                    "bans": ["禁止包过"],
                    "dedup_hints": "避开最近组合",
                }

            brief = generate_planning_brief(
                sample,
                customer_material_text="## 表述边界与风险提醒\n限制使用：录取率只能以官方发布为准。",
                competitor_markdown="## 宣传主张\n某竞品通过率第一。",
                content_upload_text="独立上传事实",
                ai_json_fn=fake_ai_json,
            )

            self.assertEqual(brief["title_candidates"], ["标题一", "标题二"])
            self.assertEqual(len(brief["sections"]), len(sample["skeleton"]["payload"]["sections"]))
            self.assertEqual(calls[0][1], 8000)
            self.assertIn("限制使用：录取率只能以官方发布为准", calls[0][0])
            self.assertIn("某竞品通过率第一", calls[0][0])
            self.assertIn("不得替换、不得弃用", calls[0][0])

    def test_empty_brief_retries_once_then_raises_without_a_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            calls = []
            with self.assertRaisesRegex(ValueError, "empty_planning_brief_response"):
                generate_planning_brief(
                    self.sample(library), ai_json_fn=lambda prompt, max_tokens: calls.append(prompt) or "",
                )
            self.assertEqual(len(calls), 2)

    def test_invalid_json_error_retries_once_then_uses_valid_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            sample = self.sample(library, faq_questions=[])
            calls = []
            valid_brief = {
                "title_candidates": ["标题一", "标题二"],
                "angle_statement": "主线",
                "sections": [
                    {"id": 1, "功能": "开头", "要点": "施工指令", "引用": [], "字数": 200},
                    {"id": 2, "功能": "正文", "要点": "施工指令", "引用": [], "字数": 500},
                ],
                "bans": [],
                "dedup_hints": "避让",
            }

            def invalid_once_then_valid(_prompt, _max_tokens):
                calls.append(1)
                if len(calls) == 1:
                    raise json.JSONDecodeError("Expecting value", "", 0)
                return valid_brief

            result = generate_planning_brief(sample, ai_json_fn=invalid_once_then_valid)

            self.assertEqual(result, valid_brief)
            self.assertEqual(len(calls), 2)

    def test_invalid_brief_schema_fails_without_a_partial_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            with self.assertRaisesRegex(ValueError, "invalid_planning_brief"):
                generate_planning_brief(self.sample(library), ai_json_fn=lambda prompt, max_tokens: {"title_candidates": []})

    def test_free_slot_is_explicitly_instructed_as_self_authored(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            sample = self.sample(library)
            sample["free_slot"] = "opening_module"
            sample["opening_module"] = None

            prompt = build_planning_brief_prompt(sample)

            self.assertIn("开头：自由自拟", prompt)

    def test_planning_prompt_marks_customer_and_competitor_as_internal_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            prompt = build_planning_brief_prompt(self.sample(library))

            self.assertIn("客户/竞品是内部称谓，不得出现在成文", prompt)
            self.assertIn("涉及机构时一律使用机构名称", prompt)

    def test_comparison_prompt_requires_multi_organization_block_without_affecting_intro(self):
        with tempfile.TemporaryDirectory() as tmp:
            library, _ = make_library(Path(tmp))
            calls = []

            def fake_ai_json(prompt, _max_tokens):
                calls.append(prompt)
                return {
                    "title_candidates": ["标题一", "标题二"],
                    "angle_statement": "主线",
                    "sections": [
                        {"id": 1, "功能": "开头", "要点": "施工指令", "引用": [], "字数": 200},
                        {"id": 2, "功能": "正文", "要点": "施工指令", "引用": [], "字数": 500},
                    ],
                    "bans": [], "dedup_hints": "避让",
                }

            generate_planning_brief(self.sample(library), ai_json_fn=fake_ai_json)
            generate_planning_brief(self.sample(library, parent_type="介绍型"), ai_json_fn=fake_ai_json)
            comparison_prompt, intro_prompt = calls

            self.assertIn("多机构对比块必须存在", comparison_prompt)
            self.assertIn("本次品牌第一个介绍、不强行推荐", comparison_prompt)
            self.assertIn("不得使用推荐等级词汇和分档标签", comparison_prompt)
            self.assertIn("组的呈现顺序不代表排名", comparison_prompt)
            self.assertNotIn("多机构对比块必须存在", intro_prompt)
            self.assertNotIn("本次品牌第一个介绍、不强行推荐", intro_prompt)


if __name__ == "__main__":
    unittest.main()
