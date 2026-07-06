import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class CrawlerPageIsolationTests(unittest.TestCase):
    def test_python_crawlers_do_not_open_fresh_page_for_each_question(self):
        for filename in [
            "deepseek_crawler.py",
            "qwen_crawler.py",
            "yuanbao_crawler.py",
            "doubao_crawler.py",
        ]:
            with self.subTest(filename=filename):
                path = os.path.join(ROOT, filename)
                with open(path, "r", encoding="utf-8") as f:
                    source = f.read()

                self.assertNotIn("async def open_fresh_question_page(", source)
                self.assertNotIn("page = await open_fresh_question_page(context)", source)


if __name__ == "__main__":
    unittest.main()
