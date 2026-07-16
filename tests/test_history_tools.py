import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RefPlatformTests(unittest.TestCase):
    def test_normalize_ref_platform_uses_url_when_platform_is_generic(self):
        from services.ref_platforms import normalize_ref_platform

        self.assertEqual(
            normalize_ref_platform("com", "http://baike.pcauto.com.cn/451733.html"),
            "pcauto",
        )
        self.assertEqual(
            normalize_ref_platform("未知", "https://www.mmsonline.com.cn/company/1.shtml"),
            "mmsonline",
        )
        self.assertEqual(
            normalize_ref_platform("cnblogs", "https://www.cnblogs.com/htyjz/p/20200822"),
            "cnblogs",
        )
        self.assertEqual(normalize_ref_platform("", ""), "未知")


class RefArticleTests(unittest.TestCase):
    def test_canonical_article_key_merges_toutiao_url_variants(self):
        from services.ref_articles import canonical_article_key

        self.assertEqual(
            canonical_article_key(
                "2026 深圳黄金回收全攻略：添价收领衔6家靠谱实体门店横向评测 - 今日头条",
                "https://www.toutiao.com/article/7655174835676480010/?wid=1782389372799",
            ),
            canonical_article_key(
                "2026 深圳黄金回收全攻略:添价收领衔6家靠谱实体门店横向评测 - 今日头条",
                "https://www.toutiao.com/a7655174835676480010?channel=",
            ),
        )

    def test_canonical_article_key_normalizes_title_when_url_missing(self):
        from services.ref_articles import canonical_article_key

        self.assertEqual(
            canonical_article_key("深圳黄金回收攻略：避坑指南 - 今日头条", ""),
            canonical_article_key("深圳黄金回收攻略: 避坑指南", ""),
        )


