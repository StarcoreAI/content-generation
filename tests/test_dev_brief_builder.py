import json
import random
import tempfile
import unittest
from pathlib import Path

from scripts.dev_brief_builder import run_brief_builder
from services.pattern_library import PatternLibrary


ROOT = Path(__file__).resolve().parents[1]


def activate(library, kind, name, payload):
    entry = library.create_candidate("industry:成人教育", kind, name, payload, {"url": f"https://example.com/{name}"})
    return library.set_status("industry:成人教育", entry["id"], "active")


class DevBriefBuilderTests(unittest.TestCase):
    def test_cli_has_no_article_subtype_option(self):
        source = (ROOT / "scripts" / "dev_brief_builder.py").read_text(encoding="utf-8")
        self.assertNotIn("article_subtype", source)
        self.assertNotIn("--article-subtype", source)

    def test_runner_writes_valid_sample_and_brief_pairs_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            client_id = "client-1"
            data_dir.mkdir()
            (data_dir / "clients.json").write_text(json.dumps([{
                "id": client_id, "name": "Client", "brand": "Brand", "industry": "成人教育",
            }], ensure_ascii=False), encoding="utf-8")
            package_dir = data_dir / "material_packages" / client_id
            package_dir.mkdir(parents=True)
            (package_dir / "latest_injection.md").write_text("# 客户资料\n客户事实", encoding="utf-8")
            library = PatternLibrary(data_dir / "pattern_library")
            activate(library, "skeleton", "Skeleton", {"parent_type": "对比型", "sections": ["开头", "正文"]})
            activate(library, "module", "Opening", {"type": "开头", "pattern": "开头套路"})

            result = run_brief_builder(
                client_id=client_id,
                parent_type="对比型",
                count=1,
                date="2026-07-20",
                data_dir=data_dir,
                ai_json_fn=lambda prompt, max_tokens: {
                    "title_candidates": ["标题一", "标题二"],
                    "angle_statement": "主线",
                    "sections": [
                        {"id": 1, "功能": "开头", "要点": "用客户资料", "引用": ["客户资料 > 客户事实"], "字数": 200},
                        {"id": 2, "功能": "正文", "要点": "补充客户资料", "引用": ["客户资料 > 客户事实"], "字数": 500},
                    ],
                    "bans": [], "dedup_hints": "避让",
                },
                rng=random.Random(1),
            )

            output = Path(result["output_path"])
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(output.exists())
            self.assertEqual(payload["client_id"], client_id)
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["brief"]["title_candidates"], ["标题一", "标题二"])


if __name__ == "__main__":
    unittest.main()
