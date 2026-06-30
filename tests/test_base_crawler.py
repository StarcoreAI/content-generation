import json
import os
import tempfile
import unittest

import base_crawler


class BaseCrawlerStateTests(unittest.TestCase):
    def test_has_cookies_reads_utf8_storage_state(self):
        original_data_dir = base_crawler.DATA_DIR
        with tempfile.TemporaryDirectory() as tmp:
            base_crawler.DATA_DIR = tmp
            try:
                state_path = os.path.join(tmp, "qwen_state.json")
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "cookies": [
                                {
                                    "name": "session",
                                    "value": "abc",
                                    "domain": ".qianwen.com",
                                    "path": "/",
                                }
                            ],
                            "origins": [
                                {
                                    "origin": "https://www.qianwen.com",
                                    "localStorage": [{"name": "昵称", "value": "测试"}],
                                }
                            ],
                        },
                        f,
                        ensure_ascii=False,
                    )

                self.assertTrue(base_crawler.has_cookies("qwen"))
                status = base_crawler.get_platform_login_status("qwen")
                self.assertTrue(status["state_file_exists"])
                self.assertTrue(status["has_saved_state"])
                self.assertEqual(status["status"], "unknown")
                self.assertFalse(status["logged_in"])
            finally:
                base_crawler.DATA_DIR = original_data_dir

    def test_has_cookies_returns_false_when_state_missing(self):
        original_data_dir = base_crawler.DATA_DIR
        with tempfile.TemporaryDirectory() as tmp:
            base_crawler.DATA_DIR = tmp
            try:
                self.assertFalse(base_crawler.has_cookies("missing"))
            finally:
                base_crawler.DATA_DIR = original_data_dir

    def test_mark_login_status_updates_platform_status(self):
        original_data_dir = base_crawler.DATA_DIR
        with tempfile.TemporaryDirectory() as tmp:
            base_crawler.DATA_DIR = tmp
            try:
                state_path = os.path.join(tmp, "deepseek_state.json")
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump({"cookies": [{"name": "session", "value": "abc"}], "origins": []}, f)

                base_crawler.mark_login_status("deepseek", "ok", "登录状态已保存")
                ok_status = base_crawler.get_platform_login_status("deepseek")
                self.assertEqual(ok_status["status"], "ok")
                self.assertTrue(ok_status["logged_in"])

                base_crawler.mark_login_status("deepseek", "expired", "登录状态已过期")
                expired_status = base_crawler.get_platform_login_status("deepseek")
                self.assertEqual(expired_status["status"], "expired")
                self.assertFalse(expired_status["logged_in"])
            finally:
                base_crawler.DATA_DIR = original_data_dir


if __name__ == "__main__":
    unittest.main()
