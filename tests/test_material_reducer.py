import unittest


class MaterialReducerTests(unittest.TestCase):
    def test_reduces_all_units_in_one_package_call(self):
        from services.material_reducer import reduce_material_units

        units = [
            {
                "unit_id": "profile.docx",
                "path": "profile.docx",
                "kind": "text",
                "text": "Brand facts.\nTemplate note to remove.",
            },
            {
                "unit_id": "catalog.xlsx::Sheet1",
                "path": "catalog.xlsx",
                "kind": "spreadsheet_sheet",
                "text": "Third party listing only.",
            },
        ]
        calls = []

        def ask_json(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return {
                "results": [
                    {"unit_id": "profile.docx", "delete_ranges": [{"start": 2, "end": 2}]},
                    {"unit_id": "catalog.xlsx::Sheet1", "delete_unit": True},
                ]
            }

        results = reduce_material_units(units, ask_json=ask_json)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 8192)
        self.assertIn("unit_id: profile.docx", calls[0][0])
        self.assertIn("[001] Brand facts.", calls[0][0])
        self.assertIn("[002] Template note to remove.", calls[0][0])
        self.assertIn('"delete_unit"', calls[0][0])
        self.assertIn('"delete_ranges"', calls[0][0])
        self.assertNotIn('"useful"', calls[0][0])
        self.assertEqual(results[0]["reduced_text"], "Brand facts.")
        self.assertEqual(results[1]["reduced_text"], "")

    def test_rejects_missing_reducer_results(self):
        from services.material_reducer import reduce_material_units

        with self.assertRaisesRegex(ValueError, "missing reducer results.*b.docx"):
            reduce_material_units(
                [
                    {"unit_id": "a.docx", "text": "A"},
                    {"unit_id": "b.docx", "text": "B"},
                ],
                ask_json=lambda *_args, **_kwargs: {
                    "results": [{"unit_id": "a.docx", "delete_ranges": []}]
                },
            )

    def test_rejects_unknown_reducer_unit_id(self):
        from services.material_reducer import reduce_material_units

        with self.assertRaisesRegex(ValueError, "unknown reducer unit_id.*other.docx"):
            reduce_material_units(
                [{"unit_id": "a.docx", "text": "A"}],
                ask_json=lambda *_args, **_kwargs: {
                    "results": [{"unit_id": "other.docx", "delete_ranges": []}]
                },
            )

    def test_default_rules_are_domain_neutral(self):
        from services.material_reducer import DEFAULT_REDUCER_RULES

        self.assertIn("customer", DEFAULT_REDUCER_RULES)
        self.assertIn("delete", DEFAULT_REDUCER_RULES.lower())
        self.assertIn("standalone marketing statistics", DEFAULT_REDUCER_RULES)
        self.assertIn("target audiences", DEFAULT_REDUCER_RULES)
        self.assertIn("use cases", DEFAULT_REDUCER_RULES)
        self.assertIn("conflicting facts", DEFAULT_REDUCER_RULES)
        self.assertIn("not to rewrite or summarize", DEFAULT_REDUCER_RULES)
        self.assertIn("representative original expressions", DEFAULT_REDUCER_RULES)
        self.assertNotIn("education", DEFAULT_REDUCER_RULES.lower())
        self.assertNotIn("province", DEFAULT_REDUCER_RULES.lower())
        self.assertNotIn("school", DEFAULT_REDUCER_RULES.lower())


if __name__ == "__main__":
    unittest.main()
