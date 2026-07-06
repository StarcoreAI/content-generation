import os
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


def read_text(name):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
        return f.read()


class StartupScriptTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
