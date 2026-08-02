# Manual Reference Route Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only manual-input experiment that turns an already-verified Query and its actually-read articles into introduction/comparison route candidates, without changing production content generation.

**实施状态（2026-07-28）：** 代码与自动化验证已完成；等待运营提供第一份已确认精读文章包后进行真实 LLM 实验。按用户约定，本轮不提交。

**Architecture:** Add one pure service that asks the configured LLM for a per-article evidence map and a single complete route candidate. Add one developer script that reads a manually prepared JSON bundle and writes normalized results. No crawler, UI, pattern-library write, or content-generation integration belongs to this experiment.

**Tech Stack:** Python standard library, existing `ai_json_fn` convention, unittest.

## Global Constraints

- All user-facing copy is Simplified Chinese.
- Manual bundles are the only article input; acquisition is out of scope.
- Do not alter `app.run_content_generation(...)`, APIs, frontend, knowledge bases, crawler, publication flow, or pattern-library persistence.
- Any new LLM call uses `max_tokens=4000` or greater.
- No new dependencies.

---

### Task 1: Pure route-analysis contract

**Files:**
- Create: `services/reference_route_analysis.py`
- Test: `tests/test_reference_route_analysis.py`

**Interfaces:**
- Produces `build_route_analysis_prompt(bundle, article) -> str`.
- Produces `normalize_route_analysis_result(raw, article_content) -> dict`.
- Produces `analyze_reference_route_article(bundle, article, ai_json_fn) -> dict`.

- [x] Write failing tests for a valid introduction route and a malformed route. The valid fixture must assert classification `介绍型`, a verified source excerpt, and a complete route with `parent_type`. The malformed fixture must assert downgrade to `不入库` and `route is None`.
- [x] Run `python -X utf8 -m unittest tests.test_reference_route_analysis -v`; it failed because the module was absent.
- [x] Implement only the three interfaces above. The prompt requires one classification from `介绍型` / `对比型` / `不入库`, keeps source evidence separate from the route, requires one complete route rather than modules, and forbids entities, figures, raw Query wording, and platform-algorithm claims in the route. Normalization rejects malformed routes and verifies excerpts by whitespace-normalized containment in article content.
- [x] Run the Task 1 tests; they pass.
- [ ] Do not commit in this round; wait for the user's explicit instruction and for a real-article experiment result.

### Task 2: Manual bundle experiment script

**Files:**
- Create: `scripts/dev_reference_route_experiment.py`
- Modify: `tests/test_reference_route_analysis.py`

**Interfaces:**
- Consumes JSON with `query`, optional `final_entities`, and `articles[]` containing `url`, `title`, `content`, and optional `support_points`.
- Produces `run_route_experiment(bundle, output_dir, ai_json_fn) -> dict`.
- Writes `<output-dir>/route_analysis.json` and nothing under application data directories.

- [x] Write a failing test that supplies one valid manual article and asserts one normalized output plus `route_analysis.json`.
- [x] Run `python -X utf8 -m unittest tests.test_reference_route_analysis -v`; it failed because `run_route_experiment` was absent.
- [x] Implement the script using only JSON and the Task 1 service. Its CLI requires `--input` and `--output-dir`. It validates non-empty Query, HTTP(S) article URL, title, and content; calls the analyzer once per article with 4000 tokens; it never fetches URLs, creates jobs, or writes a library entry.
- [x] Run `python -X utf8 -m unittest tests.test_reference_route_analysis -v; python -X utf8 -m py_compile services/reference_route_analysis.py scripts/dev_reference_route_experiment.py`; both commands pass.
- [ ] Do not commit in this round; wait for the user's explicit instruction and for a real-article experiment result.

## Verification

- [x] `python -X utf8 -m unittest tests.test_reference_route_analysis -v`
- [x] `python -X utf8 -m py_compile services/reference_route_analysis.py scripts/dev_reference_route_experiment.py`
- [x] Review new code for production data-directory references; none are present.
- [x] Confirm the test writes only its temporary output directory; the implementation has no production data-directory reference.

## Explicitly Deferred

- Acquiring articles actually read by an AI platform, whether by crawler, browser automation, manual-operations UI, or provider integration.
- Promotion of route candidates to the live pattern library or replacement of production `reference_anatomy`.
- Content-generation replacement: deleting audience angles / FAQ, route selection, new brief schema, frontend changes, and migrations. That is a second plan after this experiment is evaluated.
