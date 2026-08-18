import tempfile
import unittest
from pathlib import Path

from services import crawl_jobs
from services.storage import save_json


class CrawlJobProgressTests(unittest.TestCase):
    def test_progress_updates_running_job_and_clamps_completed_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            save_json(path, [{
                "id": "job-1",
                "status": "running",
                "created_by": "operator",
                "updated_at": "old",
            }])

            job = crawl_jobs.update_job_progress(
                path,
                "job-1",
                {"completed": 9, "total": 5, "message": "本地浏览器正在爬取"},
                lambda: "2026-08-18 14:00",
                created_by="operator",
            )

            self.assertEqual(job["progress_completed"], 5)
            self.assertEqual(job["progress_total"], 5)
            self.assertEqual(job["heartbeat_at"], "2026-08-18 14:00")
            self.assertEqual(job["updated_at"], "2026-08-18 14:00")

    def test_progress_does_not_mutate_terminal_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            save_json(path, [{
                "id": "job-1",
                "status": "completed",
                "created_by": "operator",
                "updated_at": "finished",
            }])

            job = crawl_jobs.update_job_progress(
                path,
                "job-1",
                {"completed": 1, "total": 1},
                lambda: "2026-08-18 14:00",
                created_by="operator",
            )

            self.assertEqual(job["updated_at"], "finished")
            self.assertNotIn("heartbeat_at", job)


if __name__ == "__main__":
    unittest.main()
