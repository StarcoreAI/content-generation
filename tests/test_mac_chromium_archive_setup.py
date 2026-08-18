import os
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


class MacChromiumArchiveSetupTests(unittest.TestCase):
    def test_setup_extracts_and_validates_official_chromium_archive(self):
        path = os.path.join(ROOT, "setup_operator_mac.command")
        with open(path, "r", encoding="utf-8") as script_file:
            script = script_file.read()

        self.assertIn("install_packaged_chromium_archive", script)
        self.assertIn("chrome-mac-arm64.zip", script)
        self.assertIn("ditto -x -k", script)
        self.assertIn(".chrome-mac-arm64.extracting-$$", script)
        self.assertIn(
            "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            script,
        )
        self.assertLess(
            script.index("install_packaged_chromium_archive\nrepair_packaged_chromium"),
            script.index('if [[ ! -f "$GEO_NODE_CRAWLER_ROOT/package.json" ]]'),
        )

    def test_setup_preserves_valid_official_framework_symlinks(self):
        path = os.path.join(ROOT, "setup_operator_mac.command")
        with open(path, "r", encoding="utf-8") as script_file:
            script = script_file.read()

        self.assertIn('if [[ ! -L "$versions/Current" ]]', script)
        self.assertIn('if [[ ! -L "$framework/$name" ]]', script)


if __name__ == "__main__":
    unittest.main()
