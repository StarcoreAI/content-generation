# Refactor Notes

This is a temporary working log for code-reading and small refactor decisions.
Keep entries short: facts, current problems, suggested first cut, open questions,
and verification commands.

## Reading Map

- `app.py`: about 4400 lines, 60+ Flask routes. It currently holds app setup,
  storage path constants, auth helpers, AI calls, content-generation prompts,
  reference-intelligence orchestration, daily analysis, crawl jobs, platform
  crawling, agent bot, and precise optimization.
- `templates/index.html`: 3954 lines. It contains all page markup and nearly all
  front-end controller code. Reference intelligence is a relatively small block
  compared with problem-group crawling, daily analysis, and agent code.
- Existing service modules already cover some boundaries:
  - `services/reference_stage1.py`, `reference_stage2.py`,
    `reference_stage3.py`: LLM prompt/result normalization for the 3-stage
    reference pipeline.
  - `services/article_fetcher.py`: static/browser article body fetching.
  - `services/article_structure.py`: older/general single-article structure
    analysis endpoint support.
  - `services/crawl_jobs.py`, `services/records.py`,
    `services/content_generations.py`, `services/materials.py`: partial
    extracted domains.
- Tests are concentrated in `tests/test_app_core.py`, with dedicated smaller
  tests for reference stages and article fetching. Reference-intelligence
  behavior is covered well enough for a behavior-preserving extraction.

## Global Rough Read

Current backend shape:
- `app.py` is the integration layer and also holds several domain modules inline.
  The largest inline blocks are content-generation prompts, reference
  intelligence orchestration, daily analysis/statistics, platform crawling,
  agent actions, and precise optimization.
- Some domains already have service modules, but `app.py` still wraps or
  extends them with path constants, request validation, user access checks, and
  persistence glue.
- `services/storage.py`, `services/records.py`, `services/crawl_jobs.py`,
  `services/content_generations.py`, and `services/materials.py` are useful
  existing patterns. The simplest refactor is to keep following this style:
  plain functions/classes plus thin Flask routes.

Current frontend shape:
- `templates/index.html` is a single-page UI with all scripts inline.
- The reference-intelligence JS block is relatively contained, but it depends on
  shared globals such as current client/date/toast/api helpers.
- Frontend splitting should wait until backend boundaries are clearer. Moving JS
  first would create churn without reducing much backend risk.

Risk ordering:
- Low risk: reference intelligence backend. It has a visible contiguous block,
  focused stage-service tests, and app-level tests for routes/job progress.
- Medium risk: crawl job API and local worker persistence. There is already a
  `services/crawl_jobs.py`, but persistence still touches raw records, crawl
  task reports, brand analysis fallback, and worker result shape.
- Medium risk: content generation. Storage is already extracted, but prompts are
  product behavior and tightly coupled to material bundles, reference plugins,
  sample articles, and history.
- Higher risk: daily analysis/raw records/entity reports. This is data-sensitive
  and used by several pages: records, daily stats, reference-intelligence input,
  content samples, and precise optimization.
- Higher risk: platform crawling and Node bridge. It crosses Python crawler
  modules, Node process output, login state, SSE progress, and raw-record writes.
- Defer: agent and precise optimization. They are downstream features and not
  currently blocking maintainability of the main data flow.

Recommended order:
1. Move reference-intelligence backend code out of `app.py` without renaming
   route URLs, stored JSON fields, function names exposed by `app.py`, prompts,
   or progress anchors.
2. Run focused reference and app-route tests. If stable, commit this as the
   first small refactor.
3. Re-read the moved module and decide whether any duplicated helpers can be
   merged. Do not merge during the first move unless it is mechanically obvious.
4. Consider crawl-job persistence next, but only after the reference move proves
   the extraction style.
5. Leave frontend splitting, daily analysis, and platform crawling for later
   passes.

## Module Notes

### Reference Intelligence Backend

Files read:
- `app.py`
- `services/reference_stage1.py`
- `services/reference_stage2.py`
- `services/reference_stage3.py`
- `services/article_fetcher.py`
- `services/article_structure.py`
- `scripts/dev_fetch_reference_articles.py`
- `scripts/dev_reference_stage1.py`
- `scripts/dev_reference_stage2.py`
- `scripts/dev_reference_stage3.py`
- `tests/test_app_core.py` reference-intelligence tests
- `tests/test_reference_stage1.py`
- `tests/test_reference_stage2.py`
- `tests/test_reference_stage3.py`
- `tests/test_reference_article_fetch.py`

Current understanding:
- Formal page flow uses `/api/reference_intelligence/plugins`,
  `/api/reference_intelligence/analyze`,
  `/api/reference_intelligence/analyze_status`, and
  `/api/reference_intelligence/analyze_cancel`.
- Final plugin data lives at
  `data/reference_intelligence/<client_id>/<date>_all.json`.
- Stage artifacts live under
  `data/reference_intelligence/<client_id>/<date>/`.
