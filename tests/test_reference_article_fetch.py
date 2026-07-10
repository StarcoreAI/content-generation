import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _FakeHeaders:
    def get_content_charset(self):
        return "utf-8"


class _FakeResponse:
    headers = _FakeHeaders()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size):
        return b"<html><head><title>empty</title></head><body></body></html>"


class ReferenceArticleFetchTests(unittest.TestCase):
    def test_browser_fetch_reads_body_after_goto_timeout(self):
        from services.article_fetcher import fetch_article_text_with_browser

        class FakePage:
            def goto(self, *args, **kwargs):
                raise TimeoutError("navigation timed out")

            def wait_for_load_state(self, *args, **kwargs):
                return None

            def title(self):
                return "Partial page"

            def locator(self, selector):
                if selector != "body":
                    raise AssertionError(selector)
                return self

            def inner_text(self, **kwargs):
                return "正文已经加载 " * 80

        class FakeBrowser:
            def new_page(self, **kwargs):
                return FakePage()

            def close(self):
                return None

        class FakeChromium:
            def launch(self, **kwargs):
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        result = fetch_article_text_with_browser(
            "https://example.com/slow",
            playwright_factory=lambda: FakePlaywright(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["fetch_method"], "browser")
        self.assertEqual(result["title"], "Partial page")
        self.assertIn("正文已经加载", result["content"])

    def test_fetch_article_text_uses_browser_fallback_when_static_content_is_empty(self):
        from services.article_fetcher import fetch_article_text

        calls = []

        def fake_browser_fetch(url, **kwargs):
            calls.append({"url": url, "kwargs": kwargs})
            return {
                "ok": True,
                "url": url,
                "title": "Browser title",
                "description": "",
                "content": "Browser extracted article body " * 20,
                "error": "",
                "fetch_method": "browser",
            }

        with patch("services.article_fetcher.urlopen", return_value=_FakeResponse()):
            result = fetch_article_text(
                "https://example.com/article",
                browser_fallback=True,
                browser_fetch_fn=fake_browser_fetch,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["fetch_method"], "browser")
        self.assertEqual(calls[0]["url"], "https://example.com/article")
        self.assertIn("Browser extracted", result["content"])

    def test_dev_fetch_reference_articles_writes_deduped_daily_output(self):
        from scripts.dev_fetch_reference_articles import run_fetch_reference_articles

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            raw_dir = data_dir / "raw" / "client-1"
            raw_dir.mkdir(parents=True)
            (raw_dir / "2026-07-10.json").write_text(
                json.dumps({
                    "client_id": "client-1",
                    "records": [
                        {
                            "question": "q1",
                            "refs": [
                                {"title": "A", "url": "https://example.com/a", "platform": "p1"},
                                {"title": "B", "url": "https://example.com/b", "platform": "p2"},
                            ],
                        },
                        {
                            "question": "q2",
                            "refs": [
                                {"title": "A again", "url": "https://example.com/a", "platform": "p1"},
                            ],
                        },
                    ],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            def fake_fetch(url, **kwargs):
                if url.endswith("/a"):
                    return {
                        "ok": True,
                        "url": url,
                        "title": "Fetched A",
                        "description": "",
                        "content": "正文" * 120,
                        "error": "",
                        "fetch_method": "browser",
                    }
                return {
                    "ok": False,
                    "url": url,
                    "title": "",
                    "description": "",
                    "content": "",
                    "error": "empty_content",
                    "fetch_method": "static",
                }

            result = run_fetch_reference_articles(
                client_id="client-1",
                date="2026-07-10",
                data_dir=data_dir,
                fetch_fn=fake_fetch,
            )

            self.assertEqual(result["total"], 2)
            self.assertEqual(result["fetched_ok"], 1)
            self.assertEqual(result["fetched_failed"], 1)

            output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(output["client_id"], "client-1")
            self.assertEqual(output["date"], "2026-07-10")
            self.assertEqual(len(output["articles"]), 2)
            self.assertEqual(output["articles"][0]["url"], "https://example.com/a")
            self.assertEqual(output["articles"][0]["citation_count"], 2)
            self.assertTrue(output["articles"][0]["ok"])
            self.assertEqual(output["articles"][0]["content_len"], 240)
            self.assertFalse(output["articles"][1]["ok"])


if __name__ == "__main__":
    unittest.main()
