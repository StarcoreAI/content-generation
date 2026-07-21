import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dev_quality_gate_review", ROOT / "scripts" / "dev_quality_gate_review.py")


class DevQualityGateReviewTests(unittest.TestCase):
    def test_review_runner_selects_only_pass_articles_and_respects_limit(self):
        module = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(module)
        calls = []

        def review_fn(client_id, article_id):
            calls.append((client_id, article_id))
            return {"id": article_id, "verdict": "warn"}

        with tempfile.TemporaryDirectory() as tmp:
            result = module.run_quality_gate_review(
                "client-a",
                limit=2,
                list_fn=lambda _cid: [
                    {"id": "pass-1", "gate_report": {"verdict": "pass"}},
                    {"id": "blocked", "gate_report": {"verdict": "blocked"}},
                    {"id": "pass-2", "gate_report": {"verdict": "pass"}},
                    {"id": "pass-3", "gate_report": {"verdict": "pass"}},
                ],
                review_fn=review_fn,
                output_dir=tmp,
            )

        self.assertEqual(calls, [("client-a", "pass-1"), ("client-a", "pass-2")])
        self.assertEqual(result["reviewed"], 2)


if __name__ == "__main__":
    unittest.main()
