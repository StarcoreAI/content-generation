import threading
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import app as geo_app
from services.competitor_knowledge import collect_high_frequency_article_sources


class CompetitorKnowledgeTests(unittest.TestCase):
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
