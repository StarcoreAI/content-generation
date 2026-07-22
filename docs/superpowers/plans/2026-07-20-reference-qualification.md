# Reference Qualification Precheck Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the deterministic, pre-LLM part of reference-article qualification and syndication grouping without changing the live reference-analysis pipeline.

**Architecture:** `services/reference_qualification.py` hard-rejects unusable fetches, records structural signals for eligible articles, and groups same-content URLs using canonical keys plus shingle similarity. It returns one representative per group and a full audit list; it makes no content-quality decision and performs no model call.

**Tech Stack:** Python standard library, existing `services.ref_articles.canonical_article_key`, `unittest`.

## Global Constraints

- Do not modify `app.py`, `services/reference_intelligence.py`, `services/reference_stage1.py`, routes, or the frontend.
- Hard-reject only deterministic fetch failures: invalid fetch, error/blocked page, or content under 200 characters.
- Record paragraph, heading, and duplicate-text signals without using them as a hard rejection.
- Use one `group_id` for the same canonical article or shingle-similar bodies; later evidence counting must use that group.
- Do not call an LLM or decide `learn/count_only/excluded` semantic quality in this increment.

---

### Task 1: Add Qualification and Grouping

**Files:**
- Create: `services/reference_qualification.py`
- Create: `tests/test_reference_qualification.py`

**Interfaces:**
- `prequalify_reference_articles(articles, similarity_threshold=0.82)` returns `eligible`, `rejected`, and `groups`.
- Eligible records contain the representative article, `group_id`, `group_size`, aggregate citation count, source URLs, and structural signals.
- Rejected records contain the original article, deterministic reasons, and structural signals.

- [x] **Step 1: Write failing tests for hard rejection, structural signals, exact duplicate grouping, and citation aggregation.**
- [x] **Step 2: Run the test module and verify it fails because the module does not exist.**
- [x] **Step 3: Implement deterministic precheck and group formation using canonical keys plus character shingles.**
- [x] **Step 4: Run qualification tests, the old stage-1 test, and compile checks.**

### Task 2: Record the Isolated Backend Increment

**Files:**
- Modify: `docs/content-refactor-short-term.md`
- Modify: `接手文档.md`

- [x] **Step 1: Record that deterministic qualification and grouping exist but are not mounted in the live task.**
- [x] **Step 2: Run `git diff --check` and relevant tests.**
