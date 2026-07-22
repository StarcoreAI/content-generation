# Remove Reference Plugin Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the obsolete reference-intelligence plugin compatibility and display layer without touching historical data or the three-stage analysis pipeline.

**Architecture:** Delete the plugin API and UI code instead of replacing it. Keep reference-intelligence task payloads focused on clusters and all stage/pattern-library code unchanged.

**Tech Stack:** Flask, browser JavaScript, Python unittest.

## Global Constraints

- Do not delete or migrate historical disk files.
- Do not change reference-intelligence stages, pattern-library ingestion, or content generation.
- Add a regression test for the retired API before deleting its implementation.

---

### Task 1: Lock the retired route behavior

**Files:**
- Modify: `tests/test_app_core.py`

- [ ] Replace the old plugin read test with a test that requests `/api/reference_intelligence/plugins` and expects HTTP 404.
- [ ] Run the individual test and confirm it fails while the route exists.

### Task 2: Remove Python compatibility code

**Files:**
- Modify: `app.py`
- Modify: `services/reference_intelligence.py`
- Modify: `tests/test_app_core.py`

- [ ] Delete the wrapper, route, normalizer, default `plugins` field, and the two skipped writer plugin tests.
- [ ] Run the focused app/reference tests and confirm route retirement passes.

### Task 3: Remove the UI card and request path

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_frontend_crawl_order.py`

- [ ] Delete the plugin card, renderer, request, and empty-state call.
- [ ] Update assertions so the page requires the remaining reference-intelligence controls but no plugin route or elements.
- [ ] Run focused frontend tests and confirm they pass.

### Task 4: Verify the cleanup

**Files:**
- Verify: `app.py`, `services/reference_intelligence.py`, `templates/index.html`, `static/js/app.js`

- [ ] Confirm live-code searches for `normalize_reference_plugins` and `renderReferencePlugins` have no results.
- [ ] Run the requested full unit suite and `git diff --check`.