- `app.py` still owns orchestration: job state, progress, cancellation,
  fetch-cache handling, collection of top refs, source attachment, final save,
  and route handlers.
- Stage service files only own LLM prompts/normalization; they do not own
  file paths, cache, background jobs, or final persistence.
- Dev scripts duplicate some app helpers: safe path construction, reference
  article collection, source attachment, and final live output save.
- Content generation consumes reference plugins through
  `build_content_article_subtype_prompt()` and the frontend subtype selector.

Problems worth fixing now:
- `app.py` has a clear reference-intelligence block that can move out without
  changing product behavior.
- Duplicate helper logic in dev scripts and `app.py` increases drift risk.
- Reference code sits between content-generation prompt code and daily/entity
  code, which makes `app.py` harder to scan.

Suggested first cut:
- Create one focused module, likely `services/reference_intelligence.py`, for
  path helpers, plugin normalization, reference article collection, job state,
  fetch cache, source attachment, and `run_reference_analysis_job()`.
- Keep Flask routes in `app.py` for the first cut, but make them thin wrappers
  that call the new module. This avoids introducing blueprints or app factory
  work.
- Keep frontend JS in `templates/index.html` for now. It is small and relies on
  shared globals; moving it first would add churn without reducing much risk.
- Do not change prompts, progress anchors, stored JSON shapes, or route URLs.

Verification:
- `.\.venv\Scripts\python.exe -m unittest tests.test_app_core.FlaskApiTests`
- `.\.venv\Scripts\python.exe -m unittest tests.test_reference_stage1 tests.test_reference_stage2 tests.test_reference_stage3 tests.test_reference_article_fetch tests.test_frontend_crawl_order`
- If time allows, `.\run_tests.bat`.

Implementation result:
- Created `services/reference_intelligence.py`.
- Moved reference-intelligence path helpers, plugin/cluster normalization,
  article collection, job-state helpers, fetch cache handling, source
  attachment, background pipeline, and legacy prompt-builder helpers into the
  service module.
- Kept same public functions in `app.py` as wrappers:
  `normalize_reference_plugins`, `reference_stage_dir`,
  `create_reference_analysis_job`, `update_reference_analysis_job`,
  `run_reference_analysis_job`, `queue_reference_analysis_job`,
  `build_reference_plugin_prompt`, and related helpers.
- Kept `reference_analysis_jobs` and `reference_analysis_jobs_guard` in
  `app.py` so existing tests and callers that inspect or clear job state still
  work.
- Did not change route URLs, request/response shapes, stored JSON paths,
  progress anchors, prompts, frontend JS, or dev scripts.
- Follow-up cleanup reused the new service module from
  `scripts/dev_fetch_reference_articles.py` and
  `scripts/dev_reference_stage3.py` for duplicated reference collection, fetch
  result merging, source-article attachment, plugin normalization, and live JSON
  path/save behavior.

Verified after implementation:
- `.\.venv\Scripts\python.exe -m py_compile app.py services\reference_intelligence.py`
- `.\.venv\Scripts\python.exe -m py_compile app.py services\reference_intelligence.py scripts\dev_fetch_reference_articles.py scripts\dev_reference_stage3.py`
- `.\.venv\Scripts\python.exe -m unittest tests.test_reference_stage1 tests.test_reference_stage2 tests.test_reference_stage3 tests.test_reference_article_fetch`
- `.\.venv\Scripts\python.exe -m unittest tests.test_app_core.FlaskApiTests`
- `.\.venv\Scripts\python.exe -m unittest tests.test_frontend_crawl_order`
- `.\.venv\Scripts\python.exe -m unittest tests.test_reference_stage1 tests.test_reference_stage2 tests.test_reference_stage3 tests.test_reference_article_fetch tests.test_app_core.FlaskApiTests tests.test_frontend_crawl_order`
- `.\run_tests.bat` - 244 tests passed.

Known risks:
- `services/reference_intelligence.py` has a verbose `run_reference_analysis_job`
  signature because dependencies are injected from `app.py` to avoid circular
  imports and keep app-level patching compatible.
- `app.py` still keeps wrapper functions for compatibility. That is deliberate;
  removing them would be a separate behavior-risk pass because tests and scripts
  currently import from `app.py`.

### Cloud Crawl Jobs

Files read:
- `app.py`
- `services/crawl_jobs.py`
- `services/crawl_tasks.py`
- `scripts/local_crawl_worker.py`
- `tests/test_app_core.py` crawl job tests
- `tests/test_local_crawl_worker.py`

Current understanding:
- Local worker contract is limited to:
  `GET /api/crawl_jobs`,
  `GET /api/crawl_jobs/next?worker_id=...&platform=...`, and
  `POST /api/crawl_jobs/<job_id>/result`.
- Worker consumes job fields such as `id`, `job_type`, `platform`,
  `questions`, and `repeat_count`.
