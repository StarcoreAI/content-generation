import tempfile
import threading
import unittest
import os
from unittest import mock
from pathlib import Path

from scripts import local_crawl_worker
from services.node_crawler_bridge import NodeCrawlerStopped


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


class ProgressCloudClient(FakeCloudClient):
    def __init__(self, jobs):
        super().__init__(jobs)
        self.progress_updates = []

    def update_progress(self, job_id, payload):
        self.progress_updates.append((job_id, payload))
        return {"ok": True}


class CancelOnProgressCloudClient(FakeCloudClient):
    def __init__(self, jobs):
        super().__init__(jobs, canceled_jobs={job["id"] for job in jobs})

    def update_progress(self, job_id, payload):
        return {"ok": True, "job": {"id": job_id, "status": "canceled"}}


class StatusCheckFailingCloudClient(FakeCloudClient):
    def is_job_canceled(self, job_id):
        raise RuntimeError("status check failed")


class ExpiredAfterCrawlCloudClient(FakeCloudClient):
    def get_job_status(self, job_id):
        return "expired"


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
    def test_cancel_check_requests_only_the_target_job(self):
        client = local_crawl_worker.CloudClient("http://worker.example")
        client.request_json = mock.Mock(return_value={
            "jobs": [{"id": "job/1", "status": "canceled"}]
        })

        self.assertTrue(client.is_job_canceled("job/1"))
        client.request_json.assert_called_once_with(
            "GET",
            "/api/crawl_jobs?job_id=job%2F1",
        )

    def test_progress_update_targets_only_the_claimed_job(self):
        client = local_crawl_worker.CloudClient("http://worker.example")
        client.request_json = mock.Mock(return_value={"ok": True})

        client.update_progress("job/1", {"completed": 2, "total": 5})

        client.request_json.assert_called_once_with(
            "POST",
            "/api/crawl_jobs/job/1/progress",
            {"completed": 2, "total": 5},
        )

    def test_job_status_returns_server_status(self):
        client = local_crawl_worker.CloudClient("http://worker.example")
        client.request_json = mock.Mock(return_value={
            "jobs": [{"id": "job/1", "status": "expired"}]
        })

        self.assertEqual(client.get_job_status("job/1"), "expired")

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

    def test_run_job_passes_default_node_concurrency(self):
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
            payload = local_crawl_worker.run_job(
                {
                    "id": "job-1",
                    "platform": "qwen",
                    "questions": ["问题A", "问题B"],
                    "repeat_count": 1,
                },
                run_crawler=fake_run_node_crawler,
                output_root=Path(tmp),
            )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(calls[0]["kwargs"]["concurrency"], 2)

    def test_login_recovery_error_includes_account_verification_markers(self):
        messages = [
            "verification_required",
            "captcha challenge",
            "security check required",
            "\u8d26\u53f7\u5f02\u5e38",
            "\u8bbf\u95ee\u5f02\u5e38",
            "\u98ce\u9669\u9a8c\u8bc1",
            "\u4eba\u673a\u9a8c\u8bc1",
        ]

        for message in messages:
            with self.subTest(message=message):
                self.assertTrue(local_crawl_worker.is_login_recovery_error(message))

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
        run_auth.assert_called_once_with(
            ["qwen"],
            timeout_s=1800,
            mode="manual",
            storage_state_path=str(local_crawl_worker.ROOT / "data" / "qwen_state.json"),
        )

    def test_main_local_login_only_saves_each_platform_state_used_by_crawler(self):
        with mock.patch.object(local_crawl_worker, "build_cloud_client") as build_cloud_client, \
                mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            build_cloud_client.side_effect = AssertionError("cloud should not be used for local login setup")
            run_auth.return_value = {"ok": True, "message": "ready"}

            code = local_crawl_worker.main(["--local-login-only", "--platforms", "deepseek,yuanbao"])

        self.assertEqual(code, 0)
        self.assertEqual(run_auth.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in run_auth.call_args_list],
            [["deepseek"], ["yuanbao"]],
        )
        self.assertEqual(
            [call.kwargs["storage_state_path"] for call in run_auth.call_args_list],
            [
                str(local_crawl_worker.ROOT / "data" / "deepseek_state.json"),
                str(local_crawl_worker.ROOT / "data" / "yuanbao_state.json"),
            ],
        )

    def test_main_local_login_only_attempts_remaining_platforms_after_one_fails(self):
        with mock.patch.object(local_crawl_worker, "build_cloud_client") as build_cloud_client, \
                mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            build_cloud_client.side_effect = AssertionError("cloud should not be used for local login setup")
            run_auth.side_effect = [
                {"ok": False, "message": "deepseek login not confirmed"},
                {"ok": True, "message": "yuanbao ready"},
            ]

            code = local_crawl_worker.main(
                ["--local-login-only", "--platforms", "deepseek,yuanbao"]
            )

        self.assertEqual(code, 1)
        self.assertEqual(
            [call.args[0] for call in run_auth.call_args_list],
            [["deepseek"], ["yuanbao"]],
        )

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

    def test_run_once_skips_submit_when_job_expired_after_crawl(self):
        cloud = ExpiredAfterCrawlCloudClient([
            {"id": "job-1", "platform": "qwen", "questions": ["问题A"], "repeat_count": 1}
        ])

        def fake_run_node_crawler(platform, questions, **kwargs):
            return {
                "ok": True,
                "total": 1,
                "success": 1,
                "results": [{"ok": True, "question": "问题A", "answer": "回答", "refs": []}],
            }

        worked = local_crawl_worker.run_once(
            cloud,
            worker_id="ops-laptop",
            platforms=["qwen"],
            run_crawler=fake_run_node_crawler,
        )

        self.assertTrue(worked)
        self.assertEqual(cloud.submitted, [])

    def test_run_once_stops_crawler_when_progress_reports_canceled_job(self):
        cloud = CancelOnProgressCloudClient([{
            "id": "job-1",
            "platform": "qwen",
            "questions": ["问题A"],
            "repeat_count": 1,
        }])

        def fake_run_node_crawler(platform, questions, **kwargs):
            reason = kwargs["progress_callback"]({
                "completed": 0,
                "total": 1,
                "message": "running",
            })
            self.assertEqual(reason, "server job status changed to canceled")
            raise NodeCrawlerStopped(reason)

        worked = local_crawl_worker.run_once(
            cloud,
            worker_id="ops-laptop",
            platforms=["qwen"],
            run_crawler=fake_run_node_crawler,
        )

        self.assertTrue(worked)
        self.assertEqual(cloud.submitted, [])

    def test_run_once_fails_and_releases_job_after_progress_stalls(self):
        cloud = ProgressCloudClient([{
            "id": "job-1",
            "platform": "qwen",
            "questions": ["问题A"],
            "repeat_count": 1,
        }])

        def fake_run_node_crawler(platform, questions, **kwargs):
            reason = kwargs["progress_callback"]({
                "completed": 0,
                "total": 1,
                "message": "running",
            })
            self.assertEqual(reason, "no completed question for 5 seconds")
            raise NodeCrawlerStopped(reason)

        with mock.patch.object(local_crawl_worker.time, "monotonic", side_effect=[100, 106]):
            worked = local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["qwen"],
                run_crawler=fake_run_node_crawler,
                stalled_timeout_s=5,
            )

        self.assertTrue(worked)
        self.assertEqual(len(cloud.submitted), 1)
        self.assertEqual(cloud.submitted[0][1]["status"], "failed")
        self.assertIn("no completed question for 5 seconds", cloud.submitted[0][1]["error"])

    def test_newly_completed_question_resets_stalled_timeout(self):
        cloud = ProgressCloudClient([{
            "id": "job-1",
            "platform": "qwen",
            "questions": ["问题A", "问题B"],
            "repeat_count": 1,
        }])

        def fake_run_node_crawler(platform, questions, **kwargs):
            first_reason = kwargs["progress_callback"]({"completed": 0, "total": 2})
            second_reason = kwargs["progress_callback"]({"completed": 1, "total": 2})
            third_reason = kwargs["progress_callback"]({"completed": 1, "total": 2})
            self.assertEqual([first_reason, second_reason, third_reason], ["", "", ""])
            return {
                "ok": True,
                "total": 2,
                "success": 2,
                "results": [{"ok": True}, {"ok": True}],
            }

        with mock.patch.object(
            local_crawl_worker.time,
            "monotonic",
            side_effect=[100, 104, 108, 112],
        ):
            worked = local_crawl_worker.run_once(
                cloud,
                worker_id="ops-laptop",
                platforms=["qwen"],
                run_crawler=fake_run_node_crawler,
                stalled_timeout_s=5,
            )

        self.assertTrue(worked)
        self.assertEqual(cloud.submitted[0][1]["status"], "completed")

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

    def test_run_job_returns_failed_payload_when_crawler_raises_non_login_error(self):
        def failing_crawler(*_args, **_kwargs):
            raise RuntimeError("network timeout")

        with tempfile.TemporaryDirectory() as tmp:
            payload = local_crawl_worker.run_job(
                {"id": "job-1", "platform": "qwen", "questions": ["问题A"]},
                run_crawler=failing_crawler,
                output_root=Path(tmp),
            )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("network timeout", payload["error"])
        self.assertEqual(payload["summary"], {"total": 1, "success": 0})

    def test_run_job_recovers_plain_login_failure_with_configured_concurrency(self):
        calls = []
        login_calls = []

        def flaky_crawler(platform, questions, **kwargs):
            calls.append({"platform": platform, "questions": questions, "kwargs": kwargs})
            if len(calls) == 1:
                raise RuntimeError("need_login: login action detected")
            return {
                "ok": True,
                "total": len(questions),
                "success": len(questions),
                "results": [
                    {"ok": True, "question": question, "answer": "回答", "refs": []}
                    for question in questions
                ],
            }

        def fake_login(job, timeout_s=1800):
            login_calls.append((job["platform"], timeout_s))
            return {"status": "completed", "summary": {"total": 1, "success": 1}}

        with tempfile.TemporaryDirectory() as tmp:
            payload = local_crawl_worker.run_job(
                {"id": "job-1", "platform": "qwen", "questions": ["问题A"]},
                run_crawler=flaky_crawler,
                run_login=fake_login,
                output_root=Path(tmp),
                timeout_s=77,
            )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["summary"], {"total": 1, "success": 1})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["kwargs"]["concurrency"], 2)
        self.assertEqual(calls[1]["kwargs"]["concurrency"], 2)
        self.assertEqual(login_calls, [("qwen", 77)])

    def test_run_once_reports_node_question_progress(self):
        cloud = ProgressCloudClient([{
            "id": "job-1",
            "platform": "qwen",
            "questions": ["问题A", "问题B"],
            "repeat_count": 1,
        }])

        def fake_run_node_crawler(platform, questions, **kwargs):
            kwargs["progress_callback"]({"completed": 1, "total": 2, "message": "running"})
            return {
                "ok": True,
                "total": 2,
                "success": 2,
                "results": [
                    {"ok": True, "question": question, "answer": "回答", "refs": []}
                    for question in questions
                ],
            }

        local_crawl_worker.run_once(
            cloud,
            worker_id="ops-laptop",
            platforms=["qwen"],
            run_crawler=fake_run_node_crawler,
        )

        self.assertEqual(cloud.progress_updates, [(
            "job-1",
            {"completed": 1, "total": 2, "message": "running"},
        )])

    def test_run_job_recovers_verification_failure_with_one_browser_retry(self):
        calls = []

        def flaky_crawler(platform, questions, **kwargs):
            calls.append({"platform": platform, "questions": questions, "kwargs": kwargs})
            if len(calls) == 1:
                raise RuntimeError("doubao verification_required: captcha challenge")
            return {
                "ok": True,
                "total": len(questions),
                "success": len(questions),
                "results": [
                    {"ok": True, "question": question, "answer": "回答", "refs": []}
                    for question in questions
                ],
            }

        def fake_login(_job, timeout_s=1800):
            return {"status": "completed", "summary": {"total": 1, "success": 1}}

        with tempfile.TemporaryDirectory() as tmp:
            payload = local_crawl_worker.run_job(
                {"id": "job-1", "platform": "doubao", "questions": ["问题A"]},
                run_crawler=flaky_crawler,
                run_login=fake_login,
                output_root=Path(tmp),
            )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(calls[0]["kwargs"]["concurrency"], 2)
        self.assertEqual(calls[1]["kwargs"]["concurrency"], 1)

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
        run_auth.assert_called_once_with(
            ["qwen"],
            timeout_s=1800,
            mode="manual",
            storage_state_path=str(local_crawl_worker.ROOT / "data" / "qwen_state.json"),
        )
        self.assertEqual(cloud.submitted[0][0], "login-qwen")
        self.assertEqual(cloud.submitted[0][1]["status"], "completed")
        self.assertEqual(cloud.submitted[0][1]["summary"], {"total": 1, "success": 1})

    def test_run_login_job_saves_platform_specific_state(self):
        with mock.patch.object(local_crawl_worker, "run_node_auth_preflight") as run_auth:
            run_auth.return_value = {"ok": True, "message": "ready"}

            payload = local_crawl_worker.run_login_job(
                {"id": "login-doubao", "platform": "doubao"},
                timeout_s=88,
            )

        expected_state = local_crawl_worker.ROOT / "data" / "doubao_state.json"
        self.assertEqual(payload["status"], "completed")
        run_auth.assert_called_once_with(
            ["doubao"],
            timeout_s=88,
            mode="manual",
            storage_state_path=str(expected_state),
        )

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
