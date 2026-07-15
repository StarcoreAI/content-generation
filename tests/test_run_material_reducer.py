import unittest


class RunMaterialReducerTests(unittest.TestCase):
    def test_material_reducer_model_can_be_overridden(self):
        from scripts.run_material_reducer import choose_material_reducer_model

        self.assertEqual(
            choose_material_reducer_model(
                {
                    "model": "deepseek-chat",
                    "material_reducer_model": "deepseek-v4-pro",
                }
            ),
            "deepseek-v4-pro",
        )

    def test_selects_only_kept_units_in_filter_order(self):
        from scripts.run_material_reducer import kept_unit_ids, select_units_by_id

        filter_report = {
            "results": [
                {"unit_id": "a.docx", "status": "core"},
                {"unit_id": "b.docx", "status": "redundant"},
                {"unit_id": "c.docx", "status": "representative"},
            ]
        }
        units = [
            {"unit_id": "c.docx", "text": "C"},
            {"unit_id": "a.docx", "text": "A"},
            {"unit_id": "b.docx", "text": "B"},
        ]

        self.assertEqual(kept_unit_ids(filter_report), ["a.docx", "c.docx"])
        self.assertEqual(
            [unit["unit_id"] for unit in select_units_by_id(units, ["a.docx", "c.docx"])],
            ["a.docx", "c.docx"],
        )

    def test_build_report_counts_nonempty_reductions(self):
        from scripts.run_material_reducer import build_report

        report = build_report(
            "reports/filter.json",
            {"package_path": "materials/pkg"},
            [{"unit_id": "a.docx"}, {"unit_id": "b.docx"}],
            "deepseek-chat",
            [
                {"unit_id": "a.docx", "reduced_text": "A"},
                {"unit_id": "b.docx", "reduced_text": ""},
            ],
        )

        self.assertEqual(report["input_count"], 2)
        self.assertEqual(report["reduced_count"], 1)
        self.assertEqual(report["model"], "deepseek-chat")

    def test_reducer_report_records_one_package_error(self):
        from scripts.run_material_reducer import reduce_units_for_report

        def ask_json(prompt, max_tokens):
            raise ValueError("invalid reducer JSON response")

        results, errors = reduce_units_for_report([{"unit_id": "a.docx", "text": "A"}], ask_json)

        self.assertEqual(results, [])
        self.assertEqual(errors[0]["unit_id"], "__package__")
        self.assertIn("invalid reducer JSON response", errors[0]["error"])


if __name__ == "__main__":
    unittest.main()