- Worker returns `status`, `summary`, `results`, `logs`, `error`, and
  `crawler_engine`.
- `services/crawl_jobs.py` already owns JSON job state transitions.
- `app.py` still owned `persist_local_crawl_job_results()`, which turns a
  completed cloud job into raw records and a crawl task report.

Implementation result:
- Moved cloud job result persistence into
  `services.crawl_jobs.persist_local_crawl_job_results()`.
- Kept `app.persist_local_crawl_job_results()` as a wrapper that injects cloud
  dependencies: raw-record loading, task-report saving, failure compaction,
  basic analysis, brand mention calibration, raw-record saving, and current
  time.
- Did not change local worker scripts, worker package behavior, route URLs,
  request fields, response fields, job statuses, or raw-record JSON shape.

Verified after implementation:
- `.\.venv\Scripts\python.exe -m py_compile app.py services\crawl_jobs.py`
- `.\.venv\Scripts\python.exe -m unittest tests.test_app_core.FlaskApiTests tests.test_local_crawl_worker`
- `.\run_tests.bat` - 244 tests passed.

Known risks:
- The service function takes several injected dependencies. This is intentional
  to avoid importing `app.py` from `services/crawl_jobs.py`.
- `/api/platform/crawl` direct crawling is a separate, larger path and was not
  touched.

### Raw Records And Daily Analysis

Files read:
- `app.py`
- `services/records.py`
- `services/record_insights.py`
- `templates/index.html`
- `tests/test_app_core.py`
- `tests/test_history_tools.py`

Current understanding:
- Raw-record storage already has a service boundary in `services/records.py`.
  It owns `load_client_records`, `save_raw_record`, single/batch deletes,
  entity mention deletes, and daily clear.
- `app.py` still owns duplicated route-level filtering for
  `/api/raw_records`, `/api/raw_records/platform_stats`,
  `/api/raw_records/deep_analyze`, `/api/daily/records`,
  `/api/daily/ref_stats`, `/api/daily/insights`, and
  `/api/daily/deep_analyze`.
- `/api/daily/insights` already delegates aggregation to
  `services.record_insights.build_record_insights`.
- `/api/daily/ref_stats` is a good candidate for the next small extraction:
  it is read-only, computes a JSON response from records, and has route tests
  covering task filtering, source counts, article merging, AI platform groups,
  and competitor body-hit annotations.
- Frontend code directly consumes the existing response keys from
  `/api/daily/ref_stats`: `total_records`, `total_refs`,
  `platform_weights`, `top_articles`, and `top_articles_by_ai`.

Safety boundaries for this pass:
- Do not change `data/raw_records.json`, `data/raw/<client>/<date>.json`, or
  any stored record field names.
- Do not change save/delete/clear behavior while cloud has historical data.
- Do not touch local operator worker scripts unless a real worker bug appears.
- Keep route URLs and response field names unchanged.

Suggested next cut:
- Extract only the pure `/api/daily/ref_stats` aggregation into a small service
  function.
- Keep Flask request parsing, record loading, body-hit report loading, and
  competitor annotation in `app.py`.
- Leave `/api/daily/deep_analyze` for later because it is prompt-heavy product
  behavior and less safe to move casually.

Implementation result:
- Extended `services.records.load_client_records()` with optional `question`
  and `mentioned_only` filters.
- Replaced duplicated filtering in `/api/raw_records`,
  `/api/raw_records/platform_stats`, and `/api/raw_records/deep_analyze` with
  the shared record loader.
- Added `services/daily_stats.py` for pure `/api/daily/ref_stats`
  aggregation.
- Kept body-hit report loading and competitor-match annotation in `app.py`.
- Did not change raw-record writes, deletes, clear behavior, stored JSON field
  names, route URLs, or frontend response keys.

Verification:
- `.\.venv\Scripts\python.exe -m py_compile app.py services\<new daily stats module>.py`
- `.\.venv\Scripts\python.exe -m unittest tests.test_app_core.FlaskApiTests`
- `.\run_tests.bat`

Verified after implementation:
- `.\.venv\Scripts\python.exe -m unittest tests.test_history_tools.RecordStoreTests tests.test_history_tools.DailyStatsTests`
- `.\.venv\Scripts\python.exe -m unittest tests.test_app_core.FlaskApiTests`
- `.\.venv\Scripts\python.exe -m py_compile app.py services\records.py services\daily_stats.py`
- `.\.venv\Scripts\python.exe -m unittest tests.test_history_tools.RecordStoreTests tests.test_history_tools.DailyStatsTests tests.test_app_core.FlaskApiTests`
- `.\run_tests.bat` - 246 tests passed.

## Open Questions

- Before implementing: should the first cut keep tests patching
  `app.queue_reference_analysis_job` / `app.run_reference_analysis_job` by
  re-exporting those functions from `app.py`, or should tests be updated to
  import the new service module directly? Re-exporting is less disruptive.
