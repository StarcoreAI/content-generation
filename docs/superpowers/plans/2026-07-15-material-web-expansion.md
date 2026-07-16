# Material Web Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight AI web expansion flow for customer material packages.

**Architecture:** Keep the expansion logic in one focused service module. `app.py` only wires client access, settings, LLM calls, Tavily key lookup, and HTTP routes. The frontend reuses the existing material result panel and adds one editable Markdown result for the supplement.

**Tech Stack:** Flask, vanilla JS, Python stdlib `urllib`, existing OpenAI-compatible `ai_with_settings`, existing `data/material_packages/<cid>` output directory.

## Global Constraints

- Do not create RAG, vector DB, crawler system, or per-fact review workflow.
- Do not automatically merge into `latest_injection.md`.
- Do not automatically feed the supplement into content generation.
- Do not add a new Python dependency.
- Do not make the LLM output complex intermediate JSON.
- Use `TAVILY_API_KEY` from the environment for Tavily.
- Use `country: "china"` for Tavily Search.

---

### Task 1: Backend Service

**Files:**
- Create: `services/material_web_expansion.py`
- Test: `tests/test_material_web_expansion.py`

**Interfaces:**
- Consumes: `ask_text(prompt, max_tokens)`, `search_fn(query)`, customer info dict, injection Markdown.
- Produces:
  - `parse_query_lines(text, limit=6) -> list[str]`
  - `filter_sources(results, fetched_at, limit=10, max_content_chars=1800) -> list[dict]`
  - `expand_material_web_package(...) -> dict`

- [x] Write failing tests for query parsing, source filtering, Tavily country payload, and final Markdown save.
- [x] Run `python -m unittest tests.test_material_web_expansion -v` and verify RED.
- [x] Implement the service with stdlib only.
- [x] Run the same test and verify GREEN.

### Task 2: Flask Routes

**Files:**
- Modify: `app.py`
- Test: `tests/test_app_core.py`

**Interfaces:**
- `POST /api/materials/<cid>/expand-web`
- `GET /api/materials/<cid>/web-supplement`
- `GET /api/materials/<cid>/web-supplement.md`

- [x] Write failing API tests for missing injection, missing Tavily key, successful expansion, and supplement download.
- [x] Run selected tests and verify RED.
- [x] Add thin route handlers that call the service.
- [x] Run selected tests and verify GREEN.

### Task 3: Frontend Hook

**Files:**
- Modify: `static/js/app.js`

**Interfaces:**
- Reuse `expandMaterialPackage()`.
- Add `renderMaterialWebSupplement(result)`, `copyMaterialWebSupplementMarkdown()`, and `downloadMaterialWebSupplementMarkdown()`.

- [x] Replace placeholder toast with API call.
- [x] Show loading, success Markdown preview, copy, and download.
- [x] Keep failures as toasts and do not auto-merge or auto-load over the existing material result preview.
- [x] Run backend tests; manually inspect JS diff for syntax.

### Task 4: Verification

**Files:**
- No new files.

- [x] Run `python -m unittest tests.test_material_web_expansion -v`.
- [x] Run selected Flask tests covering material routes.
- [x] Run existing related material tests if present.
- [x] Confirm no unrelated dirty files were modified by this task.
