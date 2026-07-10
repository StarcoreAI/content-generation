import json
import tempfile
import unittest
from pathlib import Path

from scripts.import_missing_raw_records import import_missing_records, record_fingerprint


def record(record_id, question, answer, platform="qwen", round_num=1, today="2026-07-09"):
    return {
        "id": record_id,
        "client_id": "client-1",
        "group_id": "group-1",
        "brand": "Test Brand",
        "question": question,
        "round": round_num,
        "today": today,
        "source_platform": platform,
        "answer": answer,
        "refs": [{"title": "Ref", "url": "https://example.com/a"}],
    }


class ImportMissingRawRecordsTests(unittest.TestCase):
    def test_fingerprint_ignores_record_id(self):
        first = record("local-id", "Question", "Answer")
        second = record("cloud-id", "Question", "Answer")

        self.assertEqual(record_fingerprint(first), record_fingerprint(second))

    def test_dry_run_does_not_modify_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.json"
            target = tmp_path / "target.json"
            source.write_text(json.dumps([record("new-id", "Q2", "A2")], ensure_ascii=False), encoding="utf-8")
            target.write_text(json.dumps([record("old-id", "Q1", "A1")], ensure_ascii=False), encoding="utf-8")

            result = import_missing_records(source, target, apply=False)

            self.assertEqual(result["append_count"], 1)
            self.assertEqual(len(json.loads(target.read_text(encoding="utf-8"))), 1)
            self.assertFalse(list(tmp_path.glob("target.json.bak_import_*")))

    def test_apply_appends_only_missing_records_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            existing = record("cloud-id", "Q1", "A1")
            duplicate = record("different-local-id", "Q1", "A1")
            missing = record("new-id", "Q2", "A2", platform="deepseek")
            source = tmp_path / "source.json"
            target = tmp_path / "target.json"
            source.write_text(json.dumps([duplicate, missing], ensure_ascii=False), encoding="utf-8")
            target.write_text(json.dumps([existing], ensure_ascii=False), encoding="utf-8")

            result = import_missing_records(source, target, apply=True)

            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(result["append_count"], 1)
            self.assertEqual(result["duplicate_count"], 1)
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved[-1]["question"], "Q2")
            self.assertTrue(list(tmp_path.glob("target.json.bak_import_*")))

    def test_apply_reassigns_colliding_id_for_different_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.json"
            target = tmp_path / "target.json"
            source.write_text(json.dumps([record("same-id", "Q2", "A2")], ensure_ascii=False), encoding="utf-8")
            target.write_text(json.dumps([record("same-id", "Q1", "A1")], ensure_ascii=False), encoding="utf-8")

            result = import_missing_records(source, target, apply=True)

            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(result["id_collision_count"], 1)
            self.assertEqual(len(saved), 2)
            self.assertNotEqual(saved[-1]["id"], "same-id")
            self.assertEqual(saved[-1]["import_source_id"], "same-id")


if __name__ == "__main__":
    unittest.main()
