# Planning Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate validated planning briefs from a sampled writing shape and persist future provenance fields without routing changes.

**Architecture:** `brief_builder` builds the complete constrained prompt, retries one empty injected JSON response, and validates the resulting brief. `ContentGenerationStore` adds nullable SQLite columns idempotently and serializes the three current JSON artifacts. The developer script assembles local files and writes an inspection artifact only after a valid brief returns.

**Tech Stack:** Python standard library, existing `PatternLibrary`, `ContentGenerationStore`, `services.storage`, `unittest`.

## Global Constraints

- Do not modify `app.py` generation routes, invoke network code from the service, or change crawler/local-worker behavior.
- LLM calls use an injected `ai_json_fn(prompt, max_tokens)` and use at least 6000 output tokens.
- A missing/invalid brief must not write a SQLite row or developer output artifact.
- The brief must preserve the sampled skeleton/module choices; free slots are the only self-authored slots.

---

### Task 1: Provenance columns

**Files:**
- Modify: `services/content_generations.py`
- Modify: `tests/test_content_generations_store.py`

- [ ] Write a failing test for idempotent column creation and JSON/null field round-trip.
- [ ] Run it and confirm the new article fields are absent.
- [ ] Add the seven nullable columns and extend insert/read serialization.
- [ ] Re-run the store tests.

### Task 2: Brief service contract

**Files:**
- Modify: `services/brief_builder.py`
- Modify: `tests/test_brief_builder.py`

- [ ] Write failing mock-LLM tests for valid output, one empty retry, schema failure, bans context, and free-slot prompt instructions.
- [ ] Run them and confirm the service API is absent.
- [ ] Implement prompt construction, one empty retry, and strict schema validation.
- [ ] Re-run focused tests.

### Task 3: Human-review script and regression

**Files:**
- Create: `scripts/dev_brief_builder.py`

- [ ] Add a UTF-8 CLI that reads explicit local inputs and persists valid sample/brief pairs by date.
- [ ] Run it once for 翼升学 with `industry:成人教育` and inspect its output path.
- [ ] Run `run_tests.bat`.
