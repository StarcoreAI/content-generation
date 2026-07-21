import json
import tempfile
import unittest
from pathlib import Path

from scripts.dev_content_generate import run_content_generate


class DevContentGenerateTests(unittest.TestCase):
    def test_runner_passes_options_exports_shared_result_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def execute(payload, audience_angles=None):
                calls.append((payload, audience_angles))
                if len(calls) == 2:
                    raise ValueError("writer_failed")
                return {
                    "id": "article-1",
                    "content": "文章全文",
                    "brief": {"sections": [{"id": 1}]},
                    "provenance": {"faq_questions": ["问题一"]},
                    "sampling": {"faq_questions": ["问题一"], "skeleton": {"id": "sk-1"}},
                }

            result = run_content_generate(
                client_id="client-1",
                parent_type="对比型",
                count=2,
                date="2026-07-20",
                data_dir=Path(tmp) / "data",
                angles=["异地在职者", "首次报考者"],
                include_injection=False,
                include_web_supplement=False,
                include_content_uploads=False,
                include_competitors=False,
                execute_fn=execute,
            )

            exported = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["generated"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(calls[0][1], ["异地在职者", "首次报考者"])
            self.assertFalse(calls[0][0]["use_material_package"])
            self.assertFalse(calls[0][0]["use_material_web_supplement"])
            self.assertFalse(calls[0][0]["use_content_uploads"])
            self.assertFalse(calls[0][0]["use_competitors"])
            self.assertNotIn("opinion", calls[0][0])
            self.assertNotIn("faq_questions", calls[0][0])
            self.assertNotIn("article_subtype", calls[0][0])
            self.assertEqual(exported["items"][0]["sampling"]["faq_questions"], ["问题一"])
            self.assertEqual(exported["items"][0]["article"]["id"], "article-1")
            self.assertEqual(exported["failures"], [{"index": 2, "error": "writer_failed"}])

    def test_runner_appends_to_existing_same_day_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            output = data_dir / "briefs" / "client-1" / "2026-07-20" / "generated_articles.json"
            output.parent.mkdir(parents=True)
            output.write_text(json.dumps({"items": [{"article": {"id": "earlier"}}], "failures": []}), encoding="utf-8")

            run_content_generate(
                client_id="client-1",
                parent_type="介绍型",
                date="2026-07-20",
                data_dir=data_dir,
                execute_fn=lambda *_args, **_kwargs: {
                    "id": "later", "brief": {}, "provenance": {}, "sampling": {},
                },
            )

            exported = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([item["article"]["id"] for item in exported["items"]], ["earlier", "later"])


if __name__ == "__main__":
    unittest.main()
