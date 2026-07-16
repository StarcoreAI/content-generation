# Local Worker Login Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep same-platform local crawler jobs at 2 browser windows by default while making every crawl use the current platform-specific login state.

**Architecture:** The Python worker owns retry policy and login recovery. The Node bridge owns state selection and translates one platform state file into the existing `accounts.txt` interface for parallel Node workers. The fix stays in those two layers and does not change the external Node scheduler.

**Tech Stack:** Python `unittest`, `unittest.mock`, `pathlib`, existing Node crawler bridge CLI contract.

## Global Constraints

- Same-platform jobs with 2 or more expanded questions use concurrency `2` by default.
- Plain `need_login` recovery retries the original job with configured concurrency `2`.
- Verification, captcha, account abnormal, and risk recovery retry once with concurrency `1`.
- Platform state files are `data/<platform>_state.json`.
- Shared `STORAGE_STATE_PATH` from the parent process must not override a platform state file.
- Keep the existing `accounts.txt` dual-window entry point.
- Do not modify the external Node scheduler or platform selectors in this pass.
- Do not commit from this dirty worktree unless the user asks.

---

### Task 1: Bridge Uses Platform State Over Parent Env

**Files:**
- Modify: `tests/test_node_crawler_bridge.py`
- Modify: `services/node_crawler_bridge.py`

**Interfaces:**
- Consumes: `prepare_storage_state_for_node(platform, work_dir) -> str`
- Produces: `run_node_crawler(..., concurrency=2)` passes child env `STORAGE_STATE_PATH=<platform state>` and writes `accounts.txt` from that same state.
- Produces: when no platform state or platform cookies exist, the child env has no `STORAGE_STATE_PATH` copied from the parent process.

- [ ] **Step 1: Write the failing test**

Add this test near `test_run_node_crawler_passes_parallel_accounts_for_concurrency`:

```python
    def test_run_node_crawler_prefers_platform_state_over_parent_storage_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            platform_state = root / "data" / "doubao_state.json"
            platform_state.parent.mkdir()
            platform_payload = '{"cookies":[{"name":"platform","value":"fresh"}],"origins":[]}'
            platform_state.write_text(platform_payload, encoding="utf-8")
            stale_shared_state = root / "storage" / "state.json"
            stale_shared_state.parent.mkdir()
            stale_shared_state.write_text('{"cookies":[{"name":"shared","value":"stale"}],"origins":[]}', encoding="utf-8")
            captured = {}

            def fake_run_node_process(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["env"] = kwargs["env"]
                accounts_file = Path(cmd[cmd.index("--accounts-file") + 1])
                account_paths = accounts_file.read_text(encoding="utf-8").splitlines()
                captured["account_paths"] = account_paths
                captured["account_payloads"] = [
                    Path(account_path).read_text(encoding="utf-8")
                    for account_path in account_paths
                ]
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                (out / "doubao-test.md").write_text(
                    """# Crawl Result - doubao

- Platform: `doubao`

## 1. 问题A

### 主问题回答
回答 A

## 2. 问题B

### 主问题回答
回答 B
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0)

            with patch("services.node_crawler_bridge.prepare_storage_state_for_node", return_value=str(platform_state)), \
                    patch.dict(os.environ, {"STORAGE_STATE_PATH": str(stale_shared_state)}, clear=False), \
                    patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "doubao",
                    ["问题A", "问题B"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                    concurrency=2,
                )

        self.assertEqual(result["success"], 2)
        self.assertEqual(captured["env"]["STORAGE_STATE_PATH"], str(platform_state))
        self.assertEqual(captured["account_paths"][0], str(platform_state))
        self.assertNotEqual(captured["account_paths"][1], str(platform_state))
        self.assertEqual(captured["account_payloads"], [platform_payload] * 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_node_crawler_bridge.NodeCrawlerBridgeTests.test_run_node_crawler_prefers_platform_state_over_parent_storage_env -v`

Expected: FAIL because `captured["env"]["STORAGE_STATE_PATH"]` is the stale shared state.

- [ ] **Step 3: Write the missing-platform-state failing test**

Add this test near the previous test:

```python
    def test_run_node_crawler_does_not_use_parent_storage_env_without_platform_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            stale_shared_state = root / "storage" / "state.json"
            stale_shared_state.parent.mkdir()
            stale_shared_state.write_text(
                '{"cookies":[{"name":"shared","value":"stale"}],"origins":[]}',
                encoding="utf-8",
            )
            captured = {}

            def fake_run_node_process(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["env"] = kwargs["env"]
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                (out / "doubao-test.md").write_text(
                    """# Crawl Result - doubao

- Platform: `doubao`

## 1. 问题A

### 主问题回答
回答 A

## 2. 问题B

### 主问题回答
回答 B
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0)

            with patch("services.node_crawler_bridge.prepare_storage_state_for_node", return_value=""), \
                    patch.dict(os.environ, {"STORAGE_STATE_PATH": str(stale_shared_state)}, clear=False), \
                    patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "doubao",
                    ["问题A", "问题B"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                    concurrency=2,
                )

        self.assertEqual(result["success"], 2)
        self.assertNotIn("STORAGE_STATE_PATH", captured["env"])
        self.assertNotIn("--accounts-file", captured["cmd"])
        self.assertNotIn("--concurrency", captured["cmd"])
```

- [ ] **Step 4: Run the missing-platform-state test to verify it fails**

Run: `python -m unittest tests.test_node_crawler_bridge.NodeCrawlerBridgeTests.test_run_node_crawler_does_not_use_parent_storage_env_without_platform_state -v`

Expected: FAIL because the child env still contains the stale shared `STORAGE_STATE_PATH`.

- [ ] **Step 5: Write minimal implementation**

Change only this block in `services/node_crawler_bridge.py`:

```python
        storage_state_path = prepare_storage_state_for_node(platform, tmp_path)
        if storage_state_path:
            env["STORAGE_STATE_PATH"] = storage_state_path
        else:
            env.pop("STORAGE_STATE_PATH", None)
```

- [ ] **Step 6: Run tests to verify pass**

Run: `python -m unittest tests.test_node_crawler_bridge.NodeCrawlerBridgeTests.test_run_node_crawler_prefers_platform_state_over_parent_storage_env tests.test_node_crawler_bridge.NodeCrawlerBridgeTests.test_run_node_crawler_does_not_use_parent_storage_env_without_platform_state -v`

Expected: PASS.

---

### Task 2: Keep Worker Retry Concurrency Explicitly Covered

**Files:**
- Modify: `tests/test_local_crawl_worker.py`
- Modify: `scripts/local_crawl_worker.py` only if the tests fail.

**Interfaces:**
- Consumes: `run_job(..., crawler_concurrency=2)`
- Produces: plain login retry calls crawler with `concurrency=2`; verification retry calls crawler with `concurrency=1`.

- [ ] **Step 1: Verify existing worker tests cover the requirement**

Run: `python -m unittest tests.test_local_crawl_worker.LocalCrawlWorkerTests.test_run_job_recovers_plain_login_failure_with_configured_concurrency tests.test_local_crawl_worker.LocalCrawlWorkerTests.test_run_job_recovers_verification_failure_with_one_browser_retry -v`

Expected: PASS.

- [ ] **Step 2: If either test fails, make the smallest worker fix**

The intended code in `scripts/local_crawl_worker.py` is:

```python
                    retry_concurrency = 1 if is_account_verification_recovery_error(first_error) else crawler_concurrency
                    return crawl_once(concurrency=retry_concurrency)
```

- [ ] **Step 3: Run the worker tests again**

Run: `python -m unittest tests.test_local_crawl_worker.LocalCrawlWorkerTests.test_run_job_recovers_plain_login_failure_with_configured_concurrency tests.test_local_crawl_worker.LocalCrawlWorkerTests.test_run_job_recovers_verification_failure_with_one_browser_retry -v`

Expected: PASS.

---

### Task 3: Final Verification

**Files:**
- Read: `git diff -- services/node_crawler_bridge.py scripts/local_crawl_worker.py tests/test_node_crawler_bridge.py tests/test_local_crawl_worker.py`

**Interfaces:**
- Produces: verified local-worker and bridge behavior for tomorrow's browser testing.

- [ ] **Step 1: Run focused test modules**

Run: `python -m unittest tests.test_local_crawl_worker tests.test_node_crawler_bridge -v`

Expected: all tests pass.

- [ ] **Step 2: Inspect diff for scope**

Run: `git diff -- services/node_crawler_bridge.py scripts/local_crawl_worker.py tests/test_node_crawler_bridge.py tests/test_local_crawl_worker.py`

Expected: only the bridge env override and targeted tests changed.

## Self-Review

- Spec coverage: Task 1 covers platform state priority and `accounts.txt`; Task 2 covers default 2 concurrency, plain login retry 2, and verification retry 1; Task 3 covers verification.
- Placeholder scan: no placeholder tasks remain.
- Type consistency: all functions referenced already exist in the current codebase.
