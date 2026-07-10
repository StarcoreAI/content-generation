# Content Generation Cloud Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Wednesday-ready internal cloud trial focused on content generation, with login protection, reliable customer-material ingestion, multi-turn article generation, and a conservative crawler data strategy.

**Architecture:** Keep content generation as the primary product surface. Deploy the Flask app as a protected internal service, with JSON storage made safer for low-concurrency use and deployment packaged so the Windows development environment can be tested against a Linux-like runtime. Do not promise stable multi-user cloud crawling before the content-generation flow is usable.

**Tech Stack:** Flask, Python 3.12, JSON files under `data/`, PDF extraction via `pdfplumber` / `PyMuPDF` / `pypdf` / `python-docx`, Docker or Ubuntu service deployment, optional Nginx reverse proxy, existing unittest suite.

## 2026-07-06 Handoff Status

Current state after the latest agent window:

- Content generation is the active delivery surface. Crawler internals are intentionally paused.
- Retired frontend modules and old `/api/articles/*` content-generation remnants have been removed from the usable UI/API surface.
- Default page is now question group management.
- Content generation history now uses SQLite via `services/content_generations.py`.
- Article generation supports explicit `对比型` and `介绍型` buttons. The backend no longer infers type from operations text.
- Article-type histories are isolated, but generated articles are still displayed together newest-first.
- Generated result cards show the configured model and article type.
- Startup scripts are simplified: use `run_dev.bat` for local development and `启动局域网.bat` only for LAN demos.
- Latest full local verification: `.\run_tests.bat -> 133 tests OK`.

## 2026-07-08 Status Update

Current state after the July 8 local work:

- Account login and operator self-registration are implemented. Registered users are operators, not admins.
- User model/API settings are isolated per login account under `data/user_settings/<username>.json`. Global `data/settings.json` remains a fallback/default, not the shared write target for logged-in operators.
- The group crawler repeat selector now includes `2次`.
- Entity normalization for competitor/store mentions is queued after raw crawl data is saved. It no longer blocks the crawler response or the next platform.
- Entity writeback merges by `record_id` against the latest `raw_records.json`, so it should not overwrite records added by a parallel platform crawl.
- Platform crawling now uses per-platform locks instead of one global lock. Different AI platforms can run in parallel; the same platform remains serialized and returns `crawl_busy` if duplicated.
- The frontend group crawl flow and Agent task flow use a limited platform pool with `CRAWL_PLATFORM_CONCURRENCY = 2`.
- JSON append paths touched by crawler output now use locked read-modify-write helpers for same-process safety: `records.json`, `raw_records.json`, and daily raw files.
- Reference intelligence has a local three-stage flow: high-frequency article statistics, second-stage structure clustering (`clusters` only), then third-stage plugin rewriting (`subtype_name`, `prompt_text`, `few_shot`). As of 2026-07-09, those plugins are available as content-generation subtypes, and `攻略对比型` is the default comparison subtype.
- Local-operations-machine crawling now has a first end-to-end task-center path: `POST /api/crawl_jobs`, `GET /api/crawl_jobs/next`, `POST /api/crawl_jobs/<job_id>/result`, and `POST /api/crawl_jobs/<job_id>/cancel` store and update jobs under `data/crawl_jobs.json`. Returned worker payloads are sanitized to avoid storing cookies, storage state, passwords, tokens, or session secrets. Successful worker results are persisted into `raw_records.json` and daily raw files, with duplicate result submissions ignored by `task_id`. Canceled jobs are not claimed, and late results for canceled jobs are not ingested.
- `scripts/local_crawl_worker.py` and `start_local_crawl_worker.bat` provide the local worker shell and reuse the existing external Node crawler through `services.node_crawler_bridge.run_node_crawler`. Long-running worker mode starts one worker loop per platform so different platforms can run in parallel while each platform remains serialized. As of 2026-07-09, the question-group `一键创建爬取任务` action enqueues local-worker jobs by default; the separate "交给本地 worker" action was removed.
- Kimi is now included in the app-level platform list, customer contract-platform choices, question-group custom platform choices, local worker defaults, and crawler smoke ordering. A real temporary Kimi task-center smoke completed: create crawl job -> local worker claim -> Node Kimi crawl -> result submit -> `raw_records.json` ingestion.
- The local worker now checks cancellation again before result submission. If a running job was canceled, the worker skips submit; if that status check fails, it still submits and relies on the server-side canceled-job ingestion guard instead of dropping the result.
- Windows operator packaging now includes setup, start, stop, operator logging, and diagnostic export entries. Not implemented yet: true cloud-initiated termination of the local browser/Node subprocess, worker heartbeat, and stale-running cleanup.
- Latest full local verification: `.\run_tests.bat -> 189 tests OK`.

