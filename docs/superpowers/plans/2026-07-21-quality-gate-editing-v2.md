# Quality Gate Editing v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make human article editing immediate and clearly distinguished from AI revisions in the quality-gate UI.

**Architecture:** Keep AI revision on its existing revision-and-gate path. Change only the human-edit route to persist title/content plus a manual-edit marker without recalculating `gate_report`; use the existing dual-list cache helper for all quality-gate actions.

**Tech Stack:** Flask, SQLite content store, vanilla JavaScript, `unittest`.

## Global Constraints

- Do not make real LLM calls; tests mock all AI functions.
- Human edits preserve the existing gate report; AI revisions keep gate rechecking.
- Do not modify crawler or local worker code.

### Task 1: Human-edit route regression tests and implementation

**Files:** `tests/test_app_core.py`, `app.py`

- [x] Add a failing PUT test asserting immediate persistence, `generation_status="人工已编辑"`, original gate report retention, and no gate calls.
- [x] Add a failing PUT exception test asserting a JSON error response.
- [x] Wrap the route body in `try/except`; update title/content and manual status only.

### Task 2: Quality-gate UI reliability and feedback

**Files:** `tests/test_frontend_crawl_order.py`, `static/js/app.js`

- [x] Add failing source assertions for copy action, cache helper lookup, AI processing label, and close confirmation.
- [x] Render the manual-edit badge, use `findContentGeneration` for view/copy, and show explicit AI gate-recheck progress.
- [x] Preserve both-list refresh after saves.

### Task 3: Verification

- [x] Run focused app/frontend tests, full `unittest discover -s tests`, Python compilation, JavaScript syntax check, and `git diff --check`.
