# Content Research Sample Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator create one cloud-side, client-scoped research package for 崔红蕾 and 古齐装饰, then download that package with a single `scp -r` command.

**Architecture:** A standard-library Python CLI reads the existing cloud `data/` directory and copies only the two matched clients' customer materials, competitor materials, selection evidence, selection reports, and reference-intelligence artifacts into a newly created output directory. It also writes filtered `clients.json` and `probe_groups.json`, never copies whole shared configuration files or mutates source data.

**Tech Stack:** Python standard library (`argparse`, `json`, `shutil`, `pathlib`), `unittest`.

## Global Constraints

- The script is executed manually on the cloud host from `/srv/geo-content-v2`.
- Source data is read-only; the only write target is the explicitly supplied export directory.
- Default client selectors are `崔红蕾` and `古齐装饰`, matching either client `name` or `brand` exactly.
- The export must not include another customer's data, `.env`, credentials, cookies, or the full `raw_records.json`.
- No network call, LLM call, package install, deployment, service restart, or Git commit is part of the feature.

---

### Task 1: Add a client-scoped export CLI

**Files:**

- Create: `scripts/export_content_research_samples.py`
- Create: `tests/test_export_content_research_samples.py`

**Interfaces:**

- `export_content_research_samples(data_dir, output_dir, selectors) -> dict`
- CLI: `python -X utf8 scripts/export_content_research_samples.py --output-dir /tmp/geo-content-research-samples`

- [x] **Step 1: Write the failing test**

```python
summary = export_content_research_samples(data_dir, output_dir, ["崔红蕾", "古齐装饰"])
self.assertEqual(summary["clients"], ["cui", "gu"])
self.assertEqual(json.loads((output_dir / "clients.json").read_text(encoding="utf-8"))[0]["id"], "cui")
self.assertFalse((output_dir / "raw_records.json").exists())
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python -X utf8 -m unittest tests.test_export_content_research_samples -v`

Expected: FAIL because the script module does not exist.

- [x] **Step 3: Write the minimal implementation**

```python
def export_content_research_samples(data_dir, output_dir, selectors):
    clients = _matched_clients(_load_json(data_dir / "clients.json"), selectors)
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "clients.json", clients)
    _write_json(output_dir / "probe_groups.json", {
        client["id"]: groups.get(client["id"], []) for client in clients
    })
    for client in clients:
        _copy_client_tree(data_dir, output_dir, "material_packages", client["id"])
        _copy_client_tree(data_dir, output_dir, "competitor_material_packages", client["id"])
        _copy_client_tree(data_dir, output_dir, "selection_surface_reports", client["id"])
        _copy_client_tree(data_dir, output_dir, "selection_evidence", client["id"])
        _copy_client_tree(data_dir, output_dir, "reference_intelligence", client["id"])
```

- [x] **Step 4: Run the test to verify it passes**

Run: `python -X utf8 -m unittest tests.test_export_content_research_samples -v`

Expected: PASS.

### Task 2: Verify CLI output and usage

**Files:**

- Modify: `scripts/export_content_research_samples.py`
- Modify: `tests/test_export_content_research_samples.py`

**Interfaces:**

- A missing selected client fails before creating the output directory.
- A successful CLI prints the exact `scp -r` source path, without any remote host or credential.

- [x] **Step 1: Write the failing test**

```python
with self.assertRaisesRegex(ValueError, "missing_client_selectors"):
    export_content_research_samples(data_dir, output_dir, ["不存在"])
self.assertFalse(output_dir.exists())
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python -X utf8 -m unittest tests.test_export_content_research_samples.ExportContentResearchSamplesTests.test_missing_client_does_not_create_partial_export -v`

Expected: FAIL because missing selectors are not validated.

- [x] **Step 3: Write the minimal implementation**

```python
if missing:
    raise ValueError("missing_client_selectors: " + "、".join(missing))
```

- [x] **Step 4: Run focused and syntax verification**

Run: `python -X utf8 -m unittest tests.test_export_content_research_samples -v; python -X utf8 -m py_compile scripts/export_content_research_samples.py`

Expected: PASS.

## Self-review

- The export is client-scoped by matching IDs from `clients.json` before copying any tree.
- The script copies the five required per-client evidence directories and only filtered client/group configuration.
- It does not touch publication, crawler, knowledge-base, content-generation, or deployment code.