Remaining constraints:

- Keep the cloud trial on one Gunicorn worker. The new locks are process-local and do not make JSON storage safe across multiple workers.
- Cloud crawling is still not the first trial promise. The crawler can be tested, but the primary cloud acceptance path remains content generation plus login. The crawler direction is a cloud task center plus local operations-machine worker, not server-side browser crawling.

Next agent should deploy using `scripts/deploy_cloud_package.sh` instead of pasting long SSH command blocks, then lightly verify login, content generation, reference-intelligence subtypes, Kimi platform selection, and local-worker job creation/result ingestion. If cloud daily data is missing local crawler records, use `scripts/import_missing_raw_records.py` to append only missing raw records; do not overwrite cloud `data/raw_records.json`. Task 3 is partly reduced by SQLite content-history storage, shared JSON-storage locking tests, and the July 8 same-process append protections, but the production constraint remains: run one worker until all mutable app data is moved to a real database or protected by a cross-process lock.

Do not use this plan to justify large cleanup. The current goal is cloud-readiness for a small internal operations team, not a rewrite.

## 2026-07-09 Morning Real Cloud Worker Test Finding (Historical)

This section records the morning failure analysis. Evening fixes and packaging
work supersede the operational recommendations here; use the latest section 0
in `接手文档.md` for the current handoff state.

The latest code was deployed to `/srv/geo-content-v2`; health returned `ok=true`, and `/api/health` included `kimi`. The cloud code was verified to contain `--check`, `STORAGE_STATE_PATH`, and `189 tests` handoff text.

One real Windows local-worker test was run against the cloud task center. The selected question group unexpectedly contained three questions: `你好`, `Hello`, and `星核引力是什么公司`, so the test was not a clean 1-question validation.

Observed cloud job state:

- `deepseek`: local Markdown/logs show 3 questions completed, but cloud job still has `result_summary=None` and `persisted_records=0`.
- `yuanbao`: `result_summary={'total': 3, 'success': 3}`, `persisted_records=3`.
- `qwen`: `result_summary={'total': 3, 'success': 1}`, `persisted_records=1`; the two greeting questions became `empty_result`, while the real company question succeeded.
- `kimi`: local Markdown/logs show 3 questions completed, but cloud job still has `result_summary=None` and `persisted_records=0`.
- `doubao`: failed with `need_login`; saved state is invalid or missing.

Morning implications at the time:

- At the time, do not hand the worker to operations yet.
- DeepSeek/Kimi likely failed during local worker submit or the platform thread exited before submit; add explicit submit-start/submit-success/submit-failure logging in `scripts/local_crawl_worker.py`.
- Before the next validation, create a clean one-question group containing only `星核引力是什么公司？`.
- Test `yuanbao,qwen,kimi,deepseek` first; run Doubao separately after refreshing login state.
- Update the cloud job creation UI/log output to show question count and a preview of selected questions, so operators can see when they accidentally selected a multi-question group.

## Global Constraints

- Wednesday scope is content generation: login, customer materials, PDF parsing, sample article reference, multi-turn rewriting, and generation history.
- Do not commit secrets. `data/settings.json` contains real API settings and must not be copied into public docs or commits.
- Do not expose the app publicly without login protection and a server-side `SECRET_KEY`.
- Do not deploy Flask production traffic with `debug=True`.
- If JSON file storage remains for Wednesday, run only one web worker or add file-level write protection before multi-user use.
- Cloud crawling is not the Wednesday stability promise. Crawler data can come from a designated stable local machine or a colleague's crawler output if fields are aligned.
- Do not start a major refactor of `app.py` or `templates/index.html` before the Wednesday trial; only isolate code where it directly reduces deployment or safety risk.
- Docker work this week should first target content generation. Browser crawling inside Docker is a later track unless leadership explicitly accepts the added risk.

---

## Current Decisions

