# Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-open, persisted quality gate to the shared content-generation entry point.

**Architecture:** `services/quality_gate.py` contains independently testable deterministic checks and one injected JSON LLM review. `app.run_content_generation` invokes it after writing and before SQLite persistence, so the API and CLI share the same behavior; blocked drafts are still retained with the report.

**Tech Stack:** Python standard library, Flask, SQLite, unittest/mock.

## Global Constraints

- Keep the single gunicorn worker and multi-thread deployment model.
- Do not change crawlers or the local worker.
- Do not execute a real LLM acceptance run.
- Gate errors fail open and must not leave a partial generation record.

---

### Task 1: Quality-gate service and unit tests

**Files:**
- Create: `services/quality_gate.py`
- Create: `tests/test_quality_gate.py`

- [x] Write failing unit tests for code checks, optional vocabulary loading, injected LLM review, and fail-open malformed replies.
- [x] Run `python -m unittest tests.test_quality_gate -v` and confirm the missing module/API failure.
- [x] Implement the smallest stdlib-only gate API and rerun the module tests.

### Task 2: Shared generation-path integration

**Files:**
- Modify: `app.py`
- Modify: `scripts/dev_content_generate.py`
- Modify: `tests/test_app_core.py`

- [x] Write failing API/store tests covering persisted reports and persisted blocked drafts.
- [x] Invoke the gate between draft generation and `append_content_generation`, source same-client recent content, and attach the report without stopping persistence.
- [x] Print gate summaries in the CLI without duplicating the generation chain, then run focused integration tests.

### Task 3: Required verification

- [x] Run the specified unit modules, full `run_tests.bat`, `py_compile`, and `git diff --check`.
