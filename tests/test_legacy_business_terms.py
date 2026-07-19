from pathlib import Path
import unittest


def _zh(codepoints):
    return "".join(chr(int(item, 16)) for item in codepoints.split())


LEGACY_TERMS = [
    _zh("53e3 8154"),
    _zh("7259 79d1"),
    _zh("7259 9f7f"),
    _zh("6b63 7578"),
    _zh("79cd 690d 7259"),
    _zh("5154 535a 58eb"),
    _zh("5c0f 767d 5154"),
    "Rabbit " + "Den" + "tal",
    "ortho" + "dontics",
    "im" + "plant services",
]


def iter_repo_text_files():
    root = Path(__file__).resolve().parents[1]
    scan_dirs = ["docs", "services", "templates", "static", "tests"]
    skip_dirs = {"__pycache__"}
    suffixes = {".py", ".md", ".html", ".js", ".json", ".txt"}
    for folder in scan_dirs:
        for path in (root / folder).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part in skip_dirs for part in path.relative_to(root).parts):
                continue
            yield root, path


class LegacyBusinessTermsTests(unittest.TestCase):
    def test_legacy_business_terms_are_not_left_in_repo_text(self):
        hits = []
        for root, path in iter_repo_text_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for term in LEGACY_TERMS:
                if term in text:
                    hits.append(f"{path.relative_to(root)}: {term}")
        self.assertEqual(hits, [])
