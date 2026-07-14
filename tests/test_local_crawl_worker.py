import tempfile
import threading
import unittest
import os
from unittest import mock
from pathlib import Path

from scripts import local_crawl_worker


class FakeCloudClient:
    def __init__(self, jobs, health_payload=None, canceled_jobs=None):
        self.jobs = list(jobs)
        self.submitted = []
        self.claims = []
        self.health_payload = health_payload or {"ok": True}
        self.canceled_jobs = set(canceled_jobs or [])

    def health(self):
        return self.health_payload

    def claim_next(self, worker_id, platform):
        self.claims.append((worker_id, platform))
        for index, job in enumerate(self.jobs):
            if job.get("platform") == platform:
                return self.jobs.pop(index)
        return None

    def is_job_canceled(self, job_id):
        return job_id in self.canceled_jobs

    def submit_result(self, job_id, payload):
        self.submitted.append((job_id, payload))
        return {"ok": True, "job": {"id": job_id, "status": payload["status"]}}


class StatusCheckFailingCloudClient(FakeCloudClient):
    def is_job_canceled(self, job_id):
        raise RuntimeError("status check failed")


class FlakySubmitCloudClient(FakeCloudClient):
    def __init__(self, jobs, failures_before_success=1):
        super().__init__(jobs)
        self.failures_before_success = failures_before_success
        self.submit_attempts = 0

    def submit_result(self, job_id, payload):
        self.submit_attempts += 1
        if self.submit_attempts <= self.failures_before_success:
            raise RuntimeError("temporary submit failure")
        return super().submit_result(job_id, payload)


