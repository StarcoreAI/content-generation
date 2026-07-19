import unittest
import json
import os
import tempfile
from unittest.mock import patch
from pathlib import Path
from subprocess import CompletedProcess

from services.node_crawler_bridge import (
    default_node_crawler_root,
    normalize_node_payload,
    parse_node_markdown,
    prepare_storage_state_for_node,
    run_node_auth_preflight,
    run_node_crawler,
)


def make_packaged_chromium(crawler_root):
    browser_dir = crawler_root / "ms-playwright" / "chromium-1217" / "chrome-win64"
    browser_dir.mkdir(parents=True)
    (browser_dir / "chrome.exe").write_text("", encoding="utf-8")


def make_packaged_macos_chromium(crawler_root):
    browser_dir = crawler_root / "ms-playwright" / "chromium-1217" / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS"
    browser_dir.mkdir(parents=True)
    (browser_dir / "Chromium").write_text("", encoding="utf-8")


class NodeCrawlerBridgeTests(unittest.TestCase):
    def test_default_node_crawler_root_points_to_real_sibling_project(self):
        root = default_node_crawler_root(Path(__file__).resolve().parents[1])
        self.assertEqual(root.name, "ai-search-crawler（进阶API处理）")
        self.assertTrue((root / "src" / "index.js").exists())

    def test_parse_node_markdown_result_with_current_chinese_headings(self):
        markdown = """# Crawl Result - qwen

- Platform: `qwen`
- Total Queries: `1`
- Workers: `1`

## 1. 上海面部提升医生怎么选？

- Crawled At: `2026-07-01T12:00:00.000Z`

### 主问题回答

回答正文第一段。
回答正文第二段。

### 追问回答

(empty)

### 参考来源

1. 上海面部提升医生选择指南
   https://www.sohu.com/a/123
"""
        result = parse_node_markdown(markdown, citations_limit=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["platform"], "qwen")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["results"][0]["question"], "上海面部提升医生怎么选？")
        self.assertIn("回答正文第二段", result["results"][0]["answer"])
        self.assertEqual(result["results"][0]["refs"][0]["platform"], "搜狐")

    def test_parse_node_markdown_result(self):
        markdown = """# Crawl Result - doubao

- Platform: `doubao`
- Total Queries: `2`
- Workers: `1`

## 1. 上海面部提升医生怎么选？

- Crawled At: `2026-07-01T12:00:00.000Z`

### 主问题回答

回答正文第一段。

回答正文第二段。

### 追问回答

(empty)

### 参考来源

1. 上海面部提升医生选择指南
   https://www.toutiao.com/article/123
2. 医美医生面诊注意事项
   https://www.sohu.com/a/456

## 2. 没有引用的问题

- Crawled At: `2026-07-01T12:01:00.000Z`

### 主问题回答

第二个回答。

### 追问回答

(empty)

### 参考来源

(empty)
"""
        result = parse_node_markdown(markdown, citations_limit=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["platform"], "doubao")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["success"], 2)
        self.assertEqual(result["results"][0]["question"], "上海面部提升医生怎么选？")
        self.assertIn("回答正文第二段", result["results"][0]["answer"])
        self.assertEqual(len(result["results"][0]["refs"]), 2)
        self.assertEqual(result["results"][0]["refs"][0]["platform"], "今日头条")
        self.assertEqual(result["results"][1]["refs"], [])

    def test_normalize_future_json_payload(self):
        payload = {
            "platform": "qwen",
            "items": [
                {
                    "query": "问题A",
                    "answer": "回答A",
                    "citations": [
                        {"title": "搜狐文章", "url": "https://www.sohu.com/a/1"}
                    ],
                }
            ],
        }
        result = normalize_node_payload(payload)
        self.assertEqual(result["platform"], "qwen")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["results"][0]["question"], "问题A")
        self.assertEqual(result["results"][0]["refs"][0]["platform"], "搜狐")

    def test_prepare_storage_state_wraps_legacy_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            cookie_path = data_dir / "doubao_cookies.json"
            cookie_path.write_text(
                json.dumps([
                    {"name": "session", "value": "abc", "domain": ".doubao.com", "path": "/"}
                ]),
                encoding="utf-8",
            )

            work_dir = root / "work"
            work_dir.mkdir()
            state_path = prepare_storage_state_for_node("doubao", work_dir, project_root=root)
            self.assertTrue(state_path)
            payload = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["cookies"][0]["name"], "session")
            self.assertEqual(payload["origins"], [])

    def test_run_node_auth_preflight_runs_one_sequential_probe_for_all_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src" / "adapters").mkdir(parents=True)
            (crawler_root / "src" / "adapters" / "index.js").write_text("// test entry", encoding="utf-8")
            make_packaged_chromium(crawler_root)
            storage_state = root / "storage" / "state.json"
            captured = {}

            def fake_runner(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                return CompletedProcess(cmd, 0)

            result = run_node_auth_preflight(
                ["deepseek", "doubao"],
                crawler_root=crawler_root,
                storage_state_path=storage_state,
                runner=fake_runner,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(any(str(item).endswith("node_auth_preflight.mjs") for item in captured["cmd"]))
        self.assertIn("--platforms", captured["cmd"])
        self.assertIn("deepseek,doubao", captured["cmd"])
        self.assertIn("--storage-state", captured["cmd"])
        self.assertIn(str(storage_state), captured["cmd"])
        self.assertIn("--mode", captured["cmd"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--mode") + 1], "strict")
        self.assertEqual(captured["kwargs"]["cwd"], str(crawler_root))
        self.assertEqual(
            captured["kwargs"]["env"]["PLAYWRIGHT_BROWSERS_PATH"],
            str(crawler_root / "ms-playwright"),
        )
        self.assertNotIn("capture_output", captured["kwargs"])

    def test_run_node_auth_preflight_uses_default_browser_cache_without_packaged_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src" / "adapters").mkdir(parents=True)
            (crawler_root / "src" / "adapters" / "index.js").write_text("// test entry", encoding="utf-8")
            storage_state = root / "storage" / "state.json"
            captured = {}

            def fake_runner(cmd, **kwargs):
                captured["kwargs"] = kwargs
                return CompletedProcess(cmd, 0)

            result = run_node_auth_preflight(
                ["deepseek"],
                crawler_root=crawler_root,
                storage_state_path=storage_state,
                runner=fake_runner,
            )

        self.assertTrue(result["ok"])
        self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", captured["kwargs"]["env"])

    def test_run_node_auth_preflight_uses_packaged_macos_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src" / "adapters").mkdir(parents=True)
            (crawler_root / "src" / "adapters" / "index.js").write_text("// test entry", encoding="utf-8")
            make_packaged_macos_chromium(crawler_root)
            storage_state = root / "storage" / "state.json"
            captured = {}

            def fake_runner(cmd, **kwargs):
                captured["kwargs"] = kwargs
                return CompletedProcess(cmd, 0)

            result = run_node_auth_preflight(
                ["deepseek"],
                crawler_root=crawler_root,
                storage_state_path=storage_state,
                runner=fake_runner,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            captured["kwargs"]["env"]["PLAYWRIGHT_BROWSERS_PATH"],
            str(crawler_root / "ms-playwright"),
        )

    def test_run_node_auth_preflight_can_request_manual_or_soft_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src" / "adapters").mkdir(parents=True)
            (crawler_root / "src" / "adapters" / "index.js").write_text("// test entry", encoding="utf-8")
            storage_state = root / "storage" / "state.json"
            captured = {}

            def fake_runner(cmd, **kwargs):
                captured["cmd"] = cmd
                return CompletedProcess(cmd, 0)

            result = run_node_auth_preflight(
                ["qwen"],
                crawler_root=crawler_root,
                storage_state_path=storage_state,
                mode="manual",
                runner=fake_runner,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--mode") + 1], "manual")

    def test_node_auth_preflight_is_sequential_and_waits_without_enter(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "node_auth_preflight.mjs").read_text(encoding="utf-8")

        self.assertIn("for (const platform of platforms)", script)
        self.assertIn("await waitForPlatformReady(adapter, page, timeoutMs, platform)", script)
        self.assertNotIn("Promise.all", script)
        self.assertNotIn("readline", script)
        self.assertNotIn("process.stdin", script)
        self.assertNotIn("if (loggedIn) {\n      await saveStorageState", script)

    def test_node_auth_preflight_supports_soft_and_manual_login_modes(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "node_auth_preflight.mjs").read_text(encoding="utf-8")

        self.assertIn('argValue("--mode", "strict")', script)
        self.assertIn("authMode === \"soft\"", script)
        self.assertIn("authMode === \"manual\"", script)
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", script)
        self.assertIn("ms-playwright", script)
        self.assertIn("async function platformHasVisibleLoginBlocker", script)
        self.assertIn("authMode === \"soft\" && !needsLogin", script)
        self.assertIn("soft login check did not confirm readiness; continuing", script)
        self.assertIn("await waitForPlatformReady(adapter, page, timeoutMs, platform)", script)
        self.assertIn("chrome-mac", script)
        self.assertIn("Chromium.app", script)

    def test_node_auth_preflight_requires_qwen_login_not_just_input(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "node_auth_preflight.mjs").read_text(encoding="utf-8")

        self.assertIn('STRICT_LOGIN_PLATFORMS = new Set(["qwen"])', script)
        self.assertIn("async function qwenIsLoggedIn(page)", script)
        self.assertIn("async function qwenHasSessionCookie(page)", script)
        self.assertIn("async function qwenHasAccountSignal(page)", script)
        self.assertIn("async function qwenLoginState(page)", script)
        self.assertIn("button:has-text", script)
        self.assertIn("page.context().cookies()", script)
        self.assertIn('"b-user-id"', script)
        self.assertIn("cookie.expires", script)
        self.assertIn("async function qwenHasVisibleLoginAction(page)", script)
        self.assertLess(
            script.index("loginAction: await qwenHasVisibleLoginAction(page)"),
            script.index("state.sessionCookie = await qwenHasSessionCookie(page)"),
        )
        self.assertIn("qwenHasSessionCookie(page)", script)
        self.assertIn("!state.loginAction && (state.sessionCookie || state.accountSignal)", script)
        self.assertIn("platform === \"qwen\"", script)
        self.assertIn("qwenIsLoggedIn(page)", script)
        self.assertIn("\\u767b\\u5f55", script)
        self.assertIn("\\u6ce8\\u518c", script)

    def test_node_auth_preflight_can_hold_qwen_page_for_debugging(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "node_auth_preflight.mjs").read_text(encoding="utf-8")

        self.assertIn("GEO_QWEN_AUTH_DEBUG_HOLD_MS", script)
        self.assertIn("async function holdQwenPageForDebugging(platform, page)", script)
        self.assertIn("await holdQwenPageForDebugging(platform, page)", script)
        self.assertLess(
            script.index("await openHome(adapter, page)"),
            script.index("await holdQwenPageForDebugging(platform, page)"),
        )
        self.assertLess(
            script.index("await holdQwenPageForDebugging(platform, page)"),
            script.index("let ready = await waitForPlatformReady(adapter, page, 10_000, platform)"),
        )

    def test_run_node_crawler_preserves_output_dir_and_disables_followup_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            make_packaged_chromium(crawler_root)
            output_dir = root / "node-output"
            captured = {}

            def fake_run_node_process(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["env"] = kwargs["env"]
                stdout_path = Path(kwargs["stdout_path"])
                stderr_path = Path(kwargs["stderr_path"])
                stdout_path.write_text("node stdout", encoding="utf-8")
                stderr_path.write_text("node stderr", encoding="utf-8")
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                (out / "qwen-test.md").write_text(
                    """# Crawl Result - qwen

- Platform: `qwen`

## 1. 测试问题

### 主问题回答

测试回答

### 参考来源

(empty)
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0)

            with patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "qwen",
                    ["测试问题"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                )

            self.assertEqual(result["success"], 1)
            self.assertEqual(captured["env"]["OUTPUT_DIR"], str(output_dir))
            self.assertEqual(captured["env"]["GEO_NODE_BRIDGE"], "1")
            self.assertEqual(captured["env"]["FOLLOWUP_API_ENABLED"], "false")
            self.assertEqual(
                captured["env"]["PLAYWRIGHT_BROWSERS_PATH"],
                str(crawler_root / "ms-playwright"),
            )
            self.assertNotIn("GEO_NODE_NEW_PAGE_PER_QUERY", captured["env"])
            self.assertEqual(captured["env"]["GEO_NODE_NEW_CONVERSATION_EVERY"], "1")
            self.assertTrue((output_dir / "qwen-test.md").exists())
            self.assertEqual((output_dir / "node-stdout.log").read_text(encoding="utf-8"), "node stdout")
            self.assertEqual((output_dir / "node-stderr.log").read_text(encoding="utf-8"), "node stderr")

    def test_run_node_crawler_does_not_overwrite_existing_node_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            output_dir.mkdir()
            (output_dir / "node-stdout.log").write_text("old stdout", encoding="utf-8")
            (output_dir / "node-stderr.log").write_text("old stderr", encoding="utf-8")

            def fake_run_node_process(cmd, **kwargs):
                Path(kwargs["stdout_path"]).write_text("new stdout", encoding="utf-8")
                Path(kwargs["stderr_path"]).write_text("new stderr", encoding="utf-8")
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                (out / "qwen-test.md").write_text(
                    """# Crawl Result - qwen

- Platform: `qwen`

## 1. test

### 主问题回答
ok
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0)

            with patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "qwen",
                    ["test"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                )

            self.assertEqual(result["success"], 1)
            self.assertEqual((output_dir / "node-stdout.log").read_text(encoding="utf-8"), "old stdout")
            self.assertEqual((output_dir / "node-stderr.log").read_text(encoding="utf-8"), "old stderr")
            self.assertEqual((output_dir / "node-stdout-2.log").read_text(encoding="utf-8"), "new stdout")
            self.assertEqual((output_dir / "node-stderr-2.log").read_text(encoding="utf-8"), "new stderr")

    def test_run_node_crawler_uses_default_browser_cache_without_packaged_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            captured = {}

            def fake_run_node_process(cmd, **kwargs):
                captured["env"] = kwargs["env"]
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                (out / "qwen-test.md").write_text(
                    """# Crawl Result - qwen

- Platform: `qwen`

## 1. 娴嬭瘯闂

### 主问题回答
测试回答
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0)

            with patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "qwen",
                    ["test"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                )

        self.assertEqual(result["success"], 1)
        self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", captured["env"])

    def test_run_node_crawler_resolves_relative_output_dir_before_calling_node(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                root = Path(tmp)
                crawler_root = root / "crawler"
                (crawler_root / "src").mkdir(parents=True)
                (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
                captured = {}

                def fake_run_node_process(cmd, **kwargs):
                    out = Path(kwargs["env"]["OUTPUT_DIR"])
                    captured["output_dir"] = out
                    self.assertTrue(out.is_absolute())
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "kimi-test.md").write_text(
                        """# Crawl Result - kimi

- Platform: `kimi`

## 1. 测试问题

### 主问题回答

测试回答

### 参考来源

(empty)
""",
                        encoding="utf-8",
                    )
                    return CompletedProcess(cmd, 0)

                with patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                    result = run_node_crawler(
                        "kimi",
                        ["测试问题"],
                        crawler_root=crawler_root,
                        output_dir="logs/kimi-smoke",
                    )

                self.assertEqual(result["success"], 1)
                self.assertEqual(captured["output_dir"], root / "logs" / "kimi-smoke")
            finally:
                os.chdir(old_cwd)

    def test_run_node_crawler_passes_all_questions_to_one_node_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            query_batches = []

            def fake_run_node_process(cmd, **kwargs):
                query_file = Path(cmd[cmd.index("--query-file") + 1])
                queries = query_file.read_text(encoding="utf-8").splitlines()
                query_batches.append(queries)
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                blocks = []
                for index, query in enumerate(queries, start=1):
                    blocks.append(
                        f"""## {index}. {query}

### 主问题回答

回答 {index}

### 参考来源

(empty)
"""
                    )
                (out / "qwen-test.md").write_text(
                    """# Crawl Result - qwen

- Platform: `qwen`

""" + "\n".join(blocks),
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0, stdout=f"stdout {len(query_batches)}", stderr="")

            with patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "qwen",
                    ["问题A", "问题B"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                )

            self.assertEqual(query_batches, [["问题A", "问题B"]])
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["success"], 2)
            self.assertEqual([item["question"] for item in result["results"]], ["问题A", "问题B"])

    def test_run_node_crawler_passes_parallel_accounts_for_concurrency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            storage_state = root / "storage" / "state.json"
            storage_state.parent.mkdir()
            expected_state_payload = '{"cookies":[{"name":"session","value":"abc"}],"origins":[]}'
            storage_state.write_text(expected_state_payload, encoding="utf-8")
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
                (out / "qwen-test.md").write_text(
                    """# Crawl Result - qwen

- Platform: `qwen`

## 1. 问题A

### 主问题回答
回答 A

### 参考来源
(empty)

## 2. 问题B

### 主问题回答
回答 B

### 参考来源
(empty)
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0)

            with patch("services.node_crawler_bridge.prepare_storage_state_for_node", return_value=str(storage_state)), \
                    patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "qwen",
                    ["问题A", "问题B"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                    concurrency=2,
                )

        self.assertEqual(result["success"], 2)
        self.assertIn("--accounts-file", captured["cmd"])
        self.assertIn("--concurrency", captured["cmd"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--concurrency") + 1], "2")
        self.assertEqual(captured["env"]["STORAGE_STATE_PATH"], str(storage_state))
        self.assertEqual(len(captured["account_paths"]), 2)
        self.assertEqual(captured["account_paths"][0], str(storage_state))
        self.assertNotEqual(captured["account_paths"][1], str(storage_state))
        self.assertEqual(captured["account_payloads"], [expected_state_payload] * 2)

    def test_run_node_crawler_forces_doubao_single_window_when_concurrency_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text("// test entry", encoding="utf-8")
            output_dir = root / "node-output"
            storage_state = root / "storage" / "state.json"
            storage_state.parent.mkdir()
            storage_state.write_text('{"cookies":[{"name":"session","value":"abc"}],"origins":[]}', encoding="utf-8")
            captured = {}

            def fake_run_node_process(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["env"] = kwargs["env"]
                out = Path(kwargs["env"]["OUTPUT_DIR"])
                out.mkdir(parents=True, exist_ok=True)
                (out / "doubao-test.md").write_text(
                    """# Crawl Result - doubao

- Platform: `doubao`

## 1. 闂A

### 涓婚棶棰樺洖绛?
鍥炵瓟 A

## 2. 闂B

### 涓婚棶棰樺洖绛?
鍥炵瓟 B
""",
                    encoding="utf-8",
                )
                return CompletedProcess(cmd, 0)

            with patch("services.node_crawler_bridge.prepare_storage_state_for_node", return_value=str(storage_state)), \
                    patch("services.node_crawler_bridge._run_node_process", side_effect=fake_run_node_process):
                result = run_node_crawler(
                    "doubao",
                    ["闂A", "闂B"],
                    crawler_root=crawler_root,
                    output_dir=output_dir,
                    concurrency=2,
                )

        self.assertEqual(result["total"], 2)
        self.assertEqual(captured["env"]["STORAGE_STATE_PATH"], str(storage_state))
        self.assertNotIn("--accounts-file", captured["cmd"])
        self.assertNotIn("--concurrency", captured["cmd"])

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
        self.assertNotIn("--accounts-file", captured["cmd"])
        self.assertNotIn("--concurrency", captured["cmd"])

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

    def test_run_node_crawler_returns_when_markdown_is_final_but_process_keeps_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crawler_root = root / "crawler"
            (crawler_root / "src").mkdir(parents=True)
            (crawler_root / "src" / "index.js").write_text(
                """
const fs = require('fs');
const path = require('path');
const out = process.env.OUTPUT_DIR;
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'qwen-final.md'), `# Crawl Result - qwen

- Platform: \\`qwen\\`

## 1. 测试问题

### 主问题回答

测试回答

### 参考来源

(empty)
`, 'utf8');
console.log('Crawl done:');
setInterval(() => {}, 1000);
""",
                encoding="utf-8",
            )
            output_dir = root / "node-output"

            result = run_node_crawler(
                "qwen",
                ["测试问题"],
                crawler_root=crawler_root,
                output_dir=output_dir,
                timeout_s=5,
            )

            self.assertEqual(result["success"], 1)
            self.assertEqual(result["results"][0]["answer"], "测试回答")


if __name__ == "__main__":
    unittest.main()
