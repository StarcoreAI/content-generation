# Reference Intelligence and Competitor Acceleration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse unchanged article work and apply bounded concurrency to citation intelligence and competitor knowledge generation without changing their source-selection rules.

**Architecture:** Persist article bodies and model-derived results under each client's knowledge-base directory, keyed by URL and a SHA-256 hash of normalized body text. Use standard-library thread pools only for independent fetches and analyses; a shared two-slot semaphore caps model analysis calls across both workflows. Keep final route merging serial because it compares the complete batch.

**Tech Stack:** Flask, Python standard library (`concurrent.futures`, `threading`, `hashlib`), JSON files, existing `fetch_article_text`, `ai_json`, and `ai_with_settings` calls.

## Global Constraints

- Citation selection remains one anchor article plus one weighted article from ranks 2–5 for each selected Query and one AI platform.
- Competitor selection remains the top 12 distinct URLs by citation count in the exact date/group/task/platform scope.
- Fetch concurrency is exactly three; browser fallback is globally one; background analysis calls shared by these workflows are globally two.
- A cache hit must never replace a newly selected URL or suppress a source whose body hash changed.
- Route merging treats wording-only differences as mergeable and different scenarios as distinct.

---

### Task 1: Cached Article Work Helpers

**Files:**
- Create: `services/article_analysis_cache.py`
- Test: `tests/test_article_analysis_cache.py`

**Interfaces:**
- Produces `body_hash(content)`, `get_cached_analysis(path, url, content)`, and `put_cached_analysis(path, url, content, analysis)`.
- Cache entries are `{url: {"body_hash": str, "analysis": dict}}` and only return when hashes match.

- [ ] **Step 1: Write failing cache tests**

```python
def test_cache_returns_only_matching_url_and_body_hash(tmp_path):
    path = tmp_path / "cache.json"
    put_cached_analysis(path, "https://a", "body one", {"value": 1})
    assert get_cached_analysis(path, "https://a", "body one") == {"value": 1}
    assert get_cached_analysis(path, "https://a", "body changed") is None
```

- [ ] **Step 2: Run the test and verify RED**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_article_analysis_cache`

Expected: import failure because `article_analysis_cache` does not exist.

- [ ] **Step 3: Implement the JSON/hash helper with `hashlib.sha256` and existing `load_json`/`save_json` helpers.**

- [ ] **Step 4: Run the test and verify GREEN**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_article_analysis_cache`

Expected: PASS.

### Task 2: Bounded Concurrent Article Execution

**Files:**
- Create: `services/bounded_article_processing.py`
- Test: `tests/test_bounded_article_processing.py`

**Interfaces:**
- Produces `fetch_articles(candidates, fetch_fn, max_workers=3)` in input order.
- Produces `analyze_articles(items, analyze_fn, semaphore)` in input order.
- `semaphore` is a process-shared `threading.BoundedSemaphore(2)` supplied by `app.py`.

- [ ] **Step 1: Write failing order and concurrency-limit tests**

```python
def test_fetch_articles_preserves_input_order_while_running_three_workers():
    result = fetch_articles(["a", "b", "c", "d"], fake_fetch, max_workers=3)
    assert result == ["A", "B", "C", "D"]
    assert observed_peak_workers <= 3

def test_analyze_articles_uses_shared_two_slot_semaphore():
    result = analyze_articles(["a", "b", "c"], fake_analyze, threading.BoundedSemaphore(2))
    assert result == ["A", "B", "C"]
    assert observed_peak_analyses <= 2
```

- [ ] **Step 2: Run the test and verify RED**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_bounded_article_processing`

Expected: import failure because `bounded_article_processing` does not exist.

- [ ] **Step 3: Implement with `ThreadPoolExecutor`, collect futures by original index, and call the provided analyzer within the supplied semaphore.**

- [ ] **Step 4: Run the test and verify GREEN**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_bounded_article_processing`

Expected: PASS.

### Task 3: Apply Caches and Concurrency to Citation Intelligence

**Files:**
- Modify: `app.py:2521-2660`
- Modify: `services/reference_route_batch_merge.py`
- Test: `tests/test_formal_content_route_entry.py`, `tests/test_reference_route_batch_merge.py`

**Interfaces:**
- Citation cache path: `data/knowledge_base/<client_id>/reference_route_analysis_cache.json`.
- Fetch selected articles with `fetch_articles`; reuse cached analysis only when URL and body hash match.
- Keep `merge_reference_route_batch` as one call per parent type after all individual analyses finish.

- [ ] **Step 1: Write failing tests for a reused analysis, changed-body reanalysis, and wording-only merge prompt.**

```python
def test_reference_analysis_reuses_matching_cached_article_analysis():
    response = post_reference_analysis_with_same_url_and_body_twice()
    assert ai_json_call_count == 1

def test_reference_analysis_reanalyzes_when_cached_body_changes():
    response = post_reference_analysis_with_changed_body()
    assert ai_json_call_count == 2

def test_batch_merge_prompt_keeps_different_scenarios_distinct():
    prompt = build_batch_merge_prompt([analysis], [], "介绍型")
    assert "场景不同" in prompt
    assert "措辞不同" in prompt
```

- [ ] **Step 2: Run focused tests and verify RED.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_formal_content_route_entry tests.test_reference_route_batch_merge`

Expected: assertion failures because no cache is used and the prior merge prompt has the former criterion.

- [ ] **Step 3: Use the two helpers in the endpoint; preserve task order, append fetch/analysis failures, and revise only the merge prompt criterion.**

- [ ] **Step 4: Run focused tests and verify GREEN.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_formal_content_route_entry tests.test_reference_route_batch_merge`

Expected: PASS.

### Task 4: Apply Caches and Concurrency to Competitor Knowledge

**Files:**
- Modify: `app.py:1598-1642`
- Modify: `services/competitor_knowledge.py`
- Test: `tests/test_competitor_knowledge.py`

**Interfaces:**
- Existing source cache remains `competitor_article_sources.json` keyed by URL.
- New extraction cache is `competitor_article_facts_cache.json` keyed by URL + body hash.
- Top-12 selection and local `merge_competitor_master_markdown` output remain unchanged.

- [ ] **Step 1: Write failing tests that verify distinct URL selection remains top-12, cached source bodies skip fetch, and matching extracted facts skip model calls.**

```python
def test_competitor_facts_cache_skips_model_for_unchanged_selected_url(tmp_path):
    first = competitor_knowledge_input("c1", ask_text=fake_ai, fetch_fn=fake_fetch)
    second = competitor_knowledge_input("c1", ask_text=fake_ai, fetch_fn=fake_fetch)
    assert fake_ai.call_count == 1
    assert first == second
```

- [ ] **Step 2: Run focused test and verify RED.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_competitor_knowledge`

Expected: assertion failure because the current implementation invokes model extraction again.

- [ ] **Step 3: Fetch uncached selected URLs through the three-worker helper; submit only uncached/changed four-article extraction groups through the shared two-slot model semaphore; combine cached and fresh Markdown locally.**

- [ ] **Step 4: Run focused test and verify GREEN.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_competitor_knowledge`

Expected: PASS.

### Task 5: Regression Verification

**Files:** none

- [ ] **Step 1: Run all focused tests.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_article_analysis_cache tests.test_bounded_article_processing tests.test_competitor_knowledge tests.test_formal_content_route_entry tests.test_reference_route_batch_merge`

Expected: PASS.

- [ ] **Step 2: Run the project suite and static checks.**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests; node --check static/js/app.js; git diff --check`

Expected: all commands exit with code 0.
