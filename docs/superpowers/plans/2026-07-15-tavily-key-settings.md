# Tavily Key Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators save `tavily_api_key` in the existing settings file while keeping `TAVILY_API_KEY` environment variable support for deployment overrides.

**Architecture:** Reuse `data/settings.json` and the existing settings API/UI. Add no new dependencies and no new config file format. The web expansion route reads environment first, then falls back to saved settings.

**Tech Stack:** Flask, vanilla JavaScript, existing JSON settings storage, Python unittest.

## Global Constraints

- Do not add a new secret storage system.
- Do not add `python-dotenv` or another dependency.
- Do not expose saved keys in `GET /api/settings`.
- Keep environment variable `TAVILY_API_KEY` as the highest-priority override.
- Keep `data/` ignored by git.

---

### Task 1: Backend Settings Fallback

**Files:**
- Modify: `app.py`
- Test: `tests/test_app_core.py`

**Interfaces:**
- Consumes: `get_settings()`, `save_current_settings(data)`, `run_client_material_web_expansion(cid)`
- Produces: saved `tavily_api_key`, safe `has_tavily_key`, expansion fallback key lookup

- [x] Write failing tests for saving Tavily key, hiding it on read, and using it when `TAVILY_API_KEY` is empty.
- [x] Run selected Flask tests and verify RED.
- [x] Add `tavily_api_key` handling to settings save/read and web expansion key lookup.
- [x] Run selected Flask tests and verify GREEN.

### Task 2: Settings Page Form

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`

**Interfaces:**
- Consumes: `/api/settings` payload with `has_tavily_key`
- Produces: POST payload field `tavily_api_key`

- [x] Add a password input for Tavily API Key in the existing settings card.
- [x] Load placeholder state from `has_tavily_key`.
- [x] Save `tavily_api_key` only when the operator typed one.
- [x] Run JS syntax check.

### Task 3: Deployment Hint

**Files:**
- Modify: `.env.example`

**Interfaces:**
- Produces: `TAVILY_API_KEY=` documented as optional deployment override.

- [x] Add `TAVILY_API_KEY=` to `.env.example`.
- [x] Run targeted tests and diff whitespace check.
