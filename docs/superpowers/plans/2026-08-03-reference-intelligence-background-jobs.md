# Reference Intelligence Background Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let citation-intelligence analysis continue on the server after the browser request ends, while the operator sees queued, running, completed, or failed status through polling.

**Architecture:** Keep the existing article selection, cache, bounded fetch/model concurrency, route merge, and one-at-a-time analysis lock. Move only the long-running orchestration into a daemon thread, persist a small per-job status JSON file, and expose a short POST enqueue endpoint plus a GET status endpoint. The existing analysis function remains directly testable and receives the submitting operator's model settings explicitly.

**Tech Stack:** Flask, Python standard library (`threading`), existing JSON persistence helpers, vanilla browser `fetch` and `setTimeout`.

## Global Constraints

- Do not change citation source-selection rules, cache keys, model prompts, or the shared two-slot model semaphore.
- Do not introduce a queue service, database, broker, or frontend dependency.
- Keep one route-analysis job inside the existing process-wide reference-intelligence lock at a time.
- Capture the current user's model settings before starting the background thread; do not read Flask session state inside it.
- The polling response must not contain full article bodies or full analysis output.

---

### Task 1: Background Job API and Persistence

**Files:**
- Modify: `app.py:2436-2710`
- Test: `tests/test_query_platform_reference_api.py`

**Interfaces:**
- `POST /api/content-routes/analyze-query-platform` returns `{ok: true, job: {id, client_id, status, message}}` with status `queued`.
- `GET /api/content-routes/reference-analysis-jobs/<cid>/<job_id>` returns the same safe job state plus final counts/routes after completion.
- `run_reference_intelligence_analysis(payload, settings, progress)` performs the present synchronous analysis for the worker and returns its task result.

- [x] **Step 1: Write failing API tests.**

```python
def test_reference_analysis_enqueue_returns_a_queued_job_without_running_inline(self):
    response = client.post("/api/content-routes/analyze-query-platform", json=payload)
    assert response.status_code == 202
    assert response.get_json()["job"]["status"] == "queued"

def test_reference_analysis_status_reports_a_completed_job_without_full_task_payload(self):
    response = client.get(f"/api/content-routes/reference-analysis-jobs/{cid}/{job_id}")
    assert response.get_json()["job"]["status"] == "completed"
    assert "analyses" not in response.get_json()["job"]
```

- [x] **Step 2: Run the focused test and verify RED.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_query_platform_reference_api`

Expected: the current POST returns the full result synchronously and the status route is absent.

- [x] **Step 3: Extract the existing long-running endpoint body into `run_reference_intelligence_analysis`, add small JSON job state helpers, enqueue a daemon worker, and add the authorized status route.**

```python
job = {"id": uid(), "client_id": cid, "status": "queued", "message": "任务已提交，正在排队", "created_at": now_str()}
save_reference_intelligence_job(cid, job)
threading.Thread(target=worker, daemon=True).start()
return jsonify({"ok": True, "job": public_reference_intelligence_job(job)}), 202
```

- [x] **Step 4: Run the focused test and verify GREEN.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_query_platform_reference_api tests.test_formal_content_route_entry`

Expected: PASS.

### Task 2: Operator Polling UI

**Files:**
- Modify: `static/js/app.js:3229-3256`
- Test: `tests/test_content_generation_ui.py`

**Interfaces:**
- `runQueryPlatformReferenceAnalysis()` submits the job once and starts polling every two seconds.
- `pollReferenceAnalysisJob(job)` updates the existing status text; it reloads routes only on `completed`, reports `failed` safely, and re-enables the button in either terminal state.

- [x] **Step 1: Write a failing UI contract test.**

```python
def test_reference_intelligence_polls_a_background_job(self):
    assert "/api/content-routes/reference-analysis-jobs/" in script
    assert "pollReferenceAnalysisJob" in script
    assert "setTimeout" in function_body
```

- [x] **Step 2: Run the focused test and verify RED.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_content_generation_ui`

Expected: assertion failure because the current page waits for the full analysis response.

- [x] **Step 3: Replace the long synchronous wait with submit-and-poll logic using the existing status element and button.**

```javascript
const result = await api('/api/content-routes/analyze-query-platform', 'POST', payload);
if (result.error) throw new Error(result.error);
pollReferenceAnalysisJob(result.job);
```

- [x] **Step 4: Run the focused test and syntax check.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_content_generation_ui; node --check static/js/app.js`

Expected: PASS and exit code 0.

### Task 3: Regression Verification

**Files:** none

- [x] **Step 1: Run citation-intelligence focused tests.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_query_platform_reference_api tests.test_formal_content_route_entry tests.test_content_generation_ui`

Expected: PASS.

- [x] **Step 2: Run the project suite and static checks.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests; node --check static/js/app.js; git diff --check`

Expected: all commands exit with code 0.

### Task 4: Competitor Knowledge Background Job Parity

**Files:**
- Modify: `app.py:1620-1680, 2132-2148`
- Modify: `static/js/app.js:3417-3458`
- Test: `tests/test_competitor_knowledge.py`, `tests/test_content_generation_ui.py`

**Interfaces:**
- `POST /api/knowledge/competitors/<cid>/sync` returns a queued job immediately.
- `GET /api/knowledge/competitors/<cid>/sync-jobs/<job_id>` returns safe progress, completion, or failure state.
- The worker receives the submitting operator's model settings and preserves the existing manual-edit overwrite confirmation.

- [x] **Step 1: Write failing API and UI tests.**

```python
def test_competitor_knowledge_sync_enqueues_a_job():
    response = client.post(f"/api/knowledge/competitors/{cid}/sync", json={})
    assert response.status_code == 202
    assert response.get_json()["job"]["status"] == "queued"
```

- [x] **Step 2: Run the focused tests and verify RED.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_competitor_knowledge tests.test_content_generation_ui`

Expected: the sync route still returns a full synchronous result and the UI has no polling helper.

- [x] **Step 3: Persist a small competitor-sync job, run the present extraction/sync operation in a daemon thread with captured settings, and poll it from the existing daily-page button.**

- [x] **Step 4: Run focused tests and verify GREEN.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_competitor_knowledge tests.test_content_generation_ui`

Expected: PASS.

- [x] **Step 5: Repeat the full regression commands from Task 3.**
