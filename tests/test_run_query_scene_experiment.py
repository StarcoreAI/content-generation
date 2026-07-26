import unittest


class QuerySceneExperimentTests(unittest.TestCase):
    def test_uses_latest_capture_date_and_forces_dry_run(self):
        from scripts.run_query_scene_experiment import run_experiment

        class Service:
            def __init__(self):
                self.calls = []

            def refresh_query_scenes(self, client_id, groups, records, ask_json, dry_run=False):
                self.calls.append((client_id, groups, records, ask_json, dry_run))
                return {"rows": [{"query": "问题一", "scene_terms": ["场景词"]}], "updated": 1, "dry_run": dry_run}

        service = Service()
        groups = [{"id": "g1", "questions": ["问题一"]}]
        records = [
            {"today": "2026-07-24", "group_id": "g1", "question": "旧问题"},
            {"today": "2026-07-26", "group_id": "g1", "question": "问题一"},
        ]

        result = run_experiment("client-1", groups, records, service, lambda *_args: {}, date_str="")

        self.assertEqual(result["source_date"], "2026-07-26")
        self.assertEqual(service.calls[0][0], "client-1")
        self.assertEqual([item["today"] for item in service.calls[0][2]], ["2026-07-26"])
        self.assertTrue(service.calls[0][4])
        self.assertTrue(result["dry_run"])


if __name__ == "__main__":
    unittest.main()
