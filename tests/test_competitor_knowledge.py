import threading
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import app as geo_app
from services.competitor_knowledge import collect_high_frequency_article_sources
from tests.test_app_core import isolated_app_data


class CompetitorKnowledgeTests(unittest.TestCase):
    def test_competitor_sync_enqueues_background_job(self):
        with isolated_app_data():
            cid = "client-competitor"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "client"}])
            with patch.object(geo_app.threading, "Thread") as start_thread:
                response = geo_app.app.test_client().post(f"/api/knowledge/competitors/{cid}/sync", json={})

            self.assertEqual(202, response.status_code)
            self.assertEqual("queued", response.get_json()["job"]["status"])
            start_thread.assert_called_once()

    def test_competitor_sync_job_status_hides_master_content(self):
        with isolated_app_data() as tmp:
            cid, job_id = "client-competitor", "job-competitor"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "client"}])
            geo_app.save(str(Path(tmp) / "competitor_knowledge_jobs" / cid / f"{job_id}.json"), {
                "id": job_id, "client_id": cid, "status": "completed", "message": "completed",
                "merged_count": 2, "master": {"content": "large payload"},
            })

            response = geo_app.app.test_client().get(f"/api/knowledge/competitors/{cid}/sync-jobs/{job_id}")

            self.assertEqual(200, response.status_code)
            self.assertEqual(2, response.get_json()["job"]["merged_count"])
            self.assertNotIn("master", response.get_json()["job"])

    def test_competitor_fact_batch_cache_skips_unchanged_model_extraction(self):
        records = [{"refs": [{"url": "https://example.com/a", "title": "文章"}]}]
        calls = 0

        def ask_text(*_args):
            nonlocal calls
            calls += 1
            return "# 竞品\n\n## 竞品 A\n\n- 可核对事实"

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(geo_app, "competitor_knowledge_context", return_value=("2026-08-02", records, [], "")), \
                    patch.object(geo_app, "competitor_knowledge_article_cache_path", return_value=Path(tmp) / "sources.json"), \
                    patch.object(geo_app, "competitor_knowledge_facts_cache_path", return_value=Path(tmp) / "facts.json"):
                first = geo_app.competitor_knowledge_input("client-a", ask_text=ask_text, fetch_fn=lambda _url: {"ok": True, "content": "正文", "title": "文章"})
                second = geo_app.competitor_knowledge_input("client-a", ask_text=ask_text, fetch_fn=lambda _url: {"ok": True, "content": "正文", "title": "文章"})

        self.assertEqual(first, second)
        self.assertEqual(calls, 1)

    def test_failed_fetch_stays_in_source_list_without_aborting_other_sources(self):
        records = [{"refs": [
            {"url": "https://example.com/fail", "title": "fail"},
            {"url": "https://example.com/ok", "title": "ok"},
        ]}]

        def fetch(url):
            if url.endswith("/fail"):
                raise RuntimeError("unavailable")
            return {"ok": True, "content": "usable body", "title": "ok"}

        sources = collect_high_frequency_article_sources(records, {}, fetch, limit=2)

        self.assertEqual([item["url"] for item in sources], ["https://example.com/fail", "https://example.com/ok"])
        self.assertFalse(sources[0]["ok"])
        self.assertTrue(sources[1]["ok"])

    def test_distinct_high_frequency_sources_fetch_at_most_three_at_once(self):
        records = [{"refs": [{"url": f"https://example.com/{index}", "title": str(index)} for index in range(4)]}]
        active = 0
        peak = 0
        guard = threading.Lock()

        def fetch(url):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return {"ok": True, "content": url, "title": url}

        sources = collect_high_frequency_article_sources(records, {}, fetch, limit=4)

        self.assertEqual([item["url"] for item in sources], [f"https://example.com/{index}" for index in range(4)])
        self.assertEqual(3, peak)


if __name__ == "__main__":
    unittest.main()
