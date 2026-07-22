# Pattern Library Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-only persistent pattern library for citation-analysis patterns without changing current APIs or frontend behavior.

**Architecture:** `services/pattern_library.py` owns scope validation, Windows-safe file paths, entry normalization, source de-duplication, state changes, and JSON persistence. Each scope is stored independently below `data/pattern_library/`; the existing reference-analysis pipeline will not call it in this increment.

**Tech Stack:** Python standard library, existing `services.storage` JSON helpers, `unittest`.

## Global Constraints

- Keep the feature backend-only: no Flask route, template, JavaScript, or current reference-analysis behavior changes.
- Store only `candidate`, `active`, and `retired` states; only distinct source URLs increase `evidence_count`.
- Promote a candidate to `active` after a second distinct source; allow explicit state changes for later operational controls.
- Do not add dependencies or a database migration.

---

### Task 1: Add the Persistent Library Service

**Files:**
- Create: `services/pattern_library.py`
- Test: `tests/test_pattern_library.py`

**Interfaces:**
- `PatternLibrary(root_dir, now_fn=None)` stores scope files below `root_dir`.
- `create_candidate(scope, kind, name, payload, source)` returns an entry with `status="candidate"` and one source.
- `add_evidence(scope, entry_id, source)` increments only for a new normalized URL and promotes on count two.
- `set_status(scope, entry_id, status)` accepts only `candidate`, `active`, or `retired`.

- [x] **Step 1: Write failing tests**

```python
library = PatternLibrary(root)
entry = library.create_candidate(
    "industry:adult_education", "skeleton", "观察分类型", {},
    {"url": "https://example.com/a", "title": "A"},
)
assert entry["status"] == "candidate"
assert entry["evidence_count"] == 1
assert (root / "industry_adult_education.json").exists()
```

- [x] **Step 2: Run the new test and verify it fails because the module does not exist.**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_pattern_library -v`

- [x] **Step 3: Implement the smallest service that persists normalized entries and sources.**

```python
def scope_path(self, scope):
    kind, value = scope.split(":", 1) if ":" in scope else (scope, "")
    safe_value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return self.root_dir / f"{kind}_{safe_value}.json"
```

- [x] **Step 4: Add evidence and state-change tests, then implement source de-duplication, automatic promotion, and explicit retirement.**

```python
updated = library.add_evidence(scope, entry["id"], {"url": "https://example.com/b"})
assert updated["evidence_count"] == 2
assert updated["status"] == "active"
assert library.add_evidence(scope, entry["id"], {"url": "https://example.com/b"})["evidence_count"] == 2
assert library.set_status(scope, entry["id"], "retired")["status"] == "retired"
```

- [x] **Step 5: Run the library test module and the repository compile check.**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_pattern_library -v`
Run: `./.venv/Scripts/python.exe -m py_compile services/pattern_library.py`

### Task 2: Record the Backend-Only Increment

**Files:**
- Modify: `docs/content-refactor-short-term.md`
- Modify: `接手文档.md`

- [x] **Step 1: Update the progress snapshot to state that the pattern-library persistence layer exists but is not yet connected to citation analysis or the frontend.**

- [x] **Step 2: Run `git diff --check` and the relevant test modules.**

- [ ] **Step 3: Commit only the pattern-library implementation, tests, and status documentation when the current worktree is ready for a commit.**