1. The Wednesday trial should prioritize an internal content-generation workflow that operations can actually use.
2. High-frequency reference articles are still needed, but they do not require this server to own all crawling. A colleague's stable crawler or a designated local crawler machine can provide raw answers and reference URLs.
3. A lightweight account system is required before cloud exposure. Full customer-level permissions can wait if access is limited to internal operators.
4. Docker is useful for reducing Windows-to-Linux deployment surprises, but it should not block local crawler experiments. Map cloud test ports away from the local Flask port when needed.
5. Initial operations scale is under five people. Start with one shared internal customer view after login; defer account-to-customer permission isolation until the first login version is stable.
6. Run the deployed app with one worker. Do not add multi-worker Gunicorn until mutable storage is fully database-backed or protected across processes.

## Company Inputs Needed

- Aliyun ECS access: host, SSH user, private key or password, and sudo permission.
- Target OS: preferably Ubuntu 22.04 or 24.04 LTS.
- Access policy: internal/VPN only or public domain. If public, provide domain, DNS control, security group control, and SSL certificate path.
- Model settings: API key, `base_url`, model name, quota owner, and billing owner.
- Initial users: names, usernames, role as `admin` or `operator`, and whether all operators may see all customers. Operators can also use the registration form to create non-admin accounts.
- Data policy: whether customer PDF files and generated content may be stored on ECS local disk, and required backup destination/frequency.
- Crawler data source decision: this app's crawler, a colleague's crawler, or a designated local machine; expected output fields and update frequency.

## Pre-Cloud Work

### Task 1: Freeze Wednesday Scope And Handoff Notes

**Files:**
- Modify: `接手文档.md`
- Create/Modify: `docs/superpowers/plans/2026-07-06-content-generation-cloud-rollout.md`

**Interfaces:**
- Consumes: leadership target of Wednesday content-generation delivery.
- Produces: a scoped execution plan that later code changes must follow.

- [x] Add a dated section to `接手文档.md` stating that content generation is the delivery focus.
- [x] Link this plan from `接手文档.md`.
- [x] Explicitly mark cloud crawling and one-click multi-platform publishing as post-Wednesday tracks.
- [ ] Commit only the plan and handoff documentation changes.

Status note: the document updates are done in the working tree. A commit was not made in the previous agent window because the repo already had many unrelated/uncommitted implementation changes.

Verification:

```powershell
git diff -- 接手文档.md docs/superpowers/plans/2026-07-06-content-generation-cloud-rollout.md
```

Expected: only the new plan and the handoff pointer are shown.

### Task 2: Add Lightweight Login Before Cloud Exposure

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html` or create a minimal login template if routing is cleaner.
- Create: `tests/test_auth.py` or extend `tests/test_app_core.py`

**Interfaces:**
- Produces: session-based auth with `admin` and `operator` roles.
- Produces: every non-health API and main page requires login.
- Produces: generated content records include `created_by` when a user is logged in.

- [x] Write a failing test that `GET /` redirects or rejects when unauthenticated.
- [x] Write a failing test that `GET /api/health` still works without login.
- [x] Write a failing test that `POST /api/content/generate` rejects unauthenticated requests.
- [x] Implement a simple user store under `data/users.json` with password hashes, not plaintext passwords.
- [x] Add login, logout, and current-user routes.
- [x] Protect all app routes except health, login, static assets, and explicitly whitelisted checks.
- [x] Add `created_by` to content-generation records.
- [x] Add an admin-only initialization path or documented CLI/bootstrap step for the first users.

Implementation note for the next agent:

- Keep the first version intentionally small: username/password login, password hashes, session cookie, logout, current-user endpoint, and a bootstrap path for initial users.
- Do not build a full role/customer permission matrix yet.
- After login exists, record `created_by` on content-generation records if the current user is available.
- Protect all business APIs. Keep `/api/health` public so server health checks still work.

Verification:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_auth tests.test_app_core -v
```

Expected: auth tests and existing core tests pass.

### Task 3: Make JSON Storage Safer For Low-Concurrency Multi-User Trial

**Files:**
- Modify: `services/storage.py`
- Modify: `app.py` if local `load` / `save` helpers still bypass shared storage behavior.
- Modify: `services/records.py`
- Modify: `services/materials.py`
- Test: `tests/test_app_core.py`, `tests/test_materials_service.py`, `tests/test_history_tools.py`

**Interfaces:**
- Produces: atomic JSON writes remain intact.
- Produces: write operations are serialized inside a single process.
- Deployment constraint: use one worker until storage is moved to SQLite/Postgres.

