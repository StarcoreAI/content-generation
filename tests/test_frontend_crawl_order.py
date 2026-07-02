import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX_HTML = os.path.join(ROOT, "templates", "index.html")


class FrontendCrawlOrderTests(unittest.TestCase):
    def test_crawl_platform_order_puts_doubao_last_for_all_entry_points(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn(
            "const CRAWL_PLATFORM_ORDER = ['deepseek', 'yuanbao', 'qwen', 'doubao'];",
            html,
        )
        self.assertIn("function sortCrawlPlatforms(platforms)", html)

        logged_in_body = re.search(
            r"async function getLoggedInCrawlPlatforms\(\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(logged_in_body)
        self.assertIn("return sortCrawlPlatforms(", logged_in_body.group("body"))

        target_body = re.search(
            r"async function getTargetCrawlPlatforms\(scope='current'\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(target_body)
        self.assertIn("return sortCrawlPlatforms([{", target_body.group("body"))


if __name__ == "__main__":
    unittest.main()
