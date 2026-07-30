import unittest
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
                response = geo_app.app.test_client().post("/api/content-routes/analyze-query-platform", json={
                    "client_id": cid, "group_id": gid, "query": "Q1", "ai_platform": "doubao",
                })

            self.assertEqual(200, response.status_code)
            self.assertEqual({"question": "Q1", "platform": "doubao"}, load_records.call_args.kwargs)
            task = response.get_json()["task"]
            self.assertEqual("doubao", task["ai_platform"])
            self.assertEqual(5, task["selected"][0]["citation_count"])
            self.assertEqual(1, len(response.get_json()["routes"]))

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
                response = geo_app.app.test_client().post("/api/content-routes/analyze-query-platform", json={
                    "client_id": cid, "group_id": gid, "query": "Q1", "ai_platform": "doubao",
                })

            self.assertEqual(200, response.status_code)
            events = [call.args[0] for call in log_stage.call_args_list]
            self.assertEqual(events[0], "request_received")
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
