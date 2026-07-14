# Crawl Job Pending Expiry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop local crawler workers from claiming stale pending crawl jobs by expiring unclaimed crawl jobs after 2 minutes and making claimed job scope visible in logs.

**Architecture:** Keep the existing JSON-backed queue. Add expiry at the shared crawl-job store boundary so every claimant gets the same behavior. Add lightweight batch metadata from the frontend, but do not introduce a new scheduler.

**Tech Stack:** Python standard library, Flask routes, vanilla JavaScript, `unittest`.

## Global Constraints

- Pending crawl job expiry is 2 minutes.
- Expiry applies only to `job_type="crawl"` and `status="pending"`.
- Running jobs are not auto-expired.
- No new dependency.
- Do not touch real `data/` during tests.

---

### Task 1: Queue Expiry

**Files:**
- Modify: `services/crawl_jobs.py`
- Test: `tests/test_app_core.py`

**Interfaces:**
- Produces: `expires_at` field on crawl jobs.
- Updates: `claim_next_job(path, worker_id, platform, now_fn, created_by=None)` skips expired pending jobs.

- [ ] **Step 1: Write failing tests for expired and fresh pending jobs**
- [ ] **Step 2: Run `.\.venv\Scripts\python.exe -m unittest tests.test_app_core.CoreFunctionTests.test_crawl_job_pending_expiry_skips_stale_job tests.test_app_core.CoreFunctionTests.test_crawl_job_pending_expiry_keeps_fresh_job -v` and verify failure**
- [ ] **Step 3: Implement 2-minute expiry in `services/crawl_jobs.py`**
- [ ] **Step 4: Re-run the same tests and verify pass**

### Task 2: Batch Metadata and Worker Log

**Files:**
- Modify: `app.py`
- Modify: `static/js/app.js`
- Modify: `scripts/local_crawl_worker.py`
- Test: `tests/test_app_core.py`
- Test: `tests/test_frontend_crawl_order.py`
- Test: `tests/test_local_crawl_worker.py`

**Interfaces:**
- Consumes: optional `batch_id` in `/api/crawl_jobs` POST body.
- Produces: `batch_id` on job records.
- Produces: local worker log line including `client_id`, `brand`, `group_id`, and `batch_id`.

- [ ] **Step 1: Write failing tests for `batch_id` pass-through, frontend batch generation, and worker scope logging**
- [ ] **Step 2: Run targeted tests and verify failure**
- [ ] **Step 3: Implement minimal pass-through and logging**
- [ ] **Step 4: Run targeted tests and syntax checks**

### Task 3: Verification

**Files:**
- Verify only.

**Interfaces:**
- Confirms no regression in crawl job and local worker behavior.

- [ ] **Step 1: Run `.\.venv\Scripts\python.exe -m unittest tests.test_app_core tests.test_local_crawl_worker tests.test_frontend_crawl_order tests.test_auth -v`**
- [ ] **Step 2: Run `.\.venv\Scripts\python.exe -m py_compile services\crawl_jobs.py scripts\local_crawl_worker.py app.py`**
- [ ] **Step 3: Report exact pass/fail output**
