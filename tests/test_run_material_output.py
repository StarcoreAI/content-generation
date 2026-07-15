import unittest


class RunMaterialOutputTests(unittest.TestCase):
    def test_material_output_model_can_be_overridden(self):
        from scripts.run_material_output import choose_material_output_model

        self.assertEqual(
            choose_material_output_model(
                {
                    "model": "deepseek-chat",
                    "material_output_model": "deepseek-v4-pro",
                }
            ),
            "deepseek-v4-pro",
        )

    def test_default_output_path_uses_markdown_extension(self):
        from scripts.run_material_output import default_output_path

        path = default_output_path({"package_path": "materials/customer package"})

        self.assertEqual(path.suffix, ".md")
        self.assertIn("material_injection_customer-package_", str(path))

    def test_output_report_records_one_package_error(self):
        from scripts.run_material_output import build_output_for_report

        def ask_text(prompt, max_tokens):
            raise ValueError("model failed")

        markdown, errors = build_output_for_report(
            {"results": [{"unit_id": "profile.docx", "reduced_text": "客户基础信息。"}]},
            ask_text,
        )

        self.assertEqual(markdown, "")
        self.assertEqual(errors[0]["unit_id"], "__package__")
        self.assertIn("model failed", errors[0]["error"])


if __name__ == "__main__":
    unittest.main()
