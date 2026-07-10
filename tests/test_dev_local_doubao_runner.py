import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DevLocalDoubaoRunnerTests(unittest.TestCase):
    def test_script_can_be_run_directly_for_help(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "dev_local_doubao_runner.py"),
                "--help",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--client-id", result.stdout)
        self.assertIn("--group-id", result.stdout)

    def test_runs_local_group_and_persists_raw_records(self):
        from scripts.dev_local_doubao_runner import run_local_doubao_group

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "clients.json").write_text(
                json.dumps([
                    {
                        "id": "client-1",
                        "name": "Test Client",
                        "brand": "Test Brand",
                    }
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "probe_groups.json").write_text(
                json.dumps({
                    "client-1": [
                        {
                            "id": "group-1",
                            "name": "Main Group",
                            "questions": ["question one", "question two"],
                        }
                    ]
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "settings.json").write_text("{}", encoding="utf-8")

            calls = []

            def fake_run_crawler(platform, questions, **kwargs):
                calls.append({"platform": platform, "questions": questions, "kwargs": kwargs})
                return {
                    "ok": True,
                    "total": 2,
                    "success": 2,
                    "results": [
                        {
                            "ok": True,
                            "question": "question one",
                            "answer": "Test Brand appears in answer one",
                            "refs": [{"title": "Ref One", "url": "https://example.com/1", "platform": "example"}],
                        },
                        {
                            "ok": True,
                            "question": "question two",
                            "answer": "answer two",
                            "refs": [],
                        },
                    ],
                }

            result = run_local_doubao_group(
                client_id="client-1",
                group_id="group-1",
                data_dir=data_dir,
                run_crawler=fake_run_crawler,
                uid_fn=iter(["raw-1", "daily-1", "raw-2", "daily-2"]).__next__,
                today_fn=lambda: "2026-07-10",
                now_fn=lambda: "2026-07-10 14:00",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["saved"], 2)
            self.assertEqual(calls[0]["platform"], "doubao")
            self.assertEqual(calls[0]["questions"], ["question one", "question two"])

            records = json.loads((data_dir / "raw_records.json").read_text(encoding="utf-8"))
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["client_id"], "client-1")
            self.assertEqual(records[0]["group_id"], "group-1")
            self.assertEqual(records[0]["brand"], "Test Brand")
            self.assertEqual(records[0]["source_platform"], "doubao")
            self.assertEqual(records[0]["crawler_engine"], "local_dev_node")
            self.assertTrue(records[0]["brand_mentioned"])
            self.assertEqual(records[0]["refs"][0]["title"], "Ref One")

            daily = json.loads((data_dir / "raw" / "client-1" / "2026-07-10.json").read_text(encoding="utf-8"))
            self.assertEqual(daily["client_id"], "client-1")
            self.assertEqual(len(daily["records"]), 2)


if __name__ == "__main__":
    unittest.main()
