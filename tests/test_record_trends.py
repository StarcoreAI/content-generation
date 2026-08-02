import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import app as geo_app
from services.auth import create_user
from services.record_trends import (
    build_article_pool,
    build_group_mention_trend,
    build_question_article_list,
    build_question_trend,
    build_source_trend,
    source_domain,
)


def record(day, platform, mentioned, refs=None, question="装修公司怎么选", round_num=1, task_id=""):
    return {
        "today": day,
        "source_platform": platform,
        "brand_mentioned": mentioned,
        "question": question,
        "round": round_num,
        "task_id": task_id,
        "refs": refs or [],
    }


@contextmanager
def isolated_trend_app():
    original = {
        "F_CLIENTS": geo_app.F_CLIENTS,
        "F_GROUPS": geo_app.F_GROUPS,
        "F_RAW_RECORDS": geo_app.F_RAW_RECORDS,
        "F_USERS": geo_app.F_USERS,
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.F_CLIENTS = os.path.join(tmp, "clients.json")
        geo_app.F_GROUPS = os.path.join(tmp, "probe_groups.json")
        geo_app.F_RAW_RECORDS = os.path.join(tmp, "raw_records.json")
        geo_app.F_USERS = os.path.join(tmp, "users.json")
        geo_app.app.config["AUTH_DISABLED"] = False
        try:
            yield tmp
        finally:
            geo_app.F_CLIENTS = original["F_CLIENTS"]
            geo_app.F_GROUPS = original["F_GROUPS"]
            geo_app.F_RAW_RECORDS = original["F_RAW_RECORDS"]
            geo_app.F_USERS = original["F_USERS"]
            if original["AUTH_DISABLED"] is None:
                geo_app.app.config.pop("AUTH_DISABLED", None)
            else:
                geo_app.app.config["AUTH_DISABLED"] = original["AUTH_DISABLED"]


class RecordTrendTests(unittest.TestCase):
    def setUp(self):
        shared = {"title": "同一篇文章 - 媒体", "url": "https://www.example.com/articles/1?from=ai", "platform": "媒体"}
        self.records = [
            record("2026-07-20", "deepseek", False, [shared]),
            record("2026-07-20", "deepseek", True, [shared], round_num=2),
            record("2026-07-21", "qwen", True, [
                {"title": "同一篇文章", "url": "https://example.com/articles/1/", "platform": "媒体"},
                {"title": "新进文章", "url": "https://news.example.com/new", "platform": "新闻"},
            ]),
            record("2026-07-22", "deepseek", False, [
                {"title": "同一篇文章", "url": "https://example.com/articles/1", "platform": "媒体"},
                {"title": "后续文章", "url": "https://news.example.com/later", "platform": "新闻"},
            ]),
            record("2026-07-22", "yuanbao", True, [], question="无关问题"),
        ]

    def test_question_trend_merges_same_day_platform_rounds(self):
        trend = build_question_trend(self.records, "装修公司怎么选")

        self.assertEqual(trend["deepseek"], [
            {"date": "2026-07-20", "mentioned": True, "records": 2},
            {"date": "2026-07-22", "mentioned": False, "records": 1},
        ])
        self.assertEqual(trend["qwen"], [
            {"date": "2026-07-21", "mentioned": True, "records": 1},
        ])
        self.assertNotIn("yuanbao", trend)

    def test_article_pool_tracks_new_retained_and_default_latest_date(self):
        pool = build_article_pool(self.records)

        self.assertEqual(pool["date"], "2026-07-22")
        self.assertEqual(pool["new_entries"], [{
            "title": "后续文章",
            "url": "https://news.example.com/later",
            "today_count": 1,
            "total_count": 1,
            "first_seen_date": "2026-07-22",
            "ai_platforms": ["deepseek"],
        }])
        self.assertEqual(pool["retained"], [{
            "title": "同一篇文章 - 媒体",
            "url": "https://www.example.com/articles/1?from=ai",
            "today_count": 1,
            "total_count": 4,
            "first_seen_date": "2026-07-20",
            "retained_days": 2,
            "ai_platforms": ["deepseek", "qwen"],
        }])

    def test_article_pool_handles_empty_records(self):
        self.assertEqual(build_question_trend([], "装修公司怎么选"), {})
        self.assertEqual(build_article_pool([]), {
            "date": "",
            "new_entries": [],
            "retained": [],
        })

    def test_question_article_list_merges_same_article_for_one_exact_question(self):
        articles = build_question_article_list([
            item for item in self.records if item["question"] == "装修公司怎么选"
        ])

        self.assertEqual(articles["total_records"], 4)
        self.assertEqual(articles["total_refs"], 6)
        self.assertEqual(articles["articles"][0], {
            "title": "同一篇文章 - 媒体",
            "url": "https://www.example.com/articles/1?from=ai",
            "count": 4,
            "source_platforms": ["媒体"],
            "ai_platforms": ["deepseek", "qwen"],
        })

    def test_source_domain_normalizes_urls_and_falls_back_to_platform(self):
        self.assertEqual(source_domain("https://www.news.example.com/path/", "媒体"), "example.com")
        self.assertEqual(source_domain("http://example.com/", "媒体"), "example.com")
        self.assertEqual(source_domain("www.example.com/path", "媒体"), "example.com")
        self.assertEqual(source_domain("not a url", "中文站名"), "中文站名")
        self.assertEqual(source_domain("http://[bad", "中文站名"), "中文站名")
        self.assertEqual(source_domain("", "中文站名"), "中文站名")

    def test_source_trend_uses_actual_capture_dates_and_merges_non_top_five_into_other(self):
        records = [
            record("2026-07-01", "deepseek", False, [{"url": "https://legacy.com/a", "platform": "Legacy"}]),
            *[
                record(
                    f"2026-07-{day:02}",
                    "deepseek",
                    False,
                    [{"url": "https://alpha.com/a", "platform": "Alpha"}]
                    + ([
                        {"url": f"https://{source}.com/a", "platform": source}
                        for source in ["bravo", "charlie", "delta", "echo", "foxtrot"]
                    ] if day == 8 else []),
                )
                for day in range(2, 9)
            ],
        ]

        trend = build_source_trend(records)
        sources = {item["source"]: item for item in trend["series"]}

        self.assertEqual(trend["dates"], [f"2026-07-{day:02}" for day in range(2, 9)])
        self.assertEqual(len(trend["series"]), 6)
        self.assertEqual(sources["alpha.com"]["shares"], [1.0] * 6 + [1 / 6])
        self.assertEqual(sources["其他"]["total_count"], 1)
        self.assertEqual(sources["其他"]["shares"], [0] * 6 + [1 / 6])
        self.assertAlmostEqual(sum(item["shares"][-1] for item in trend["series"]), 1.0)

    def test_source_trend_limits_output_to_latest_seven_capture_dates_and_handles_empty_data(self):
        records = [
            record(
                f"2026-07-{day:02}",
                "deepseek",
                False,
                [{"url": "https://alpha.com/article", "platform": "Alpha"}],
            )
            for day in range(1, 10)
        ]

        self.assertEqual(build_source_trend(records)["dates"], [f"2026-07-{day:02}" for day in range(3, 10)])
        self.assertEqual(build_source_trend([]), {"dates": [], "series": []})

    def test_source_trend_keeps_capture_dates_without_citations(self):
        trend = build_source_trend([
            record("2026-07-20", "deepseek", False, [{"url": "https://alpha.com/a", "platform": "Alpha"}]),
            record("2026-07-21", "deepseek", False, []),
        ])

        self.assertEqual(trend["dates"], ["2026-07-20", "2026-07-21"])
        self.assertEqual(trend["series"], [{
            "source": "alpha.com",
            "total_count": 1,
            "shares": [1.0, 0],
        }])

    def test_group_mention_trend_keeps_each_crawl_record_and_question_visible(self):
        question_one = "问题一"
        question_two = "问题二"
        question_without_records = "问题三"
        records = [
            record("2026-07-20", "deepseek", False, question=question_one),
            record("2026-07-20", "deepseek", True, question=question_one, round_num=2),
            record("2026-07-20", "qwen", False, question=question_one),
            record("2026-07-20", "deepseek", False, question=question_two),
            record("2026-07-21", "deepseek", False, question=question_one),
            record("2026-07-21", "deepseek", True, question=question_two),
            record("2026-07-21", "qwen", True, question=question_two),
        ]

        trend = build_group_mention_trend(records, [question_one, question_two, question_without_records])

        self.assertEqual(trend["dates"], ["2026-07-20", "2026-07-21"])
        self.assertEqual(trend["overall"], [
            {"mentioned": 1, "total": 4},
            {"mentioned": 2, "total": 3},
        ])
        self.assertEqual(trend["questions"], [
            {"question": question_one, "values": [{"mentioned": 1, "total": 3}, {"mentioned": 0, "total": 1}]},
            {"question": question_two, "values": [{"mentioned": 0, "total": 1}, {"mentioned": 2, "total": 2}]},
            {"question": question_without_records, "values": [{"mentioned": 0, "total": 0}, {"mentioned": 0, "total": 0}]},
        ])

        selected_platform = build_group_mention_trend(records, [question_one, question_two], platform="deepseek")
        self.assertEqual(selected_platform["overall"], [{"mentioned": 1, "total": 3}, {"mentioned": 1, "total": 2}])
        self.assertEqual(build_group_mention_trend(records, [question_one, question_two], platform="all")["dates"], [])

    def test_group_mention_trend_counts_distinct_tasks_without_collapsing_them(self):
        records = [
            record("2026-07-24", "doubao", True, task_id="task-one"),
            record("2026-07-24", "doubao", False, task_id="task-two"),
            record("2026-07-24", "doubao", False, task_id="task-three"),
            record("2026-07-24", "doubao", False, task_id="task-one"),
        ]

        trend = build_group_mention_trend(records, ["装修公司怎么选"])

        self.assertEqual(trend["overall"], [{"mentioned": 1, "total": 3}])
        self.assertEqual(trend["questions"], [{
            "question": "装修公司怎么选",
            "values": [{"mentioned": 1, "total": 3}],
        }])


class RecordTrendRouteTests(unittest.TestCase):
    def test_trend_routes_return_client_records_and_hide_other_clients(self):
        with isolated_trend_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "alice-client", "owner_username": "alice", "contract_platforms": ["deepseek", "qwen"]},
                {"id": "bob-client", "owner_username": "bob", "contract_platforms": ["doubao"]},
            ])
            geo_app.save(geo_app.F_GROUPS, {
                "alice-client": [{"id": "group-1", "questions": ["装修公司怎么选"]}],
            })
            records = [
                record("2026-07-20", "deepseek", True, [
                    {"url": "https://example.com/article", "platform": "示例站"},
                ], question="装修公司怎么选"),
                record("2026-07-21", "qwen", False, question="装修公司怎么选"),
            ]
            for item in records:
                item["client_id"] = "alice-client"
                item["group_id"] = "group-1"
            geo_app.save(geo_app.F_RAW_RECORDS, records)

            alice = geo_app.app.test_client()
            self.assertEqual(
                alice.post("/api/auth/login", json={"username": "alice", "password": "secret-pass"}).status_code,
                200,
            )
            trend = alice.get("/api/records/question_trend?client_id=alice-client&question=装修公司怎么选")
            self.assertEqual(trend.status_code, 200)
            self.assertEqual(trend.get_json()["trend"]["deepseek"][0]["mentioned"], True)
            self.assertEqual(alice.get("/api/records/article_pool?client_id=alice-client").status_code, 200)
            question_articles = alice.get(
                "/api/records/question_articles?client_id=alice-client&group_id=group-1&question=装修公司怎么选"
            )
            self.assertEqual(question_articles.status_code, 200)
            self.assertEqual(question_articles.get_json()["articles"][0]["count"], 1)
            source_trend = alice.get("/api/records/source_trend?client_id=alice-client")
            self.assertEqual(source_trend.status_code, 200)
            self.assertEqual(source_trend.get_json()["series"][0]["source"], "example.com")
            self.assertEqual(
                alice.get("/api/records/group_trend?client_id=alice-client&group_id=group-1").get_json()["error"],
                "ai_platform_required",
            )
            self.assertEqual(
                alice.get("/api/records/group_trend?client_id=alice-client&group_id=group-1&platform=doubao").get_json()["error"],
                "ai_platform_not_configured",
            )
            group_trend = alice.get("/api/records/group_trend?client_id=alice-client&group_id=group-1&platform=deepseek")
            self.assertEqual(group_trend.status_code, 200)
            self.assertEqual(group_trend.get_json()["overall"][0], {"mentioned": 1, "total": 1})

            bob = geo_app.app.test_client()
            self.assertEqual(
                bob.post("/api/auth/login", json={"username": "bob", "password": "secret-pass"}).status_code,
                200,
            )
            self.assertEqual(
                bob.get("/api/records/question_trend?client_id=alice-client&question=装修公司怎么选").status_code,
                404,
            )
            self.assertEqual(bob.get("/api/records/source_trend?client_id=alice-client").status_code, 404)
            self.assertEqual(
                bob.get("/api/records/question_articles?client_id=alice-client&question=装修公司怎么选").status_code,
                404,
            )
            self.assertEqual(
                bob.get("/api/records/group_trend?client_id=alice-client&group_id=group-1&platform=deepseek").status_code,
                404,
            )


