import json
import os
import tempfile
import unittest

from services.content_generations import ContentGenerationStore


def article(article_id, created_at="2026-01-01 10:00:00"):
    return {
        "id": article_id,
        "title": f"Title {article_id}",
        "content": f"Content {article_id}",
        "model": "deepseek-chat",
        "material_count": 1,
        "created_at": created_at,
    }


class ContentGenerationStoreTests(unittest.TestCase):
    def test_route_context_columns_are_idempotent_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentGenerationStore(os.path.join(tmp, "content.sqlite3"))
            with store._connection() as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(content_articles)")}
            self.assertTrue({
                "parent_id", "root_id", "batch_id", "route_context_json",
                "gate_report_json", "modify_instruction",
            }.issubset(columns))
            self.assertFalse({"article_subtype", "brief_json", "provenance_json"}.intersection(columns))

            store.append_generation(
                "client-a",
                {
                    **article("a1"),
                    "parent_id": "parent-1",
                    "root_id": "root-1",
                    "batch_id": "batch-1",
                    "route_context": {"route_id": "route-1"},
                    "gate_report": {"ok": True},
                    "modify_instruction": "只改标题",
                },
                {"role": "user", "content": "request"},
                {"role": "assistant", "content": "article", "article_id": "a1"},
            )

            saved = store.load_session("client-a")["articles"][0]
            self.assertEqual(saved["parent_id"], "parent-1")
            self.assertEqual(saved["root_id"], "root-1")
            self.assertEqual(saved["batch_id"], "batch-1")
            self.assertEqual(saved["route_context"], {"route_id": "route-1"})
            self.assertEqual(saved["gate_report"], {"ok": True})
            self.assertEqual(saved["modify_instruction"], "只改标题")

    def test_append_generation_adds_rows_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentGenerationStore(os.path.join(tmp, "content.sqlite3"))

            first = store.append_generation(
                "client-a",
                article("a1", "2026-01-01 10:00:00"),
                {"role": "user", "content": "first request", "created_at": "2026-01-01 10:00:00"},
                {"role": "assistant", "content": "first article", "created_at": "2026-01-01 10:00:00", "article_id": "a1"},
            )
            second = store.append_generation(
                "client-a",
                article("a2", "2026-01-01 10:05:00"),
                {"role": "user", "content": "second request", "created_at": "2026-01-01 10:05:00"},
                {"role": "assistant", "content": "second article", "created_at": "2026-01-01 10:05:00", "article_id": "a2"},
            )

            session = store.load_session("client-a")

            self.assertEqual(first["sequence"], 1)
            self.assertEqual(second["sequence"], 2)
            self.assertEqual([item["id"] for item in session["articles"]], ["a1", "a2"])
            self.assertEqual([item["content"] for item in session["messages"]], [
                "first request",
                "first article",
                "second request",
                "second article",
            ])

    def test_clients_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentGenerationStore(os.path.join(tmp, "content.sqlite3"))

            store.append_generation(
                "client-a",
                article("shared-id"),
                {"role": "user", "content": "client a request", "created_at": "2026-01-01 10:00:00"},
                {"role": "assistant", "content": "client a article", "created_at": "2026-01-01 10:00:00", "article_id": "shared-id"},
            )
            store.append_generation(
                "client-b",
                article("shared-id"),
                {"role": "user", "content": "client b request", "created_at": "2026-01-01 10:00:00"},
                {"role": "assistant", "content": "client b article", "created_at": "2026-01-01 10:00:00", "article_id": "shared-id"},
            )

            self.assertEqual([item["content"] for item in store.load_session("client-a")["articles"]], ["Content shared-id"])
            self.assertEqual([item["content"] for item in store.load_session("client-b")["articles"]], ["Content shared-id"])

    def test_load_session_and_messages_can_filter_by_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentGenerationStore(os.path.join(tmp, "content.sqlite3"))

            store.append_generation(
                "client-a",
                {**article("old", "2026-01-01 10:00:00"), "article_type": "对比型"},
                {"role": "user", "content": "old request", "created_at": "2026-01-01 10:00:00"},
                {"role": "assistant", "content": "old article", "created_at": "2026-01-01 10:00:00", "article_id": "old"},
            )
            store.append_generation(
                "client-a",
                {**article("today", "2026-01-02 10:00:00"), "article_type": "对比型"},
                {"role": "user", "content": "today request", "created_at": "2026-01-02 10:00:00"},
                {"role": "assistant", "content": "today article", "created_at": "2026-01-02 10:00:00", "article_id": "today"},
            )

            session = store.load_session("client-a", date="2026-01-02")
            messages = store.load_messages("client-a", article_type="对比型", date="2026-01-02")

            self.assertEqual([item["id"] for item in session["articles"]], ["today"])
            self.assertEqual([item["content"] for item in messages], ["today request", "today article"])

    def test_legacy_two_stage_columns_are_migrated_without_losing_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "content.sqlite3")
            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("""CREATE TABLE content_articles (
                    id TEXT, client_id TEXT, sequence INTEGER, title TEXT, content TEXT, model TEXT,
                    material_count INTEGER, article_type TEXT, article_subtype TEXT, created_at TEXT,
                    brief_json TEXT, provenance_json TEXT, route_context_json TEXT
                )""")
                conn.execute("""INSERT INTO content_articles VALUES
                    ('a1', 'client-a', 1, 'Title', 'Body', 'model', 1, '介绍型', '旧子类型',
                     '2026-01-01 10:00:00', '{}', '{}', '{"route_id":"route-a"}')""")
                conn.commit()
            finally:
                conn.close()
            store = ContentGenerationStore(db_path)
            saved = store.load_session("client-a")["articles"][0]
            with store._connection() as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(content_articles)")}

            self.assertEqual(saved["content"], "Body")
            self.assertEqual(saved["route_context"], {"route_id": "route-a"})
            self.assertFalse({"article_subtype", "brief_json", "provenance_json"}.intersection(columns))

    def test_delete_generation_removes_article_and_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentGenerationStore(os.path.join(tmp, "content.sqlite3"))

            store.append_generation(
                "client-a",
                {**article("a1", "2026-01-01 10:00:00"), "article_type": "对比型"},
                {"role": "user", "content": "request a1", "created_at": "2026-01-01 10:00:00"},
                {"role": "assistant", "content": "article a1", "created_at": "2026-01-01 10:00:00", "article_id": "a1"},
            )
            store.append_generation(
                "client-a",
                {**article("a2", "2026-01-01 10:05:00"), "article_type": "对比型"},
                {"role": "user", "content": "request a2", "created_at": "2026-01-01 10:05:00"},
                {"role": "assistant", "content": "article a2", "created_at": "2026-01-01 10:05:00", "article_id": "a2"},
            )

            self.assertTrue(store.delete_generation("client-a", "a1"))

            session = store.load_session("client-a")
            self.assertEqual([item["id"] for item in session["articles"]], ["a2"])
            self.assertEqual([item["content"] for item in session["messages"]], ["request a2", "article a2"])
            self.assertFalse(store.delete_generation("client-a", "missing"))

    def test_manual_edit_and_revision_lineage_preserve_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentGenerationStore(os.path.join(tmp, "content.sqlite3"))
            store.append_generation(
                "client-a",
                {**article("root"), "article_type": "介绍型"},
                {"role": "user", "content": "original request"},
                {"role": "assistant", "content": "original article", "article_id": "root"},
            )
            edited = store.update_article_content("client-a", "root", "Edited title\nEdited body")
            store.append_generation(
                "client-a",
                {
                    **article("revision", "2026-01-01 10:05:00"),
                    "content": "Revision body",
                    "parent_id": "root",
                    "root_id": "root",
                    "modify_instruction": "Add a practical example",
                    "article_type": "介绍型",
                },
                {"role": "user", "content": "Add a practical example"},
                {"role": "assistant", "content": "Revision body", "article_id": "revision"},
            )

            saved = store.load_session("client-a")["articles"]
            self.assertEqual(saved[0]["content"], "Edited title\nEdited body")
            self.assertEqual(saved[0]["title"], "Edited title")
            self.assertEqual([item["id"] for item in store.load_revision_lineage("client-a", "revision")], ["root", "revision"])
            self.assertEqual(store.load_revision_lineage("client-a", "revision")[1]["modify_instruction"], "Add a practical example")

    def test_load_session_imports_legacy_json_once_for_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = os.path.join(tmp, "content_generations.json")
            with open(legacy_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "client-a": {
                            "messages": [
                                {"role": "user", "content": "legacy request", "created_at": "2026-01-01 09:00:00"},
                                {"role": "assistant", "content": "legacy article", "created_at": "2026-01-01 09:00:00", "article_id": "legacy-a"},
                            ],
                            "articles": [
                                {
                                    **article("legacy-a", "2026-01-01 09:00:00"),
                                    "sequence": 3,
                                }
                            ],
                        },
                        "client-b": {
                            "messages": [{"role": "user", "content": "other client", "created_at": "2026-01-01 09:00:00"}],
                            "articles": [{**article("legacy-b", "2026-01-01 09:00:00"), "sequence": 1}],
                        },
                    },
                    f,
                    ensure_ascii=False,
                )

            store = ContentGenerationStore(
                os.path.join(tmp, "content.sqlite3"),
                legacy_json_path=legacy_path,
            )
            imported = store.load_session("client-a")
            appended = store.append_generation(
                "client-a",
                article("a4", "2026-01-01 10:00:00"),
                {"role": "user", "content": "new request", "created_at": "2026-01-01 10:00:00"},
                {"role": "assistant", "content": "new article", "created_at": "2026-01-01 10:00:00", "article_id": "a4"},
            )

            self.assertEqual([item["id"] for item in imported["articles"]], ["legacy-a"])
            self.assertEqual(appended["sequence"], 4)
            self.assertEqual([item["id"] for item in store.load_session("client-a")["articles"]], ["legacy-a", "a4"])
            self.assertEqual([item["id"] for item in store.load_session("client-b")["articles"]], ["legacy-b"])


if __name__ == "__main__":
    unittest.main()
