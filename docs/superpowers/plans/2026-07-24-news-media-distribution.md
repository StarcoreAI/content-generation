# News Media Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator sync and manually submit one frozen publication draft to either a RWMeiti self-media or news-media resource.

**Architecture:** Keep one resource table and one order route. Each stored resource carries `resource_type` (`self_media` or `news_media`), and the order route dispatches to the corresponding RWMeiti endpoint. The browser sends the selected resource ID and type; short video is excluded.

**Tech Stack:** Flask, SQLite, Python stdlib, vanilla JavaScript, unittest/mock.

## Global Constraints

- Every supplier submission remains explicitly triggered by an operator.
- Submit the frozen draft's HTML body; do not use a public preview link.
- Support only `self_media` and `news_media`; do not add short-video code or UI.
- Use the operator's existing per-user RWMeiti credentials; never expose them to the browser.
- Do not introduce a provider abstraction, background publishing, automatic retry, or a new database table.
- User asked not to commit each task; leave all work uncommitted.

---

### Task 1: Add the RWMeiti news-media request methods

**Files:**
- Modify: `services/rwmeiti.py`
- Test: `tests/test_rwmeiti.py`

**Interfaces:**
- Produces `RWMeitiClient.list_news_media(page=1, limit=200, resource_id=None)`.
- Produces `RWMeitiClient.create_news_media_order(title, content, mid, no, saling_price)` which POSTs `create_media_order`.

- [ ] **Step 1: Write the failing test**

```python
@patch("services.rwmeiti.urlopen")
def test_create_news_media_order_uses_news_endpoint(self, mocked):
    mocked.return_value.__enter__.return_value.read.return_value = b'{"code":200}'
    client = RWMeitiClient("http://example.test", "sid", "secret")
    client.create_news_media_order("标题", "<p>正文</p>", "1364", "geo-1", 99)
    request = mocked.call_args.args[0]
    self.assertTrue(request.full_url.endswith("/create_media_order"))
    self.assertIn("mid=1364", request.data.decode("utf-8"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_rwmeiti.RWMeitiTests.test_create_news_media_order_uses_news_endpoint -v`

Expected: FAIL because `create_news_media_order` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def create_news_media_order(self, title, content, mid, no, saling_price):
    return self._post_form("create_media_order", {
        "title": title, "content": content, "mid": mid, "no": no,
        "saling_price": saling_price,
    })
```

Also pass the optional `id` argument to `media_lst` when a single news-media resource is synchronized.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_rwmeiti -v`

Expected: PASS.

### Task 2: Preserve resource type and dispatch the server-side order

**Files:**
- Modify: `services/publications.py`
- Modify: `app.py`
- Test: `tests/test_distribution_routes.py`
- Test: `tests/test_publications.py`

**Interfaces:**
- `PublicationStore.upsert_resources` stores `item.get("resource_type") or "self_media"`.
- `PublicationStore.get_resource(client_id, resource_id, resource_type)` returns only the selected type.
- `POST /api/distribution/resources/sync` accepts `resources: [{"resource_id": "1364", "resource_type": "news_media"}]`; legacy `resource_ids` remains self-media.
- `POST /api/distribution/orders` accepts `resource_type` and dispatches to the matching client method.

- [ ] **Step 1: Write the failing tests**

```python
def test_resource_store_keeps_same_id_in_two_types(self):
    self.store.upsert_resources("client-a", [
        {"resource_id": "7", "resource_type": "self_media", "name": "账号", "price": 88, "status": "1"},
        {"resource_id": "7", "resource_type": "news_media", "name": "媒体", "price": 99, "status": "1"},
    ], "2026-07-24 10:00:00")
    self.assertEqual(self.store.get_resource("client-a", "7", "news_media")["name"], "媒体")

def test_order_dispatches_news_media_to_news_client(self):
    response = client.post("/api/distribution/orders", json={
        "client_id": client_id, "draft_id": draft["id"],
        "resource_id": "1364", "resource_type": "news_media",
    })
    self.assertEqual(response.status_code, 200)
    self.assertEqual(supplier.news_order[2], "1364")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_publications tests.test_distribution_routes -v`

Expected: FAIL because storage hardcodes self-media and the route always calls `create_self_media_order`.

- [ ] **Step 3: Write minimal implementation**

```python
resource_type = str(data.get("resource_type") or "self_media")
if resource_type not in {"self_media", "news_media"}:
    return jsonify({"error": "invalid_resource_type"}), 400
resource = publication_store().get_resource(cid, resource_id, resource_type)
create_order = (client.create_news_media_order if resource_type == "news_media"
                else client.create_self_media_order)
result = create_order(draft["article_title"], supplier_content, resource_id, order_no, resource["price"])
```

Use `list_news_media(..., resource_id=...)` for news-media synchronization and retain the existing self-media behavior for legacy requests.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_publications tests.test_distribution_routes tests.test_rwmeiti -v`

Expected: PASS.

### Task 3: Let the operator choose and sync either type in the UI

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Test: `tests/test_content_generation_ui.py`

**Interfaces:**
- Resource list and publish options display `自媒体` or `新闻媒体`.
- The publish selection sends `resource_type` with `resource_id`.
- Temporary synchronization has one type selector, defaulting to self-media.
- A matched favorite candidate can be synchronized with its returned type.

- [ ] **Step 1: Write the failing UI assertion**

```python
def test_distribution_ui_sends_resource_type_for_news_media(self):
    source = Path("static/js/app.js").read_text(encoding="utf-8")
    self.assertIn("resource_type", source)
    self.assertIn("新闻媒体", source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui.ContentGenerationUiTests.test_distribution_ui_sends_resource_type_for_news_media -v`

Expected: FAIL because the current page labels every resource as self-media and only submits its ID.

- [ ] **Step 3: Write minimal implementation**

```javascript
const resource = JSON.parse(document.getElementById('publish-resource-' + draftId).value);
await api('/api/distribution/orders', 'POST', {
  client_id: currentClientId, draft_id: draftId,
  resource_id: resource.resource_id, resource_type: resource.resource_type,
});
```

Render only the two supported labels and send the selected type to the existing sync endpoint. Do not add a video option.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui -v; node --check static/js/app.js`

Expected: PASS.

### Task 4: Full verification

**Files:**
- Modify only files from Tasks 1-3.

- [ ] **Step 1: Run focused validation**

Run: `git diff --check; ./.venv/Scripts/python.exe -m py_compile app.py services/publications.py services/rwmeiti.py; ./.venv/Scripts/python.exe -m unittest tests.test_rwmeiti tests.test_publications tests.test_distribution_routes tests.test_auth.UserSettingsTests tests.test_content_generation_ui -v; node --check static/js/app.js`

Expected: exit code 0; the only tolerated output is Git's existing CRLF warnings.

- [ ] **Step 2: Verify manually without supplier calls**

Use Flask's mocked test client to check that a self-media order calls only `create_self_media_order`, a news-media order calls only `create_news_media_order`, and both receive the frozen HTML body.

## Self-review

- The plan covers both types from resource synchronization through manual order submission.
- The shared resource table uses its existing type-aware primary key, so identical IDs cannot overwrite each other.
- Short video, automatic publishing, price calculation, and status polling are intentionally excluded.
