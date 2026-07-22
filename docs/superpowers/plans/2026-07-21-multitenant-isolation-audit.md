# Multi-tenant Isolation Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure operators receive a 404 for every non-owned customer resource while administrators retain global access and shared pattern layers remain readable.

**Architecture:** Reuse `require_client_access` at every route boundary that already has a customer id. Add small ownership lookups only for identifier-only routes (daily record ids and reference-analysis job ids). Pattern-library scope access distinguishes `client:<cid>` from shared `industry:*`/`global`, and restricts shared writes to administrators.

**Tech Stack:** Flask sessions, JSON/SQLite stores, vanilla JavaScript, `unittest`.

## Global Constraints

- Operators receive 404 for another owner's client resource; admins receive normal responses.
- `industry:*` and `global` pattern-library reads remain shared; only their writes become admin-only.
- Do not run real LLM, crawling, or local-worker workflows.

### Task 1: Three-account route isolation tests

**Files:** `tests/test_auth.py`, `tests/test_app_core.py`

- [ ] Add A/B/admin session tests for content generate, batch job status/cancel, content configuration, groups, materials, records, and reference-analysis jobs.
- [ ] Add pattern scope tests: client scope follows customer ownership; global/industry reads are shared; shared status writes require admin.

### Task 2: Identifier-only and pattern route guards

**Files:** `app.py`, `static/js/app.js`

- [ ] Add customer-owner checks for daily single/batch record deletion and reference-analysis status/cancel.
- [ ] Filter inaccessible client scopes, guard client entry reads/writes, restrict global/industry status changes to admins, and omit operator action buttons for those scopes.

### Task 3: Gate-report readability copy

**Files:** `static/js/app.js`, `tests/test_frontend_crawl_order.py`

- [ ] Add a fixed Chinese map for check ids and verdict handling recommendations.
- [ ] Render each check explanation beside its result and the recommendation in its verdict badge.

### Task 4: Verification

- [ ] Run focused auth/core/frontend tests, full `unittest discover -s tests`, compilation, JavaScript syntax check, and `git diff --check`.
