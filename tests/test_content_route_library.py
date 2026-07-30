import json
import tempfile
import unittest
from pathlib import Path

from services.content_route_library import ContentRouteLibrary


def route():
    return {
        "parent_type": "介绍型", "name": "主线", "reader_task": "任务", "signature": "特征",
        "steps": [{"purpose": "说明判断", "evidence_role": "客户事实", "output_action": "解释做法"}],
    }


def source(url="https://example.com/a"):
    return {"url": url, "title": "文章 A", "source_evidence": [{
        "role": "框架", "finding": "文章先解释判断，再给出适配边界。",
        "excerpt": "这是一段能够在原文连续找到、长度超过二十个非空白字符的来源节选，用于验证路线。",
    }]}


class ContentRouteLibraryTests(unittest.TestCase):
    def test_verified_route_is_immediately_available_without_a_status_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = ContentRouteLibrary(Path(tmp))
            entry = library.create_route("医美", route(), source())
            self.assertNotIn("status", entry)
            self.assertEqual(entry["industry"], "医美")
            self.assertEqual(library.sample_route("医美", "介绍型")["id"], entry["id"])
            with self.assertRaisesRegex(ValueError, "industry_required"):
                library.create_route("", route(), source())

    def test_legacy_status_is_removed_and_extra_source_keeps_route_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = {
                "industry": "装修",
                "routes": [{
                    "id": "route_legacy", "industry": "装修", **{**route(), "parent_type": "对比型"},
                    "status": "candidate", "sources": [source()], "evidence_count": 1,
                    "created_at": "2026-07-29 00:00:00", "updated_at": "2026-07-29 00:00:00",
                }],
            }
            path = root / "industry_装修.json"
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            library = ContentRouteLibrary(root)
            migrated = library.list_routes("装修")[0]
            self.assertNotIn("status", migrated)
            self.assertNotIn("status", json.loads(path.read_text(encoding="utf-8"))["routes"][0])
            updated = library.add_source("装修", migrated["id"], source("https://example.com/b"))
            self.assertNotIn("status", updated)
            sampled = library.sample_route("装修", "对比型", set())
            self.assertNotIn("sources", sampled)
            self.assertNotIn("source_evidence", json.dumps(sampled, ensure_ascii=False))
            with self.assertRaisesRegex(ValueError, "duplicate_source_url"):
                library.add_source("装修", migrated["id"], source("https://example.com/b"))

    def test_delete_route_removes_it_from_the_industry_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = ContentRouteLibrary(Path(tmp))
            entry = library.create_route("装修", route(), source())
            library.delete_route("装修", entry["id"])
            self.assertEqual(library.list_routes("装修"), [])
            with self.assertRaisesRegex(ValueError, "content_route_not_found"):
                library.delete_route("装修", entry["id"])

    def test_same_source_url_merges_new_query_platform_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = ContentRouteLibrary(Path(tmp))
            first = {
                **source(),
                "citation_contexts": [{"query": "问题 A", "ai_platform": "doubao", "citation_count": 5}],
            }
            second = {
                **source(),
                "citation_contexts": [{"query": "问题 B", "ai_platform": "yuanbao", "citation_count": 3}],
            }
            entry = library.create_route("装修", route(), first)
            updated = library.add_or_merge_source("装修", entry["id"], second)

        self.assertEqual(1, len(updated["sources"]))
        self.assertEqual(2, len(updated["sources"][0]["citation_contexts"]))

if __name__ == "__main__":
    unittest.main()
