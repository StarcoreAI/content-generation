# Content Generation Brief Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch `/api/content/generate` from legacy plugin prompts to active pattern-library sampling, a planning brief, article writing, and atomic provenance persistence.

**Architecture:** Keep `build_brief_sample` as the sole sampling point and add only the three missing inputs: merged client question-group questions, persisted client audience angles, and recent ending IDs from SQLite provenance. The generation route owns orchestration and persists only after both LLM calls succeed. The writing prompt consumes the brief rather than making structural decisions.

**Tech Stack:** Flask, Python standard library, SQLite, existing `PatternLibrary`, `ContentGenerationStore`, unittest, browser-side vanilla JavaScript.

## Global Constraints

- Do not remove old plugin APIs or the front-end plugin list in this step.
- `/api/content/generate` must never fall back to the plugin path.
- FAQ is omitted when the supplied question list is empty; do not create placeholder FAQ content.
- LLM calls are injected/mocked in tests; production writing call uses at least 10000 max tokens and retries one empty response.
- Persist an article only after sampling, planning brief, and article writing have all succeeded.
- The final real two-article acceptance commands are run by the user, not this implementation task.

---

### Task 1: Extend sampler inputs and write-prompt contract

**Files:**
- Modify: `services/brief_builder.py`
- Modify: `services/content_prompts.py`
- Test: `tests/test_brief_builder.py`
- Test: `tests/test_content_prompts.py`

**Consumes:** active pattern entries and the Step D brief schema.

**Produces:** `build_brief_sample(..., recent_endings=None)` and `build_content_generation_messages(..., brief, customer_material_text, content_upload_text, competitor_markdown, ...)`.

- [x] **Step 1: Write failing sampler and prompt tests**

```python
result = build_brief_sample(..., faq_questions=[], recent_endings=[])
assert result["faq_module"] is None
assert result["sampling_meta"]["missing_slots"]["faq_module_reason"] == "faq_questions_empty"

prompt = json.dumps(build_content_generation_messages(...), ensure_ascii=False)
assert "简报逐节施工指令" in prompt
assert "禁令 A" in prompt
assert "攻略对比型展开 few-shot 示例" not in prompt
```

- [x] **Step 2: Run focused tests and confirm expected failures**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_brief_builder tests.test_content_prompts -v`

Expected: failures for the missing `recent_endings` argument and the old prompt text.

- [x] **Step 3: Implement the minimal sampler and writing-prompt changes**

```python
faq = rng.choice(candidates["faq_module"]) if faq_questions and rng.random() < FAQ_PROBABILITY else None
ending = _choose_ending(candidates["ending_module"], recent_endings, rng)
```

Render the brief sections, bans, dedup hints, combo warning, and free-slot instructions verbatim. Remove exported few-shot/template constants and all structural article-type/subtype prompt branches from the writer path.

- [x] **Step 4: Re-run focused tests**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_brief_builder tests.test_content_prompts -v`

Expected: PASS.

### Task 2: Persist audience angles and collect routing inputs

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Test: `tests/test_app_core.py`

**Consumes:** `clients.json` client objects and `probe_groups.json` group objects.

**Produces:** an `audience_angles` client configuration list, a content-page multiline editor, and helpers returning deduplicated question strings and seven-day provenance history.

- [x] **Step 1: Write failing round-trip and route-input tests**

```python
updated = client.put("/api/clients/c1", json={"audience_angles": ["异地在职者"]})
assert updated.get_json()["client"]["audience_angles"] == ["异地在职者"]
assert geo_app.load_client_faq_questions("c1") == ["问题一", "问题二"]
```

- [x] **Step 2: Run the focused route tests and confirm expected failures**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_app_core -v`

Expected: failures because client updates discard angles and the helpers do not exist.

- [x] **Step 3: Implement storage and UI wiring**

```python
client["audience_angles"] = _normalize_lines(d.get("audience_angles", []))
questions = _unique_strings(q for group in load(F_GROUPS, {}).get(cid, []) for q in group.get("questions", []))
```

Use the existing `PUT /api/clients/<cid>` endpoint. Add one textarea to the content page, load its saved client value on client change, and save its non-empty lines through that endpoint. Do not change legacy plugin controls.

- [x] **Step 4: Re-run focused route tests**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_app_core -v`

Expected: PASS.

### Task 3: Route new generation chain atomically and expose provenance

**Files:**
- Modify: `app.py`
- Modify: `static/js/app.js`
- Test: `tests/test_app_core.py`

**Consumes:** Task 1 sampler/prompt and Task 2 client inputs; `ContentGenerationStore` Step D JSON columns.

**Produces:** route-generated articles with `brief` and `provenance`, including sampled entry IDs/names, fingerprint, free slot, material switches, audience angle, and recent-ending history.

- [x] **Step 1: Write failing integration tests**

```python
with patch.object(geo_app, "ai_json", return_value=valid_brief), \\
     patch.object(geo_app, "ai_deepseek_pro", return_value="Article"):
    response = client.post("/api/content/generate", json=request_data)
assert response.status_code == 200
assert response.get_json()["article"]["brief"] == valid_brief
assert response.get_json()["article"]["provenance"]["skeleton"]["id"] == sampled_id
```

Add separate tests where brief generation or writing raises and assert `load_content_session(cid)["articles"] == []`.

- [x] **Step 2: Run the integration tests and confirm expected failures**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_app_core -v`

Expected: old route calls a single legacy writer and does not persist provenance.

- [x] **Step 3: Implement the orchestration path**

```python
sample = build_brief_sample(...)
brief = generate_planning_brief(sample, ..., ai_json_fn=ai_json)
content = _generate_article_with_retry(messages)
article = append_content_generation(cid, {"brief": brief, "provenance": provenance, ...}, ...)
```

Read only records whose `created_at` is in the last seven calendar days and extract `fingerprint`/`ending_module.id` from their `provenance`. Use existing material toggles, build the same material text for both LLM layers, and pass `ai_deepseek_pro(messages, 10000)`. On any exception return an error before `append_content_generation`.

- [x] **Step 4: Show selected entry names in existing result cards**

```javascript
const patterns = Object.values(a.provenance?.entries || {}).flatMap(...).map(item => item.name);
```

Render a compact, escaped text line only when provenance is present.

- [x] **Step 5: Re-run route tests**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_app_core -v`

Expected: PASS.

### Task 4: Regression verification and user handoff

**Files:**
- Modify: `docs/superpowers/plans/2026-07-20-content-generation-brief-routing.md`

- [x] **Step 1: Run focused tests and full regression**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_brief_builder tests.test_content_prompts tests.test_app_core -v`

Run: `run_tests.bat`

Expected: all tests pass.

- [x] **Step 2: Inspect diff and mark verified plan tasks complete**

Run: `git diff --check`

Expected: no whitespace errors.

- [x] **Step 3: Hand the real acceptance commands to the user**

Provide two browser/API generation instructions: one comparison and one introduction, each with 2–3 saved audience-angle lines and an existing question group. Do not run those real acceptance calls.
