# Manual RWMeiti Content Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Let operators manually send a chosen generated article to a RWMeiti self-media resource, track the order, and register the final URL for GEO attribution.

**Architecture:** Content generation remains unchanged. A new SQLite PublicationStore keeps frozen article snapshots, opaque public preview tokens, resource snapshots, supplier orders, and publication records in the current content SQLite database. A small stdlib-only RWMeiti client handles one supplier. Gate results are shown as context only: operators decide for all pass, warn, and blocked articles.

**Tech Stack:** Python stdlib (hashlib, urllib, secrets), Flask, SQLite, vanilla JS, unittest/mock.

## Global Constraints

- Every supplier submission and order refresh is explicitly triggered by an operator; do not automatically submit, retry, poll, cancel, or schedule supplier orders.
- V1 supports only self-media: wmedia_lst, create_wmedia_order, and query_wmedia_order.
- V1 passes the chosen supplier price directly as saling_price; do not add pricing, markup, calendar, approval, or generic-provider features.
- RWMEITI_SECRET_ID and RWMEITI_SECRET_KEY are server environment variables only; never place them in data files, API output, HTML, or JS.
- Keep the single-worker deployment and current multi-tenant 404 behavior. Do not change crawlers, local worker, or content-generation prompts.
- A preview route uses only a random token, freezes content at draft creation, and returns X-Robots-Tag: noindex, nofollow.
- All test provider calls are mocked. No real supplier order is part of development verification.

## Operator Flow

~~~text
运营在质量门禁页自行判断
-> 创建发布草稿（冻结标题、正文、门禁结果）
-> 外网确认预览链接可打开
-> 内容分发页手动同步自媒体资源
-> 选择资源，确认真实下单
-> 手动刷新订单状态
-> 完成且有发布 URL 时，系统写入发布登记
~~~

Before production enablement, request one fixed signing vector from the supplier: request parameters, expected uppercase MD5 signature, Content-Type, and response JSON. Match that vector in a mocked unit test before real credentials are used.

## File Structure

- Create: services/publications.py — the only writer for distribution state.
- Create: services/rwmeiti.py — signing and three supplier calls using urllib.request.
- Create: tests/test_publications.py and tests/test_rwmeiti.py.
- Modify: app.py, templates/index.html, static/js/app.js, static/css/app.css.
- Modify: tests/test_app_core.py, tests/test_auth.py, tests/test_content_generation_ui.py.
- Modify: .env.example, 工程化说明.md, 接手文档.md, docs/content-refactor-long-term.md.

---

### Task 1: Persist publication drafts and final publication registration

**Files:**
- Create: services/publications.py
- Create: tests/test_publications.py
- Modify: services/content_generations.py
- Modify: tests/test_content_generations_store.py

**Interfaces:**
- PublicationStore(db_path)
- create_draft(client_id, article, created_by)
- get_draft, get_draft_by_preview_token, list_drafts
- save_resources, list_resources
- create_supplier_order, update_supplier_order
- record_completed_publication, list_publications
- article_has_publication_state

- [ ] **Step 1: Write the failing storage tests.**

~~~python
def test_blocked_article_can_become_manual_draft_and_is_frozen(self):
    article = {
        "id": "a1", "title": "原标题", "content": "原正文",
        "gate_report": {"verdict": "blocked"},
    }
    draft = self.store.create_draft("client-a", article, "operator-a")
    article["content"] = "后来编辑的正文"

    saved = self.store.get_draft("client-a", draft["id"])
    self.assertEqual(saved["gate_verdict"], "blocked")
    self.assertEqual(saved["article_content"], "原正文")
    self.assertEqual(saved["status"], "draft")
    self.assertTrue(saved["preview_token"])

def test_completion_creates_one_publication_record(self):
    order = self.store.create_supplier_order(
        "client-a", "draft-1", "rw-100", "self_media", "7", "账号A", 88.0
    )
    first = self.store.record_completed_publication(
        "client-a", order["id"], "账号A", "https://example.com/a", "标题", "2026-07-22 10:00:00"
    )
    second = self.store.record_completed_publication(
        "client-a", order["id"], "账号A", "https://example.com/a", "标题", "2026-07-22 10:00:00"
    )
    self.assertEqual(first["id"], second["id"])
    self.assertEqual(len(self.store.list_publications("client-a")), 1)
