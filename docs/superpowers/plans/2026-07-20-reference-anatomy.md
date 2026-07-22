# Reference Anatomy Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new, backend-only article-anatomy contract for the future reference-intelligence pipeline while retaining the legacy stage-1 contract unchanged.

**Architecture:** `services/reference_anatomy.py` owns anatomy prompts and defensive normalization. It receives an already-approved article and returns a source block plus an optional skeleton and up to three modules; no filtering, library writes, routes, or existing stage calls are changed. `PatternLibrary` retains the complete source metadata when later code persists a card.

**Tech Stack:** Python standard library and `unittest`.

## Global Constraints

- Do not modify `services/reference_stage1.py`, `app.py`, existing routes, or current reference-analysis output.
- Low-quality article filtering belongs to the later stage-0 module and is out of scope.
- Prompt input is limited to the title and article body; URL, source group, publication date, platform, and citation count stay outside the prompt.
- No frontend, API, model call in tests, dependency, or data migration.

---

### Task 1: Add the New Anatomy Contract

**Files:**
- Create: `services/reference_anatomy.py`
- Create: `tests/test_reference_anatomy.py`

**Interfaces:**
- `build_anatomy_prompt(article)` returns a title/body-only prompt.
- `normalize_anatomy_result(raw, article_content="")` returns a normalized card payload without source data.
- `analyze_article_anatomy(article, ai_json_fn)` returns the normalized payload plus the source block.

- [x] **Step 1: Write failing tests for prompt isolation and normalization.**

```python
card = normalize_anatomy_result({
    "skeleton": {"name": "分类观察", "sections": ["背景"] * 8},
    "modules": [{"type": "未知", "name": "模块", "pattern": "可复用套路"}] * 5,
}, article_content="原文片段")
assert len(card["skeleton"]["sections"]) == 6
assert len(card["modules"]) == 3
assert card["modules"][0]["type"] == "其他"
```

- [x] **Step 2: Run the new test and verify it fails because the module does not exist.**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_reference_anatomy -v`

- [x] **Step 3: Implement defensive prompt and result normalization.**

```python
MODULE_TYPES = {"开头", "结尾", "FAQ段", "对比表", "其他"}
excerpt_verified = normalize_whitespace(excerpt) in normalize_whitespace(article_content)
```

- [x] **Step 4: Add and pass tests for empty skeletons, malformed LLM output, missing module patterns, retained risk marks, and excerpt verification.**

- [x] **Step 5: Run the anatomy test module and compile check.**

### Task 2: Preserve Full Source Metadata in the Library

**Files:**
- Modify: `services/pattern_library.py`
- Modify: `tests/test_pattern_library.py`

- [x] **Step 1: Write a failing test asserting that source `group_id`, `published_at`, `platform`, and `citation_count` survive candidate creation.**

- [x] **Step 2: Extend source normalization to retain those optional fields while retaining URL-based de-duplication.**

- [x] **Step 3: Run the pattern-library tests and record that the anatomy path remains unmounted.**
