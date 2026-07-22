# Batch Generation v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click, strictly serial batch content-generation job for 1, 3, or 5 articles, while removing content-generation subtype use from the new pipeline.

**Architecture:** Keep batch state in process memory, matching the existing reference-analysis job pattern. A single daemon thread processes one article at a time by calling `app.run_content_generation`; it records progress in the job object and never introduces a second generation path. Sampling gets a small optional pair-avoidance input so the batch runner can avoid previously selected skeleton/opening pairs before any LLM call.

**Tech Stack:** Flask, Python standard-library `threading`, SQLite via `ContentGenerationStore`, vanilla browser JavaScript, `unittest`.

## Global Constraints

- One Gunicorn worker; articles must run strictly serially in one job thread.
- Reuse `run_content_generation`; do not make a new LLM generation chain.
- Do not modify crawler or local-worker code.
- Batch jobs are in-memory; no restart recovery is claimed in v1.
- `count` accepts only `1`, `3`, or `5`; the frontend default is `5`.
- Blocked articles are persisted and shown; failed writing attempts are only recorded in the batch ledger.
- Preserve `content_articles.article_subtype` storage compatibility; new-path writes are empty.

---

### Task 1: Add the batch job service and its tests

**Files:**
- Create: `services/batch_generation.py`
- Create: `tests/test_batch_generation.py`

**Interfaces:**
- Produces `BatchGenerationJobs(uid_fn, now_fn, run_generation_fn)` with `create`, `get`, `cancel`, and `run(job_id)`.
- `run_generation_fn(payload, *, batch_id, avoid_skeleton_opening_pairs, created_by)` returns the persisted article.
- Each job item is `{"index", "status", "article_id", "title", "error"}`; allowed statuses are `排队`, `生成中`, `完成`, `门禁拦截`, `失败`.

- [ ] **Step 1: Write failing serial-run tests**

```python
def test_run_calls_generation_one_at_a_time_and_accumulates_pairs(self):
    calls = []
    def generate(payload, **kwargs):
        calls.append(kwargs["avoid_skeleton_opening_pairs"])
        return {"id": str(len(calls)), "title": "A", "provenance": {"entries": {"skeleton": {"id": "s"}, "opening_module": {"id": f"o{len(calls)}"}}}}
    jobs = BatchGenerationJobs(lambda: "job", lambda: "now", generate)
    job = jobs.create({"client_id": "c"}, 3)
    jobs.run(job["job_id"])
    self.assertEqual([[], [("s", "o1")], [("s", "o1"), ("s", "o2")] ], calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_batch_generation -v`

Expected: import failure because `services.batch_generation` does not exist.

- [ ] **Step 3: Implement only the in-memory job container**

```python
class BatchGenerationJobs:
    def create(self, payload, count, created_by=""):
        # Copy only the request payload; build `count` queued items.
    def run(self, job_id):
        # Check cancellation before each item, call once, then update that item.
```

Use one `threading.RLock`; `run()` itself is synchronous so the Flask adapter owns thread creation.

- [ ] **Step 4: Add failure, cancellation, batch-id and blocked-item tests**

```python
def test_failed_article_is_recorded_and_later_items_continue(self): ...
def test_cancel_before_next_item_leaves_remaining_items_queued(self): ...
def test_every_generation_receives_the_same_batch_id(self): ...
def test_blocked_persisted_article_is_marked_门禁拦截(self): ...
```

- [ ] **Step 5: Run the service suite**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_batch_generation -v`

Expected: all batch service tests pass.

### Task 2: Add sampler pair avoidance and remove subtype from the new sampling API

**Files:**
- Modify: `services/brief_builder.py`
- Modify: `tests/test_brief_builder.py`

**Interfaces:**
- `build_brief_sample(..., avoid_skeleton_opening_pairs=None, ...)` no longer accepts `article_subtype`.
- Sample output no longer contains `article_subtype`.
- Pair representation is `(skeleton_id, opening_module_id)`; an empty opening uses `""`.

- [ ] **Step 1: Write failing pair-avoidance tests**

```python
def test_avoid_pairs_retries_when_skeleton_and_opening_pair_is_used(self): ...
def test_avoid_pairs_exhaustion_returns_sample_with_conflict_marker(self): ...
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_brief_builder -v`

Expected: keyword-argument error for `avoid_skeleton_opening_pairs`.

- [ ] **Step 3: Implement minimal retry rule**

```python
pair = (result["skeleton"]["id"], (result["opening_module"] or {}).get("id", ""))
if pair not in avoid_pairs and fingerprint not in recent:
    return result
```

Use the existing fingerprint retry limit. On exhaustion, preserve the existing fingerprint conflict behavior and add `sampling_meta["pair_conflict"]`.

- [ ] **Step 4: Remove subtype argument and assertions from this suite**

Update every `build_brief_sample` invocation and expected sample payload; keep all probability and fingerprint behavior tests.

- [ ] **Step 5: Run focused tests**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_brief_builder -v`

Expected: all pass.

