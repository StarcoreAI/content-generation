import tempfile
import unittest
from pathlib import Path

from services.pattern_library import PatternLibrary


class PatternLibraryTests(unittest.TestCase):
    def test_candidate_is_persisted_in_its_scope_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = PatternLibrary(root, now_fn=lambda: "2026-07-20 12:00:00")

            entry = library.create_candidate(
                "industry:adult_education",
                "skeleton",
                "Observation classification",
                {"sections": ["context", "comparison"]},
                {
                    "url": "https://example.com/article-a",
                    "title": "Article A",
                    "group_id": "group-a",
                    "published_at": "2026-07-20",
                    "platform": "example-platform",
                    "citation_count": 3,
                },
            )

            self.assertEqual(entry["status"], "candidate")
            self.assertEqual(entry["evidence_count"], 1)
            self.assertEqual(entry["sources"], [{
                "url": "https://example.com/article-a",
                "title": "Article A",
                "group_id": "group-a",
                "published_at": "2026-07-20",
                "platform": "example-platform",
                "citation_count": 3,
                "risk_marks": [],
                "alias_urls": [],
            }])
            self.assertTrue((root / "industry_adult_education.json").exists())
            self.assertEqual(library.list_entries("industry:adult_education"), [entry])

    def test_distinct_source_promotes_candidate_and_duplicate_does_not_count_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            scope = "industry:adult_education"
            entry = library.create_candidate(
                scope,
                "module",
                "Pain-point questions",
                {"module_type": "opening"},
                {"url": "https://example.com/article-a", "title": "Article A"},
            )

            duplicate = library.add_evidence(
                scope,
                entry["id"],
                {"url": "https://example.com/article-a", "title": "Article A revised"},
            )
            promoted = library.add_evidence(
                scope,
                entry["id"],
                {"url": "https://example.com/article-b", "title": "Article B"},
            )

            self.assertEqual(duplicate["evidence_count"], 1)
            self.assertEqual(duplicate["status"], "candidate")
            self.assertEqual(promoted["evidence_count"], 2)
            self.assertEqual(promoted["status"], "active")
            self.assertEqual(len(promoted["sources"]), 2)

    def test_entry_can_be_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            entry = library.create_candidate(
                "global",
                "checklist",
                "Clear decision criteria",
                {"checks": ["has_selection_criteria"]},
                {"url": "https://example.com/article-a", "title": "Article A"},
            )

            retired = library.set_status("global", entry["id"], "retired")

            self.assertEqual(retired["status"], "retired")

    def test_source_metadata_fields_are_retained_when_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")

            entry = library.create_candidate(
                "global",
                "checklist",
                "Decision criteria",
                {},
                {"url": "https://example.com/article-a", "title": "Article A"},
            )

            self.assertEqual(entry["sources"], [{
                "url": "https://example.com/article-a",
                "title": "Article A",
                "group_id": "",
                "published_at": "",
                "platform": "",
                "citation_count": 0,
                "risk_marks": [],
                "alias_urls": [],
            }])

    def test_group_aliases_do_not_create_duplicate_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            entry = library.create_candidate(
                "global", "module", "Pattern", {},
                {"url": "https://example.com/main", "alias_urls": ["https://example.com/replica"]},
            )

            duplicate = library.add_evidence(
                "global", entry["id"],
                {"url": "https://example.com/replica", "alias_urls": ["https://example.com/new-main"]},
            )

            self.assertEqual(duplicate["evidence_count"], 1)
            self.assertEqual(duplicate["sources"][0]["alias_urls"], ["https://example.com/replica"])

    def test_verified_examples_replace_unverified_then_append_and_risk_notes_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            entry = library.create_candidate(
                "global", "module", "Pattern",
                {"excerpt": "unverified example", "excerpt_verified": False, "risk_notes": "risk one"},
                {"url": "https://example.com/a"},
            )
            replaced = library.add_evidence(
                "global", entry["id"], {"url": "https://example.com/b"},
                payload_update={"excerpt": "verified example", "excerpt_verified": True, "risk_notes": "risk two"},
            )
            appended = library.add_evidence(
                "global", entry["id"], {"url": "https://example.com/c"},
                payload_update={"excerpt": "second verified example", "excerpt_verified": True, "risk_notes": "risk one"},
            )

            self.assertEqual(replaced["payload"]["excerpt"], "verified example")
            self.assertTrue(replaced["payload"]["excerpt_verified"])
            self.assertEqual(len(appended["payload"]["excerpts"]), 2)
            self.assertIn("risk one", appended["payload"]["risk_notes"])
            self.assertIn("risk two", appended["payload"]["risk_notes"])

    def test_two_blocked_risk_sources_stay_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            entry = library.create_candidate(
                "global", "module", "Pattern", {},
                {"url": "https://example.com/a", "risk_marks": ["AI 生成痕迹明显"]},
            )
            updated = library.add_evidence(
                "global", entry["id"],
                {"url": "https://example.com/b", "risk_marks": ["冒充口吻"]},
            )

            self.assertEqual(updated["evidence_count"], 2)
            self.assertEqual(updated["status"], "candidate")

    def test_clean_plus_blocked_risk_source_stays_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            entry = library.create_candidate("global", "module", "Pattern", {}, {"url": "https://example.com/a"})
            updated = library.add_evidence(
                "global", entry["id"],
                {"url": "https://example.com/b", "risk_marks": ["AI 生成痕迹明显"]},
            )

            self.assertEqual(updated["evidence_count"], 2)
            self.assertEqual(updated["status"], "candidate")

    def test_two_clean_sources_promote_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            entry = library.create_candidate("global", "module", "Pattern", {}, {"url": "https://example.com/a"})
            updated = library.add_evidence("global", entry["id"], {"url": "https://example.com/b"})

            self.assertEqual(updated["evidence_count"], 2)
            self.assertEqual(updated["status"], "active")
