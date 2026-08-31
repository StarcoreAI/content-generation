import json
import tempfile
import unittest
from pathlib import Path

from scripts import crawler_smoke


class CrawlerSmokeTests(unittest.TestCase):
    def test_parse_platforms_expands_all_in_stable_order(self):
        self.assertEqual(
            crawler_smoke.parse_platforms("all"),
            ["deepseek", "yuanbao", "qwen", "wenxin", "kimi", "doubao"],
        )
        self.assertEqual(
            crawler_smoke.parse_platforms("qwen,doubao"),
            ["qwen", "doubao"],
        )

    def test_load_probe_payload_reads_real_question_without_cli_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            clients = [
                {
                    "id": "client-1",
                    "name": "\u626c\u5dde\u82cf\u97f5\u6c7d\u8f66\u97f3\u54cd",
                    "brand": "\u82cf\u97f5\u6c7d\u8f66\u97f3\u54cd",
                }
            ]
            groups = {
                "client-1": [
                    {
                        "id": "group-1",
                        "name": "\u626c\u5dde\u82cf\u97f5\u6c7d\u8f66\u97f3\u54cd",
                        "questions": [
                            "\u626c\u5dde\u6c7d\u8f66\u97f3\u54cd\u6539\u88c5\u5347\u7ea7\u54ea\u5bb6\u597d",
                            "\u626c\u5dde\u65b0\u80fd\u6e90\u6c7d\u8f66\u97f3\u54cd\u6539\u88c5\u5e97\u63a8\u8350\uff1f",
                        ],
                    }
                ]
            }
            (data_dir / "clients.json").write_text(
                json.dumps(clients, ensure_ascii=False),
                encoding="utf-8",
            )
            (data_dir / "probe_groups.json").write_text(
                json.dumps(groups, ensure_ascii=False),
                encoding="utf-8",
            )

            probe = crawler_smoke.load_probe_payload(
                data_dir,
                client_id="client-1",
                group_id="group-1",
                question_index=2,
            )

        self.assertEqual(probe["brand"], "\u82cf\u97f5\u6c7d\u8f66\u97f3\u54cd")
        self.assertEqual(
            probe["questions"],
            ["\u626c\u5dde\u65b0\u80fd\u6e90\u6c7d\u8f66\u97f3\u54cd\u6539\u88c5\u5e97\u63a8\u8350\uff1f"],
        )
        self.assertEqual(probe["group_name"], "\u626c\u5dde\u82cf\u97f5\u6c7d\u8f66\u97f3\u54cd")

    def test_write_report_preserves_unicode_and_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = {
                "probe": {"question": "\u626c\u5dde\u6c7d\u8f66\u97f3\u54cd\u6539\u88c5\u5347\u7ea7\u54ea\u5bb6\u597d"},
                "platform_results": [],
            }

            path = crawler_smoke.write_report(report, Path(tmp))
            loaded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            loaded["probe"]["question"],
            "\u626c\u5dde\u6c7d\u8f66\u97f3\u54cd\u6539\u88c5\u5347\u7ea7\u54ea\u5bb6\u597d",
        )
        self.assertTrue(path.name.startswith("crawler_smoke_"))


if __name__ == "__main__":
    unittest.main()