### Task 3: Wire batch jobs and subtype removal through the shared generation entry

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_core.py`

**Interfaces:**
- `run_content_generation(payload, audience_angles=None, created_by="", batch_id="", avoid_skeleton_opening_pairs=None)` adds `batch_id` to the persisted article and passes avoidance to `build_brief_sample`.
- `POST /api/content/generate_batch` creates a job for `3` or `5`.
- `GET /api/content/generate_batch/<job_id>` returns the job only to an authorized client user.
- `POST /api/content/generate_batch/<job_id>/cancel` requests cancellation only to an authorized client user.

- [ ] **Step 1: Write failing route and entry-point tests**

```python
def test_generate_batch_rejects_invalid_count(self):
    for count in (0, 2, 4, 6, 11):
        self.assertEqual(400, self.client.post('/api/content/generate_batch', json={"client_id": "c", "count": count}).status_code)

def test_generate_batch_accepts_three_and_five(self): ...
def test_single_generate_response_shape_is_unchanged(self): ...
def test_batch_id_reaches_persisted_article(self): ...
```

- [ ] **Step 2: Run focused app tests and verify failure**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_app_core -v`

Expected: 404 for the new batch route.

- [ ] **Step 3: Add the smallest Flask adapter**

Add one process-wide `BatchGenerationJobs` instance guarded by its own `RLock`. The queue helper starts one daemon `threading.Thread`; it calls only the job service, whose generation callback calls `run_content_generation` with the job's `batch_id` and current avoidance list.

For `count == 1`, retain the existing `/api/content/generate` route and its exact response. The batch route accepts only `3` and `5` in the UI path, while validation may allow `1` for API consistency only if it returns a job by explicit test.

- [ ] **Step 4: Remove new-path subtype behavior**

Delete subtype reading, sample passing, and article-dict writing from `run_content_generation`. Do not alter `ContentGenerationStore` insert or row mapping.

- [ ] **Step 5: Run focused app tests**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_app_core tests.test_batch_generation -v`

Expected: all pass.

### Task 4: Expose the batch job in the content-production page

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `static/css/app.css` only if an existing status style cannot be reused
- Modify: `tests/test_content_generation_ui.py`
- Modify: `tests/test_frontend_crawl_order.py`

**Interfaces:**
- A fixed `1 / 3 / 5` selector has default value `5`.
- `1` retains `generateContentArticle()` and the existing single POST behavior.
- `3` and `5` call `/api/content/generate_batch`, poll its job route, render item statuses, and expose cancel.

- [ ] **Step 1: Write failing static UI assertions**

```python
def test_content_page_defaults_batch_count_to_five(self): ...
def test_content_page_keeps_single_generate_path_for_count_one(self): ...
def test_content_page_no_longer_renders_article_subtype_badges(self): ...
```

- [ ] **Step 2: Run UI tests and verify failure**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui tests.test_frontend_crawl_order -v`

Expected: selector and batch functions are absent.

- [ ] **Step 3: Implement the smallest UI state**

Use one `activeContentBatchJobId` plus one poll timer. Disable the button while polling; render `第 x/n 篇` and the existing job item statuses; cancel only sends the cancel POST. On terminal status, clear the timer, enable generation, and call `loadContentGenerations()`.

- [ ] **Step 4: Remove subtype badges only**

Delete `article_subtype` reads and `子类型：` labels from content and quality list renderers. Do not touch the legacy plugin compatibility functions.

- [ ] **Step 5: Run UI suites**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui tests.test_frontend_crawl_order -v`

Expected: all pass.

### Task 5: Remove subtype CLI plumbing and run the complete test set

**Files:**
- Modify: `scripts/dev_brief_builder.py`
- Modify: `scripts/dev_content_generate.py`
- Modify: `tests/test_dev_brief_builder.py`
- Modify: `tests/test_dev_content_generate.py`
- Modify: any directly failing new-pipeline test only

- [ ] **Step 1: Write/update failing CLI tests**

```python
def test_content_generate_payload_has_no_article_subtype(self): ...
def test_brief_builder_cli_has_no_article_subtype_option(self): ...
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_dev_content_generate tests.test_dev_brief_builder -v`

Expected: tests find `--subtype` or `--article-subtype`.

- [ ] **Step 3: Remove only CLI subtype arguments and payload fields**

Keep CLI `--count` and all existing material switches. Do not change the existing shared-entry call.

- [ ] **Step 4: Verify focused and full regression suites**

Run in order:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_generation -v
.\.venv\Scripts\python.exe -m unittest tests.test_brief_builder tests.test_app_core tests.test_content_generation_ui tests.test_frontend_crawl_order tests.test_dev_content_generate tests.test_dev_brief_builder -v
.\run_tests.bat
.\.venv\Scripts\python.exe -m py_compile app.py services\batch_generation.py services\brief_builder.py scripts\dev_content_generate.py scripts\dev_brief_builder.py
git diff --check
```

Expected: all unit tests pass; `run_tests.bat` has no regressions; compile and diff checks exit 0.

## Coverage Review

- Serial progress, errors, cancellation, common batch id, and pair avoidance are covered by Task 1.
- Pair retry and subtype sampler removal are covered by Task 2.
- Route validation, auth reuse, and unchanged single generation are covered by Task 3.
- Default-five UI, polling, cancel, and subtype badge removal are covered by Task 4.
- CLI subtype cleanup and full verification are covered by Task 5.
