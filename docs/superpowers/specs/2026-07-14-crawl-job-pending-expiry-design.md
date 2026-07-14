# Crawl Job Pending Expiry Design

## Goal

Prevent local workers from accidentally consuming stale crawl jobs for another customer while preserving the current lightweight local-worker workflow.

## Scope

- Pending crawl jobs expire after 2 minutes if no worker has claimed them.
- Expiry applies only to `pending` jobs. `running`, `completed`, `failed`, and `canceled` jobs are not auto-expired by this rule.
- Existing pending jobs without `expires_at` are treated as expirable from `created_at + 2 minutes`.
- Login jobs are not changed by this fix.
- The local worker logs claimed `client_id`, `brand`, `group_id`, and optional `batch_id` before running a crawl.
- The one-click frontend path may attach a shared `batch_id` to per-platform jobs, but worker claiming remains simple: owner + platform + non-expired pending.

## Design

`services/crawl_jobs.py` owns the queue behavior. Job creation writes `expires_at` for crawl jobs and optional `batch_id`. Claiming first marks expired pending crawl jobs as `expired`, then claims the first non-expired pending job matching the current operator and platform.

`app.py` passes request `batch_id` through to the crawl job store. `static/js/app.js` generates one batch ID per one-click action and sends it with each platform job. `scripts/local_crawl_worker.py` logs job scope after claiming so wrong-customer claims are visible before the platform crawl starts.

## Testing

Regression tests cover:

- Expired pending crawl jobs are skipped and marked `expired`.
- Fresh pending crawl jobs can still be claimed.
- `expires_at` is written on newly created crawl jobs.
- Frontend one-click code sends a shared `batch_id`.
- Worker claim log includes customer scope fields.

## Risk

Operators who create jobs and wait more than 2 minutes before starting the worker must create the jobs again. This is intentional; stale pending jobs are the source of the reported wrong-customer crawl.