~~~

- [ ] **Step 2: Run the test and verify it fails.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_publications -v  
Expected: import failure for services.publications.

- [ ] **Step 3: Implement the smallest store.**

Use the existing content SQLite file, but keep distribution tables separate from content_articles:

~~~sql
CREATE TABLE IF NOT EXISTS publication_drafts (
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, article_id TEXT NOT NULL,
  article_title TEXT NOT NULL, article_content TEXT NOT NULL,
  gate_verdict TEXT NOT NULL DEFAULT '', preview_token TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'draft', created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS supplier_resources (
  client_id TEXT NOT NULL, provider TEXT NOT NULL, resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', price REAL,
  status TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL DEFAULT '{}',
  synced_at TEXT NOT NULL,
  PRIMARY KEY (client_id, provider, resource_type, resource_id)
);
CREATE TABLE IF NOT EXISTS supplier_orders (
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, draft_id TEXT NOT NULL,
  provider TEXT NOT NULL, provider_order_no TEXT NOT NULL UNIQUE,
  resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, resource_name TEXT NOT NULL,
  price REAL, status TEXT NOT NULL, provider_url TEXT NOT NULL DEFAULT '',
  provider_reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publication_records (
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, article_id TEXT NOT NULL,
  draft_id TEXT NOT NULL, provider_order_id TEXT NOT NULL UNIQUE,
  channel_name TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
  published_at TEXT NOT NULL, advertising_labeled INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'rwmeiti', created_at TEXT NOT NULL
);
~~~

Use uuid.uuid4().hex for IDs, secrets.token_urlsafe(32) for tokens, json.dumps with ensure_ascii=False for raw resource payload, and BEGIN IMMEDIATE for writes. create_draft copies title/content/gate_report.verdict without validating the verdict. Unique provider_order_id makes registry writes idempotent.

- [ ] **Step 4: Protect traceable content from deletion.**

Add article_has_publication_state(client_id, article_id) and make the current delete route return 409 with error article_has_publication_state when a draft exists.

- [ ] **Step 5: Verify and commit.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_publications tests.test_content_generations_store -v  
Expected: PASS.

~~~powershell
git add services/publications.py services/content_generations.py tests/test_publications.py tests/test_content_generations_store.py
git commit -m "feat: persist manual publication drafts"
~~~

### Task 2: Add protected APIs and token-only public previews

**Files:**
- Create: templates/publication_preview.html
- Modify: app.py
- Modify: tests/test_app_core.py
- Modify: tests/test_auth.py

**Interfaces:**
- POST /api/distribution/drafts with client_id and article_id
- GET /api/distribution/drafts?client_id=<id>
- GET /api/distribution/publications?client_id=<id>
- GET /public/publications/<preview_token>

- [ ] **Step 1: Write failing route and tenant-isolation tests.**

~~~python
def test_operator_can_create_draft_for_blocked_article(self):
    response = self.client.post(
        "/api/distribution/drafts",
        json={"client_id": self.client_id, "article_id": "blocked-a"},
    )
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.get_json()["draft"]["gate_verdict"], "blocked")

def test_cross_tenant_distribution_read_is_404(self):
    response = self.other_client.get(
        "/api/distribution/drafts?client_id=" + self.client_id
    )
    self.assertEqual(response.status_code, 404)

def test_preview_needs_only_valid_token(self):
    response = self.client.get("/public/publications/" + self.draft["preview_token"])
    self.assertEqual(response.status_code, 200)
    self.assertIn("冻结正文", response.get_data(as_text=True))
    self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
~~~

- [ ] **Step 2: Run the tests and verify missing routes fail.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_app_core tests.test_auth -v  
Expected: failures for distribution and preview routes.

- [ ] **Step 3: Implement routes with current auth helpers.**

Create publication_store() beside content_generation_store(), using the same database path. Add only publication_preview to ANONYMOUS_ENDPOINTS. Every API route calls require_client_access(cid).

~~~python
@app.route("/api/distribution/drafts", methods=["POST"])
def create_publication_draft_route():
    data = request.get_json(silent=True) or {}
    cid = str(data.get("client_id") or "")
    article_id = str(data.get("article_id") or "")
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    article = content_generation_store().get_article(cid, article_id)
    if not article:
        return jsonify({"error": "article_not_found"}), 404
    draft = publication_store().create_draft(
        cid, article, (current_user() or {}).get("username", "")
    )
    return jsonify({"ok": True, "draft": draft})
~~~

The preview uses get_draft_by_preview_token and only renders the saved snapshot. publication_preview.html escapes title/body, has no authenticated app shell, client navigation, or private metadata.

- [ ] **Step 4: Verify and commit.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_app_core tests.test_auth tests.test_content_generations_store -v  
Expected: PASS; preview works without login, APIs do not.

~~~powershell
git add app.py templates/publication_preview.html tests/test_app_core.py tests/test_auth.py
git commit -m "feat: add publication draft APIs and previews"
~~~

### Task 3: Add RWMeiti self-media signing and manual resource synchronization

**Files:**
- Create: services/rwmeiti.py
- Create: tests/test_rwmeiti.py
- Modify: app.py
- Modify: .env.example
- Modify: 工程化说明.md

**Interfaces:**
- RWMeitiClient.list_self_media(page, limit)
- RWMeitiClient.create_self_media_order(title, content, mid, no, saling_price, account_rule)
- RWMeitiClient.query_self_media_orders(order_numbers)
- POST /api/distribution/resources/sync
- GET /api/distribution/resources?client_id=<id>&query=<text>

- [ ] **Step 1: Write the network-free client tests.**

~~~python
def test_signature_matches_supplier_vector_and_key_is_not_sent(self):
    params = {"page": 1, "secret_id": "sid", "timestamp": 1700000000}
    self.assertEqual(
        build_signature(params, "secret"),
        "4CDC99B74D47CAB45834CEF536CEED1B",
    )
    payload = build_form_payload(params, "SIGNATURE")
    self.assertNotIn("secret", payload)
    self.assertEqual(payload["signature"], "SIGNATURE")

@patch("services.rwmeiti.urlopen")
def test_list_self_media_normalizes_resource(self, mocked):
    mocked.return_value.__enter__.return_value.read.return_value = (
        b'{"code":200,"data":[{"id":7,"wemedia_name":"账号A","price":"88","status":1}]}'
    )
    self.assertEqual(self.client.list_self_media(1, 200)[0]["resource_id"], "7")
~~~

This unit vector verifies the documented ordering/MD5 rule. Also add the provider’s fixed request/response vector once supplied, before enabling production credentials; do not discover it with a real order.

- [ ] **Step 2: Run tests and verify the module import fails.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_rwmeiti -v  
Expected: import failure for services.rwmeiti.

- [ ] **Step 3: Implement the stdlib client.**

~~~python
def build_signature(params, secret_key):
    pairs = [
        f"{key}={params[key]}"
        for key in sorted(params)
        if key != "signature" and params[key] not in ("", None)
    ]
    raw = "&".join(pairs) + f"&key={secret_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

def _post_form(self, path, params):
    signed = {**params, "secret_id": self.secret_id, "timestamp": int(time.time())}
    signed["signature"] = build_signature(signed, self.secret_key)
    body = urllib.parse.urlencode(signed).encode("utf-8")
    req = urllib.request.Request(
        self.base_url + "/" + path, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))