- [ ] Identify every direct JSON write path still used by Wednesday features: clients, materials, content generations, settings, raw records.
- [x] Add a process-local file write lock around JSON save operations.
- [x] Keep atomic temp-file replace behavior.
- [x] Avoid broad storage refactors before Wednesday.
- [x] Document one-worker production constraint in deployment docs.

2026-07-08 status note:

- Same-process JSON writes now go through `services/storage.py` locking for the shared storage helper.
- Crawler append paths for `records.json`, `raw_records.json`, and daily raw files use locked read-modify-write updates.
- This is not a cross-process lock. Keep Gunicorn at one worker for the trial.

Verification:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_app_core tests.test_materials_service tests.test_history_tools -v
```

Expected: tests pass and existing JSON behavior is unchanged for callers.

### Task 4: Package Content Generation For Linux-Like Deployment

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.dockerignore`
- Create: `deploy/README.md`
- Optionally create: `deploy/nginx.conf.example`
- Modify: `requirements.txt` if `gunicorn` or missing PDF dependencies are not present.

**Interfaces:**
- Produces: container or documented Ubuntu deployment for the content-generation app.
- Consumes: `data/`, `pdf/`, and `logs/` as persistent writable directories.
- Consumes: model API settings from environment variables or server-side config, never from committed secrets.

- [ ] Add a Docker image based on Python 3.12 slim or an Ubuntu-compatible Python image.
- [ ] Install system dependencies needed by PDF parsing.
- [ ] Install Python requirements.
- [ ] Start the app with Gunicorn using one worker for JSON-storage safety.
- [ ] Mount `data/`, `pdf/`, and `logs/` as volumes in compose.
- [ ] Map container port `5000` to host port `8080` for local Docker tests to avoid clashing with the Windows Flask service.
- [ ] Add `.env.example` with placeholder values only.
- [ ] Document Docker and non-Docker Ubuntu commands in `deploy/README.md`.

Implementation note for the next agent:

- User has not installed Docker yet. Ask them to install Docker only when the Docker files are ready to test, or when Aliyun ECS access arrives.
- Local Docker test should map host `8080` to container `5000`, so it does not collide with the existing Windows service on `5000`.
- If Docker is not available locally, still create the files and verify syntax/build assumptions as far as possible without network installs.

Verification:

```powershell
docker compose up --build
```

Expected: app starts locally at `http://localhost:8080`, login works, and content generation can be tested with configured model settings.

### Task 5: Verify The Wednesday Content-Generation Flow Locally

**Files:**
- No required code files if Tasks 2-4 are complete.
- Optional: `docs/content-generation-acceptance.md`

**Interfaces:**
- Consumes: one test customer, at least one parsed PDF/DOCX material, one selected high-frequency reference article, and one operations opinion.
- Produces: a repeatable acceptance checklist for operations.

- [ ] Create or select one customer.
- [ ] Upload/import customer material and confirm the material status is usable.
- [ ] Generate one platform-neutral guide article.
- [ ] Generate one revision using a multi-turn operations opinion.
- [ ] Confirm article history displays newest first.
- [ ] Confirm generation record shows material count and selected article count.
- [ ] Confirm risky medical expressions can be removed by a follow-up operations opinion.

Verification:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_materials_service tests.test_materials_api tests.test_app_core tests.test_frontend_crawl_order -v
```

Expected: tests pass. Manual acceptance should produce two usable articles for the same customer.

## Crawler Data Strategy

### Task 6: Align Crawler Output With The Colleague's Stable Machine

**Files:**
- Create or modify later only if needed: `docs/crawler-data-contract.md`
- Potential future code: an import endpoint or script for the colleague's crawler output.

**Interfaces:**
- Required fields from crawler output:
  - `client_id` or stable customer name mapping
  - `group_id` or question group name
  - `question`
  - `answer`
  - `refs`: title, url, source platform if known
  - `ai_platform`
  - `crawl_time`
  - optional `brand_mentioned`
  - optional `task_id`
- Produces: high-frequency reference article data usable by operations content generation.

- [ ] Ask the colleague for a sample output file.
- [ ] Compare their customer/sales display metrics with this app's operations metrics.
- [ ] Agree that raw answers and reference URLs are the shared contract; display metrics can differ.
- [ ] If fields can be mapped, create an import plan instead of duplicating cloud crawler work.
- [ ] If leadership requires a demo crawler, use a single controlled machine/account and do not claim multi-user cloud crawling stability.

Verification:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_app_core tests.test_frontend_crawl_order -v
```

