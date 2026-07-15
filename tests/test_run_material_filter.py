import unittest


class RunMaterialFilterTests(unittest.TestCase):
    def test_material_filter_prefers_chat_model_over_extraction_model(self):
        from scripts.run_material_filter import choose_material_filter_model

        self.assertEqual(
            choose_material_filter_model(
                {
                    "model": "deepseek-chat",
                    "extraction_model": "deepseek-v4-pro",
                }
            ),
            "deepseek-chat",
        )

    def test_material_filter_model_can_be_overridden(self):
        from scripts.run_material_filter import choose_material_filter_model

        self.assertEqual(
            choose_material_filter_model(
                {
                    "model": "deepseek-chat",
                    "material_filter_model": "deepseek-v4-pro",
                }
            ),
            "deepseek-v4-pro",
        )

    def test_filter_report_uses_one_package_call(self):
        from scripts.run_material_filter import filter_units_for_report

        units = [
            {"unit_id": "profile.docx", "text": "客户简介"},
            {"unit_id": "case.docx", "text": "客户案例"},
            {"unit_id": "service.docx", "text": "customer service"},
        ]
        calls = []

        def ask_json(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return {
                "results": [
                    {"unit_id": "profile.docx", "status": "core"},
                    {"unit_id": "case.docx", "status": "representative"},
                    {"unit_id": "service.docx", "status": "core"},
                ]
            }

        results, errors = filter_units_for_report(units, ask_json)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 4096)
        self.assertEqual(
            results,
            [
                {"unit_id": "profile.docx", "status": "core"},
                {"unit_id": "case.docx", "status": "representative"},
                {"unit_id": "service.docx", "status": "core"},
            ],
        )
        self.assertEqual(errors, [])

    def test_report_counts_only_core_and_representative_as_kept(self):
        from scripts.run_material_filter import build_report

        units = [
            {"unit_id": "profile.docx", "path": "profile.docx"},
            {"unit_id": "case.docx", "path": "case.docx"},
            {"unit_id": "duplicate.docx", "path": "duplicate.docx"},
        ]
        report = build_report(
            "package",
            {},
            units,
            [
                {"unit_id": "profile.docx", "status": "core"},
                {"unit_id": "case.docx", "status": "representative"},
                {"unit_id": "duplicate.docx", "status": "redundant"},
            ],
        )

        self.assertEqual(report["kept_count"], 2)
        self.assertEqual(
            [item["unit_id"] for item in report["kept_units"]],
            ["profile.docx", "case.docx"],
        )
        self.assertNotIn("useful_count", report)
        self.assertNotIn("useful_units", report)

    def test_filter_report_records_one_package_error(self):
        from scripts.run_material_filter import filter_units_for_report

        units = [
            {"unit_id": "profile.docx", "text": "客户简介"},
            {"unit_id": "case.docx", "text": "客户案例"},
            {"unit_id": "service.docx", "text": "customer service"},
        ]

        def ask_json(prompt, max_tokens):
            raise ValueError("invalid package JSON response")

        results, errors = filter_units_for_report(units, ask_json)

        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["unit_id"], "__package__")
        self.assertIn("invalid package JSON response", errors[0]["error"])


if __name__ == "__main__":
    unittest.main()
