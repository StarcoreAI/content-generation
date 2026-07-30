import unittest


class BatchGenerationJobsTests(unittest.TestCase):
    def make_jobs(self, generate, prepare=None):
        from services.batch_generation import BatchGenerationJobs

        ids = iter(["job-1", "batch-1"])
        return BatchGenerationJobs(lambda: next(ids), lambda: "2026-07-21 10:00:00", generate, prepare)

    def test_runs_articles_serially_without_retired_template_arguments(self):
        calls = []

        def generate(_payload, **kwargs):
            calls.append(dict(kwargs))
            index = len(calls)
            return {
                "id": f"article-{index}",
                "title": f"标题{index}",
                "route_context": {"route_id": f"route-{index}"},
            }

        jobs = self.make_jobs(generate)
        job = jobs.create({"client_id": "client-1"}, 3, created_by="tester")
        finished = jobs.run(job["job_id"])

        self.assertEqual([{"batch_id": "batch-1", "created_by": "tester"}] * 3, calls)
        self.assertEqual("completed", finished["status"])
        self.assertEqual(["完成", "完成", "完成"], [item["status"] for item in finished["items"]])

    def test_failure_is_recorded_and_later_articles_continue(self):
        calls = []

        def generate(_payload, **_kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise ValueError("writer_failed")
            return {"id": f"article-{len(calls)}", "title": "正常", "provenance": {}}

        jobs = self.make_jobs(generate)
        job = jobs.create({"client_id": "client-1"}, 3)
        finished = jobs.run(job["job_id"])

        self.assertEqual(3, len(calls))
        self.assertEqual(["完成", "失败", "完成"], [item["status"] for item in finished["items"]])
        self.assertEqual("writer_failed", finished["items"][1]["error"])

    def test_cancel_stops_before_remaining_article(self):
        calls = []
        holder = {}

        def generate(_payload, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                holder["jobs"].cancel(holder["job_id"])
            return {"id": "article-1", "title": "正常", "provenance": {}}

        jobs = self.make_jobs(generate)
        job = jobs.create({"client_id": "client-1"}, 3)
        holder.update(jobs=jobs, job_id=job["job_id"])
        finished = jobs.run(job["job_id"])

        self.assertEqual(1, len(calls))
        self.assertEqual("cancelled", finished["status"])
        self.assertEqual(["完成", "排队", "排队"], [item["status"] for item in finished["items"]])

    def test_passes_one_batch_id_and_marks_blocked_articles(self):
        received_batch_ids = []

        def generate(_payload, **kwargs):
            received_batch_ids.append(kwargs["batch_id"])
            return {
                "id": "article-1",
                "title": "标题",
                "generation_status": "门禁拦截",
                "provenance": {},
            }

        jobs = self.make_jobs(generate)
        job = jobs.create({"client_id": "client-1"}, 1)
        finished = jobs.run(job["job_id"])

        self.assertEqual([job["batch_id"]], received_batch_ids)
        self.assertEqual("门禁拦截", finished["items"][0]["status"])
        self.assertEqual("article-1", finished["items"][0]["article_id"])

    def test_runs_preflight_once_without_lazy_choice_argument(self):
        prepared, received = [], []

        def prepare(payload):
            prepared.append(payload["client_id"])

        def generate(_payload, **kwargs):
            received.append(kwargs)
            return {"id": f"article-{len(received)}", "title": "正常", "provenance": {}}

        jobs = self.make_jobs(generate, prepare)
        job = jobs.create({"client_id": "client-1"}, 3)
        jobs.run(job["job_id"])

        self.assertEqual(["client-1"], prepared)
        self.assertEqual([{"batch_id": "batch-1", "created_by": ""}] * 3, received)


if __name__ == "__main__":
    unittest.main()
