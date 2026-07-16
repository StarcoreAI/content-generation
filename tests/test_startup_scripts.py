import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


def read_text(name):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
        return f.read()


class StartupScriptTests(unittest.TestCase):
    def test_top_level_batch_files_are_cmd_safe(self):
        bat_files = [
            name for name in os.listdir(ROOT)
            if name.lower().endswith(".bat")
        ]
        self.assertTrue(bat_files)
        for name in bat_files:
            with self.subTest(name=name):
                with open(os.path.join(ROOT, name), "rb") as f:
                    raw = f.read()
                self.assertNotIn(b"\xef\xbb\xbf", raw)
                self.assertIn(b"\r\n", raw)
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
                self.assertTrue(all(byte < 128 for byte in raw))

    def test_local_doubao_dev_launcher_stays_local(self):
        script = read_text("dev_run_local_doubao_group.bat")

        self.assertIn("scripts\\dev_local_doubao_runner.py", script)
        self.assertIn("%*", script)
        self.assertNotIn("local_crawl_worker.py", script)
        self.assertNotIn("run_with_operator_log.ps1", script)
        self.assertNotIn("GEO_WORKER_BASE_URL", script)
        self.assertNotIn("18080", script)

    def test_engineering_rules_document_runtime_entry_script_policy(self):
        rules = read_text(os.path.join("docs", "engineering-rules.md"))

        self.assertIn("Runtime entry scripts", rules)
        self.assertIn("ASCII", rules)
        self.assertIn("CRLF", rules)
        self.assertIn("no UTF-8 BOM", rules)
        self.assertIn("Do not move frontend Chinese copy or content-generation prompts to English", rules)

    def test_gitattributes_keeps_batch_files_cmd_safe(self):
        attrs = read_text(".gitattributes")

        self.assertIn("*.bat text eol=crlf", attrs)
        self.assertIn("*.cmd text eol=crlf", attrs)
        self.assertIn("*.command text eol=lf", attrs)

    def test_windows_operator_setup_checks_and_installs_prerequisites(self):
        script = read_text("setup_operator_windows.bat")
        setup = read_text(os.path.join("scripts", "setup_operator_windows.ps1"))

        self.assertIn("scripts\\run_with_operator_log.ps1", script)
        self.assertIn("-Name setup", script)
        self.assertIn("--logged", script)
        self.assertIn("scripts\\setup_operator_windows.ps1", script)
        self.assertIn("Test-Command", setup)
        self.assertIn("Install-WingetPackage", setup)
        self.assertIn("Python.Python.3.12", setup)
        self.assertIn("OpenJS.NodeJS.LTS", setup)
        self.assertIn("resolve_node_crawler_root.ps1", setup)
        self.assertIn("playwright", setup)
        self.assertIn("chromium", setup)
        self.assertIn("Checking packaged Node dependencies", setup)
        self.assertIn("Checking packaged Playwright Chromium", setup)
        self.assertIn("node_modules\\playwright", setup)
        self.assertIn("ms-playwright", setup)
        self.assertIn("chrome-win64\\chrome.exe", setup)
        self.assertIn("Operator package is incomplete", setup)
        self.assertNotIn('Invoke-CheckedCommand "npm"', setup)
        self.assertNotIn('Invoke-CheckedCommand "npx"', setup)
        self.assertIn("start_local_crawl_worker.bat", setup)
        self.assertIn("scripts\\first_login_all_platforms.bat", setup)
        self.assertIn('call "%~dp0scripts\\first_login_all_platforms.bat" --no-pause', script)
        self.assertIn("Next: run start_local_crawl_worker.bat", script)

    def test_operator_entry_scripts_write_logs_and_export_diagnostics(self):
        setup = read_text("setup_operator_windows.bat")
        worker = read_text("start_local_crawl_worker.bat")
        stopper = read_text("stop_local_crawl_worker.bat")
        logger = read_text(os.path.join("scripts", "run_with_operator_log.ps1"))
        exporter = read_text(os.path.join("scripts", "export_operator_diagnostics.ps1"))
        export_bat = read_text("export_operator_diagnostics.bat")
        chinese_export_bat = read_text("导出诊断日志.bat")

        for script, name in [
            (setup, "setup"),
            (worker, "worker"),
            (stopper, "stop-worker"),
        ]:
            with self.subTest(name=name):
                self.assertIn("scripts\\run_with_operator_log.ps1", script)
                self.assertIn(f"-Name {name}", script)
                self.assertIn("--logged", script)

        self.assertIn("operator_logs", logger)
        self.assertIn("GEO_OPERATOR_LOG_RETENTION_DAYS", logger)
        self.assertIn("14", logger)
        self.assertIn("AddDays(-$RetentionDays)", logger)
        self.assertIn("Remove-Item", logger)
        self.assertIn("Please send this log file", logger)

        self.assertIn("operator_logs", exporter)
        self.assertIn("GEO-diagnostic-", exporter)
        self.assertIn("Compress-Archive", exporter)
        self.assertIn("python --version", exporter)
        self.assertIn("node --version", exporter)
        self.assertIn("npm --version", exporter)
        self.assertIn("node_modules\\playwright", exporter)
        self.assertIn("ms-playwright", exporter)
        self.assertIn("chrome-win64\\chrome.exe", exporter)
        self.assertNotIn("storage\\state.json", exporter)

        self.assertIn("scripts\\export_operator_diagnostics.ps1", export_bat)
        self.assertIn("export_operator_diagnostics.bat", chinese_export_bat)

    def test_operator_manual_covers_fresh_windows_setup_and_recovery(self):
        manual = read_text("运营使用说明.md")

        self.assertIn("setup_operator_windows.bat", manual)
        self.assertIn("导出诊断日志.bat", manual)
        self.assertIn("operator_logs", manual)
        self.assertIn("启动本地爬虫worker.bat", manual)
        self.assertIn("停止本地爬虫worker.bat", manual)
        self.assertIn("云端页面", manual)
        self.assertIn("取消", manual)
        self.assertIn("补爬", manual)
        self.assertIn("Mac", manual)
        self.assertIn("GEO-operator-worker-macos-arm64", manual)
        self.assertIn("setup_operator_mac.command", manual)
        self.assertIn("start_local_crawl_worker.command", manual)
        self.assertIn("stop_local_crawl_worker.command", manual)
        self.assertNotIn("Mac 暂时不要跑本地 worker", manual)

    def test_run_dev_is_the_single_foreground_start_entry(self):
        script = read_text("run_dev.bat")

        self.assertIn('set "GEO_HOST=127.0.0.1"', script)
        self.assertIn('set "GEO_PORT=5000"', script)
        self.assertIn("%PYTHON% -u app.py", script)
        self.assertNotIn("pip install", script)
        self.assertNotIn("playwright install", script)

    def test_local_chinese_launcher_is_removed_but_lan_demo_remains(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "启动.bat")))

        lan = read_text("启动局域网.bat")

        self.assertIn('set "GEO_HOST=0.0.0.0"', lan)
        self.assertIn('call "%~dp0run_dev.bat"', lan)
        self.assertNotIn("%PYTHON% app.py", lan)

    def test_docs_point_to_run_dev_and_current_test_count(self):
        readme = read_text("README.md")
        engineering = read_text("工程化说明.md")

        self.assertIn(".\\run_dev.bat", readme)
        self.assertIn(".\\run_dev.bat", engineering)
        self.assertNotIn("启动.bat", readme)
        self.assertNotIn("启动.bat", engineering)
        self.assertIn(".\\run_tests.bat", engineering)
        self.assertNotIn("80 tests OK", engineering)
        self.assertNotIn("96 tests OK", engineering)

    def test_direct_app_start_defaults_to_localhost(self):
        app_py = read_text("app.py")

        self.assertIn('os.environ.get("GEO_HOST", "127.0.0.1")', app_py)

    def test_restart_entry_explicitly_starts_lan_service(self):
        restart = read_text("restart.bat")
        start_server = read_text(os.path.join("scripts", "start_server.ps1"))

        self.assertIn('set "GEO_HOST=0.0.0.0"', restart)
        self.assertIn('set "GEO_PORT=5000"', restart)
        self.assertIn("$env:GEO_PORT", start_server)
        self.assertIn("$env:GEO_HOST", start_server)
        self.assertIn("function Get-LanIps", start_server)
        self.assertIn("198\\.(18|19)\\.", start_server)
        self.assertIn("vEthernet|Virtual|VMware|VirtualBox|Loopback|Bluetooth|Tailscale|ZeroTier|Clash|Sakura|VPN|Wintun|TAP|Hyper-V|Docker|WSL", start_server)

    def test_local_worker_launcher_runs_preflight_check(self):
        script = read_text("start_local_crawl_worker.bat")
        with open(os.path.join(ROOT, "start_local_crawl_worker.bat"), "rb") as f:
            raw_script = f.read()
        chinese_launcher = read_text("启动本地爬虫worker.bat")

        self.assertIn("GEO_NODE_CRAWLER_ROOT", script)
        self.assertIn("STORAGE_STATE_PATH", script)
        self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", script)
        self.assertIn("scripts\\resolve_node_crawler_root.ps1", script)
        self.assertIn("scripts\\local_crawl_worker.py", script)
        self.assertIn("--check", script)
        self.assertIn("--auth-mode none", script)
        self.assertIn("--platforms \"%GEO_WORKER_PLATFORMS%\"", script)
        self.assertIn('set "GEO_WORKER_PLATFORMS=all"', script)
        self.assertNotIn("GEO_NODE_CRAWLER_ROOT is not set", script)
        self.assertNotIn('if "%GEO_WORKER_PLATFORMS%"=="" set "GEO_WORKER_PLATFORMS=all"', script)
        self.assertIn(b"\r\n", raw_script)
        self.assertEqual(raw_script.count(b"\n"), raw_script.count(b"\r\n"))
        self.assertIn("start_local_crawl_worker.bat", chinese_launcher)
        self.assertNotIn("--auth-mode manual", script)
        self.assertNotIn("--auth-mode soft", script)

    def test_setup_uses_internal_first_login_without_operator_launcher(self):
        script = read_text(os.path.join("scripts", "first_login_all_platforms.bat"))

        self.assertIn("GEO_NODE_CRAWLER_ROOT", script)
        self.assertIn("STORAGE_STATE_PATH", script)
        self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", script)
        self.assertIn("scripts\\resolve_node_crawler_root.ps1", script)
        self.assertIn("scripts\\local_crawl_worker.py", script)
        self.assertIn("--local-login-only", script)
        self.assertIn("--no-pause", script)
        self.assertIn("--platforms \"%GEO_WORKER_PLATFORMS%\"", script)
        self.assertIn('set "GEO_WORKER_PLATFORMS=all"', script)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "首次登录所有平台.bat")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "first_login_all_platforms.bat")))

    def test_local_worker_launcher_opens_control_panel(self):
        script = read_text("start_local_crawl_worker.bat")
        panel = read_text(os.path.join("scripts", "local_worker_control_panel.ps1"))

        self.assertIn("scripts\\local_worker_control_panel.ps1", script)
        self.assertLess(script.index("--check"), script.index("scripts\\local_worker_control_panel.ps1"))
        self.assertLess(script.index("scripts\\local_worker_control_panel.ps1"), script.rindex("scripts\\local_crawl_worker.py"))
        self.assertIn("System.Windows.Forms", panel)
        self.assertIn("Stop local crawler", panel)
        self.assertIn("stop_local_crawl_worker.ps1", panel)

    def test_mac_operator_launchers_use_shell_and_python_worker(self):
        setup = read_text("setup_operator_mac.command")
        worker = read_text("start_local_crawl_worker.command")
        stopper = read_text("stop_local_crawl_worker.command")
        first_login = read_text(os.path.join("scripts", "first_login_all_platforms_mac.command"))
        logger = read_text(os.path.join("scripts", "operator_log.sh"))

        for script, name in [
            (setup, "setup"),
            (worker, "worker"),
            (stopper, "stopper"),
            (first_login, "first-login"),
        ]:
            with self.subTest(name=name):
                self.assertTrue(script.startswith("#!/usr/bin/env bash\n"))
                self.assertIn("set -euo pipefail", script)
                self.assertNotIn("powershell", script.lower())
                self.assertNotIn(".ps1", script)

        self.assertIn("uname -m", setup)
        self.assertIn("arm64", setup)
        self.assertIn("node_modules/playwright/package.json", setup)
        self.assertIn("ms-playwright", setup)
        self.assertIn("chrome-mac/Chromium.app", setup)
        self.assertIn("scripts/first_login_all_platforms_mac.command", setup)
        self.assertIn("GEO_WORKER_BASE_URL", worker)
        self.assertIn("Cloud username:", worker)
        self.assertIn("Cloud password:", worker)
        self.assertIn("scripts/resolve_node_crawler_root.py", worker)
        self.assertIn("scripts/local_crawl_worker.py", worker)
        self.assertIn("--check", worker)
        self.assertIn("--auth-mode none", worker)
        self.assertNotIn("--auth-mode soft", worker)
        self.assertIn("--local-login-only", first_login)
        self.assertIn("pkill", stopper)
        self.assertIn("local_crawl_worker.py", stopper)
        self.assertIn("node_auth_preflight.mjs", stopper)
        self.assertIn("scripts/operator_log.sh", setup)
        self.assertIn("scripts/operator_log.sh", worker)
        self.assertIn("operator_logs", logger)
        self.assertIn("tee -a", logger)
        self.assertIn('find "$log_dir"', logger)

    def test_mac_operator_package_script_builds_complete_arm64_zip(self):
        script = read_text(os.path.join("scripts", "package_operator_mac.sh"))

        self.assertTrue(script.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", script)
        self.assertIn("uname -m", script)
        self.assertIn("arm64", script)
        self.assertIn("scripts/resolve_node_crawler_root.py", script)
        self.assertIn("npm install", script)
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", script)
        self.assertIn("npx playwright install chromium", script)
        self.assertIn("GEO-operator-worker-macos-arm64", script)
        self.assertIn("rsync", script)
        self.assertIn("--exclude .git", script)
        self.assertIn("--exclude data", script)
        self.assertIn("--exclude .venv", script)
        self.assertIn("chmod +x", script)
        self.assertIn("setup_operator_mac.command", script)
        self.assertIn("start_local_crawl_worker.command", script)
        self.assertIn("stop_local_crawl_worker.command", script)
        self.assertIn("zip -qry", script)

    def test_local_worker_launcher_always_prompts_credentials(self):
        script = read_text("start_local_crawl_worker.bat")

        self.assertIn('set "GEO_WORKER_USERNAME="', script)
        self.assertIn('set "GEO_WORKER_PASSWORD="', script)
        self.assertIn('set /p "GEO_WORKER_USERNAME=Cloud username: "', script)
        self.assertIn('set /p "GEO_WORKER_PASSWORD=Cloud password: "', script)
        self.assertLess(script.index('set /p "GEO_WORKER_USERNAME=Cloud username: "'), script.index("scripts\\run_with_operator_log.ps1"))
        self.assertLess(script.index('set /p "GEO_WORKER_PASSWORD=Cloud password: "'), script.index("scripts\\run_with_operator_log.ps1"))
        logged_branch = script[script.index(":Main"):]
        self.assertNotIn('set /p "GEO_WORKER_USERNAME=Cloud username: "', logged_branch)
        self.assertNotIn('set /p "GEO_WORKER_PASSWORD=Cloud password: "', logged_branch)
        self.assertNotIn('if "%GEO_WORKER_USERNAME%"=="" set /p', script)
        self.assertNotIn('if "%GEO_WORKER_PASSWORD%"=="" set /p', script)

    def test_local_worker_launcher_rediscovers_local_paths(self):
        script = read_text("start_local_crawl_worker.bat")
        resolver = read_text(os.path.join("scripts", "resolve_node_crawler_root.ps1"))

        self.assertIn("scripts\\resolve_node_crawler_root.ps1", script)
        self.assertIn('set "STORAGE_STATE_PATH=%GEO_NODE_CRAWLER_ROOT%\\storage\\state.json"', script)
        self.assertNotIn('set "PLAYWRIGHT_BROWSERS_PATH=%GEO_NODE_CRAWLER_ROOT%\\ms-playwright"', script)
        self.assertIn("$env:GEO_NODE_CRAWLER_ROOT", resolver)
        self.assertIn("src\\adapters\\index.js", resolver)
        self.assertIn("ai-search-crawler*", resolver)
        self.assertIn("Test-CrawlerRoot", resolver)

    def test_crawler_resolver_prefers_packaged_sibling_over_stale_env(self):
        if not shutil.which("powershell"):
            self.skipTest("PowerShell is required for resolver integration test")

        with tempfile.TemporaryDirectory() as tmp:
            package_root = os.path.join(tmp, "operator-package")
            project_root = os.path.join(package_root, "geo_v2-pro")
            scripts_dir = os.path.join(project_root, "scripts")
            packaged_crawler = os.path.join(package_root, "ai-search-crawler")
            stale_crawler = os.path.join(tmp, "old", "ai-search-crawler")

            os.makedirs(scripts_dir)
            for crawler_root in (packaged_crawler, stale_crawler):
                os.makedirs(os.path.join(crawler_root, "src", "adapters"))
                with open(os.path.join(crawler_root, "src", "adapters", "index.js"), "w", encoding="utf-8") as f:
                    f.write("export function getAdapter() {}\n")

            shutil.copyfile(
                os.path.join(ROOT, "scripts", "resolve_node_crawler_root.ps1"),
                os.path.join(scripts_dir, "resolve_node_crawler_root.ps1"),
            )

            env = os.environ.copy()
            env["GEO_NODE_CRAWLER_ROOT"] = stale_crawler
            output = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    os.path.join(scripts_dir, "resolve_node_crawler_root.ps1"),
                ],
                text=True,
                env=env,
            ).strip()

            self.assertEqual(os.path.normcase(output), os.path.normcase(packaged_crawler))

    def test_python_crawler_resolver_prefers_packaged_sibling_over_stale_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = os.path.join(tmp, "operator-package")
            project_root = os.path.join(package_root, "geo_v2-pro")
            scripts_dir = os.path.join(project_root, "scripts")
            packaged_crawler = os.path.join(package_root, "ai-search-crawler")
            stale_crawler = os.path.join(tmp, "old", "ai-search-crawler")

            os.makedirs(scripts_dir)
            for crawler_root in (packaged_crawler, stale_crawler):
                os.makedirs(os.path.join(crawler_root, "src", "adapters"))
                with open(os.path.join(crawler_root, "src", "adapters", "index.js"), "w", encoding="utf-8") as f:
                    f.write("export function getAdapter() {}\n")

            shutil.copyfile(
                os.path.join(ROOT, "scripts", "resolve_node_crawler_root.py"),
                os.path.join(scripts_dir, "resolve_node_crawler_root.py"),
            )

            env = os.environ.copy()
            env["GEO_NODE_CRAWLER_ROOT"] = stale_crawler
            output = subprocess.check_output(
                [
                    os.sys.executable,
                    os.path.join(scripts_dir, "resolve_node_crawler_root.py"),
                ],
                text=True,
                env=env,
            ).strip()

            self.assertEqual(os.path.normcase(output), os.path.normcase(packaged_crawler))

    def test_local_worker_stop_launcher_targets_only_crawler_processes(self):
        script = read_text("stop_local_crawl_worker.bat")
        stopper = read_text(os.path.join("scripts", "stop_local_crawl_worker.ps1"))

        self.assertIn("scripts\\stop_local_crawl_worker.ps1", script)
        self.assertNotIn("server.pid", script)
        self.assertNotIn(":5000", script)
        self.assertIn("Get-CimInstance Win32_Process", stopper)
        self.assertIn("Stop-Process", stopper)
        self.assertIn("local_crawl_worker\\.py", stopper)
        self.assertIn("node_auth_preflight\\.mjs", stopper)
        self.assertIn("ai-search-crawler.*src[\\\\/]index\\.js", stopper)


if __name__ == "__main__":
    unittest.main()
