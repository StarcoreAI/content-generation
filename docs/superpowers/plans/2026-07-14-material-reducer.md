# Material Reducer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a package-level material reducer that compresses filter-kept units into concise GEO source material.

**Architecture:** `services/material_reducer.py` owns prompt construction, model response validation, and the one-call reducer API. `scripts/run_material_reducer.py` loads a filter report, re-extracts the original package, selects kept units, calls the reducer once, and writes a report.

**Tech Stack:** Python standard library, existing `scripts.extract_entities` helpers, existing `services.material_package_extractor`, existing `services.material_filter.KEPT_STATUSES`.

## Global Constraints

- Keep the prompt domain-neutral.
- No chunking, master/worker split, memory system, RAG, or multi-model review.
- Output contract is only `unit_id` plus `reduced_text`.
- Empty `reduced_text` means the unit should not enter the output worker.
- Do not commit unless the user explicitly asks.

---

### Task 1: Reducer Service

**Files:**
- Create: `services/material_reducer.py`
- Test: `tests/test_material_reducer.py`

**Interfaces:**
- Produces: `reduce_material_units(units, ask_json, question=None, max_tokens=8192) -> list[dict]`
- Produces: `DEFAULT_REDUCER_RULES: str`

- [ ] **Step 1: Write the failing service tests**

```python
import unittest


class MaterialReducerTests(unittest.TestCase):
    def test_reduces_all_units_in_one_package_call(self):
        from services.material_reducer import reduce_material_units

        units = [
            {"unit_id": "profile.docx", "path": "profile.docx", "kind": "text", "text": "Brand facts and repeated praise."},
            {"unit_id": "catalog.xlsx::Sheet1", "path": "catalog.xlsx", "kind": "spreadsheet_sheet", "text": "Third party listing only."},
        ]
        calls = []

        def ask_json(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return {
                "results": [
                    {"unit_id": "profile.docx", "reduced_text": "Brand facts."},
                    {"unit_id": "catalog.xlsx::Sheet1", "reduced_text": ""},
                ]
            }

        results = reduce_material_units(units, ask_json=ask_json)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 8192)
        self.assertIn("unit_id: profile.docx", calls[0][0])
        self.assertIn("Brand facts and repeated praise.", calls[0][0])
        self.assertNotIn('"useful"', calls[0][0])
        self.assertEqual(results[1]["reduced_text"], "")

    def test_rejects_missing_reducer_results(self):
        from services.material_reducer import reduce_material_units

        with self.assertRaisesRegex(ValueError, "missing reducer results.*b.docx"):
            reduce_material_units(
                [{"unit_id": "a.docx", "text": "A"}, {"unit_id": "b.docx", "text": "B"}],
                ask_json=lambda *_args, **_kwargs: {"results": [{"unit_id": "a.docx", "reduced_text": "A"}]},
            )

    def test_rejects_unknown_reducer_unit_id(self):
        from services.material_reducer import reduce_material_units

        with self.assertRaisesRegex(ValueError, "unknown reducer unit_id.*other.docx"):
            reduce_material_units(
                [{"unit_id": "a.docx", "text": "A"}],
                ask_json=lambda *_args, **_kwargs: {"results": [{"unit_id": "other.docx", "reduced_text": "A"}]},
            )

    def test_default_rules_are_domain_neutral(self):
        from services.material_reducer import DEFAULT_REDUCER_RULES

        self.assertIn("customer", DEFAULT_REDUCER_RULES)
        self.assertNotIn("翼升学", DEFAULT_REDUCER_RULES)
        self.assertNotIn("成考", DEFAULT_REDUCER_RULES)
        self.assertNotIn("河北", DEFAULT_REDUCER_RULES)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_reducer -v`

Expected: import failure for `services.material_reducer`.

- [ ] **Step 3: Implement the minimal service**

Create `services/material_reducer.py` with:

```python
DEFAULT_REDUCER_RULES = """You are reducing retained customer material into concise source material for public GEO article generation.
Keep customer-specific facts: identity, brand, official channels, locations, coverage, audience, products or services, service process, delivery boundaries, conditions, compliance limits, prohibitions, and supported concrete claims.
Remove form instructions, placeholders, blank fields, template explanations, internal execution notes, handoff notes, unrelated examples, competitor notes, duplicated statements, generic praise without facts, unsupported strong claims, guarantees, rankings, absolute success statements, and third-party catalogs that add no customer-specific facts.
If retained units conflict on a relevant customer-specific fact, keep a short pending-verification line instead of guessing.
Do not use external knowledge. Do not write an article. Do not invent facts."""
```

