# Brief Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mechanically sample active pattern-library entries into a structured input for the future brief LLM.

**Architecture:** `services/brief_builder.py` owns constants, scope merging, eligibility checks, slot sampling, and fingerprint retry. It receives all caller-owned data as arguments and has no route, storage, LLM, or network dependency.

**Tech Stack:** Python standard library, existing `PatternLibrary`, `unittest`.

## Global Constraints

- Read only `active` entries from supplied scopes; do not read question-group or SQLite storage.
- Do not modify `app.py`, invoke an LLM, or access the network.
- Missing module slots return `None` and metadata; a missing eligible skeleton raises `ValueError`.

---

### Task 1: Deterministic sampling contract

**Files:**
- Create: `tests/test_brief_builder.py`
- Create: `services/brief_builder.py`

- [x] Write failing fixture-backed tests for active-only reads, parent-type filtering, table compatibility, free slots, missing slots, and fingerprint retries.
- [x] Run the test module and verify it fails because `brief_builder` is absent.
- [x] Implement `build_brief_sample(...)` using injected `random.Random` and the existing library service.
- [x] Re-run focused tests and verify they pass.

### Task 2: Probability contract

**Files:**
- Modify: `tests/test_brief_builder.py`
- Modify: `services/brief_builder.py`

- [x] Add seeded 1,000-run assertions for FAQ, table, free-slot, and body-module probabilities.
- [x] Run the test module to verify the probability contract.

### Task 3: Regression verification

**Files:**
- No application-route changes.

- [x] Compile the new module and run `run_tests.bat`.
