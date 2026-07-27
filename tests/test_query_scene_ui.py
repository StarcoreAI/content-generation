import unittest
from pathlib import Path


class QuerySceneUiTests(unittest.TestCase):
    def test_refresh_button_shows_running_label_until_request_finishes(self):
        script = (Path(__file__).resolve().parents[1] / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("const refreshButton = document.getElementById('btnRefreshQueryScenes');", script)
        self.assertIn("const originalLabel = refreshButton?.textContent || '';", script)
        self.assertIn("refreshButton.textContent = '正在提取场景词...'", script)
        self.assertIn("refreshButton.textContent = originalLabel", script)


if __name__ == "__main__":
    unittest.main()
