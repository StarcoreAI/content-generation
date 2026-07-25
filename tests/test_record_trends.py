import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import app as geo_app
from services.auth import create_user
from services.record_trends import build_article_pool, build_question_trend


def record(day, platform, mentioned, refs=None, question="装修公司怎么选", round_num=1):
    return {
        "today": day,
        "source_platform": platform,
        "brand_mentioned": mentioned,
        "question": question,
        "round": round_num,
        "refs": refs or [],
    }


@contextmanager
def isolated_trend_app():
    original = {
        "F_CLIENTS": geo_app.F_CLIENTS,
        "F_RAW_RECORDS": geo_app.F_RAW_RECORDS,
        "F_USERS": geo_app.F_USERS,
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.F_CLIENTS = os.path.join(tmp, "clients.json")
        geo_app.F_RAW_RECORDS = os.path.join(tmp, "raw_records.json")
        geo_app.F_USERS = os.path.join(tmp, "users.json")
        geo_app.app.config["AUTH_DISABLED"] = False
        try:
            yield tmp
        finally:
            geo_app.F_CLIENTS = original["F_CLIENTS"]
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


class RecordTrendRouteTests(unittest.TestCase):
    def test_trend_routes_return_client_records_and_hide_other_clients(self):
        with isolated_trend_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
            geo_app.save(geo_app.F_CLIENTS, [
                {"id": "alice-client", "owner_username": "alice"},
                {"id": "bob-client", "owner_username": "bob"},
            ])
            records = [
                record("2026-07-20", "deepseek", True, question="装修公司怎么选"),
                record("2026-07-21", "qwen", False, question="装修公司怎么选"),
            ]
            for item in records:
                item["client_id"] = "alice-client"
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

            bob = geo_app.app.test_client()
            self.assertEqual(
                bob.post("/api/auth/login", json={"username": "bob", "password": "secret-pass"}).status_code,
                200,
            )
            self.assertEqual(
                bob.get("/api/records/question_trend?client_id=alice-client&question=装修公司怎么选").status_code,
                404,
            )


class RecordTrendUiTests(unittest.TestCase):
    def test_records_library_wires_question_and_article_pool_views(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("问题提及变化", template)
        self.assertIn('id="recordQuestionTrend"', template)
        self.assertIn("引用文章池", template)
        self.assertIn('id="recordArticlePoolDate"', template)
        self.assertIn('id="recordArticlePool"', template)
        self.assertIn("async function loadRecordQuestionTrend", script)
        self.assertIn("async function loadRecordArticlePool", script)
        self.assertIn("/api/records/question_trend", script)
        self.assertIn("/api/records/article_pool", script)
        self.assertIn("已留存 ${article.retained_days} 天", script)


if __name__ == "__main__":
    unittest.main()
