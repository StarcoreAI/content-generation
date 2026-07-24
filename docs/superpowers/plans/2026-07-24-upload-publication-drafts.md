# Upload Publication Drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators drag article files or select a folder on the Publish page and create editable publication drafts directly.

**Architecture:** Reuse `PublicationStore.create_draft`; uploaded source files are parsed in the request and become frozen draft title/body without entering quality gate. The browser submits multiple files from either drag/drop or a directory-enabled file input; no raw uploaded-file archive or new article table is needed.

**Tech Stack:** Flask, existing `python-docx`, vanilla JavaScript, Python `unittest`.

## Global Constraints

- Support `.txt`, `.md`, and `.docx` only.
- Each valid non-empty file creates one draft for the selected client.
- Preserve the existing public-preview and supplier-order flows.
- Do not create supplier orders as part of upload.

---

### Task 1: Add direct-upload draft API [x]

**Files:**
- Modify: `app.py`
- Modify: `tests/test_distribution_routes.py`

**Interfaces:**
- `POST /api/distribution/drafts/upload` accepts multipart `files` and `client_id`.
- Returns `{ok: true, drafts: [...], rejected: [...]}` for parsed non-empty documents and invalid files.

- [ ] **Step 1: Write failing route test**

```python
uploaded = client.post("/api/distribution/drafts/upload", data={
    "client_id": "client-a",
    "files": [(io.BytesIO("标题\n\n正文".encode()), "稿件.md")],
}, content_type="multipart/form-data")
self.assertEqual(uploaded.status_code, 200)
self.assertEqual(uploaded.get_json()["drafts"][0]["article_title"], "标题")
```

- [ ] **Step 2: Run it and verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_distribution_routes.DistributionRouteTests.test_upload_article_creates_publish_draft_directly -v`

Expected: FAIL with 404.

- [ ] **Step 3: Implement the minimal parser and route**

Use first non-empty text line as title, fallback to the filename stem. Parse UTF-8 text/Markdown directly and use `python-docx` for DOCX. Return a rejection per unsupported or empty file without failing valid files in the same batch.

- [ ] **Step 4: Run focused tests**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_distribution_routes -v`

Expected: PASS.

### Task 2: Add drag/drop and folder upload controls to Publish page [x]

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_content_generation_ui.py`

**Interfaces:**
- `uploadPublicationFiles(files)` posts selected files to `/api/distribution/drafts/upload` then refreshes the publish list.
- `#publicationFolderUpload` uses the browser directory-picker attribute.

- [ ] **Step 1: Write failing static UI test**

```python
self.assertIn('id="publicationFileUpload"', html)
self.assertIn('id="publicationFolderUpload"', html)
self.assertIn("uploadPublicationFiles", js)
self.assertIn("/api/distribution/drafts/upload", js)
```

- [ ] **Step 2: Run it and verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_content_generation_ui -v`

Expected: FAIL because the upload controls do not exist.

- [ ] **Step 3: Implement the minimal controls**

Add a file input, a `webkitdirectory` folder input, and a visible drop zone. Prevent browser navigation on drop, pass files to the upload helper, show success/rejection count, and reload the drafts.

- [ ] **Step 4: Run UI test and syntax check**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_content_generation_ui -v; node --check static\\js\\app.js`

Expected: PASS.

### Task 3: Verify the complete change [x]

- [ ] **Step 1: Run full targeted verification**

Run: `git diff --check; .\\.venv\\Scripts\\python.exe -m py_compile app.py; .\\.venv\\Scripts\\python.exe -m unittest tests.test_distribution_routes tests.test_content_generation_ui tests.test_publications -v; node --check static\\js\\app.js`

Expected: PASS.
