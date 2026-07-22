# Quality Gate UI and Revisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every generated article and its quality-gate result in a sidebar quality-gate page, and support manual edits plus AI-created revision children.

**Architecture:** Reuse the content-generation SQLite store and its existing lineage columns. The content page gets compact gate badges and edit actions; the new quality page reuses the generation listing API without filtering. AI revisions are separate persisted articles with a parent/root link and inject only the selected article's ancestor instructions.

**Tech Stack:** Flask, SQLite, vanilla JavaScript/CSS, Python unittest.

## Global Constraints

- Do not call real LLMs during tests or acceptance.
- Keep all generated and blocked articles visible; never delete or overwrite an original during revision.
- Keep single-worker deployment and do not alter crawlers or local workers.

---

### Task 1: Store and API mutation paths

**Files:**
- Modify: `services/content_generations.py`
- Modify: `app.py`
- Test: `tests/test_content_generations_store.py`, `tests/test_app_core.py`

- [x] Write failing tests for in-place manual content edits and an AI revision stored as a new parent/root-linked article.
- [x] Run the focused tests and confirm missing APIs fail.
- [x] Add minimal store methods and protected Flask routes; re-run focused tests.

### Task 2: Quality page and content-card actions

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `static/css/app.css`
- Test: `tests/test_app_core.py`

- [x] Write a failing static/API contract test for the quality-gate navigation and returned gate reports.
- [x] Add the sidebar page, all-article gate cards, gate badges, a manual editor dialog, and an AI-modification instruction dialog.
- [x] Re-run focused tests.

### Task 3: Manual historical LLM review command

**Files:**
- Create: `scripts/dev_quality_gate_review.py`
- Test: `tests/test_dev_quality_gate_review.py`

- [x] Write a failing mock-only CLI runner test selecting `verdict=pass` articles.
- [x] Implement a manual command that re-runs the shared quality gate and persists only reports.
- [x] Do not run the command against a real LLM; run its mock test.

### Task 4: Verification

- [x] Run focused modules, `run_tests.bat`, compilation, and `git diff --check`.
