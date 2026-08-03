import unittest
from pathlib import Path
from unittest.mock import patch

import app as geo_app
from tests.test_app_core import isolated_app_data


def _record(question, platform, url):
    return {"question": question, "source_platform": platform, "refs": [{"title": "引用文章", "url": url}]}


ANALYSIS = {
    "classification": "介绍型",
    "source": {"url": "https://example.com/a", "title": "引用文章"},
    "source_evidence": [{"role": "判断框架", "finding": "先解释判断条件", "excerpt": "这是一段可以在原文中连续找到且长度足够用于验证的来源片段。"}],
    "route": {
        "parent_type": "介绍型", "name": "先解释再落地", "reader_task": "帮助读者判断",
        "signature": "从判断到行动", "risk_notes": "", "steps": [
            {"purpose": "解释判断", "evidence_role": "来源证据", "output_action": "展开说明"},
        ],
    },
    "library_decision": {"eligible": True, "reason": "可积累"},
}


class QueryPlatformReferenceApiTests(unittest.TestCase):
    def test_one_click_enqueues_background_job_and_returns_before_analysis(self):
        with isolated_app_data():
            cid, gid = "client-reference", "group-reference"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "client", "brand": "brand", "industry": "test", "contract_platforms": ["doubao"]}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": gid, "questions": ["Q1"]}]})
            with patch.object(geo_app.threading, "Thread") as start_thread:
                response = geo_app.app.test_client().post("/api/content-routes/analyze-query-platform", json={
                    "client_id": cid, "group_id": gid, "query": "Q1", "ai_platform": "doubao",
                })

            self.assertEqual(202, response.status_code)
            self.assertEqual("queued", response.get_json()["job"]["status"])
            start_thread.assert_called_once()

    def test_background_job_status_is_small_and_authorized_by_client(self):
        with isolated_app_data() as tmp:
            cid, job_id = "client-reference", "job-reference"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "client"}])
            job_path = Path(tmp) / "reference_intelligence_jobs" / cid / f"{job_id}.json"
            geo_app.save(str(job_path), {
                "id": job_id, "client_id": cid, "status": "completed", "message": "completed",
                "analyses_count": 2, "failed_count": 1, "routes": [{"id": "route-a"}],
                "task": {"analyses": [{"large": "payload"}]},
            })

            response = geo_app.app.test_client().get(f"/api/content-routes/reference-analysis-jobs/{cid}/{job_id}")

            self.assertEqual(200, response.status_code)
            job = response.get_json()["job"]
            self.assertEqual("completed", job["status"])
            self.assertEqual(2, job["analyses_count"])
            self.assertNotIn("task", job)

    def test_one_click_recounts_exact_query_and_platform_then_merges(self):
        with isolated_app_data():
            cid, gid = "client-reference", "group-reference"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "测试行业", "contract_platforms": ["doubao"]}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": gid, "questions": ["Q1"]}]})
            records = [_record("Q1", "doubao", "https://example.com/a") for _ in range(5)]
            records += [_record("Q1", "doubao", "https://example.com/b") for _ in range(4)]
            records.append(_record("Q1", "deepseek", "https://example.com/ignored-platform"))
            records.append(_record("Q2", "doubao", "https://example.com/ignored-query"))
            with patch.object(geo_app, "load_client_records", return_value=records) as load_records, \
                    patch.object(geo_app, "fetch_article_text", return_value={"ok": True, "title": "引用文章", "content": "这是抓取到的完整文章正文，用于引用情报分析。"}), \
                    patch.object(geo_app, "analyze_content_route_article", return_value=ANALYSIS), \
                    patch.object(geo_app, "merge_reference_route_batch", return_value={"updates": [{"action": "create", "analysis_indexes": [0], "route": ANALYSIS["route"], "reason": "新路线"}]}):
                context = geo_app.reference_intelligence_context({
                    "client_id": cid, "group_id": gid, "query": "Q1", "ai_platform": "doubao",
                })
                task = geo_app.run_reference_intelligence_analysis(context, settings={})

            self.assertEqual({"question": "Q1", "platform": "doubao"}, load_records.call_args.kwargs)
            self.assertEqual("doubao", task["ai_platform"])
            self.assertEqual(5, task["selected"][0]["citation_count"])
            self.assertEqual(1, len(task["routes"]))

    def test_all_group_questions_are_merged_in_one_reference_batch(self):
        with isolated_app_data():
            cid, gid = "client-reference", "group-reference"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "测试行业", "contract_platforms": ["doubao"]}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": gid, "questions": ["Q1", "Q2"]}]})
            records = [_record("Q1", "doubao", "https://example.com/a") for _ in range(5)]
            records += [_record("Q2", "doubao", "https://example.com/b") for _ in range(4)]
            merge_result = {"updates": [{"action": "create", "analysis_indexes": [0, 1], "route": ANALYSIS["route"], "reason": "同一写法路线"}]}
            with patch.object(geo_app, "load_client_records", return_value=records) as load_records, \
                    patch.object(geo_app, "fetch_article_text", return_value={"ok": True, "title": "引用文章", "content": "这是抓取到的完整文章正文，用于引用情报分析。"}), \
                    patch.object(geo_app, "analyze_content_route_article", return_value=ANALYSIS), \
                    patch.object(geo_app, "merge_reference_route_batch", return_value=merge_result) as merge_batch:
                context = geo_app.reference_intelligence_context({
                    "client_id": cid, "group_id": gid, "query": "", "analyze_all_questions": True, "ai_platform": "doubao",
                })
                task = geo_app.run_reference_intelligence_analysis(context, settings={})

            self.assertEqual({"platform": "doubao"}, load_records.call_args.kwargs)
            batch = merge_batch.call_args.args[0]
            self.assertEqual(["Q1", "Q2"], [item["source_query"] for item in batch])
            self.assertTrue(task["analyze_all_questions"])
            self.assertEqual(["Q1", "Q2"], task["queries"])
            self.assertEqual(2, len(task["analyses"]))

    def test_one_click_logs_lock_selection_and_fetch_stages(self):
        with isolated_app_data():
            cid, gid = "client-reference", "group-reference"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "测试行业", "contract_platforms": ["doubao"]}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": gid, "questions": ["Q1"]}]})
            records = [_record("Q1", "doubao", "https://example.com/a") for _ in range(5)]
            records += [_record("Q1", "doubao", "https://example.com/b") for _ in range(4)]
            with patch.object(geo_app, "load_client_records", return_value=records), \
                    patch.object(geo_app, "fetch_article_text", return_value={"ok": True, "title": "引用文章", "content": "用于分析的文章正文。"}), \
                    patch.object(geo_app, "analyze_content_route_article", return_value=ANALYSIS), \
                    patch.object(geo_app, "merge_reference_route_batch", return_value={"updates": [{"action": "create", "analysis_indexes": [0], "route": ANALYSIS["route"], "reason": "新路线"}]}), \
                    patch.object(geo_app, "_log_reference_intelligence") as log_stage:
                context = geo_app.reference_intelligence_context({
                    "client_id": cid, "group_id": gid, "query": "Q1", "ai_platform": "doubao",
                })
                geo_app.run_reference_intelligence_analysis(context, settings={})

            events = [call.args[0] for call in log_stage.call_args_list]
            self.assertIn("lock_acquired", events)
            self.assertIn("articles_selected", events)
            self.assertEqual(events.count("article_fetch_started"), 2)
            self.assertEqual(events.count("article_fetch_finished"), 2)

    def test_one_click_rejects_query_outside_selected_group(self):
        with isolated_app_data():
            cid, gid = "client-reference", "group-reference"
            geo_app.save(geo_app.F_CLIENTS, [{"id": cid, "name": "客户", "brand": "品牌", "industry": "测试行业", "contract_platforms": ["doubao"]}])
            geo_app.save(geo_app.F_GROUPS, {cid: [{"id": gid, "questions": ["Q1"]}]})

            with patch.object(geo_app, "_log_reference_intelligence") as log_stage:
                response = geo_app.app.test_client().post("/api/content-routes/analyze-query-platform", json={
                    "client_id": cid, "group_id": gid, "query": "其他问题", "ai_platform": "doubao",
                })

            self.assertEqual(400, response.status_code)
            self.assertEqual("query_not_in_group", response.get_json()["error"])
            self.assertEqual("request_received", log_stage.call_args_list[0].args[0])
