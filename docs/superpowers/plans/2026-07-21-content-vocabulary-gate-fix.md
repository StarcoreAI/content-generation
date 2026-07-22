# Content Vocabulary Gate Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent internal workflow vocabulary in published articles and downgrade cautioned banned-word references to warnings.

**Architecture:** Add reader-facing constraints to the existing planning and writing prompts. Keep detection in the existing quality gate, adding a short local context check only for banned-word evidence.

**Tech Stack:** Python, unittest, existing LLM prompt and quality-gate services.

## Global Constraints

- Do not call a real LLM or run a long-running acceptance command.
- Keep ordinary banned-word hits blocking and keep internal-workflow vocabulary blocking.
- Add regression tests before production changes.

---

### Task 1: Add failing quality-gate regressions

**Files:**
- Modify: `tests/test_quality_gate.py`

- [ ] Add tests for cautionary `包过` language, ordinary `包过` blocking, and internal vocabulary being blocked by `meta_discourse`.
- [ ] Run `python -m unittest tests.test_quality_gate -v` and confirm failure before implementation.

### Task 2: Implement the shared quality-gate behavior

**Files:**
- Modify: `services/quality_gate.py`

- [ ] Add the specified workflow-vocabulary phrases to the meta-discourse list.
- [ ] Detect a 20-character cautionary context around banned-word matches and downgrade only that match to a warning with `cautionary_context=true`.
- [ ] Run `python -m unittest tests.test_quality_gate -v` and confirm it passes.

### Task 3: Add and implement prompt safeguards

**Files:**
- Modify: `tests/test_content_prompts.py`
- Modify: `tests/test_brief_builder.py`
- Modify: `services/content_prompts.py`
- Modify: `services/brief_builder.py`

- [ ] Add failing assertions for the reader-facing writing rule and internal-name instruction in the brief prompt.
- [ ] Add the exact safeguards to the existing prompts without changing generation control flow.
- [ ] Run the two focused test modules and confirm they pass.

### Task 4: Verify the changed units

**Files:**
- Verify: `services/quality_gate.py`, `services/content_prompts.py`, `services/brief_builder.py`

- [ ] Run focused unit tests and `py_compile` for the three changed services.
- [ ] Run `git diff --check`.