~~~

The sync route loops page=1 onward with limit=200 and stops after the first short page. It stores normalized resource ID/name/price/status/raw data. There is no scheduler: the operator presses “同步自媒体资源”.

Add these names/defaults to .env.example:

~~~dotenv
RWMEITI_BASE_URL=http://dr.rwmeiti.com/meijieapi/daili3
RWMEITI_SECRET_ID=
RWMEITI_SECRET_KEY=
GEO_PUBLIC_BASE_URL=https://geo.example.com
~~~

Require GEO_PUBLIC_BASE_URL to be absolute https before submission. Supplier traffic remains server-side even if the provider base URL is HTTP.

- [ ] **Step 4: Verify and commit.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_rwmeiti tests.test_app_core tests.test_auth -v  
Expected: PASS with urlopen mocked.

~~~powershell
git add services/rwmeiti.py tests/test_rwmeiti.py app.py .env.example 工程化说明.md
git commit -m "feat: sync rwmeiti self-media resources"
~~~

### Task 4: Submit and manually refresh supplier orders

**Files:**
- Modify: services/publications.py
- Modify: services/rwmeiti.py
- Modify: app.py
- Modify: tests/test_publications.py
- Modify: tests/test_rwmeiti.py
- Modify: tests/test_app_core.py

**Interfaces:**
- POST /api/distribution/orders with client_id, draft_id, resource_id
- POST /api/distribution/orders/<order_id>/refresh with client_id
- GET /api/distribution/orders?client_id=<id>
- Timeout status: submit_unknown; automatic retry: prohibited.