Expected after future import work: high-frequency reference articles remain available to content generation without requiring this server to own all crawling.

## After Aliyun Access Arrives

### Task 7: Provision And Deploy The Internal Trial

**Files:**
- Use: `deploy/README.md`
- Use: `.env` on server only, not committed.
- Use: `docker-compose.yml` or documented Ubuntu service commands.

**Interfaces:**
- Consumes: ECS credentials, API settings, access policy, and initial user list.
- Produces: internal URL for operations to test content generation.

- [x] Confirm ECS OS and resources.
- [x] Install Python runtime if not using Docker: conda env `geo-content-v2`, Python `3.12.13`.
- [x] Create deploy directory: `/srv/geo-content-v2`.
- [x] Copy uploaded deployment package and unzip it.
- [x] Create server-only `.env`.
- [x] Create persistent directories: `data/`, `pdf/`, `logs/`.
- [ ] Start the service with one worker through systemd.
- [ ] Do not configure Nginx/SSL for the first trial; use port `18080` directly.
- [ ] Lock down security groups to the required ports and source ranges.
- [ ] Create the first admin user.
- [ ] Allow operators to self-register non-admin accounts if needed.
- [ ] Run acceptance tests manually from a non-developer machine.

Status note: Aliyun ECS access is available. Use `ssh geo-content-v2` from the
Windows laptop. If SakuraCat/VPN blocks new SSH connections, connect with VPN
off first. Continue with `deploy/README.md` Current Non-Docker Runbook.

2026-07-08 status note: the server directory was prepared earlier, but the
latest local code changes from July 8 have not been synced to
`/srv/geo-content-v2` yet. Before starting systemd, upload or pull the latest
code, then re-run the server-side health check.

Verification:

```bash
curl http://127.0.0.1:18080/api/health
```

Expected: health endpoint returns success locally on the server; browser access requires login.

### Task 8: Backup And Rollback

**Files:**
- Create: `deploy/backup.ps1` or `deploy/backup.sh` depending on server OS.
- Modify: `deploy/README.md`

**Interfaces:**
- Consumes: persistent directories `data/`, `pdf/`, and `logs/`.
- Produces: daily archive or manual backup process before risky changes.

- [ ] Document what must be backed up: `data/`, `pdf/`, `logs/`, and any browser profile directories if crawler is later deployed.
- [ ] Add a manual backup command.
- [ ] Add a restore command.
- [ ] Add a rollback command for the application container or service.
- [ ] Run one backup/restore dry run on non-production data.

Implementation note for the next agent:

- Include the SQLite content-generation database in the backup list.
- The minimum backup set is `data/`, `pdf/`, and `logs/`.
- If crawler browser profiles or platform login states are later moved to server storage, document whether they should be backed up or deliberately re-created.

Verification:

```bash
ls -lh backups/
```

Expected: backup archive exists and includes `data/`, `pdf/`, and `logs/`.

## Code Organization Policy Before Wednesday

The codebase has prototype debt:

- `app.py` is too large and mixes routes, storage, crawling, content generation, and deployment-sensitive settings.
- `templates/index.html` is too large and mixes markup, styling, and frontend logic.
- JSON storage is acceptable for the Wednesday internal trial only if write concurrency is controlled.

Do not start a large cleanup now. Safe cleanup before Wednesday is limited to:

- new small modules for login/auth if needed;
- deployment config files;
- storage locking around existing helpers;
- extracting only code that is directly needed for deployment safety.

Large cleanup after the trial:

- move content generation routes into a blueprint or service module;
- split frontend content-generation UI from the monolithic template;
- move JSON storage to SQLite/Postgres;
- add a formal crawler import contract;
- separate crawler orchestration from content generation.

## Wednesday Acceptance Criteria

- The app is reachable from an approved company network or URL.
- Unauthenticated users cannot access the main app or APIs.
- At least one operator account can log in.
- One customer can upload/import material and see usable material status.
- Content generation works with customer materials and selected sample/reference article context.
- Multi-turn rewrite works on an existing article.
- Generated history is visible newest first.
- API key is not exposed in any response or committed file.
- Data directories are persistent and included in the backup plan.
- If crawler data is used, its source and freshness are clearly stated.

## Explicit Non-Goals For Wednesday

- No one-click multi-platform publishing.
- No stable multi-user cloud crawler claim.
- No full role/customer permission matrix.
- No migration to a database unless JSON concurrency becomes a blocking issue.
- No large UI redesign.
