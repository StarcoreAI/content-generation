# Engineering Rules

## Runtime entry scripts

Runtime entry scripts are files that operators may double-click or run directly,
such as top-level `.bat`, `.cmd`, and `.ps1` launchers.

Rules:

- Use ASCII content only in top-level Windows batch entry scripts.
- Use CRLF line endings for `.bat` and `.cmd` files.
- Use no UTF-8 BOM in `.bat` and `.cmd` files.
- Do not hard-code Chinese path literals in runtime entry scripts. Use ASCII
  wildcards or move path discovery into Python or PowerShell.
- Keep batch files thin. Put non-trivial logic in Python or PowerShell where
  encoding and error handling are easier to test.

## Chinese text boundary

Keep Chinese where it is part of the product behavior:

- frontend user-facing copy
- content-generation prompts
- model output requirements
- customer-facing examples and article templates

Do not move frontend Chinese copy or content-generation prompts to English
unless the product behavior is intentionally changing.

Non-product Chinese text may be replaced with English when it reduces runtime
or maintenance risk, especially in terminal logs, background scripts, comments,
and internal maintenance documentation.

## Test guard

`tests/test_startup_scripts.py` enforces the top-level batch-file contract:

- CRLF line endings
- no UTF-8 BOM
- ASCII-only batch content
- `.gitattributes` keeps `.bat` and `.cmd` files on CRLF

## Local crawler operations

- Use `setup_operator_windows.bat` for first-time Windows operator setup. It
  should check Python/Node prerequisites and validate packaged crawler assets.
  Do not make operator machines run `npm install`, `npx playwright install`, or
  a live browser download during setup.
- Windows operator packages must include `ai-search-crawler\node_modules` and
  a matching `ai-search-crawler\ms-playwright` Chromium cache. If either is
  missing, setup should fail with an "incomplete package" message.
- Use `start_local_crawl_worker.bat` to run the local crawler worker.
- Use `stop_local_crawl_worker.bat` to stop only the local crawler worker.
- `stop.bat` is for the Flask app service, not for crawler workers.
- `start_local_crawl_worker.bat` must ask operators for cloud username and
  password on every launch. Do not rely on pre-set operator environment
  variables for credentials.
- Local crawler paths must be detected before use. A stale
  `GEO_NODE_CRAWLER_ROOT` value should be ignored when it no longer points to a
  valid Node crawler folder.
- After login preflight succeeds, the launcher opens a small local control
  panel with a stop button for operators.
- When a platform hits anti-bot or peak-hour rejection, cancel that platform's
  cloud crawl job in the UI, stop the local worker if needed, and later enqueue
  only the affected platform again.

## Cloud deploy and data sync

- Prefer Git for ECS code sync: commit and push locally, then run
  `git pull --ff-only` in `/srv/geo-content-v2`, restart
  `geo-content-v2.service`, and verify `/api/health`.
- Keep `scripts/deploy_cloud_package.sh` as a fallback when Git is unavailable.
  Do not paste a long multi-line deploy block into SSH unless both Git and the
  helper path are unavailable.
- A code package deploy may restart `geo-content-v2.service`, but it must not
  overwrite cloud `data/`, `pdf/`, `logs/`, or `.env`.
- Before changing cloud files, create a timestamped backup under
  `/srv/backups/geo-content-v2`.
- After copying code to `/srv/geo-content-v2`, repair ownership and basic
  permissions so files belong to `geosystem:geosystem`.
- Code sync and data sync are separate. Do not replace cloud
  `data/raw_records.json` with a local copy.
- To backfill missing crawler records, use
  `scripts/import_missing_raw_records.py` in dry-run mode first, review the
  summary, then run with `--apply` only if the append count is expected.
- Stop `geo-content-v2.service` briefly before applying a raw-record import,
  then start it again and verify `/api/health`.