class RecordTrendUiTests(unittest.TestCase):
    def test_records_library_wires_minimal_query_scene_table(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("问题组场景词提示", template)
        self.assertIn('id="btnRefreshQueryScenes"', template)
        self.assertIn('id="querySceneRows"', template)
        self.assertNotIn('id="btnDryRunQueryScenes"', template)
        self.assertIn("async function loadQueryScenes", script)
        self.assertIn("async function refreshQueryScenes", script)
        self.assertIn("/api/records/selection-evidence/", script)
        self.assertIn("问题组</th><th>Query</th><th>场景词", script)

    def test_records_library_removes_temporary_selection_surface_reports(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("选择层分析报告", template)
        self.assertNotIn('id="selectionSurfaceReports"', template)
        self.assertNotIn('id="selectionSurfaceReportPreview"', template)
        self.assertNotIn("loadSelectionSurfaceReports", script)
        self.assertNotIn("viewSelectionSurfaceReport", script)
        self.assertNotIn("/api/records/selection-reports/", script)

    def test_records_library_wires_group_trend_and_article_pool_views(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("问题组提及变化", template)
        self.assertIn('id="rec-group-filter"', template)
        self.assertIn('id="recordGroupPlatformChoices"', template)
        self.assertIn('id="recordGroupTrend"', template)
        self.assertIn('id="recordGroupQuestionMatrix"', template)
        self.assertIn("引用文章池", template)
        self.assertIn('id="recordArticlePoolDate"', template)
        self.assertIn('id="recordArticlePool"', template)
        self.assertIn("async function loadRecordGroupTrend", script)
        self.assertIn("renderRecordGroupPlatformChoices", script)
        self.assertIn("recordGroupTrendPlatform", script)
        self.assertIn("platform=${encodeURIComponent(recordGroupTrendPlatform)}", script)
        self.assertNotIn('data-record-group-platform="all"', script)
        self.assertIn("async function loadRecordArticlePool", script)
        self.assertIn("/api/records/group_trend", script)
        self.assertIn("/api/records/article_pool", script)
        self.assertIn("已留存 ${article.retained_days} 天", script)
        self.assertIn("引用来源站变化", template)
        self.assertIn('id="recordSourceTrend"', template)
        self.assertIn("async function loadRecordSourceTrend", script)
        self.assertIn("/api/records/source_trend", script)
        self.assertIn("sourceTrend.dates", script)
        self.assertIn("record-source-bar", script)
        self.assertIn("实际爬取次数", script)

    def test_records_library_wires_question_article_view(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("按具体问题看引用文章", template)
        self.assertIn('id="recordQuestionArticleFilter"', template)
        self.assertIn('id="recordQuestionArticles"', template)
        self.assertIn("async function loadRecordQuestionArticles", script)
        self.assertIn("/api/records/question_articles", script)

    def test_records_library_removes_views_duplicated_by_daily_data(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('id="platformStatsCard"', template)
        self.assertNotIn('id="topArticlesList"', template)
        self.assertNotIn('id="rawRecordList"', template)
        self.assertNotIn('id="rec-date-filter"', template)
        self.assertIn("async function loadRecordsLibraryViews", script)
        self.assertEqual(script.count("async function loadRecordsLibraryViews"), 1)


if __name__ == "__main__":
    unittest.main()
