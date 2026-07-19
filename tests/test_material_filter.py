import unittest


class MaterialFilterTests(unittest.TestCase):
    def test_short_unit_uses_full_text(self):
        from services.material_filter import sample_unit_text

        self.assertEqual(sample_unit_text({"text": "完整的短资料"}), "完整的短资料")

    def test_long_unit_samples_head_middle_and_tail_within_budget(self):
        from services.material_filter import sample_unit_text

        text = "HEAD" + "A" * 2000 + "MIDDLE" + "Z" * 2000 + "TAIL"
        preview = sample_unit_text({"text": text}, max_chars=180)

        self.assertLessEqual(len(preview), 180)
        self.assertIn("HEAD", preview)
        self.assertIn("MIDDLE", preview)
        self.assertIn("TAIL", preview)

    def test_filters_all_candidates_in_one_package_call(self):
        from services.material_filter import filter_material_units

        units = [
            {
                "unit_id": "profile.docx",
                "path": "profiles/profile.docx",
                "kind": "text",
                "extract_status": "ok",
                "text": "客户自身简介和服务范围。",
            },
            {
                "unit_id": "case.docx",
                "path": "cases/case.docx",
                "kind": "text",
                "extract_status": "ok",
                "text": "客户自身的代表案例。",
            },
            {
                "unit_id": "service.docx",
                "path": "services/service.docx",
                "kind": "text",
                "extract_status": "ok",
                "text": "customer service process",
            },
        ]
        prompts = []

        def ask_json(prompt, max_tokens):
            prompts.append((prompt, max_tokens))
            return {
                "results": [
                    {"unit_id": "profile.docx", "status": "core"},
                    {"unit_id": "case.docx", "status": "representative"},
                    {"unit_id": "service.docx", "status": "core"},
                ]
            }

        results = filter_material_units(units, ask_json=ask_json)

        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][1], 4096)
        self.assertIn("unit_id: profile.docx", prompts[0][0])
        self.assertIn("unit_id: case.docx", prompts[0][0])
        self.assertIn("完整字符数", prompts[0][0])
        self.assertNotIn('"useful"', prompts[0][0])
        self.assertNotIn('"reason"', prompts[0][0])
        self.assertEqual(
            results,
            [
                {"unit_id": "profile.docx", "status": "core"},
                {"unit_id": "case.docx", "status": "representative"},
                {"unit_id": "service.docx", "status": "core"},
            ],
        )

    def test_keeps_all_readable_units_without_model_when_package_has_fewer_than_three(self):
        from services.material_filter import filter_material_units

        units = [
            {"unit_id": "profile.docx", "extract_status": "ok", "text": "customer profile"},
            {"unit_id": "case.docx", "extract_status": "ok", "text": "customer case"},
        ]

        def ask_json(*_args, **_kwargs):
            raise AssertionError("model should not be called for fewer than three readable units")

        self.assertEqual(
            filter_material_units(units, ask_json=ask_json),
            [
                {"unit_id": "profile.docx", "status": "core"},
                {"unit_id": "case.docx", "status": "core"},
            ],
        )

    def test_package_prompt_identifies_units_from_the_same_source_file(self):
        from services.material_filter import filter_material_units

        units = [
            {
                "unit_id": "details.xlsx::A",
                "path": "details.xlsx",
                "kind": "spreadsheet_sheet",
                "text": "Columns: name | price\nPreview:\nA | 10",
            },
            {
                "unit_id": "details.xlsx::B",
                "path": "details.xlsx",
                "kind": "spreadsheet_sheet",
                "text": "Columns: item | cost\nPreview:\nB | 20",
            },
            {
                "unit_id": "profile.docx",
                "path": "profile.docx",
                "kind": "text",
                "text": "Customer profile",
            },
        ]
        prompts = []

        def ask_json(prompt, max_tokens):
            prompts.append(prompt)
            return {
                "results": [
                    {"unit_id": "details.xlsx::A", "status": "representative"},
                    {"unit_id": "details.xlsx::B", "status": "reference_only"},
                    {"unit_id": "profile.docx", "status": "core"},
                ]
            }

        filter_material_units(units, ask_json=ask_json)

        self.assertIn("same_source_unit_count: 2", prompts[0])
        self.assertIn("同源多单元组", prompts[0])
        self.assertIn("details.xlsx::A | details.xlsx::B", prompts[0])

    def test_exact_duplicate_is_not_sent_to_model(self):
        from services.material_filter import filter_material_units

        units = [
            {"unit_id": "preferred.docx", "text": "Same Customer Facts"},
            {"unit_id": "duplicate.docx", "text": " same  customer\n facts "},
            {"unit_id": "other.docx", "text": "Other Customer Facts"},
        ]
        prompts = []

        def ask_json(prompt, max_tokens):
            prompts.append(prompt)
            return {
                "results": [
                    {"unit_id": "preferred.docx", "status": "core"},
                    {"unit_id": "other.docx", "status": "core"},
                ]
            }

        results = filter_material_units(units, ask_json=ask_json)

        self.assertEqual(len(prompts), 1)
        self.assertIn("unit_id: preferred.docx", prompts[0])
        self.assertNotIn("unit_id: duplicate.docx", prompts[0])
        self.assertEqual(
            results,
            [
                {"unit_id": "preferred.docx", "status": "core"},
                {
                    "unit_id": "duplicate.docx",
                    "status": "exact_duplicate",
                    "duplicate_of": "preferred.docx",
                },
                {"unit_id": "other.docx", "status": "core"},
            ],
        )

    def test_needs_conversion_unit_is_deferred_without_model_judgment(self):
        from services.material_filter import filter_material_units

        units = [
            {
                "unit_id": "legacy.doc",
                "kind": "legacy_office",
                "extract_status": "needs_conversion",
                "text": "不可靠的二进制探测文本",
            },
            {"unit_id": "profile.docx", "extract_status": "ok", "text": "客户简介"},
            {"unit_id": "case.docx", "extract_status": "ok", "text": "customer case"},
        ]
        prompts = []

        def ask_json(prompt, max_tokens):
            prompts.append(prompt)
            return {
                "results": [
                    {"unit_id": "profile.docx", "status": "core"},
                    {"unit_id": "case.docx", "status": "representative"},
                ]
            }

        results = filter_material_units(units, ask_json=ask_json)

        self.assertNotIn("unit_id: legacy.doc", prompts[0])
        self.assertEqual(
            results[0],
            {"unit_id": "legacy.doc", "status": "needs_conversion"},
        )

    def test_default_rules_preserve_eight_direction_material(self):
        from services.material_filter import DEFAULT_FILTER_RULES

        for keyword in [
            "品牌基础",
            "产品与服务",
            "核心优势",
            "目标人群",
            "价格与费用",
            "信任凭证",
            "合规风险",
            "行业公共背景",
        ]:
            self.assertIn(keyword, DEFAULT_FILTER_RULES)
        self.assertIn("缺口与检索提示", DEFAULT_FILTER_RULES)
        self.assertIn("资料没有的，不要编造", DEFAULT_FILTER_RULES)

    def test_rejects_missing_model_decisions(self):
        from services.material_filter import filter_material_units

        units = [
            {"unit_id": "profile.docx", "text": "客户简介"},
            {"unit_id": "case.docx", "text": "客户案例"},
            {"unit_id": "service.docx", "text": "customer service"},
        ]

        with self.assertRaisesRegex(ValueError, "missing filter decisions.*case.docx"):
            filter_material_units(
                units,
                ask_json=lambda *_args, **_kwargs: {
                    "results": [
                        {"unit_id": "profile.docx", "status": "core"},
                    ]
                },
            )

    def test_rejects_unknown_filter_status(self):
        from services.material_filter import filter_material_units

        with self.assertRaisesRegex(ValueError, "unknown filter status.*low_information"):
            filter_material_units(
                [
                    {"unit_id": "noise.rtf", "text": "format noise"},
                    {"unit_id": "profile.docx", "text": "customer profile"},
                    {"unit_id": "case.docx", "text": "customer case"},
                ],
                ask_json=lambda *_args, **_kwargs: {
                    "results": [
                        {"unit_id": "noise.rtf", "status": "low_information"},
                        {"unit_id": "profile.docx", "status": "core"},
                        {"unit_id": "case.docx", "status": "representative"},
                    ]
                },
            )

    def test_default_rules_are_domain_neutral_and_select_representatives(self):
        from services.material_filter import DEFAULT_FILTER_RULES

        self.assertIn("整个资料包", DEFAULT_FILTER_RULES)
        self.assertIn("最多保留 6 个", DEFAULT_FILTER_RULES)
        self.assertIn("拿不准", DEFAULT_FILTER_RULES)
        self.assertNotIn("翼升学", DEFAULT_FILTER_RULES)
        self.assertNotIn("10 省", DEFAULT_FILTER_RULES)

    def test_default_rules_make_repeated_group_caps_override_detail_differences(self):
        from services.material_filter import DEFAULT_FILTER_RULES

        self.assertIn("同一数据集拆分出的多个结构相似单元", DEFAULT_FILTER_RULES)
        self.assertIn("硬性上限", DEFAULT_FILTER_RULES)
        self.assertIn("组内细节不同不能作为全部保留的理由", DEFAULT_FILTER_RULES)


if __name__ == "__main__":
    unittest.main()