class LocalCrawlWorkerTests(unittest.TestCase):
    def test_default_platforms_include_kimi_before_doubao(self):
        self.assertEqual(
            local_crawl_worker.parse_platforms("all"),
            ["deepseek", "yuanbao", "qwen", "kimi", "doubao"],
        )

    def test_default_worker_id_uses_hostname_when_computername_is_missing(self):
        with mock.patch.dict(os.environ, {"HOSTNAME": "ops-macbook"}, clear=True):
            args = local_crawl_worker.build_parser().parse_args([])

        self.assertEqual(args.worker_id, "ops-macbook")

    def test_expand_job_questions_repeats_each_question(self):
        job = {"questions": ["问题A", "问题B"], "repeat_count": 2}

        self.assertEqual(
            local_crawl_worker.expand_job_questions(job),
            ["问题A", "问题A", "问题B", "问题B"],
        )

    def test_run_once_claims_platform_runs_node_and_submits_result(self):
        cloud = FakeCloudClient([
            {
                "id": "job-1",
                "platform": "qwen",
                "questions": ["问题A"],
                "repeat_count": 2,
            }
        ])
        calls = []

        def fake_run_node_crawler(platform, questions, **kwargs):
            calls.append({"platform": platform, "questions": questions, "kwargs": kwargs})
            return {
                "ok": True,
                "total": len(questions),
                "success": len(questions),
                "results": [
                    {"ok": True, "question": question, "answer": "回答", "refs": []}
                    for question in questions
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            worked = local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["qwen"],
                run_crawler=fake_run_node_crawler,
                output_root=Path(tmp),
            )

        self.assertTrue(worked)
        self.assertEqual(cloud.claims, [("ops-laptop", "qwen")])
        self.assertEqual(calls[0]["platform"], "qwen")
        self.assertEqual(calls[0]["questions"], ["问题A", "问题A"])
        self.assertTrue(str(calls[0]["kwargs"]["output_dir"]).endswith(str(Path("job-1") / "qwen")))
        self.assertEqual(cloud.submitted[0][0], "job-1")
        self.assertEqual(cloud.submitted[0][1]["status"], "completed")
        self.assertEqual(cloud.submitted[0][1]["summary"], {"total": 2, "success": 2})

    def test_run_once_logs_claimed_job_scope_before_crawling(self):
        cloud = FakeCloudClient([
            {
                "id": "job-1",
                "platform": "doubao",
                "client_id": "client-1",
                "brand": "测试品牌",
                "group_id": "group-1",
                "batch_id": "batch-1",
                "questions": ["问题A"],
                "repeat_count": 1,
            }
        ])
        messages = []

        def fake_run_node_crawler(platform, questions, **kwargs):
            return {
                "ok": True,
                "total": 1,
                "success": 1,
                "results": [{"ok": True, "question": "问题A", "answer": "回答", "refs": []}],
            }

        with mock.patch.object(local_crawl_worker, "log", side_effect=messages.append), \
                tempfile.TemporaryDirectory() as tmp:
            local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["doubao"],
                run_crawler=fake_run_node_crawler,
                output_root=Path(tmp),
            )

        claimed_logs = [message for message in messages if message.startswith("claimed job:")]
        self.assertEqual(len(claimed_logs), 1)
        self.assertIn("client=client-1", claimed_logs[0])
        self.assertIn("brand=测试品牌", claimed_logs[0])
        self.assertIn("group=group-1", claimed_logs[0])
        self.assertIn("batch=batch-1", claimed_logs[0])

    def test_check_environment_reports_cloud_node_root_and_storage_state(self):
        cloud = FakeCloudClient([], health_payload={"ok": True, "version": "2.3"})
        with tempfile.TemporaryDirectory() as tmp:
            node_root = Path(tmp) / "node-crawler"
            storage_state = Path(tmp) / "storage" / "state.json"
            node_root.mkdir()
            storage_state.parent.mkdir()
            storage_state.write_text("{}", encoding="utf-8")

            result = local_crawl_worker.check_environment(
                cloud,
                platforms=["kimi"],
                node_root=node_root,
                storage_state_path=storage_state,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [(item["name"], item["ok"]) for item in result["checks"]],
            [
                ("cloud", True),
                ("node_root", True),
                ("storage_state", True),
                ("platforms", True),
            ],
        )

    def test_check_environment_allows_first_run_before_storage_state_exists(self):
        cloud = FakeCloudClient([], health_payload={"ok": True, "version": "2.3"})
        with tempfile.TemporaryDirectory() as tmp:
            node_root = Path(tmp) / "node-crawler"
            storage_state = Path(tmp) / "storage" / "state.json"
            node_root.mkdir()

            result = local_crawl_worker.check_environment(
                cloud,
                platforms=["doubao"],
                node_root=node_root,
                storage_state_path=storage_state,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["checks"][2]["name"], "storage_state")
        self.assertTrue(result["checks"][2]["ok"])

    def test_main_check_runs_soft_auth_preflight_after_basic_checks(self):
        with mock.patch.object(local_crawl_worker, "build_cloud_client", return_value=FakeCloudClient([])), \
                mock.patch.object(local_crawl_worker, "check_environment") as check_environment, \
                mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            check_environment.return_value = {"ok": True, "checks": []}
            run_auth.return_value = {"ok": True, "message": "ready"}

            code = local_crawl_worker.main(["--check", "--platforms", "all"])

        self.assertEqual(code, 0)
        check_environment.assert_called_once()
        run_auth.assert_called_once()
        self.assertEqual(run_auth.call_args.args[0], ["deepseek", "yuanbao", "qwen", "kimi", "doubao"])
        self.assertEqual(run_auth.call_args.kwargs["mode"], "soft")

    def test_main_check_can_run_manual_login_preflight(self):
        with mock.patch.object(local_crawl_worker, "build_cloud_client", return_value=FakeCloudClient([])), \
                mock.patch.object(local_crawl_worker, "check_environment") as check_environment, \
                mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            check_environment.return_value = {"ok": True, "checks": []}
            run_auth.return_value = {"ok": True, "message": "ready"}

            code = local_crawl_worker.main(["--check", "--platforms", "all", "--auth-mode", "manual"])

        self.assertEqual(code, 0)
        run_auth.assert_called_once()
        self.assertEqual(run_auth.call_args.kwargs["mode"], "manual")

    def test_main_check_soft_auth_failure_blocks_startup(self):
        with mock.patch.object(local_crawl_worker, "build_cloud_client", return_value=FakeCloudClient([])), \
                mock.patch.object(local_crawl_worker, "check_environment") as check_environment, \
                mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            check_environment.return_value = {"ok": True, "checks": []}
            run_auth.return_value = {"ok": False, "message": "login not confirmed"}

            code = local_crawl_worker.main(["--check", "--platforms", "qwen"])

        self.assertEqual(code, 1)
        self.assertEqual(run_auth.call_args.kwargs["mode"], "soft")

    def test_main_local_login_only_runs_manual_auth_without_cloud(self):
        with mock.patch.object(local_crawl_worker, "build_cloud_client") as build_cloud_client, \
                mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            build_cloud_client.side_effect = AssertionError("cloud should not be used for local login setup")
            run_auth.return_value = {"ok": True, "message": "ready"}

            code = local_crawl_worker.main(["--local-login-only", "--platforms", "qwen"])

        self.assertEqual(code, 0)
        run_auth.assert_called_once_with(["qwen"], timeout_s=1800, mode="manual")

    def test_main_check_does_not_start_auth_preflight_when_basic_check_fails(self):
        with mock.patch.object(local_crawl_worker, "build_cloud_client", return_value=FakeCloudClient([])), \
                mock.patch.object(local_crawl_worker, "check_environment") as check_environment, \
                mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            check_environment.return_value = {"ok": False, "checks": [{"name": "cloud", "ok": False, "message": "down"}]}

            code = local_crawl_worker.main(["--check", "--platforms", "all"])

        self.assertEqual(code, 1)
        run_auth.assert_not_called()

    def test_run_once_skips_submit_when_job_was_canceled_after_crawl(self):
        cloud = FakeCloudClient(
            [{"id": "job-1", "platform": "qwen", "questions": ["问题A"], "repeat_count": 1}],
            canceled_jobs={"job-1"},
        )
        calls = []

        def fake_run_node_crawler(platform, questions, **kwargs):
            calls.append((platform, questions))
            return {
                "ok": True,
                "total": 1,
                "success": 1,
                "results": [{"ok": True, "question": "问题A", "answer": "回答", "refs": []}],
            }

        with tempfile.TemporaryDirectory() as tmp:
            worked = local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["qwen"],
                run_crawler=fake_run_node_crawler,
                output_root=Path(tmp),
            )

        self.assertTrue(worked)
        self.assertEqual(len(calls), 1)
        self.assertEqual(cloud.submitted, [])

    def test_run_once_still_submits_when_cancel_status_check_fails(self):
        cloud = StatusCheckFailingCloudClient([
            {"id": "job-1", "platform": "qwen", "questions": ["问题A"], "repeat_count": 1}
        ])

        def fake_run_node_crawler(platform, questions, **kwargs):
            return {
                "ok": True,
                "total": 1,
                "success": 1,
                "results": [{"ok": True, "question": "问题A", "answer": "回答", "refs": []}],
            }

        with tempfile.TemporaryDirectory() as tmp:
            worked = local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["qwen"],
                run_crawler=fake_run_node_crawler,
                output_root=Path(tmp),
            )

        self.assertTrue(worked)
        self.assertEqual(len(cloud.submitted), 1)
        self.assertEqual(cloud.submitted[0][1]["status"], "completed")

    def test_run_once_retries_submit_result(self):
        cloud = FlakySubmitCloudClient([
            {"id": "job-1", "platform": "qwen", "questions": ["问题A"], "repeat_count": 1}
        ])

        def fake_run_node_crawler(platform, questions, **kwargs):
            return {
                "ok": True,
                "total": 1,
                "success": 1,
                "results": [{"ok": True, "question": "问题A", "answer": "回答", "refs": []}],
            }

        with tempfile.TemporaryDirectory() as tmp:
            worked = local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["qwen"],
                run_crawler=fake_run_node_crawler,
                output_root=Path(tmp),
            )

        self.assertTrue(worked)
        self.assertEqual(cloud.submit_attempts, 2)
        self.assertEqual(len(cloud.submitted), 1)

    def test_run_job_returns_failed_payload_when_crawler_raises(self):
        def failing_crawler(*_args, **_kwargs):
            raise RuntimeError("need_login: login action detected")

        with tempfile.TemporaryDirectory() as tmp:
            payload = local_crawl_worker.run_job(
                {"id": "job-1", "platform": "qwen", "questions": ["问题A"]},
                run_crawler=failing_crawler,
                output_root=Path(tmp),
            )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("need_login", payload["error"])
        self.assertEqual(payload["summary"], {"total": 1, "success": 0})

    def test_run_once_handles_login_job_with_manual_auth_preflight(self):
        cloud = FakeCloudClient([
            {
                "id": "login-qwen",
                "job_type": "login",
                "platform": "qwen",
                "questions": [],
            }
        ])

        with mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth, \
                tempfile.TemporaryDirectory() as tmp:
            run_auth.return_value = {"ok": True, "message": "ready"}
            worked = local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["qwen"],
                run_crawler=mock.Mock(side_effect=AssertionError("crawler should not run for login jobs")),
                output_root=Path(tmp),
            )

        self.assertTrue(worked)
        run_auth.assert_called_once_with(["qwen"], timeout_s=1800, mode="manual")
        self.assertEqual(cloud.submitted[0][0], "login-qwen")
        self.assertEqual(cloud.submitted[0][1]["status"], "completed")
        self.assertEqual(cloud.submitted[0][1]["summary"], {"total": 1, "success": 1})

    def test_run_once_parallel_starts_different_platforms_together(self):
        qwen_started = threading.Event()
        deepseek_started = threading.Event()
        cloud = FakeCloudClient([
            {"id": "job-qwen", "platform": "qwen", "questions": ["问题A"], "repeat_count": 1},
            {"id": "job-deepseek", "platform": "deepseek", "questions": ["问题B"], "repeat_count": 1},
        ])

        def fake_run_node_crawler(platform, questions, **kwargs):
            if platform == "qwen":
                qwen_started.set()
                self.assertTrue(deepseek_started.wait(1))
            if platform == "deepseek":
                deepseek_started.set()
            return {
                "ok": True,
                "total": len(questions),
                "success": len(questions),
                "results": [{"ok": True, "question": questions[0], "answer": "回答", "refs": []}],
            }

        with tempfile.TemporaryDirectory() as tmp:
            worked = local_crawl_worker.run_once_parallel(
                lambda: cloud,
                worker_id="ops-laptop",
                platforms=["qwen", "deepseek"],
                run_crawler=fake_run_node_crawler,
                output_root=Path(tmp),
            )

        self.assertTrue(worked)
        self.assertTrue(qwen_started.is_set())
        self.assertTrue(deepseek_started.is_set())
        self.assertEqual(len(cloud.submitted), 2)


if __name__ == "__main__":
    unittest.main()
