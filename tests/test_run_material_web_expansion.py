import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class RunMaterialWebExpansionTests(unittest.TestCase):
    def test_complete_text_does_not_send_max_tokens(self):
        from scripts.run_material_web_expansion import complete_text

        captured = {}

        class FakeChoices:
            message = type("Message", (), {"content": "ok"})

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return type("Response", (), {"choices": [FakeChoices()]})

        client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": FakeCompletions()})()},
        )()

        self.assertEqual(complete_text(client, "model-a", "prompt-a"), "ok")
        self.assertNotIn("max_tokens", captured)
        self.assertEqual(captured["model"], "model-a")

    def test_stream_text_does_not_send_max_tokens(self):
        from scripts.run_material_web_expansion import stream_text

        captured = {}

        class Delta:
            content = "ok"

        class Choice:
            delta = Delta()

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return [type("Chunk", (), {"choices": [Choice()]})()]

        client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": FakeCompletions()})()},
        )()

        chunks = []
        text = stream_text(client, "model-a", "prompt-a", chunks.append)

        self.assertEqual(text, "ok")
        self.assertEqual(chunks, ["ok"])
        self.assertTrue(captured["stream"])
        self.assertNotIn("max_tokens", captured)

    def test_stream_text_skips_empty_choice_chunks(self):
        from scripts.run_material_web_expansion import stream_text

        class Delta:
            content = "正文"

        class Choice:
            delta = Delta()

        class FakeCompletions:
            def create(self, **_kwargs):
                return [
                    type("EmptyChunk", (), {"choices": []})(),
                    type("ContentChunk", (), {"choices": [Choice()]})(),
                ]

        client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": FakeCompletions()})()},
        )()

        chunks = []
        text = stream_text(client, "model-a", "prompt-a", chunks.append)

        self.assertEqual(text, "正文")
        self.assertEqual(chunks, ["正文"])

    def test_load_sources_requires_json_list(self):
        from scripts.run_material_web_expansion import load_sources

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text('[{"url":"https://example.com"}]', encoding="utf-8")

            self.assertEqual(load_sources(path), [{"url": "https://example.com"}])

            path.write_text('{"url":"https://example.com"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_sources(path)


if __name__ == "__main__":
    unittest.main()
