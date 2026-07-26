# Low-frequency selection-surface sample Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a random sample of up to 30 lowest-frequency cited articles to the existing question-grouped selection-surface report.

**Architecture:** Reuse the current canonical article aggregation. Select the minimum citation-count tier after date filtering, sample it with Python's standard `random` module, and pass the selected articles through the existing fetch, question grouping, and similarity rendering path. The low-frequency output name includes its mode so it cannot overwrite the high-frequency report.

**Tech Stack:** Python standard library, existing `services.selection_surface`, existing CLI report script, unittest.

## Global Constraints

- Do not add dependencies, routes, UI, crawler behavior, or business-data writes.
- Preserve high-frequency selection as the CLI default.
- Keep the existing one-second request spacing and mocked-fetch test approach.

---

### Task 1: Low-frequency selection

**Files:**
- Modify: `services/selection_surface.py`
- Test: `tests/test_selection_surface_report.py`

**Interfaces:**
- Produces: `sample_low_frequency_selection_articles(records, date_from=None, date_to=None, top=30, random_seed=None)`.
- Behavior: aggregate canonically, retain only the lowest `citation_count` tier, randomly choose at most `top`, then return the normal article dictionaries.

- [ ] **Step 1: Write the failing test**

```python
sample = sample_low_frequency_selection_articles(records, top=2, random_seed=7)
self.assertEqual(len(sample), 2)
self.assertTrue(all(article["citation_count"] == 1 for article in sample))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -X utf8 -m unittest tests.test_selection_surface_report`

Expected: import failure because the low-frequency selector does not exist.

- [ ] **Step 3: Implement the minimum selector**

```python
lowest = min(article["citation_count"] for article in articles)
return random.Random(random_seed).sample(lowest_articles, min(top, len(lowest_articles)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -X utf8 -m unittest tests.test_selection_surface_report`

Expected: PASS.

### Task 2: CLI mode and non-overwriting report name

**Files:**
- Modify: `scripts/run_selection_surface_report.py`
- Test: `tests/test_selection_surface_report.py`

**Interfaces:**
- Consumes: `selection_mode` of `high-frequency` or `low-frequency-random`, plus optional `random_seed`.
- Produces: the same report schema and a filename ending in `_low_frequency_random_selection_surface.md` for the new mode.

- [ ] **Step 1: Write the failing report test**

```python
result = run_selection_surface_report(..., selection_mode="low-frequency-random", random_seed=7)
self.assertTrue(result["output_path"].endswith("_low_frequency_random_selection_surface.md"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -X utf8 -m unittest tests.test_selection_surface_report`

Expected: `TypeError` because the report runner has no selection mode.

- [ ] **Step 3: Add the CLI choices and reuse current report path**

```python
parser.add_argument("--selection-mode", choices=("high-frequency", "low-frequency-random"), default="high-frequency")
```

- [ ] **Step 4: Run focused and full tests**

Run: `python -X utf8 -m unittest tests.test_selection_surface_report; .\run_tests.bat`

Expected: all tests pass.