class RecordStoreTests(unittest.TestCase):
    def test_load_client_records_applies_optional_record_filters(self):
        from services.records import load_client_records

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw_records.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "r1",
                            "client_id": "client-1",
                            "today": "2026-07-10",
                            "question": "target question",
                            "brand_mentioned": True,
                        },
                        {
                            "id": "r2",
                            "client_id": "client-1",
                            "today": "2026-07-10",
                            "question": "target question",
                            "brand_mentioned": False,
                        },
                        {
                            "id": "r3",
                            "client_id": "client-1",
                            "today": "2026-07-11",
                            "question": "other question",
                            "brand_mentioned": True,
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            records = load_client_records(
                path,
                "client-1",
                date="2026-07-10",
                question="target",
                mentioned_only="1",
            )

        self.assertEqual([r["id"] for r in records], ["r1"])


class DailyStatsTests(unittest.TestCase):
    def test_build_daily_ref_stats_groups_articles_by_ai_platform(self):
        from services.daily_stats import build_daily_ref_stats

        records = [
            {
                "source_platform": "qwen",
                "refs": [
                    {"title": "Article A", "url": "https://a.example", "platform": "Sohu", "position": 2},
                ],
            },
            {
                "source_platform": "deepseek",
                "refs": [
                    {"title": "Article A", "url": "https://a.example", "platform": "Sohu", "position": 1},
                    {"title": "Article B", "url": "https://b.example", "platform": "Zhihu", "position": 3},
                ],
            },
        ]

        stats = build_daily_ref_stats(
            records,
            platform_names={"qwen": "Qwen", "deepseek": "DeepSeek"},
            platform_order=["deepseek", "qwen"],
        )

        self.assertEqual(stats["total_records"], 2)
        self.assertEqual(stats["total_refs"], 3)
        self.assertEqual(stats["platform_weights"][0]["platform"], "Sohu")
        self.assertEqual(stats["top_articles"][0]["title"], "Article A")
        self.assertEqual(stats["top_articles"][0]["count"], 2)
        self.assertEqual(stats["top_articles"][0]["avg_position"], 1.5)
        self.assertEqual(stats["top_articles"][0]["ai_platforms"], ["deepseek", "qwen"])
        self.assertEqual(
            [group["source_platform"] for group in stats["top_articles_by_ai"]],
            ["deepseek", "qwen"],
        )


class ContentPromptTests(unittest.TestCase):
    def test_content_prompt_helpers_normalize_samples(self):
        from services.content_prompts import (
            normalize_sample_links,
            normalize_selected_sample_articles,
        )

        self.assertEqual(
            normalize_sample_links("https://a.example\nhttps://a.example, https://b.example"),
            ["https://a.example", "https://b.example"],
        )
        self.assertEqual(
            normalize_selected_sample_articles([
                {"title": "Article A", "url": "https://a.example", "platform": "Sohu", "count": 2},
                {"title": "Article A duplicate", "url": "https://a.example", "platform": "Sohu", "count": 3},
            ]),
            [{"title": "Article A", "url": "https://a.example", "platform": "Sohu", "count": 2}],
        )


class RecordStatsTests(unittest.TestCase):
    def test_build_raw_platform_stats_preserves_route_shape(self):
        from services.record_stats import build_raw_platform_stats

        records = [
            {
                "refs": [
                    {"title": "Article A", "url": "https://a.example", "platform": "Sohu", "position": 1},
                    {"title": "Article B", "url": "https://b.example", "platform": "Zhihu", "position": 3},
                ],
            },
            {
                "refs": [
                    {"title": "Article A", "url": "https://a.example", "platform": "Sohu", "position": 5},
                ],
            },
        ]

        stats = build_raw_platform_stats(records)

        self.assertEqual(stats["total_records"], 2)
        self.assertEqual(stats["total_refs"], 3)
        self.assertEqual(stats["platform_weights"][0]["platform"], "Sohu")
        self.assertEqual(stats["platform_weights"][0]["pct"], 66.7)
        self.assertEqual(stats["platform_weights"][0]["avg_position"], 3.0)
        self.assertEqual(stats["platform_weights"][0]["sample_articles"], [
            {"title": "Article A", "url": "https://a.example"},
        ])
        self.assertEqual(stats["top_articles"][0]["title"], "Article A")
        self.assertEqual(stats["top_articles"][0]["count"], 2)


class BackfillTaskIdTests(unittest.TestCase):
    def test_plan_backfill_updates_matches_records_to_task_window(self):
        from scripts.backfill_task_ids import plan_backfill_updates

        records = [
            {
                "id": "r1",
                "client_id": "client-1",
                "group_id": "group-1",
                "source_platform": "qwen",
                "today": "2026-07-02",
                "crawl_time": "2026-07-02 11:16",
                "question": "问题A",
            },
            {
                "id": "r2",
                "client_id": "client-1",
                "group_id": "group-1",
                "source_platform": "doubao",
                "today": "2026-07-02",
                "crawl_time": "2026-07-02 11:16",
                "question": "问题A",
            },
        ]
        tasks = [
            {
                "task_id": "task-qwen",
                "task_report": "data/tasks/2026-07-02_task-qwen.json",
                "status": "completed",
                "started_at": "2026-07-02 11:10",
                "finished_at": "2026-07-02 11:17",
                "client_id": "client-1",
                "group_id": "group-1",
                "platform": "qwen",
                "crawler_engine": "node",
                "questions": ["问题A"],
            }
        ]

        plan = plan_backfill_updates(records, tasks)

        self.assertEqual(len(plan["updates"]), 1)
        self.assertEqual(plan["updates"][0]["record_id"], "r1")
        self.assertEqual(plan["updates"][0]["task_id"], "task-qwen")
        self.assertEqual(plan["task_summaries"]["task-qwen"]["matched"], 1)
        self.assertEqual(plan["skipped_existing"], 0)

    def test_plan_backfill_updates_prefers_exact_window_over_tolerance_match(self):
        from scripts.backfill_task_ids import plan_backfill_updates

        records = [
            {
                "id": "record-boundary",
                "client_id": "client-1",
                "group_id": "group-1",
                "source_platform": "doubao",
                "crawl_time": "2026-07-02 09:45",
                "question": "question-a",
            }
        ]
        tasks = [
            {
                "task_id": "task-exact",
                "task_report": "data/tasks/task-exact.json",
                "status": "completed",
                "started_at": "2026-07-02 09:43",
                "finished_at": "2026-07-02 09:45",
                "client_id": "client-1",
                "group_id": "group-1",
                "platform": "doubao",
                "questions": ["question-a"],
            },
            {
                "task_id": "task-tolerance",
                "task_report": "data/tasks/task-tolerance.json",
                "status": "completed",
                "started_at": "2026-07-02 09:46",
                "finished_at": "2026-07-02 09:48",
                "client_id": "client-1",
                "group_id": "group-1",
                "platform": "doubao",
                "questions": ["question-a"],
            },
        ]

        plan = plan_backfill_updates(records, tasks, tolerance_minutes=1)

        self.assertEqual(plan["conflicts"], [])
        self.assertEqual(len(plan["updates"]), 1)
        self.assertEqual(plan["updates"][0]["task_id"], "task-exact")
        self.assertEqual(plan["task_summaries"]["task-exact"]["matched"], 1)
        self.assertEqual(plan["task_summaries"]["task-tolerance"]["matched"], 0)


class RecordInsightsTests(unittest.TestCase):
    def test_build_record_insights_groups_platforms_articles_sources_and_entities(self):
        from services.record_insights import build_record_insights

        records = [
            {
                "id": "r1",
                "source_platform": "qwen",
                "brand_mentioned": True,
                "answer": "A",
                "question": "问题A",
                "refs": [
                    {"title": "文章A", "url": "https://a.example", "platform": "搜狐", "position": 1}
                ],
                "mentioned_entities": [
                    {"name": "竞品汽车音响", "type": "门店", "sentiment": "positive", "evidence": "推荐竞品汽车音响"}
                ],
            },
            {
                "id": "r2",
                "source_platform": "doubao",
                "brand_mentioned": False,
                "answer": "",
                "question": "问题B",
                "refs": [
                    {"title": "文章A", "url": "https://a.example", "platform": "搜狐", "position": 2},
                    {"title": "文章B", "url": "https://b.example", "platform": "知乎", "position": 1},
                ],
                "mentioned_entities": [
                    {"name": "竞品汽车音响", "type": "门店", "sentiment": "neutral", "evidence": "还提到竞品汽车音响"}
                ],
            },
        ]

        insights = build_record_insights(records)

        self.assertEqual(insights["total_records"], 2)
        self.assertEqual(insights["total_refs"], 3)
        self.assertEqual(insights["ai_platforms"][0]["source_platform"], "all")
        self.assertEqual(insights["ai_platforms"][0]["platform_name"], "全部平台")
        self.assertEqual(insights["ai_platforms"][0]["total_records"], 2)
        self.assertEqual(insights["ai_platforms"][0]["total_refs"], 3)
        self.assertEqual(
            insights["ai_platforms"][0]["ref_platforms"],
            [
                {"platform": "搜狐", "count": 2, "pct": 66.7},
                {"platform": "知乎", "count": 1, "pct": 33.3},
            ],
        )
        self.assertEqual(insights["ai_platforms"][1]["source_platform"], "doubao")
        self.assertEqual(insights["top_articles"][0]["url"], "https://a.example")
        self.assertEqual(insights["top_articles"][0]["count"], 2)
        self.assertEqual(insights["top_ref_platforms"][0]["platform"], "搜狐")
        self.assertEqual(insights["mentioned_entities"][0]["name"], "竞品汽车音响")
        self.assertEqual(insights["mentioned_entities"][0]["count"], 2)

    def test_build_record_insights_counts_brand_mentions_from_entity_aliases(self):
        from services.record_insights import build_record_insights

        records = [
            {
                "id": "r1",
                "brand": "苏韵汽车音响",
                "source_platform": "deepseek",
                "brand_mentioned": False,
                "answer": "回答没有直接写完整品牌名。",
                "refs": [],
                "mentioned_entities": [
                    {"name": "苏韵汽车音响", "type": "门店", "evidence": "推荐苏韵汽车音响"}
                ],
            },
            {
                "id": "r2",
                "brand": "苏韵汽车音响",
                "source_platform": "deepseek",
                "brand_mentioned": False,
                "answer": "只提到其他门店。",
                "refs": [],
                "mentioned_entities": [
                    {"name": "其他汽车音响", "type": "门店", "evidence": "其他汽车音响"}
                ],
            },
        ]

        insights = build_record_insights(records)

        self.assertEqual(insights["brand_mentions"], 1)
        self.assertEqual(insights["mention_rate"], 50.0)
        self.assertEqual(insights["ai_platforms"][0]["brand_mentions"], 1)
        self.assertEqual(insights["ai_platforms"][0]["mention_rate"], 50.0)

    def test_build_record_insights_counts_client_name_and_brand_but_filters_them_from_entities(self):
        from services.record_insights import build_record_insights

        records = [
            {
                "id": "r1",
                "brand": "西安兔博士口腔",
                "source_platform": "doubao",
                "brand_mentioned": False,
                "answer": "兔博士口腔适合学生党，复诊方便。竞品A也被提到。",
                "refs": [],
                "mentioned_entities": [
                    {"name": "兔博士口腔", "type": "口腔机构", "evidence": "兔博士口腔适合学生党"},
                    {"name": "竞品A", "type": "口腔机构", "evidence": "竞品A也被提到"},
                ],
            },
            {
                "id": "r2",
                "brand": "西安兔博士口腔",
                "source_platform": "doubao",
                "brand_mentioned": False,
                "answer": "这里只提到其他机构。",
                "refs": [],
                "mentioned_entities": [
                    {"name": "其他机构", "type": "口腔机构", "evidence": "其他机构"}
                ],
            },
        ]

        insights = build_record_insights(
            records,
            own_brand="兔博士",
            own_client_name="西安兔博士口腔",
        )

        self.assertEqual(insights["brand_mentions"], 1)
        self.assertEqual(insights["mention_rate"], 50.0)
        self.assertEqual([item["name"] for item in insights["mentioned_entities"]], ["竞品A", "其他机构"])

    def test_build_record_insights_filters_new_and_old_own_brand_entities(self):
        from services.record_insights import build_record_insights

        records = [
            {
                "id": "r1",
                "brand": "旧品牌",
                "source_platform": "qwen",
                "brand_mentioned": False,
                "answer": "旧品牌、旧品牌门店和竞品A都被提到。",
                "refs": [],
                "mentioned_entities": [
                    {"name": "旧品牌", "type": "品牌", "evidence": "旧品牌"},
                    {"name": "旧品牌门店", "type": "门店", "evidence": "旧品牌门店"},
                    {"name": "竞品A", "type": "品牌", "evidence": "竞品A"},
                ],
            },
            {
                "id": "r2",
                "brand": "新品牌",
                "source_platform": "deepseek",
                "brand_mentioned": True,
                "answer": "新品牌和新品牌旗舰店被提到。",
                "refs": [],
                "mentioned_entities": [
                    {"name": "新品牌", "type": "品牌", "evidence": "新品牌"},
                    {"name": "新品牌旗舰店", "type": "门店", "evidence": "新品牌旗舰店"},
                ],
            },
        ]

        insights = build_record_insights(records, own_brand="新品牌")

        self.assertEqual([item["name"] for item in insights["mentioned_entities"]], ["竞品A"])

    def test_build_record_insights_hides_all_platform_when_configured_and_actual_single_ai(self):
        from services.record_insights import build_record_insights

        records = [
            {
                "id": "r1",
                "source_platform": "qwen",
                "brand_mentioned": False,
                "answer": "回答",
                "refs": [
                    {"title": "文章A", "url": "https://a.example", "platform": "搜狐", "position": 1}
                ],
            }
        ]

        insights = build_record_insights(records, configured_platforms=["qwen"])

        self.assertEqual(len(insights["ai_platforms"]), 1)
        self.assertEqual(insights["ai_platforms"][0]["source_platform"], "qwen")

    def test_build_record_insights_does_not_return_competitor_article_candidates(self):
        from services.record_insights import build_record_insights

        records = [
            {
                "id": "r1",
                "source_platform": "deepseek",
                "question": "问题A",
                "answer": "回答推荐一号汽车音响，并引用了行业榜单。",
                "refs": [
                    {"title": "扬州汽车音响改装店推荐榜", "url": "https://rank.example/a", "platform": "榜单网", "position": 1},
                    {"title": "三号汽车音响门店介绍", "url": "https://store.example/c", "platform": "门店库", "position": 2},
                ],
                "mentioned_entities": [
                    {"name": "一号汽车音响", "type": "门店", "evidence": "推荐一号汽车音响"},
                    {"name": "二号汽车音响", "type": "门店", "evidence": "提到二号汽车音响"},
                    {"name": "三号汽车音响", "type": "门店", "evidence": "提到三号汽车音响"},
                ],
            },
            {
                "id": "r2",
                "source_platform": "qwen",
                "question": "问题B",
                "answer": "一号汽车音响适合做无损升级。",
                "refs": [
                    {"title": "扬州汽车音响改装店推荐榜", "url": "https://rank.example/a", "platform": "榜单网", "position": 1},
                ],
                "mentioned_entities": [
                    {"name": "一号汽车音响", "type": "门店", "evidence": "一号汽车音响"},
                    {"name": "二号汽车音响", "type": "门店", "evidence": "二号汽车音响"},
                ],
            },
            {
                "id": "r3",
                "source_platform": "doubao",
                "question": "问题C",
                "answer": "二号汽车音响也被提及。",
                "refs": [
                    {"title": "其他文章", "url": "https://other.example/b", "platform": "资讯网", "position": 1},
                ],
                "mentioned_entities": [
                    {"name": "一号汽车音响", "type": "门店", "evidence": "一号汽车音响"},
                    {"name": "二号汽车音响", "type": "门店", "evidence": "二号汽车音响"},
                ],
            },
            {
                "id": "r4",
                "source_platform": "yuanbao",
                "question": "问题D",
                "answer": "一号汽车音响再次出现。",
                "refs": [
                    {"title": "扬州汽车音响改装店推荐榜", "url": "https://rank.example/a", "platform": "榜单网", "position": 3},
                ],
                "mentioned_entities": [
                    {"name": "一号汽车音响", "type": "门店", "evidence": "一号汽车音响"},
                ],
            },
        ]

        insights = build_record_insights(records)

        self.assertNotIn("selected_competitors", insights)
        self.assertNotIn("competitor_articles", insights)
        self.assertNotIn("weak_competitor_articles", insights)
        self.assertEqual(insights["mentioned_entities"][0]["name"], "一号汽车音响")


class ArticleBodyHitTests(unittest.TestCase):
    def test_check_article_body_hits_extracts_html_and_matches_entities(self):
        from services.article_body_hits import check_article_body_hits

        articles = [
            {
                "title": "扬州汽车音响改装指南",
                "url": "https://article.example/a",
                "platform": "示例站",
                "count": 3,
                "ai_platforms": ["deepseek"],
            },
            {
                "title": "无链接文章",
                "url": "",
                "platform": "未知",
                "count": 2,
            },
        ]

        def fetcher(url, timeout=10):
            self.assertEqual(url, "https://article.example/a")
            return """
            <html><head><script>var ignored = "二号汽车音响";</script></head>
            <body><h1>指南</h1><p>正文重点推荐一号汽车音响，施工稳定。</p></body></html>
            """

        hits = check_article_body_hits(articles, ["一号汽车音响", "二号汽车音响"], fetcher=fetcher)

        self.assertEqual(hits[0]["status"], "matched")
        self.assertEqual(hits[0]["matched_entities"], ["一号汽车音响"])
        self.assertIn("正文重点推荐一号汽车音响", hits[0]["evidence"])
        self.assertEqual(hits[1]["status"], "skipped")
        self.assertEqual(hits[1]["error"], "missing_url")

    def test_upsert_body_hit_report_replaces_same_scope(self):
        from scripts.check_competitor_article_bodies import upsert_body_hit_report

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "body_hits.json"
            first = {
                "client_id": "client-1",
                "date": "2026-07-03",
                "task_id": "",
                "group_id": "",
                "platform": "",
                "generated_at": "2026-07-03 10:00:00",
                "body_hits": [{"title": "old"}],
            }
            second = {
                **first,
                "generated_at": "2026-07-03 11:00:00",
                "body_hits": [{"title": "new"}],
            }
            other_scope = {
                **first,
                "task_id": "task-2",
                "body_hits": [{"title": "other"}],
            }

            upsert_body_hit_report(store, first)
            upsert_body_hit_report(store, other_scope)
            upsert_body_hit_report(store, second)

            saved = json.loads(store.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 2)
            by_task = {item.get("task_id", ""): item for item in saved}
            self.assertEqual(by_task[""]["body_hits"][0]["title"], "new")
            self.assertEqual(by_task["task-2"]["body_hits"][0]["title"], "other")


    def test_build_record_insights_adds_ref_platform_distribution_per_ai_platform(self):
        from services.record_insights import build_record_insights

        records = [
            {
                "id": "r1",
                "source_platform": "deepseek",
                "refs": [
                    {"title": "A", "url": "https://a.example", "platform": "source-a"},
                    {"title": "B", "url": "https://b.example", "platform": "source-a"},
                    {"title": "C", "url": "https://c.example", "platform": "source-b"},
                ],
            },
            {
                "id": "r2",
                "source_platform": "qwen",
                "refs": [
                    {"title": "D", "url": "https://d.example", "platform": "source-c"},
                ],
            },
        ]

        insights = build_record_insights(records)
        deepseek = next(item for item in insights["ai_platforms"] if item["source_platform"] == "deepseek")

        self.assertEqual(
            deepseek["ref_platforms"],
            [
                {"platform": "source-a", "count": 2, "pct": 66.7},
                {"platform": "source-b", "count": 1, "pct": 33.3},
            ],
        )


class EntityExtractionTests(unittest.TestCase):
    def test_parse_entity_response_filters_own_brand_aliases(self):
        from scripts.extract_entities import parse_entity_response

        raw = """```json
        {
          "entities": [
            {"name": "苏韵汽车音响", "type": "门店", "sentiment": "positive", "evidence": "苏韵汽车音响不错"},
            {"name": "竞品汽车音响", "type": "门店", "sentiment": "positive", "evidence": "竞品汽车音响也被推荐"}
          ]
        }
        ```"""

        entities = parse_entity_response(raw, own_brand="扬州苏韵汽车音响")

        self.assertEqual(
            entities,
            [
                {
                    "name": "竞品汽车音响",
                    "type": "门店",
                    "sentiment": "positive",
                    "evidence": "竞品汽车音响也被推荐",
                }
            ],
        )

    def test_parse_entity_response_extracts_json_from_wrapped_text(self):
        from scripts.extract_entities import parse_entity_response

        raw = """下面是结果：
        ```json
        {"entities":[{"name":"道声汽车音响","type":"门店","sentiment":"positive","evidence":"推荐道声汽车音响"}]}
        ```
        请查收。
        """

        entities = parse_entity_response(raw, own_brand="扬州苏韵汽车音响")

        self.assertEqual(entities[0]["name"], "道声汽车音响")

    def test_extract_for_records_continues_when_one_response_is_invalid(self):
        from scripts.extract_entities import extract_for_records

        class FakeMessage:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content):
                self.message = FakeMessage(content)

        class FakeResponse:
            def __init__(self, content):
                self.choices = [FakeChoice(content)]

        class FakeCompletions:
            def __init__(self):
                self.calls = 0

            def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse("not json")
                return FakeResponse('{"entities":[{"name":"道声汽车音响","type":"门店","sentiment":"positive","evidence":"推荐道声汽车音响"}]}')

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeClient:
            def __init__(self):
                self.chat = FakeChat()

        records = [
            {"id": "r1", "question": "q1", "source_platform": "deepseek", "brand": "扬州苏韵汽车音响", "answer": "A"},
            {"id": "r2", "question": "q2", "source_platform": "deepseek", "brand": "扬州苏韵汽车音响", "answer": "B"},
        ]

        results = extract_for_records(records, {"model": "test-model"}, client=FakeClient())

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["entities"], [])
        self.assertIn("error", results[0])
        self.assertEqual(results[1]["entities"][0]["name"], "道声汽车音响")