- [ ] **Step 1: Write failing idempotency tests.**

~~~python
def test_submit_uses_one_stable_provider_order_number(self):
    first = self.client.post("/api/distribution/orders", json=self.payload)
    second = self.client.post("/api/distribution/orders", json=self.payload)
    self.assertEqual(first.status_code, 200)
    self.assertEqual(second.status_code, 409)
    self.assertEqual(self.provider.create_calls, ["geo-" + self.draft_id])

def test_timeout_is_saved_as_unknown_without_retry(self):
    self.provider.create_error = TimeoutError("timed out")
    response = self.client.post("/api/distribution/orders", json=self.payload)
    self.assertEqual(response.status_code, 202)
    self.assertEqual(response.get_json()["order"]["status"], "submit_unknown")
    self.assertEqual(len(self.provider.create_calls), 1)
~~~

- [ ] **Step 2: Run targeted tests and verify missing submission routes fail.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_publications tests.test_rwmeiti tests.test_app_core -v  
Expected: failures for /api/distribution/orders.

- [ ] **Step 3: Implement one deliberate submit path.**

Save selected resource ID/name/price before the request. Use geo- plus draft ID as the durable supplier order number. Send the required preview link as content:

~~~python
preview_url = publication_preview_url(draft["preview_token"])
content = '稿件链接：<a href="' + html.escape(preview_url, quote=True) + '">' + html.escape(preview_url) + "</a>"
result = client.create_self_media_order(
    title=draft["article_title"], content=content, mid=resource["resource_id"],
    no="geo-" + draft["id"], saling_price=resource["price"], account_rule=3,
)
~~~

account_rule=3 is fixed in V1 to request no account substitution. A timeout/malformed response writes submit_unknown and returns “勿重复提交；请刷新状态或联系供应商”; it never calls create again.

Refresh uses query_wmedia_order. Map -2/-1/0/1/2 to deleted/rejected/pending/publishing/completed. A completed response with URL calls record_completed_publication. Completed without URL stays completed but is not registered.

- [ ] **Step 4: Verify and commit.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_publications tests.test_rwmeiti tests.test_app_core tests.test_auth -v  
Expected: PASS; provider interactions are mocked.

~~~powershell
git add services/publications.py services/rwmeiti.py app.py tests/test_publications.py tests/test_rwmeiti.py tests/test_app_core.py
git commit -m "feat: submit and track manual rwmeiti orders"
~~~

### Task 5: Add the operator distribution page

**Files:**
- Modify: templates/index.html
- Modify: static/js/app.js
- Modify: static/css/app.css
- Modify: tests/test_content_generation_ui.py

**Interfaces:**
- loadDistributionPage()
- createDistributionDraft(articleId)
- syncDistributionResources()
- submitDistributionOrder(draftId, resourceId)
- refreshDistributionOrder(orderId)

