# Local Distribution Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each operator sync RWMeiti resources into a local catalog, choose common publishing platforms by name, and refresh only those platforms by stable supplier IDs.

**Architecture:** Keep the supplier catalog and its sync job in per-operator JSON files, just like credentials and favorites. A favorite stores the supplier resource type and ID; publication and order routes resolve their current name, price, and status from the current operator’s catalog instead of a client-scoped manually synced list. Full catalog sync is asynchronous; favorite refresh does only ID lookups.

**Tech Stack:** Flask, JSON persistence, existing `RWMeitiClient`, vanilla JavaScript, Python `unittest`.

## Global Constraints

- Never create a supplier order during a catalog operation.
- Credentials and catalog data remain isolated by authenticated operator.
- The UI does not ask operators to enter or match supplier IDs manually.
- Keep support for both `self_media` and `news_media`; short video remains out of scope.
- No new dependency or database migration is needed.

---

### Task 1: Add catalog persistence and full-sync behavior [x]

**Files:**
- Modify: `app.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Produces `current_distribution_catalog() -> tuple[str, list[dict]]`.
- Produces `start_distribution_catalog_sync(username, supplier) -> dict` and `sync_distribution_catalog(username, supplier, progress=None) -> dict`.
- Produces `GET|POST /api/distribution/catalog/sync` and `GET /api/distribution/catalog`.

- [ ] **Step 1: Write failing tests**

```python
def test_catalog_sync_saves_both_resource_types_per_operator(self):
    class FakeSupplier:
        def list_self_media(self, page, limit):
            return [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}] if page == 1 else []
        def list_news_media(self, page, limit):
            return [{"resource_id": "8", "name": "媒体A", "price": 99, "status": "1", "raw": {}}] if page == 1 else []
    result = geo_app.sync_distribution_catalog("alice", FakeSupplier())
    self.assertEqual(result["count"], 2)
    self.assertEqual([(x["resource_type"], x["resource_id"]) for x in geo_app.load(geo_app.distribution_catalog_path("alice"), [])], [("self_media", "7"), ("news_media", "8")])

def test_catalog_query_is_local_and_isolated_by_operator(self):
    # Persist Alice and Bob catalogs, call the route while each is logged in,
    # and assert only the matching local resource is returned.
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_auth.UserSettingsTests.test_catalog_sync_saves_both_resource_types_per_operator -v`

Expected: FAIL because `sync_distribution_catalog` does not exist.

- [ ] **Step 3: Write the minimal implementation**

```python
def sync_distribution_catalog(username, supplier, progress=None):
    resources = []
    for resource_type, list_page in (("self_media", supplier.list_self_media), ("news_media", supplier.list_news_media)):
        page = 1
        while True:
            batch = list_page(page, 200)
            resources.extend({**item, "resource_type": resource_type} for item in batch)
            if len(batch) < 200:
                break
            page += 1
    save(distribution_catalog_path(username), resources)
    return {"count": len(resources)}
```

Add the asynchronous job wrapper following the existing job pattern, status and query routes, and do not call any order API.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_auth.UserSettingsTests -v`

Expected: PASS.

### Task 2: Make favorites catalog-backed and refreshable by ID [x]

**Files:**
- Modify: `app.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- `POST /api/distribution/favorites` accepts `{resource_id, resource_type}` and rejects resources absent from the current operator catalog.
- `POST /api/distribution/favorites/refresh` looks up each favorite by its type and ID, updates the local catalog, and returns `{count}`.
- `GET /api/distribution/favorites` returns favorites resolved with current catalog name, price, and status.

- [ ] **Step 1: Write failing tests**

```python
def test_favorite_is_added_from_catalog_and_refreshes_by_its_id(self):
    # Seed Alice's catalog with resource 7, add it through the route, then use
    # a fake supplier returning a changed price and assert only (1, 5, "7")
    # was requested and the displayed favorite price changed.

def test_cannot_add_favorite_not_in_current_operator_catalog(self):
    # Post a valid-shaped ID without seeding it and assert 404 catalog_resource_not_found.