class EntityNormalizeScriptTests(unittest.TestCase):
    def test_select_records_can_filter_manual_entity_scope(self):
        from scripts.extract_entities import select_records

        records = [
            {
                "id": "keep",
                "client_id": "c1",
                "today": "2026-07-13",
                "group_id": "g1",
                "source_platform": "qwen",
                "answer": "A",
                "mentioned_entities": [],
            },
            {
                "id": "other-group",
                "client_id": "c1",
                "today": "2026-07-13",
                "group_id": "g2",
                "source_platform": "qwen",
                "answer": "B",
                "mentioned_entities": [],
            },
            {
                "id": "other-platform",
                "client_id": "c1",
                "today": "2026-07-13",
                "group_id": "g1",
                "source_platform": "doubao",
                "answer": "C",
                "mentioned_entities": [],
            },
        ]

        selected = select_records(records, client_id="c1", date="2026-07-13", group_id="g1", platform="qwen")

        self.assertEqual([item["id"] for item in selected], ["keep"])

    def test_filter_entity_candidates_only_dedupes_first_layer_candidates(self):
        from scripts.normalize_entities import filter_entity_candidates

        candidates = [
            {"name": "添价收黄金奢侈品回收中心", "canonical_name": "添价收", "business": "黄金回收", "evidence": "添价收黄金奢侈品回收中心"},
            {"name": "添价收黄金奢侈品回收中心", "canonical_name": "添价收", "business": "黄金回收", "evidence": "重复提到添价收"},
        ]

        kept, rejected = filter_entity_candidates(candidates, own_brand="粤宝福")

        self.assertEqual([item["canonical_name"] for item in kept], ["添价收"])
        self.assertEqual([item["reason"] for item in rejected], ["duplicate"])

    def test_parse_candidate_response_accepts_first_layer_candidate_fields(self):
        from scripts.normalize_entities import parse_candidate_response

        raw = json.dumps({
            "competitors": [
                {"n": "粤宝福", "e": "粤宝福黄金回收", "b": "黄金回收"},
                {"n": "添价收", "e": "添价收黄金奢侈品回收中心", "b": "黄金回收"},
            ]
        }, ensure_ascii=False)

        competitors = parse_candidate_response(raw)

        self.assertEqual(competitors[0]["name"], "粤宝福")
        self.assertEqual(competitors[0]["business"], "黄金回收")
        self.assertEqual(competitors[1]["name"], "添价收")
        self.assertEqual(competitors[1]["evidence"], "添价收黄金奢侈品回收中心")

    def test_build_candidate_extraction_prompt_only_extracts_matching_entities(self):
        from scripts.normalize_entities import build_candidate_extraction_prompt

        prompt = build_candidate_extraction_prompt({
            "brand": "粤宝福黄金回收",
            "question": "深圳黄金回收门店推荐？",
            "answer": "回答正文",
        }, competitor_category="黄金回收服务商、黄金回收门店、黄金回收平台")

        self.assertIn("只抽取符合范围的实体", prompt)
        self.assertIn("黄金回收服务商、黄金回收门店、黄金回收平台", prompt)
        self.assertIn("A/B", prompt)
        self.assertIn("不要输出 A/B 组合名", prompt)
        self.assertNotIn("粤宝福", prompt)
        self.assertNotIn("本客户品牌", prompt)
        self.assertIn("只抽取符合范围的实体", prompt)
        self.assertIn('"n"', prompt)
        self.assertIn('"e"', prompt)
        self.assertIn('"b"', prompt)
        self.assertIn("营业执照", prompt)
        self.assertIn("XRF光谱仪", prompt)
        self.assertIn("competitors", prompt)

    def test_build_candidate_batch_extraction_prompt_keeps_record_boundaries(self):
        from scripts.normalize_entities import build_candidate_batch_extraction_prompt

        prompt = build_candidate_batch_extraction_prompt([
            {"id": "r1", "brand": "粤宝福", "question": "q1", "answer": "answer 1", "source_platform": "qwen"},
            {"id": "r2", "brand": "粤宝福", "question": "q2", "answer": "answer 2", "source_platform": "doubao"},
        ], competitor_category="黄金回收")

        self.assertIn('"records"', prompt)
        self.assertIn('"record_id": "r1"', prompt)
        self.assertIn('"record_id": "r2"', prompt)
        self.assertIn("每条回答必须按 record_id 单独输出", prompt)
        self.assertIn("A/B", prompt)
        self.assertIn("不要输出 A/B 组合名", prompt)
        self.assertNotIn("粤宝福", prompt)
        self.assertNotIn('"brand"', prompt)
        self.assertNotIn("本客户品牌", prompt)
        self.assertIn('"n"', prompt)
        self.assertIn('"e"', prompt)
        self.assertIn('"b"', prompt)

    def test_extract_candidates_uses_extraction_model_and_dedupes_candidates(self):
        from scripts.normalize_entities import extract_candidates_for_records

        class FakeMessage:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content):
                self.message = FakeMessage(content)

        class FakeResponse:
            def __init__(self, content):
                self.choices = [FakeChoice(content)]

        class FakeCompletions:
            def __init__(self):
                self.kwargs = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                return FakeResponse(json.dumps({
                    "competitors": [
                        {"n": "添价收", "e": "添价收", "b": "黄金回收"},
                    ]
                }, ensure_ascii=False))

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeClient:
            def __init__(self):
                self.chat = FakeChat()

        client = FakeClient()
        results = extract_candidates_for_records(
            [{"id": "r1", "brand": "粤宝福", "answer": "添价收和营业执照", "source_platform": "qwen"}],
            {"model": "deepseek-chat", "extraction_model": "deepseek-v4-pro"},
            client=client,
            competitor_category="黄金回收",
        )

        self.assertEqual(client.chat.completions.kwargs["model"], "deepseek-v4-pro")
        self.assertEqual(client.chat.completions.kwargs["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual([item["name"] for item in results[0]["competitors"]], ["添价收"])
        self.assertEqual(results[0]["rejected_competitors"], [])

    def test_extract_candidates_batches_five_records_and_splits_results(self):
        from scripts.normalize_entities import extract_candidates_for_records

        class FakeMessage:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content):
                self.message = FakeMessage(content)

        class FakeResponse:
            def __init__(self, content):
                self.choices = [FakeChoice(content)]

        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                prompt = kwargs["messages"][0]["content"]
                ids = ["r6"] if '"record_id": "r6"' in prompt else ["r1", "r2", "r3", "r4", "r5"]
                return FakeResponse(json.dumps({
                    "records": [
                        {
                            "record_id": record_id,
                            "competitors": [
                                {
                                    "n": f"entity-{record_id}",
                                    "e": f"entity-{record_id}",
                                    "b": "黄金回收",
                                }
                            ],
                        }
                        for record_id in ids
                    ]
                }, ensure_ascii=False))

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeClient:
            def __init__(self):
                self.chat = FakeChat()

        records = [
            {"id": f"r{i}", "brand": "粤宝福", "answer": f"answer {i}", "source_platform": "qwen"}
            for i in range(1, 7)
        ]
        client = FakeClient()

        results = extract_candidates_for_records(
            records,
            {"model": "deepseek-chat", "extraction_model": "deepseek-v4-pro"},
            client=client,
            competitor_category="黄金回收",
        )

        self.assertEqual(len(client.chat.completions.calls), 2)
        self.assertEqual([result["record_id"] for result in results], ["r1", "r2", "r3", "r4", "r5", "r6"])
        self.assertEqual([result["competitors"][0]["name"] for result in results], [
            "entity-r1", "entity-r2", "entity-r3", "entity-r4", "entity-r5", "entity-r6"
        ])

    def test_resolve_competitor_category_uses_client_config_then_industry(self):
        from scripts.normalize_entities import resolve_competitor_category

        clients = [
            {"id": "client-1", "industry": "黄金回收"},
            {"id": "client-2", "industry": "车载音响服务", "competitor_category": "汽车音响改装服务商"},
        ]

        self.assertEqual(resolve_competitor_category("手动品类", "client-1", clients), "手动品类")
        self.assertEqual(resolve_competitor_category("", "client-2", clients), "汽车音响改装服务商")
        self.assertEqual(resolve_competitor_category("", "client-1", clients), "黄金回收")

    def test_build_existing_entity_summary_groups_by_name_and_ai(self):
        from scripts.normalize_entities import build_existing_entity_summary

        records = [
            {
                "source_platform": "deepseek",
                "mentioned_entities": [
                    {"name": "道声汽车音响", "type": "门店", "evidence": "推荐道声汽车音响"}
                ],
            },
            {
                "source_platform": "qwen",
                "mentioned_entities": [
                    {"name": "道声汽车音响", "type": "门店", "evidence": "还提到道声汽车音响"}
                ],
            },
        ]

        summary = build_existing_entity_summary(records)

        self.assertEqual(summary[0]["name"], "道声汽车音响")
        self.assertEqual(summary[0]["count"], 2)
        self.assertEqual(summary[0]["ai_platform_counts"], {"deepseek": 1, "qwen": 1})

    def test_build_competitor_report_prompt_converts_backend_summary_to_report(self):
        from scripts.normalize_entities import build_competitor_report_prompt

        prompt = build_competitor_report_prompt([
            {
                "name": "道声汽车音响",
                "count": 2,
                "ai_platform_counts": {"deepseek": 1, "qwen": 1},
                "evidence_samples": ["推荐道声汽车音响"],
            }
        ])

        self.assertIn("只输出保留实体", prompt)
        self.assertIn("canonical_entities", prompt)
        self.assertIn('"n"', prompt)
        self.assertIn('"a"', prompt)
        self.assertNotIn("rejected_entities", prompt)
        self.assertNotIn("platform_findings", prompt)
        self.assertNotIn("alias_groups", prompt)

    def test_parse_competitor_report_response_accepts_compact_canonical_entities(self):
        from scripts.normalize_entities import parse_competitor_report_response

        report = parse_competitor_report_response(json.dumps({
            "canonical_entities": [
                {"n": "收的顶", "a": ["收的顶", "收的顶黄金奢侈品回收"]},
                {"n": "粤宝福", "a": ["粤宝福", "粤宝福黄金回收"]},
            ]
        }, ensure_ascii=False))

        self.assertEqual(
            report["canonical_entities"],
            [
                {"canonical_name": "收的顶", "aliases": ["收的顶", "收的顶黄金奢侈品回收"]},
                {"canonical_name": "粤宝福", "aliases": ["粤宝福", "粤宝福黄金回收"]},
            ],
        )

    def test_simplify_competitor_report_for_output_hides_unused_legacy_fields(self):
        from scripts.normalize_entities import simplify_competitor_report_for_output

        report = simplify_competitor_report_for_output({
            "canonical_entities": [{"canonical_name": "A", "aliases": ["A1"]}],
            "competitor_rankings": [],
            "rejected_entities": [],
            "platform_findings": [],
            "alias_groups": [],
            "batches": 1,
            "parse_errors": ["bad json"],
            "batch_reports": [
                {
                    "canonical_entities": [{"canonical_name": "A", "aliases": ["A1"]}],
                    "competitor_rankings": [],
                    "rejected_entities": [],
                    "platform_findings": [],
                    "alias_groups": [],
                    "parse_error": "bad json",
                    "raw": '{"canonical_entities": [',
                }
            ],
        })

        self.assertEqual(set(report), {"canonical_entities", "batches", "parse_errors", "batch_reports"})
        self.assertEqual(set(report["batch_reports"][0]), {"canonical_entities", "parse_error", "raw"})

    def test_request_competitor_report_keeps_raw_response_when_json_is_malformed(self):
        from scripts.normalize_entities import request_competitor_report

        class FakeMessage:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content):
                self.message = FakeMessage(content)

        class FakeResponse:
            def __init__(self, content):
                self.choices = [FakeChoice(content)]

        class FakeCompletions:
            def create(self, **kwargs):
                return FakeResponse('{"canonical_entities": [{"canonical_name": "道声",],}')

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeClient:
            def __init__(self):
                self.chat = FakeChat()

        report = request_competitor_report(
            [{"name": "道声", "count": 1, "ai_platform_counts": {"qwen": 1}}],
            {"model": "test-model"},
            client=FakeClient(),
        )

        self.assertEqual(report["canonical_entities"], [])
        self.assertIn("parse_error", report)
        self.assertIn("raw", report)

    def test_final_competitor_summary_uses_canonical_entities_and_rejects_others(self):
        from scripts.normalize_entities import build_final_competitor_summary

        mentions = [
            {"raw_name": "添价收", "source_platform": "deepseek", "record_id": "r1", "evidence": "提到添价收"},
            {"raw_name": "添价收黄金奢侈品回收中心", "source_platform": "qwen", "record_id": "r2", "evidence": "提到添价收黄金奢侈品回收中心"},
            {"raw_name": "君佩", "source_platform": "deepseek", "record_id": "r3", "evidence": "君佩古法金"},
        ]
        report = {
            "canonical_entities": [
                {
                    "canonical_name": "添价收黄金奢侈品回收中心",
                    "aliases": ["添价收", "添价收黄金奢侈品回收中心"],
                }
            ],
            "rejected_entities": [
                {"name": "君佩", "reason": "被回收的金饰品牌，不是回收服务商"}
            ],
        }

        summary = build_final_competitor_summary(mentions, report)

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["name"], "添价收黄金奢侈品回收中心")
        self.assertEqual(summary[0]["mention_count"], 2)
        self.assertEqual(summary[0]["ai_platform_counts"], {"deepseek": 1, "qwen": 1})

    def test_merge_competitor_reports_combines_canonical_and_rejected_entities(self):
        from scripts.normalize_entities import merge_competitor_reports

        merged = merge_competitor_reports([
            {
                "canonical_entities": [{"canonical_name": "添价收", "aliases": ["添价收"]}],
                "rejected_entities": [{"name": "君佩", "reason": "非竞品"}],
                "platform_findings": [{"source_platform": "deepseek", "finding": "多次提及"}],
            },
            {
                "canonical_entities": [{"canonical_name": "收的顶", "aliases": ["收的顶"]}],
                "rejected_entities": [{"name": "宝兰", "reason": "非竞品"}],
            },
        ])

        self.assertEqual([item["canonical_name"] for item in merged["canonical_entities"]], ["添价收", "收的顶"])
        self.assertEqual([item["name"] for item in merged["rejected_entities"]], ["君佩", "宝兰"])
        self.assertEqual(merged["platform_findings"][0]["source_platform"], "deepseek")

    def test_second_layer_defaults_to_single_global_batch_for_current_scale(self):
        from scripts.normalize_entities import request_competitor_report_batched

        class FakeMessage:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content):
                self.message = FakeMessage(content)

        class FakeResponse:
            def __init__(self, content):
                self.choices = [FakeChoice(content)]

        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return FakeResponse(json.dumps({
                    "canonical_entities": [],
                    "competitor_rankings": [],
                    "rejected_entities": [],
                    "platform_findings": [],
                    "alias_groups": [],
                }, ensure_ascii=False))

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeClient:
            def __init__(self):
                self.chat = FakeChat()

        client = FakeClient()
        raw_summary = [{"name": f"entity-{idx}", "count": 1} for idx in range(86)]

        report = request_competitor_report_batched(raw_summary, {"model": "test-model"}, client=client)

        self.assertEqual(len(client.chat.completions.calls), 1)
        self.assertEqual(report["batches"], 1)

    def test_final_summary_marks_own_brand_without_filtering_it(self):
        from scripts.normalize_entities import build_final_competitor_summary

        mentions = [
            {"raw_name": "粤宝福", "source_platform": "deepseek", "record_id": "r1", "evidence": "提到粤宝福"},
            {"raw_name": "添价收", "source_platform": "qwen", "record_id": "r2", "evidence": "提到添价收"},
        ]
        report = {
            "canonical_entities": [
                {"canonical_name": "粤宝福", "aliases": ["粤宝福"]},
                {"canonical_name": "添价收", "aliases": ["添价收"]},
            ]
        }

        summary = build_final_competitor_summary(mentions, report, own_brand="粤宝福")

        own = next(item for item in summary if item["name"] == "粤宝福")
        self.assertTrue(own["is_own_brand"])
        competitor = next(item for item in summary if item["name"] == "添价收")
        self.assertFalse(competitor["is_own_brand"])

    def test_final_summary_splits_combined_raw_name_into_known_canonical_entities(self):
        from scripts.normalize_entities import build_final_competitor_summary

        mentions = [
            {"raw_name": "A/B", "source_platform": "yuanbao", "record_id": "r1", "evidence": "A / B recommended"},
        ]
        report = {
            "canonical_entities": [
                {"canonical_name": "A", "aliases": ["A", "A/B"]},
                {"canonical_name": "B", "aliases": ["B"]},
            ]
        }

        summary = build_final_competitor_summary(mentions, report)

        self.assertEqual([item["name"] for item in summary], ["A", "B"])
        self.assertEqual([item["mention_count"] for item in summary], [1, 1])
        self.assertEqual(summary[0]["aliases"], [])
        self.assertEqual(summary[1]["aliases"], [])

    def test_apply_competitor_report_results_writes_canonical_entities_with_backup(self):
        from scripts.normalize_entities import apply_competitor_report_results

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_records_path = Path(tmpdir) / "raw_records.json"
            records = [
                {"id": "r1", "mentioned_entities": []},
                {"id": "r2", "mentioned_entities": []},
                {"id": "r3", "mentioned_entities": [{"name": "old"}]},
            ]
            raw_records_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            report = {
                "results": [
                    {
                        "record_id": "r1",
                        "competitors": [
                            {"name": "A/B", "type": "gold", "sentiment": "neutral", "evidence": "A / B recommended"},
                        ],
                    },
                    {
                        "record_id": "r2",
                        "competitors": [
                            {"name": "C raw", "type": "gold", "sentiment": "neutral", "evidence": "C evidence"},
                        ],
                    },
                ],
                "competitor_report": {
                    "canonical_entities": [
                        {"canonical_name": "A", "aliases": ["A"]},
                        {"canonical_name": "B", "aliases": ["B"]},
                        {"canonical_name": "C", "aliases": ["C raw"]},
                    ]
                },
            }

            result = apply_competitor_report_results(raw_records_path, records, report)
            saved = json.loads(raw_records_path.read_text(encoding="utf-8"))

            self.assertEqual(result["changed"], 2)
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertEqual([item["name"] for item in saved[0]["mentioned_entities"]], ["A", "B"])
            self.assertEqual([item["name"] for item in saved[1]["mentioned_entities"]], ["C"])
            self.assertEqual(saved[2]["mentioned_entities"], [{"name": "old"}])

    def test_apply_competitor_report_results_preserves_records_added_after_selection(self):
        from scripts.normalize_entities import apply_competitor_report_results

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_records_path = Path(tmpdir) / "raw_records.json"
            selected_snapshot = [
                {"id": "r1", "mentioned_entities": []},
            ]
            raw_records_path.write_text(json.dumps([
                {"id": "r1", "mentioned_entities": []},
                {"id": "r2", "mentioned_entities": [{"name": "new-platform"}]},
            ], ensure_ascii=False), encoding="utf-8")
            report = {
                "results": [
                    {
                        "record_id": "r1",
                        "competitors": [
                            {"name": "Entity", "type": "门店", "sentiment": "neutral", "evidence": "Entity"},
                        ],
                    }
                ],
                "competitor_report": {
                    "canonical_entities": [{"canonical_name": "Entity", "aliases": ["Entity"]}],
                },
            }

            apply_competitor_report_results(raw_records_path, selected_snapshot, report)

            saved = json.loads(raw_records_path.read_text(encoding="utf-8"))
            self.assertEqual([record["id"] for record in saved], ["r1", "r2"])
            self.assertEqual(saved[0]["mentioned_entities"][0]["name"], "Entity")
            self.assertEqual(saved[1]["mentioned_entities"], [{"name": "new-platform"}])

    def test_main_extract_missing_apply_writes_records_and_report(self):
        from scripts import normalize_entities

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            report_dir = Path(tmpdir) / "reports"
            data_dir.mkdir()
            records = [
                {
                    "id": "r1",
                    "client_id": "c1",
                    "today": "2026-07-03",
                    "answer": "answer",
                    "mentioned_entities": [],
                }
            ]
            (data_dir / "raw_records.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            (data_dir / "settings.json").write_text("{}", encoding="utf-8")
            (data_dir / "clients.json").write_text(json.dumps([
                {"id": "c1", "brand": "Brand", "industry": "Industry"}
            ], ensure_ascii=False), encoding="utf-8")
            fake_body = {
                "mode": "extract_missing",
                "selected_records": 1,
                "own_brand": "Brand",
                "raw_entity_summary": [],
                "competitor_report": {
                    "canonical_entities": [
                        {"canonical_name": "Entity", "aliases": ["RawEntity"]}
                    ]
                },
                "final_competitor_summary": [],
                "results": [
                    {
                        "record_id": "r1",
                        "competitors": [
                            {"name": "RawEntity", "type": "Industry", "sentiment": "neutral", "evidence": "RawEntity"}
                        ],
                    }
                ],
            }

            with patch.object(normalize_entities, "build_extract_missing_report", return_value=fake_body):
                code = normalize_entities.main([
                    "--data-dir", str(data_dir),
                    "--report-dir", str(report_dir),
                    "--client-id", "c1",
                    "--date", "2026-07-03",
                    "--extract-missing",
                    "--apply",
                ])

            saved = json.loads((data_dir / "raw_records.json").read_text(encoding="utf-8"))
            reports = list(report_dir.glob("entity_normalize_c1_*.json"))
            report = json.loads(reports[0].read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            self.assertEqual(saved[0]["mentioned_entities"][0]["name"], "Entity")
            self.assertTrue(report["data_written"])
            self.assertEqual(report["apply_result"]["changed"], 1)

if __name__ == "__main__":
    unittest.main()
