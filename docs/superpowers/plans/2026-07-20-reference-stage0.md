# Reference Stage 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `test-driven-development` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated pre-stage analysis that excludes fetch residues, groups syndicated articles, obtains one LLM qualification per group, and writes an audit record without mounting the live pipeline.

**Architecture:** `services/reference_stage0.py` owns its stage-0 output contract. It reuses the existing deterministic residue predicate, forms groups using whitespace-normalized character shingles and Jaccard similarity, selects the longest body as representative, and injects `ai_json_fn` for one qualification call per group. A runner persists metadata only to `stage0_filter_groups.json`.

**Tech Stack:** Python standard library, `services.reference_qualification`, `services.storage`, `unittest`.

## Global Constraints

- Do not change `app.py`, `services/reference_intelligence.py`, `services/reference_stage1.py`, routes, or frontend code.
- Use the supplied generic prompt; never include the client brand in it.
- Truncate only the prompt body to 12,000 characters and use a small model token budget.
- Treat only LLM invocation failures as fail-open; malformed LLM results normalize conservatively.
- Persist every analysed group, including rejected groups, without article body text.

---

### Task 1: Define the stage-0 contract with failing tests

**Files:**
- Create: `tests/test_reference_stage0.py`

**Interfaces:**
- `group_reference_articles(articles, similarity_threshold=SHINGLE_SIMILARITY_THRESHOLD)` returns groups and exclusions.
- `build_stage0_prompt(article, syndication_count)` returns the supplied audit prompt.
- `normalize_stage0_result(raw)` returns strict `learnable`, closed `article_type`, and sanitized fields.
- `analyze_stage0_groups(articles, client_brand, ai_json_fn, stage_dir, ...)` writes `stage0_filter_groups.json` and returns its payload.

- [x] Write tests for grouping, residue exclusion, prompt isolation, normalization, fail-open, sponsor derivation, and metadata-only persistence.
- [x] Run the test module and verify it fails because `services.reference_stage0` does not exist.

### Task 2: Implement the isolated stage-0 module

**Files:**
- Create: `services/reference_stage0.py`

- [x] Implement grouping, prompt construction, strict normalization, sponsor derivation, and one-call-per-group analysis.
- [x] Persist the full group audit to `stage0_filter_groups.json` without content.
- [x] Run stage-0 tests and adjacent reference tests.

### Task 3: Record reusable real-run verification

**Files:**
- Modify: `docs/content-refactor-short-term.md`
- Modify: `接手文档.md`

- [x] Add a short command and expected artifact for offline real-data verification after this model stage.
- [x] Run `git diff --check` and relevant tests.
