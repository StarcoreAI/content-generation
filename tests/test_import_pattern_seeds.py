import tempfile
import unittest
import json
from pathlib import Path

from scripts.import_pattern_seeds import import_pattern_seeds
from services.pattern_library import PatternLibrary


class ImportPatternSeedsTests(unittest.TestCase):
    def test_neutralized_seed_and_library_patterns_keep_conditions_not_institution_recommendations(self):
        root = Path(__file__).resolve().parents[1]
        seeds = json.loads((root / "docs" / "pattern-library-seeds-v1.json").read_text(encoding="utf-8"))
        global_entries = json.loads((root / "data" / "pattern_library" / "global.json").read_text(encoding="utf-8"))["entries"]
        adult_entries = json.loads((root / "data" / "pattern_library" / "industry_成人教育.json").read_text(encoding="utf-8"))["entries"]
        seed_pattern = next(item for item in seeds["seeds"] if item["seed_id"] == "ED-G01")["payload"]["pattern"]
        global_pattern = next(item for item in global_entries if item["sources"][0]["url"] == "seed://ED-G01")["payload"]["pattern"]
        faq_pattern = next(item for item in adult_entries if item["name"] == "场景搜索词直答型")["payload"]["pattern"]

        self.assertIn("用户类型 -> 优先考虑方向 -> 理由", seed_pattern)
        self.assertEqual(seed_pattern, global_pattern)
        self.assertIn("不得写具体机构名", seed_pattern)
        self.assertIn("条件式结论", faq_pattern)
        self.assertIn("不得把单一机构写成最优选择或唯一答案", faq_pattern)

    def test_import_is_idempotent_and_uses_global_seed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pattern_library"

            first = import_pattern_seeds(library_root=root)
            second = import_pattern_seeds(library_root=root)

            entries = PatternLibrary(root).list_entries("global")
            self.assertEqual(first, {"imported": 11, "skipped": 0})
            self.assertEqual(second, {"imported": 0, "skipped": 11})
            self.assertEqual(len(entries), 11)
            self.assertTrue(all(entry["status"] == "candidate" for entry in entries))
            self.assertEqual(
                {entry["sources"][0]["url"] for entry in entries},
                {
                    "seed://SK-G01", "seed://SK-G02", "seed://SK-G03", "seed://SK-G04",
                    "seed://OP-G01", "seed://OP-G02", "seed://OP-G03", "seed://ED-G01",
                    "seed://ED-G02", "seed://FQ-G01", "seed://TB-G01",
                },
            )


if __name__ == "__main__":
    unittest.main()