- [ ] **Step 1: Write failing UI tests.**

~~~python
def test_distribution_page_and_actions_are_wired(self):
    self.assertIn("navTo('distribution'", self.template)
    self.assertIn('id="page-distribution"', self.template)
    self.assertIn("createDistributionDraft", self.script)
    self.assertIn("syncDistributionResources", self.script)
    self.assertIn("submitDistributionOrder", self.script)
    self.assertIn("refreshDistributionOrder", self.script)

def test_blocked_articles_are_not_hidden_from_manual_distribution(self):
    self.assertNotIn("gate_report?.verdict === 'blocked' ? ''", self.script)
~~~

- [ ] **Step 2: Run test and verify it fails.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui -v  
Expected: missing distribution UI assertions.

- [ ] **Step 3: Implement the minimum UI.**

Add 内容分发 after 质量门禁 in the sidebar. Its only cards are: 待处理发布草稿, 自媒体资源（同步与名称搜索）, and 供应商订单与发布结果. Do not add providers, price rules, a calendar, automatic refresh, or an approval queue.

Show “创建发布草稿” on every quality-gate article card, no matter its verdict. Before submitDistributionOrder calls the API, use confirm() to show frozen title, resource name, supplier price, and “将向供应商创建真实发稿订单，可能扣费。确认提交？”. A submit_unknown order displays “勿重复提交；请刷新状态或联系供应商”. Reuse current api, toast, escHtml, currentClientId, and navTo helpers.

- [ ] **Step 4: Verify and commit.**

Run: ./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui tests.test_app_core tests.test_auth -v  
Expected: PASS; no automatic-submit timer or verdict-based block exists.

~~~powershell
git add templates/index.html static/js/app.js static/css/app.css tests/test_content_generation_ui.py
git commit -m "feat: add manual content distribution workspace"
~~~

### Task 6: Document and verify without spending money

**Files:**
- Modify: 工程化说明.md
- Modify: 接手文档.md
- Modify: docs/content-refactor-long-term.md

- [ ] **Step 1: Document the exact operating sequence.**

~~~text
选择客户 -> 运营在质量门禁页决定是否创建发布草稿（门禁仅供参考）
-> 确认预览 URL 可外网访问 -> 同步自媒体资源
-> 选择资源并确认真实下单 -> 手动刷新供应商状态
-> 订单完成且有 URL 后检查发布登记。
~~~

State that unknown submissions cannot be re-submitted before querying supplier order number, and secret_key is server .env only. Update the long-term document to say supplier submission is manually triggered for every verdict while publication registration/attribution remains the goal.

- [ ] **Step 2: Run non-destructive verification.**

~~~powershell
.\.venv\Scripts\python.exe -m py_compile app.py services\publications.py services\rwmeiti.py
.\.venv\Scripts\python.exe -m unittest tests.test_publications tests.test_rwmeiti tests.test_content_generations_store tests.test_content_generation_ui tests.test_app_core tests.test_auth -v
.\run_tests.bat
git diff --check
~~~

Expected: all tests pass, no whitespace errors, and no command calls RWMeiti.

- [ ] **Step 3: Run one operator-controlled staging check.**

If supplier provides non-production credentials, verify only resource synchronization and a public preview URL. Do not call create-order unless an operator explicitly approves a real chargeable test order.

- [ ] **Step 4: Commit.**

~~~powershell
git add 工程化说明.md 接手文档.md docs/content-refactor-long-term.md
git commit -m "docs: document manual content distribution operations"
~~~

## Self-review

- Manual decision for every gate result is covered by Tasks 1, 2, 4, and 5.
- Supplier work is intentionally self-media only; add news/short-video endpoints only after V1 is used successfully.
- Excluded deliberately: automatic publishing, workers, retries, cancellation, price configuration, provider abstraction, and attribution reports.
- A timeout cannot create a second chargeable request, post-draft edits cannot alter supplier preview content, secrets do not leave the server, and client access is checked for every client-scoped operation.
