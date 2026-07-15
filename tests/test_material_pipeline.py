import json
import tempfile
import unittest
from pathlib import Path


class MaterialPipelineTests(unittest.TestCase):
    def test_runs_three_stage_package_pipeline_and_writes_latest_files(self):
        from services.material_pipeline import (
            load_latest_material_package_result,
            run_material_package_pipeline,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "uploads" / "client-1"
            output_dir = root / "material_packages" / "client-1"
            package_dir.mkdir(parents=True)
            (package_dir / "profile.txt").write_text("Brand facts.\nKeep this line.", encoding="utf-8")
            (package_dir / "noise.txt").write_text("Third party listing only.", encoding="utf-8")

            def ask_filter_json(_prompt, _max_tokens):
                raise AssertionError("fewer than three readable units should skip filter LLM")

            def ask_reducer_json(prompt, max_tokens):
                self.assertIn('"delete_unit"', prompt)
                return {
                    "results": [
                        {"unit_id": "noise.txt", "delete_unit": True, "delete_ranges": []},
                        {"unit_id": "profile.txt", "delete_unit": False, "delete_ranges": []},
                    ]
                }

            expected_markdown = "# 客户资料注入包\n\nBrand facts."

            def ask_output_text(prompt, max_tokens):
                self.assertIn("Brand facts.", prompt)
                self.assertNotIn("Third party listing only.", prompt)
                return expected_markdown

            status = run_material_package_pipeline(
                package_dir,
                output_dir,
                ask_filter_json=ask_filter_json,
                ask_reducer_json=ask_reducer_json,
                ask_output_text=ask_output_text,
            )

            self.assertTrue(status["ok"])
            self.assertEqual(status["filter"]["readable_units"], 2)
            self.assertEqual(status["filter"]["kept_units"], 2)
            self.assertEqual(status["reducer"]["reduced_units"], 1)
            self.assertEqual(status["output"]["markdown_chars"], len(expected_markdown))
            self.assertEqual((output_dir / "latest_injection.md").read_text(encoding="utf-8"), expected_markdown)
            self.assertTrue((output_dir / "latest_filter.json").exists())
            self.assertTrue((output_dir / "latest_reducer.json").exists())
            self.assertTrue((output_dir / "latest_status.json").exists())

            loaded = load_latest_material_package_result(output_dir)
            self.assertEqual(loaded["markdown"], expected_markdown)
            self.assertEqual(loaded["status"]["status"], "completed")
            self.assertEqual(json.loads((output_dir / "latest_status.json").read_text(encoding="utf-8"))["status"], "completed")


if __name__ == "__main__":
    unittest.main()