Add `reduce_material_units`, a small prompt builder, and response validation.

- [ ] **Step 4: Run the service tests and verify they pass**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_reducer -v`

Expected: all tests pass.

### Task 2: Reducer Runner

**Files:**
- Create: `scripts/run_material_reducer.py`
- Test: `tests/test_run_material_reducer.py`

**Interfaces:**
- Consumes: `reduce_material_units(units, ask_json, max_tokens=8192)`
- Produces: `choose_material_reducer_model(settings) -> str`
- Produces: `kept_unit_ids(filter_report) -> list[str]`
- Produces: `select_units_by_id(units, unit_ids) -> list[dict]`
- Produces: `build_report(filter_report_path, filter_report, units, model, results, errors=None) -> dict`

- [ ] **Step 1: Write the failing runner tests**

```python
import unittest


class RunMaterialReducerTests(unittest.TestCase):
    def test_material_reducer_model_can_be_overridden(self):
        from scripts.run_material_reducer import choose_material_reducer_model

        self.assertEqual(
            choose_material_reducer_model({"model": "deepseek-chat", "material_reducer_model": "deepseek-v4-pro"}),
            "deepseek-v4-pro",
        )

    def test_selects_only_kept_units_in_filter_order(self):
        from scripts.run_material_reducer import kept_unit_ids, select_units_by_id

        filter_report = {
            "results": [
                {"unit_id": "a.docx", "status": "core"},
                {"unit_id": "b.docx", "status": "redundant"},
                {"unit_id": "c.docx", "status": "representative"},
            ]
        }
        units = [
            {"unit_id": "c.docx", "text": "C"},
            {"unit_id": "a.docx", "text": "A"},
            {"unit_id": "b.docx", "text": "B"},
        ]

        self.assertEqual(kept_unit_ids(filter_report), ["a.docx", "c.docx"])
        self.assertEqual([unit["unit_id"] for unit in select_units_by_id(units, ["a.docx", "c.docx"])], ["a.docx", "c.docx"])

    def test_build_report_counts_nonempty_reductions(self):
        from scripts.run_material_reducer import build_report

        report = build_report(
            "reports/filter.json",
            {"package_path": "materials/pkg"},
            [{"unit_id": "a.docx"}, {"unit_id": "b.docx"}],
            "deepseek-chat",
            [{"unit_id": "a.docx", "reduced_text": "A"}, {"unit_id": "b.docx", "reduced_text": ""}],
        )

        self.assertEqual(report["input_count"], 2)
        self.assertEqual(report["reduced_count"], 1)
        self.assertEqual(report["model"], "deepseek-chat")

    def test_reducer_report_records_one_package_error(self):
        from scripts.run_material_reducer import reduce_units_for_report

        def ask_json(prompt, max_tokens):
            raise ValueError("invalid reducer JSON response")

        results, errors = reduce_units_for_report([{"unit_id": "a.docx", "text": "A"}], ask_json)

        self.assertEqual(results, [])
        self.assertEqual(errors[0]["unit_id"], "__package__")
        self.assertIn("invalid reducer JSON response", errors[0]["error"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_run_material_reducer -v`

Expected: import failure for `scripts.run_material_reducer`.

- [ ] **Step 3: Implement the minimal runner**

Create `scripts/run_material_reducer.py` by following the shape of `scripts/run_material_filter.py`, but read a filter report path instead of a package path.

- [ ] **Step 4: Run runner tests and existing material tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_reducer tests.test_run_material_reducer tests.test_material_filter tests.test_run_material_filter tests.test_material_package_extractor -v`

Expected: all tests pass.

### Task 3: Real Experiment

**Files:**
- No source changes unless the real run exposes a small bug.

**Interfaces:**
- Consumes: `scripts/run_material_reducer.py`

- [ ] **Step 1: Run the latest real filter report through the reducer**

Run: `.\.venv\Scripts\python.exe scripts\run_material_reducer.py reports\material_filter_翼升学-GEO资料-6月11日汇总版_20260714-105549.json --max-tokens 8192`

Expected: writes `reports/material_reducer_翼升学-GEO资料-6月11日汇总版_<timestamp>.json`.

- [ ] **Step 2: Inspect output directionally**

Check:

- intro-style material keeps customer facts and removes generic praise
- high-density workbook material keeps concrete facts and compliance boundaries
- third-party listing material with no customer-specific facts reduces to empty text

