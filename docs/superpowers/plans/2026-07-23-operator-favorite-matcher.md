# Operator Favorite Matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each operator run a read-only background scan that finds exact supplier-resource candidates for their own favorite names.

**Architecture:** `RWMeitiClient` will expose normalized news-media pages in addition to existing self-media pages. A per-operator JSON job record tracks a daemon-thread scan; when it finishes, matching candidates are written only to that operator’s favorite-list JSON. The resource-management page starts the scan, polls status, and lets the operator inspect candidates without selecting or ordering any resource.

**Tech Stack:** Flask, Python standard library threads/JSON, SQLite-free per-operator JSON, vanilla JavaScript, `unittest`.

## Global Constraints

- All supplier calls are list endpoints only: never call `create_*_order`.
- Match exact normalized names only; do not silently select a candidate or invent a resource ID.
- Keep favorites and scan results isolated by logged-in operator.
- Preserve current direct self-media resource-ID sync behavior.

---

### Task 1: Normalize supplier news-media list pages

**Files:**
- Modify: `services/rwmeiti.py`
- Test: `tests/test_rwmeiti.py`

**Interfaces:**
- Produces: `RWMeitiClient.list_news_media(page=1, limit=200) -> list[dict]`
- Each result contains `resource_id`, `name`, `price`, `status`, `resource_type='news_media'`, and `raw`.

- [ ] Write `test_list_news_media_normalizes_provider_resource` with a mocked `media_lst` response containing `id`, `media_name`, `price`, and `status`.
- [ ] Run `python -m unittest tests.test_rwmeiti.RWMeitiTests.test_list_news_media_normalizes_provider_resource -v`; expect an attribute error.
- [ ] Implement `list_news_media` by calling `_read_form('media_lst', {'page': page, 'limit': limit})`, rejecting non-200 provider codes, and normalizing each item.
- [ ] Re-run the test; expect pass.

### Task 2: Implement a per-operator read-only matching job

**Files:**
- Modify: `app.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `POST /api/distribution/favorites/match` returning `202` and a `GET /api/distribution/favorites/match` job status.
- Consumes: current operator favorite entries and a supplier client with `list_self_media` and `list_news_media`.
- Stores: matching `candidates` on the current operator’s favorite entries; each candidate has `resource_id`, `name`, `price`, `status`, `resource_type`, and `raw`.

- [ ] Write a route test that patches the matching worker start, starts a job as Alice, and confirms Bob cannot read Alice’s job state.
- [ ] Run the route test; expect a 404 because the endpoints do not exist.
- [ ] Add `F_DISTRIBUTION_MATCH_JOBS`, helpers for current-operator job paths, and `normalize_supplier_name` using `strip().casefold()`.
- [ ] Implement a daemon-thread worker: load fresh favorites, scan `list_self_media` then `list_news_media` page-by-page (200 records/page), save only exact normalized matches as candidates, and persist completed/failed status. No candidate is selected automatically.
- [ ] Implement start/status routes; reject a second start while the same operator’s job is running.
- [ ] Re-run the route test; expect pass.

### Task 3: Expose matching and candidates in resource management

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Test: `tests/test_content_generation_ui.py`

**Interfaces:**
- Produces: `startDistributionFavoriteMatch()`, `loadDistributionFavoriteMatchStatus()`, and candidate rendering within `#distributionFavoriteList`.
- Consumes: `/api/distribution/favorites/match` and favorite `candidates` fields.

- [ ] Write a UI wiring test requiring the start-match control and both matching JavaScript functions.
- [ ] Run it; expect failure because the controls are absent.
- [ ] Add a “匹配供应商资源” button and status span. Poll job status every two seconds only while it is `running`; reload favorites when it becomes terminal.
- [ ] Render candidate name, resource type, ID, price, and status below each favorite; show “未匹配” only after a completed scan.
- [ ] Re-run the UI test; expect pass.

### Task 4: Verify the feature without placing an order

**Files:**
- Verify only: `app.py`, `services/rwmeiti.py`, tests above

- [ ] Compile `app.py` and `services/rwmeiti.py` with the project virtual environment.
- [ ] Run `tests.test_rwmeiti`, `tests.test_auth.UserSettingsTests`, `tests.test_distribution_routes`, and `tests.test_content_generation_ui`.
- [ ] Run one live read-only list call with the configured `ylj` credentials only if the job logic is implemented; print counts/status only, never credentials, names, IDs, or order data.
- [ ] Confirm no `create_*_order` method was called.
