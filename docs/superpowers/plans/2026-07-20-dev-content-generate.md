# Dev Content Generate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CLI that runs the same persisted content-generation pipeline as `/api/content/generate`, including question-group FAQ input and SQLite provenance.

**Architecture:** Extract the route body into one callable in `app.py`; the Flask route adapts request/response around it and the CLI imports that callable. The CLI only parses options, invokes the shared callable repeatedly, and writes a review export using the standard-library JSON storage helper.

**Tech Stack:** Flask, Python standard library, existing `ContentGenerationStore`, unittest.

## Global Constraints

- Do not duplicate or reassemble the sampling, planning, writing, or persistence chain in the CLI.
- FAQ questions must be obtained by the shared pipeline from existing question groups; the CLI accepts no FAQ arguments.
- The CLI calls real LLM functions by default, but tests inject mocks and no real LLM invocation is performed during implementation verification.
- A failed item remains absent from storage and does not stop later requested items.
- Exports are UTF-8 JSON at `data/briefs/<client_id>/<date>/generated_articles.json`.

---

### Task 1: Extract one content-generation service entry

**Files:**
- Modify: `app.py`
- Test: `tests/test_app_core.py`

**Consumes:** route request values and existing content generation helpers.

**Produces:** `run_content_generation(payload, audience_angles=None)` returning the fully persisted article, with `sampling` attached only to its returned result for CLI export.

- [x] **Step 1: Write a failing shared-entry test**

```python
article = geo_app.run_content_generation({"client_id": "c1", "opinion": "test", "article_type": "对比型"})
assert article["provenance"]["faq_questions"] == ["问题一"]
assert article["sampling"]["faq_questions"] == ["问题一"]
```

- [x] **Step 2: Run the targeted test and confirm it fails because the callable is absent**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_app_core.CoreFunctionTests.test_content_generation_shared_entry_reads_question_groups -v`

Expected: FAIL with missing `run_content_generation`.

- [x] **Step 3: Extract the route body into the shared callable**

```python
def run_content_generation(payload, audience_angles=None):
    # validate, sample, plan, write, and append exactly once
    return {**article, "sampling": sample}
```

Keep the Flask route responsible only for translating validation/generation exceptions into HTTP responses and removing `sampling` from its public response.

- [x] **Step 4: Run the targeted test and existing route tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_app_core -v`

Expected: PASS.

### Task 2: Add the CLI runner and its test

**Files:**
- Create: `scripts/dev_content_generate.py`
- Create: `tests/test_dev_content_generate.py`

**Consumes:** `app.run_content_generation` and user CLI options.

**Produces:** `run_content_generate(...)` and a command-line `main()`.

- [x] **Step 1: Write a failing runner test**

```python
result = run_content_generate("c1", "对比型", count=2, angles=["角度 A"], execute_fn=fake_execute)
assert result["generated"] == 1
assert result["failed"] == 1
assert export["items"][0]["sampling"]["faq_questions"] == ["问题一"]
```

- [x] **Step 2: Run the runner test and confirm import failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_dev_content_generate -v`

Expected: FAIL because `scripts.dev_content_generate` does not exist.

- [x] **Step 3: Implement the minimal CLI**

```python
for index in range(max(1, int(count))):
    try:
        article = execute_fn(payload, audience_angles=angles)
    except Exception as exc:
        failures.append({"index": index + 1, "error": str(exc)})
        continue
    items.append({"sampling": article.pop("sampling"), "brief": article["brief"], "article": article})
```

Parse the specified options, preserve saved angles by passing `None` when `--angles` is omitted, write an export even when some items fail, and configure UTF-8 console output.

- [x] **Step 4: Run the runner test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_dev_content_generate -v`

Expected: PASS.

### Task 3: Verify and hand off commands

**Files:**
- Modify: `docs/superpowers/plans/2026-07-20-dev-content-generate.md`

- [x] **Step 1: Run script and core focused tests without a real LLM**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_dev_content_generate tests.test_app_core tests.test_brief_builder -v`

Expected: PASS.

- [x] **Step 2: Run the full regression suite and static checks**

Run: `run_tests.bat`

Run: `.\.venv\Scripts\python.exe -m py_compile app.py scripts\dev_content_generate.py`

Run: `git diff --check`

Expected: all pass with no whitespace errors.

- [x] **Step 3: Provide, but do not execute, the two real LLM commands**

```powershell
.\.venv\Scripts\python.exe scripts\dev_content_generate.py --client-id <id> --parent-type 对比型 --count 1 --angles "角度 A,角度 B"
.\.venv\Scripts\python.exe scripts\dev_content_generate.py --client-id <id> --parent-type 介绍型 --count 1
```
