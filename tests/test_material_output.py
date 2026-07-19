import unittest


class MaterialOutputTests(unittest.TestCase):
    def test_builds_markdown_injection_package_in_one_call(self):
        from services.material_output import build_material_output

        reducer_report = {
            "package_path": "materials/customer",
            "results": [
                {"unit_id": "profile.docx", "reduced_text": "客户基础信息。"},
                {"unit_id": "empty.xlsx::Sheet1", "reduced_text": ""},
                {"unit_id": "case.docx", "reduced_text": "案例素材。"},
            ],
        }
        calls = []

        def ask_text(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return "# 客户资料注入包\n\n## 客户基础信息\n- 客户基础信息。"

        markdown = build_material_output(reducer_report, ask_text=ask_text)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 8192)
        self.assertIn("unit_id: profile.docx", calls[0][0])
        self.assertIn("客户基础信息。", calls[0][0])
        self.assertNotIn("empty.xlsx::Sheet1", calls[0][0])
        self.assertNotIn("JSON", calls[0][0])
        self.assertTrue(markdown.startswith("# 客户资料注入包"))

    def test_rejects_empty_markdown_response(self):
        from services.material_output import build_material_output

        with self.assertRaisesRegex(ValueError, "empty material output"):
            build_material_output(
                {"results": [{"unit_id": "profile.docx", "reduced_text": "客户基础信息。"}]},
                ask_text=lambda *_args, **_kwargs: "   ",
            )

    def test_default_rules_are_markdown_only_and_not_article(self):
        from services.material_output import DEFAULT_OUTPUT_RULES

        self.assertIn("Markdown", DEFAULT_OUTPUT_RULES)
        self.assertIn("not a promotional article", DEFAULT_OUTPUT_RULES)
        self.assertIn("up to 6", DEFAULT_OUTPUT_RULES)
        self.assertNotIn("JSON", DEFAULT_OUTPUT_RULES)

    def test_output_prompt_organizes_by_eight_customer_material_directions(self):
        from services.material_output import build_material_output

        prompts = []

        def ask_text(prompt, max_tokens):
            prompts.append(prompt)
            return "# 客户资料注入包\n\n## 1. 品牌基础\n- 测试"

        build_material_output(
            {"results": [{"unit_id": "profile.txt", "reduced_text": "品牌基础资料"}]},
            ask_text=ask_text,
        )

        prompt = prompts[0]
        for heading in [
            "## 1. 品牌基础",
            "## 2. 产品与服务",
            "## 3. 核心优势",
            "## 4. 目标人群与需求痛点",
            "## 5. 价格与费用表达",
            "## 6. 信任凭证",
            "## 7. 合规风险表述",
            "## 8. 行业公共背景",
            "## 缺口与检索提示",
        ]:
            self.assertIn(heading, prompt)
        self.assertIn("资料中没有的，不要编造", prompt)
        self.assertIn("推断，待确认", prompt)
        self.assertIn("限制使用", prompt)


if __name__ == "__main__":
    unittest.main()
