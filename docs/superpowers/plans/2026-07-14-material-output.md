# Material Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Markdown output worker that turns reducer reports into injection packages.

**Architecture:** `services/material_output.py` builds the Markdown-output prompt and validates the returned Markdown text. `scripts/run_material_output.py` reads a reducer report, calls the service once, and writes a `.md` file.

**Tech Stack:** Python standard library, existing OpenAI/settings helpers from `scripts.extract_entities`.

## Global Constraints

- Markdown only.
- One model call.
- No JSON schema for output content.
- Do not reopen original package files.
- Do not generate a promotional article.
- Do not commit unless the user asks.

---

### Task 1: Output Service

**Files:**
- Create: `services/material_output.py`
- Test: `tests/test_material_output.py`

**Interfaces:**
- Produces: `build_material_output(reducer_report, ask_text, question=None, max_tokens=8192) -> str`
- Produces: `DEFAULT_OUTPUT_RULES: str`

### Task 2: Output Runner

**Files:**
- Create: `scripts/run_material_output.py`
- Test: `tests/test_run_material_output.py`

**Interfaces:**
- Consumes: `build_material_output`
- Produces: `choose_material_output_model(settings) -> str`
- Produces: `default_output_path(reducer_report) -> Path`

### Task 3: Real Experiment

Run the latest reducer report through the output worker and inspect the generated Markdown.

