# Material Package Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace isolated per-unit model calls with a compact package-level filter that performs deterministic exact deduplication and semantic representative selection.

**Architecture:** `services/material_filter.py` prepares bounded previews, removes deterministic exclusions and exact duplicates, then makes one model call for all remaining candidates. `scripts/run_material_filter.py` invokes that package API once and writes rich decisions to the existing JSON report.

**Tech Stack:** Python 3.12 standard library, existing OpenAI-compatible client, `unittest`.

## Global Constraints

- No new dependency or vector index.
- Keep the prompt domain-neutral.
- Keep full text available locally but send at most 1,800 characters per candidate.
- The first filter only selects whole units; paragraph cleanup remains deferred.
- Model variability is reviewed through a real experiment, not a strict golden-answer test.

---

### Task 1: Preview Sampling and Deterministic Decisions

**Files:**
- Modify: `services/material_filter.py`
- Test: `tests/test_material_filter.py`

**Interfaces:**
- Produces: `sample_unit_text(unit, max_chars=1800) -> str`
- Produces: `filter_material_units(units, ask_json, question=None, max_tokens=4096, preview_chars=1800) -> list[dict]`

- [ ] **Step 1: Write failing sampling and exact-deduplication tests**

```python
def test_samples_head_middle_and_tail_within_budget():
    preview = sample_unit_text({"text": "A" * 2000 + "MIDDLE" + "Z" * 2000}, 120)
    assert "A" in preview and "MIDDLE" in preview and "Z" in preview
    assert len(preview) <= 120

def test_exact_duplicates_use_one_model_candidate():
    results = filter_material_units(units, ask_json)
    assert len(prompts) == 1
    assert results[1]["status"] == "exact_duplicate"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_filter -v`

Expected: FAIL because package sampling and deduplication are not implemented.

- [ ] **Step 3: Implement bounded head/middle/tail sampling and normalized exact hashes**

```python
def sample_unit_text(unit, max_chars=1800):
    text = str(unit.get("text") or "").strip()
    if len(text) <= max_chars:
        return text
    # Return labeled head, middle, and tail excerpts within max_chars.
```

- [ ] **Step 4: Run tests and verify pass**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_filter -v`

Expected: PASS.

### Task 2: Package-Level Model Contract

**Files:**
- Modify: `services/material_filter.py`
- Test: `tests/test_material_filter.py`

**Interfaces:**
- Consumes: `sample_unit_text`
- Produces: one prompt containing every non-deterministic candidate and one result per readable input unit

- [ ] **Step 1: Write failing package prompt and response-validation tests**

```python
def test_filters_all_candidates_in_one_model_call():
    results = filter_material_units(units, ask_json)
    assert len(prompts) == 1
    assert all(unit["unit_id"] in prompts[0] for unit in units)
    assert results == expected

def test_rejects_missing_model_decisions():
    with self.assertRaisesRegex(ValueError, "missing"):
        filter_material_units(units, lambda *_: {"results": []})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_filter -v`

Expected: FAIL because the current implementation calls the model once per unit.

- [ ] **Step 3: Implement the package prompt and strict ID validation**

```python
payload = ask_json(package_prompt, max_tokens=max_tokens)
entries = payload.get("results")
# Validate known, unique, complete IDs and allowed `status` values.
```

- [ ] **Step 4: Run tests and verify pass**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_filter -v`

Expected: PASS.

### Task 3: Runner Integration and Real Experiment

**Files:**
- Modify: `scripts/run_material_filter.py`
- Test: `tests/test_run_material_filter.py`

**Interfaces:**
- Consumes: `filter_material_units`
- Produces: existing report JSON with rich package decisions and package-level errors

- [ ] **Step 1: Write a failing runner test proving one package call and visible package errors**

```python
def test_filter_report_uses_one_package_call():
    results, errors = filter_units_for_report(units, ask_json)
    assert calls == 1
    assert not errors
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_run_material_filter -v`

Expected: FAIL because the runner still invokes the model per unit.

- [ ] **Step 3: Switch the runner to `filter_material_units` and raise the default output budget to 4,096 tokens**

```python
def filter_units_for_report(units, ask_json, max_tokens=4096):
    try:
        return filter_material_units(units, ask_json=ask_json, max_tokens=max_tokens), []
    except Exception as exc:
        return [], [{"unit_id": "__package__", "error": str(exc)}]
```

- [ ] **Step 4: Run all relevant tests and syntax checks**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_material_filter tests.test_run_material_filter tests.test_material_package_extractor -v`

Run: `.\.venv\Scripts\python.exe -m py_compile services\material_filter.py scripts\run_material_filter.py`

Expected: all tests pass and compilation exits zero.

- [ ] **Step 5: Run the real experiment**

Run: `.\.venv\Scripts\python.exe scripts\run_material_filter.py "pdf\翼升学 GEO资料-6月11日汇总版" --max-tokens 4096`

Expected: one report with 30 readable units, no package error, and inspectable `status` fields.
