# Content Input Choices and Lazy Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make audience angles, FAQ questions, and competitor inputs stable customer-level choices, while allowing an empty customer to generate once without manual configuration.

**Architecture:** Keep the existing sampling → brief → writing → gate pipeline intact. Add small pure helpers for choice normalization and competitor selection, and let `app.run_content_generation` resolve/persist missing choices before sampling. Batch jobs invoke the same preflight exactly once, then keep calling the shared generation entry serially.

**Tech Stack:** Python standard library, Flask, JSON file stores, SQLite content generation store, vanilla JavaScript, `unittest`.

## Global Constraints

- Single gunicorn worker and multi-threaded deployment; every batch article remains strictly serial with no parallel LLM calls.
- Do not modify crawler code or local worker code.
- Do not run a real LLM generation; all automated tests mock LLM injection.
- Preserve historical content rows and the existing generation pipeline.

---

### Task 1: Choice and competitor-selection helpers

**Files:**
- Create: `services/content_choices.py`
- Modify: `services/quality_gate.py`
- Test: `tests/test_content_choices.py`

- [x] Write failing unit tests for legacy string migration, enabled-only selection, all-disabled detection, must/banned selection, Markdown subset extraction, and candidate heading extraction.
- [x] Implement normalization to `{text, enabled, source}`, active-text lookup, explicit-all-disabled detection, rule normalization, 2–4 competitor selection, and Markdown section filtering with standard-library code only.
- [x] Move the existing quality-gate competitor-heading parsing logic into `services/quality_gate.py` as its shared extractor; have the app import it.
- [x] Run `python -m unittest tests.test_content_choices -v` and keep it green.

### Task 2: Persisted lazy audience/FAQ configuration and shared generation wiring

**Files:**
- Modify: `app.py`
- Modify: `services/batch_generation.py`
- Test: `tests/test_app_core.py`
- Test: `tests/test_batch_generation.py`

- [x] Write failing mock-LLM tests for empty configuration persistence/use, nonempty skip, all-disabled no lazy generation, failed parse fail-open, and batch preflight running once.
- [x] Add client fields `faq_questions` and `competitor_rules`, normalize incoming legacy data, and expose an authenticated content-options endpoint with live competitor candidates.
- [x] Add one fail-open LLM preflight that generates only missing audience/FAQ lists, uses material text or brand/industry fallback, persists valid AI results immediately, and returns active choices for the current article.
- [x] Make `run_content_generation` use enabled audience/FAQ entries, select/filter per-article competitors before both LLM stages, write the selected names to provenance, and pass that same subset to the gate.
- [x] Extend serial batch jobs with a once-per-job preflight and a small used-competitor preference list; do not change the count=1 synchronous route.
- [x] Run the focused app and batch test modules.

### Task 3: Brief prompt and client-configuration UI

**Files:**
- Modify: `services/brief_builder.py`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Test: `tests/test_brief_builder.py`
- Test: `tests/test_frontend_crawl_order.py`

- [x] Write failing prompt/UI source assertions for customer-first placement including must-use competitors and the choice controls.
- [x] Extend the brief instruction that client brand precedes every selected competitor, including must-use choices.
- [x] Remove the obsolete content-production audience textarea and add simple client-page angle/FAQ toggle, add, delete, AI marker, and competitor three-state controls backed by the new endpoint.
- [x] Run focused prompt/frontend checks.

### Task 4: Regression verification

**Files:**
- Modify: relevant tests only for changed stored representation.

- [x] Update legacy audience/FAQ tests to assert automatic normalized entries rather than raw strings.
- [x] Run the full mocked `python -m unittest` suite and `git diff --check`.
- [x] Do not perform a real content-generation or LLM acceptance run; hand that verification to the user.
