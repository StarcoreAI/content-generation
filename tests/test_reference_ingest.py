import tempfile
import unittest
from pathlib import Path
import json

from services.pattern_library import PatternLibrary
from services.reference_ingest import STAGE2_MAX_TOKENS, build_ingest_prompt, ingest_anatomy_cards


def anatomy_card(group_id, url, name="Decision skeleton", features=None):
    return {
        "source": {
            "url": url,
            "title": f"Source for {name}",
            "group_id": group_id,
            "published_at": "2026-07-17",
            "platform": "DeepSeek",
            "citation_count": 4,
        },
        "skeleton": {
            "name": name,
            "parent_type": "comparison",
            "sections": ["establish criteria", "compare options", "close with next steps"],
            "signature": "A reusable decision sequence.",
            "risk_notes": "",
        },
        "modules": [],
        "citability_features": features or [],
    }


def group(group_id, *urls, risk_marks=None):
    return {
        "group_id": group_id,
        "member_urls": list(urls),
        "risk_marks": risk_marks or [],
    }


class ReferenceIngestTests(unittest.TestCase):
    def test_stage2_token_budget_covers_pattern_and_citability_results(self):
        self.assertEqual(STAGE2_MAX_TOKENS, 1600)

    def test_manual_runner_reads_stage1_cards_and_writes_stage2_report(self):
        from scripts.dev_reference_ingest import run_reference_ingest

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            stage_dir = data_dir / "reference_intelligence" / "client-1" / "2026-07-20"
            stage_dir.mkdir(parents=True)
            (stage_dir / "stage1_anatomy_cards.json").write_text(json.dumps({
                "cards": [anatomy_card("group-a", "https://example.com/a")],
            }), encoding="utf-8")
            (stage_dir / "stage0_filter_groups.json").write_text(json.dumps({
                "groups": [group("group-a", "https://example.com/a")],
            }), encoding="utf-8")

            result = run_reference_ingest(
                client_id="client-1",
                industry="adult_education",
                date="2026-07-20",
                data_dir=data_dir,
                ai_json_fn=lambda prompt, max_tokens: self.fail("empty library must skip LLM"),
            )

            output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["cards"], 1)
            self.assertEqual(output["scope"], "industry:adult_education")
            self.assertEqual(output["items"][0]["action"], "created")

    def test_match_adds_one_evidence_without_creating_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            scope = "industry:adult_education"
            existing = library.create_candidate(
                scope, "skeleton", "Existing decision skeleton", {},
                {"url": "https://example.com/old", "group_id": "old"},
            )

            report = ingest_anatomy_cards(
                [anatomy_card("new", "https://example.com/new")],
                library=library,
                scope=scope,
                groups_by_id={"new": group("new", "https://example.com/new")},
                ai_json_fn=lambda prompt, max_tokens: {"results": [{
                    "item_key": "skeleton", "match": existing["id"], "reason": "same reusable sequence",
                }]},
            )

            entries = library.list_entries(scope)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["evidence_count"], 2)
            self.assertEqual(report["items"][0]["action"], "matched")
            self.assertEqual(report["items"][0]["entry_id"], existing["id"])

    def test_non_match_creates_candidate_and_features_aggregate_without_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            scope = "industry:adult_education"
            library.create_candidate(
                scope, "skeleton", "Existing", {}, {"url": "https://example.com/old"},
            )

            report = ingest_anatomy_cards(
                [anatomy_card("new", "https://example.com/new", features=["FAQ user wording"])],
                library=library,
                scope=scope,
                groups_by_id={"new": group("new", "https://example.com/new")},
                ai_json_fn=lambda prompt, max_tokens: {"results": [{
                    "item_key": "skeleton", "match": None, "reason": "different structure",
                }, {
                    "item_key": "citability_0", "tag": "FAQ用用户原话提问", "match": None,
                    "reason": "same semantic feature",
                }]},
            )

            self.assertEqual(len(library.list_entries(scope)), 3)
            self.assertEqual(report["items"][0]["action"], "created")
            checklist = next(entry for entry in library.list_entries(scope) if entry["kind"] == "checklist")
            self.assertEqual(checklist["name"], "FAQ用用户原话提问")
            self.assertEqual(checklist["payload"]["raw_labels"], ["FAQ user wording"])

    def test_same_round_second_card_matches_first_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            scope = "industry:adult_education"
            calls = []

            def fake_ai_json(prompt, max_tokens):
                calls.append(prompt)
                return {"results": [{
                    "item_key": "skeleton",
                    "match": library.list_entries(scope)[0]["id"],
                    "reason": "same pattern created earlier this run",
                }]}

            report = ingest_anatomy_cards(
                [
                    anatomy_card("one", "https://example.com/one"),
                    anatomy_card("two", "https://example.com/two"),
                ],
                library=library,
                scope=scope,
                groups_by_id={
                    "one": group("one", "https://example.com/one"),
                    "two": group("two", "https://example.com/two"),
                },
                ai_json_fn=fake_ai_json,
            )

            entries = library.list_entries(scope)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["evidence_count"], 2)
            self.assertEqual([item["action"] for item in report["items"]], ["created", "matched"])

    def test_prompt_excludes_examples_and_urls(self):
        prompt = build_ingest_prompt(
            [{
                "id": "module_old", "kind": "module", "name": "Existing", "status": "candidate",
                "payload": {"pattern": "existing shape", "excerpt": "EXCERPT_SECRET"},
                "sources": [{"url": "https://example.com/secret"}],
            }],
            [{
                "item_key": "module_0", "kind": "module", "name": "New",
                "payload": {"pattern": "new shape", "excerpt": "NEW_EXCERPT_SECRET"},
            }],
        )

        self.assertIn("existing shape", prompt)
        self.assertIn("new shape", prompt)
        self.assertNotIn("EXCERPT_SECRET", prompt)
        self.assertNotIn("NEW_EXCERPT_SECRET", prompt)
        self.assertNotIn("https://example.com/secret", prompt)
        self.assertIn("引用友好特征词表", prompt)
        self.assertIn("按语义归类，不要按字面", prompt)
        self.assertIn("词表归类与库中已有条目无关", prompt)

    def test_library_name_and_summary_share_the_300_character_limit(self):
        prompt = build_ingest_prompt(
            [{
                "id": "module_old", "kind": "module", "name": "N" * 150, "status": "candidate",
                "payload": {"pattern": "P" * 500},
            }],
            [{"item_key": "module_0", "kind": "module", "name": "New", "payload": {"pattern": "shape"}}],
        )

        line = next(value for value in prompt.splitlines() if value.startswith("module_old |"))
        fields = line.split(" | ")
        self.assertLessEqual(len(fields[2]) + len(fields[4]), 300)

    def test_controlled_tag_aggregates_two_raw_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            scope = "industry:adult_education"
            first = anatomy_card("one", "https://example.com/one", features=["免责声明标注"])
            second = anatomy_card("two", "https://example.com/two", features=["免责声明与广告标注"])
            first["skeleton"] = None
            second["skeleton"] = None

            ingest_anatomy_cards(
                [first, second], library=library, scope=scope,
                groups_by_id={
                    "one": group("one", "https://example.com/one"),
                    "two": group("two", "https://example.com/two"),
                },
                ai_json_fn=lambda prompt, max_tokens: {"results": [{
                    "item_key": "citability_0", "tag": "免责与广告标注", "match": None,
                    "reason": "same controlled tag",
                }]},
            )

            entry = library.list_entries(scope)[0]
            self.assertEqual(entry["name"], "免责与广告标注")
            self.assertEqual(entry["evidence_count"], 2)
            self.assertEqual(entry["payload"]["raw_labels"], ["免责声明标注", "免责声明与广告标注"])

    def test_other_tag_creates_then_matches_existing_other_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            scope = "industry:adult_education"
            first = anatomy_card("one", "https://example.com/one", features=["独特特征"])
            second = anatomy_card("two", "https://example.com/two", features=["另一种措辞"])
            first["skeleton"] = None
            second["skeleton"] = None

            def fake_ai_json(prompt, max_tokens):
                existing = library.list_entries(scope)
                return {"results": [{
                    "item_key": "citability_0", "tag": "其他:独特特征",
                    "match": existing[0]["id"] if existing else None,
                    "reason": "same other feature",
                }]}

            ingest_anatomy_cards(
                [first, second], library=library, scope=scope,
                groups_by_id={
                    "one": group("one", "https://example.com/one"),
                    "two": group("two", "https://example.com/two"),
                },
                ai_json_fn=fake_ai_json,
            )

            entry = library.list_entries(scope)[0]
            self.assertEqual(entry["name"], "其他:独特特征")
            self.assertEqual(entry["evidence_count"], 2)
            self.assertEqual(entry["payload"]["raw_labels"], ["独特特征", "另一种措辞"])

    def test_unknown_tag_is_safely_namespaced_as_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            card = anatomy_card("one", "https://example.com/one", features=["原始标签"])
            card["skeleton"] = None

            ingest_anatomy_cards(
                [card], library=library, scope="industry:adult_education",
                groups_by_id={"one": group("one", "https://example.com/one")},
                ai_json_fn=lambda prompt, max_tokens: {"results": [{
                    "item_key": "citability_0", "tag": "野生返回", "match": None,
                    "reason": "unexpected tag",
                }]},
            )

            self.assertEqual(library.list_entries("industry:adult_education")[0]["name"], "其他:野生返回")

    def test_retries_an_empty_llm_response_once_before_recording_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = PatternLibrary(Path(tmp), now_fn=lambda: "2026-07-20 12:00:00")
            card = anatomy_card("one", "https://example.com/one", features=["免责声明"])
            card["skeleton"] = None
            attempts = []

            def fake_ai_json(prompt, max_tokens):
                attempts.append(prompt)
                if len(attempts) == 1:
                    raise ValueError("empty JSON response")
                return {"results": [{
                    "item_key": "citability_0", "tag": "免责与广告标注", "match": None,
                    "reason": "recovered response",
                }]}

            report = ingest_anatomy_cards(
                [card], library=library, scope="industry:adult_education",
                groups_by_id={"one": group("one", "https://example.com/one")},
                ai_json_fn=fake_ai_json,
            )

            self.assertEqual(len(attempts), 2)
            self.assertEqual(report["errors"], [])
            self.assertEqual(library.list_entries("industry:adult_education")[0]["name"], "免责与广告标注")


if __name__ == "__main__":
    unittest.main()