```

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_auth.UserSettingsTests.test_favorite_is_added_from_catalog_and_refreshes_by_its_id tests.test_auth.UserSettingsTests.test_cannot_add_favorite_not_in_current_operator_catalog -v`

Expected: FAIL because the current route accepts arbitrary names and IDs.

- [ ] **Step 3: Write minimal implementation**

Store `{id, resource_id, resource_type}` for new favorites. Resolve display fields by joining favorites against the local catalog. For refresh, call `list_self_media(1, 5, resource_id=...)` or `list_news_media(1, 5, resource_id=...)` for each favorite, replace matching catalog entries, and leave failures reported without overwriting old entries.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_auth.UserSettingsTests -v`

Expected: PASS.

### Task 3: Publish from current operator favorites, not client-scoped manual resources [x]

**Files:**
- Modify: `app.py`
- Modify: `tests/test_distribution_routes.py`

**Interfaces:**
- `GET /api/distribution/resources?client_id=...` returns the current operator’s catalog-backed favorites after checking client access.
- `POST /api/distribution/orders` accepts only a resource present in those favorites and uses its refreshed price.

- [ ] **Step 1: Write failing tests**

```python
def test_publish_resources_are_the_current_operators_favorites(self):
    # Seed a favorite/catalog for operator, without client resources, and assert
    # GET resources returns it after client access is checked.

def test_order_uses_a_catalog_backed_favorite_without_manual_client_sync(self):
    # Seed draft and operator catalog/favorite, patch the supplier, post order,
    # and assert the supplier receives the catalog price.
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_distribution_routes -v`

Expected: FAIL because the route still reads `PublicationStore` client resources.

- [ ] **Step 3: Write minimal implementation**

Use the same catalog-resolved favorites helper in the resource listing and order route. Retain existing client access, credentials, public preview URL, and confirmation behavior. Delete the obsolete manual resource-sync route only after its callers and tests are removed.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_distribution_routes -v`

Expected: PASS.

### Task 4: Replace manual-ID controls with catalog search and common-platform controls [x]

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_content_generation_ui.py`

**Interfaces:**
- `loadDistributionCatalog`, `searchDistributionCatalog`, `startDistributionCatalogSync`, and `refreshDistributionFavorites` use the new routes.
- The resource page has no input or button that asks the operator to enter, save, or match a supplier resource ID.

- [ ] **Step 1: Write a failing static UI test**

```python
def test_resource_page_uses_catalog_search_not_manual_id_matching(self):
    html = read("templates/index.html")
    js = read("static/js/app.js")
    self.assertIn("distributionCatalogSearch", html)
    self.assertIn("刷新常用平台信息", html)
    self.assertNotIn("匹配供应商资源", html)
    self.assertNotIn("distributionFavoriteResourceId", html)
    self.assertIn("searchDistributionCatalog", js)
```

- [ ] **Step 2: Run the UI test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_content_generation_ui -v`

Expected: FAIL because the page still contains manual matching controls.

- [ ] **Step 3: Write minimal implementation**

Replace the old favorites/match/manual sync cards with: full-catalog sync status/button; local search input/results with “加入常用平台”; current favorites showing name, type, ID, price/status, refresh and remove buttons. Keep IDs as display-only metadata.

- [ ] **Step 4: Run UI tests and JavaScript syntax verification**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_content_generation_ui -v; node --check static\\js\\app.js`

Expected: PASS and no syntax errors.

### Task 5: Verify the complete change [x]

**Files:**
- Modify only files needed to fix verification failures.

- [ ] **Step 1: Check whitespace and compilation**

Run: `git diff --check; .\\.venv\\Scripts\\python.exe -m py_compile app.py services\\rwmeiti.py services\\publications.py`

Expected: exit code 0 (line-ending notices are acceptable).

- [ ] **Step 2: Run distribution and authentication tests**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_auth.UserSettingsTests tests.test_distribution_routes tests.test_rwmeiti tests.test_publications tests.test_content_generation_ui -v`

Expected: PASS.
