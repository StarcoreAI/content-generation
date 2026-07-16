# Material Package Filter Design

## Goal

Turn the first filter stage into a package-level selector that removes clearly unusable units and redundant files while preserving enough material for the second-stage content reducer.

## Boundary

The first filter decides whether a whole extracted unit is kept. It may remove exact duplicates and select a few representative units from a semantically similar group, but it does not delete paragraphs inside a retained unit. Paragraph cleanup, factual extraction, and cross-document statement deduplication belong to the second-stage reducer.

## Input Preparation

The extractor remains the source of full text and metadata. Full normalized text is used locally for exact duplicate detection and is not sent wholesale to the model.

Each model candidate includes its `unit_id`, path, kind, extraction status, table metadata, full character count, and a preview:

- Units up to 1,800 characters use their full text.
- Longer units use head, middle, and tail excerpts within a total 1,800-character budget.
- Unreadable legacy Office probes are excluded from model judgment and remain visible in the manifest as `needs_conversion`.

The model receives all remaining candidate previews in one package-level request, so it can compare units globally.

## Selection Rules

Deterministic processing happens before the model:

- Skip units without readable text.
- Defer `needs_conversion` units instead of treating their binary probes as reliable content.
- Normalize Unicode, case, and whitespace, then retain one representative for each exact duplicate group.

The model then:

- Keeps units containing reusable, customer-specific facts, offerings, parameters, boundaries, compliance information, or representative first-party evidence.
- Drops generic templates, unrelated third-party material, ordinary internal execution records, unsupported promotional filler, and low-information units.
- Groups semantic duplicates and same-purpose examples across the package.
- Keeps one best near-duplicate and at most three materially different representatives from a repeated example group.
- Keeps uncertain units so the second-stage reducer can make the finer decision.

The prompt is domain-neutral and must not mention the current education sample.

## Output

Each readable unit produces one authoritative `status`. Model statuses are `core`, `representative`, `redundant`, `irrelevant`, and `reference_only`; deterministic processing may also produce `needs_conversion` or `exact_duplicate`. Downstream processing keeps only `core` and `representative`. Exact duplicate decisions also include `duplicate_of`.

## Failure Handling

The package model response must be one JSON object containing one allowed status for every model candidate. Unknown statuses and unknown, duplicate, or missing IDs make the package call fail visibly rather than silently dropping material. Deterministic decisions are reproducible across runs.

## Experiment

Run the filter against `pdf/翼升学 GEO资料-6月11日汇总版`, inspect unit IDs and statuses, and compare directionally with the existing human review. The experiment is not a strict golden-output test because model output can vary.
