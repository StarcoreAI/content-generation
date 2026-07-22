# Pattern Library Seeds and Global Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the shared writing-pattern seeds and include global entries in stage2 pattern matching.

**Architecture:** A small Python CLI reads the versioned JSON seed source and calls `PatternLibrary` for each missing `seed://<seed_id>` entry. Stage2 combines current-industry and global skeleton/module entries only for LLM matching, then uses the matched entry's real scope when adding evidence.

**Tech Stack:** Python standard library, existing `PatternLibrary`, `unittest`.

## Global Constraints

- All seeds use `global` scope and remain `candidate` until manually approved.
- Seed sources use `seed://<seed_id>` and never impersonate real articles.
- Checklist aggregation remains industry-scoped.
- Do not modify crawler/local-worker behavior or old content-production code.

---

### Task 1: Seed import CLI

**Files:**
- Create: `scripts/import_pattern_seeds.py`
- Test: `tests/test_import_pattern_seeds.py`

- [x] Write an idempotency test that runs the importer twice against a temporary library.
- [x] Run it and confirm it fails because the script is absent.
- [x] Implement the smallest UTF-8 CLI that creates each JSON seed as a global candidate, skips existing seed source URLs, and prints imported/skipped counts.
- [x] Re-run the test and confirm it passes.

### Task 2: Stage2 global comparison

**Files:**
- Modify: `services/reference_ingest.py`
- Modify: `tests/test_reference_ingest.py`

- [x] Write a test showing a global skeleton in the prompt, evidence written to `global.json`, and an unmatched item created only in the industry scope.
- [x] Run it and confirm it fails under industry-only matching.
- [x] Add the four controlled citability tags and use entry scope for matched pattern evidence.
- [x] Re-run the focused tests and confirm they pass.

### Task 3: Import and full verification

**Files:**
- Create: `data/pattern_library/global.json`

- [x] Run the importer twice and verify the second run skips all seeds.
- [x] Verify the pattern-library scope endpoint exposes `global` and status controls continue to operate against that scope.
- [x] Run `run_tests.bat` and inspect the resulting diff.
