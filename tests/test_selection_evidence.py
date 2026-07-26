import tempfile
import unittest
from pathlib import Path


class QueryEvidenceTests(unittest.TestCase):
    def test_refresh_batches_queries_keeps_model_terms_and_reuses_cache(self):
        from services.selection_evidence import SelectionEvidenceService

        groups = [{"id": "group-1", "name": "学历提升", "questions": ["评职称怎么提升学历？", "工作忙怎么报名？"]}]
        records = [
            {"group_id": "group-1", "question": "评职称怎么提升学历？", "refs": [
                {"title": "学历提升文章甲", "url": "https://example.com/a"},
                {"title": "学历提升文章乙", "url": "https://example.com/b"},
                {"title": "学历提升文章丙", "url": "https://example.com/c"},
            ]},
            {"group_id": "group-1", "question": "工作忙怎么报名？", "refs": [
                {"title": "报名文章甲", "url": "https://example.com/d"},
                {"title": "报名文章乙", "url": "https://example.com/e"},
                {"title": "报名文章丙", "url": "https://example.com/f"},
            ]},
        ]
        calls = []

        def fetch(url, **_kwargs):
            return {"ok": True, "url": url, "html": (
                "<title>学历提升文章</title><meta name='description' content='适合评职称的在职人员'>"
                "<p>这是针对工作忙、需要评职称的人群的长首段，用于测试场景词提示输入，并补充报名和节点管理相关说明，确保超过既有提取器的长度阈值。</p>"
            )}

        def ask_json(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return {"items": [
                {"group_id": "group-1", "query": "评职称怎么提升学历？", "scene_terms": ["评职称", "怎么选"]},
                {"group_id": "group-1", "query": "工作忙怎么报名？", "scene_terms": ["工作忙", "报名"]},
            ]}

        with tempfile.TemporaryDirectory() as tmp:
            service = SelectionEvidenceService(Path(tmp), fetch_article=fetch)
            first = service.refresh_query_scenes("client-1", groups, records, ask_json)
            second = service.refresh_query_scenes("client-1", groups, records, ask_json)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 4000)
        self.assertIn("评职称怎么提升学历？", calls[0][0])
        self.assertIn("工作忙怎么报名？", calls[0][0])
        self.assertIn("标题：学历提升文章", calls[0][0])
        self.assertIn("Meta：适合评职称的在职人员", calls[0][0])
        self.assertIn("首段：这是针对工作忙", calls[0][0])
        self.assertIn("AI 平台会根据 Query 生成检索关键词", calls[0][0])
        self.assertEqual(first["rows"][0]["scene_terms"], ["评职称", "怎么选"])
        self.assertEqual(first["rows"][1]["scene_terms"], ["工作忙", "报名"])
        self.assertEqual(second["updated"], 0)

    def test_uses_each_querys_own_citations_and_skips_query_without_three_articles(self):
        from services.selection_evidence import SelectionEvidenceService

        groups = [{"id": "group-1", "name": "学历提升", "questions": ["问题甲", "问题乙", "问题丙"]}]
        records = [
            {"group_id": "group-1", "question": "问题甲", "refs": [
                {"title": "甲一", "url": "https://example.com/a1"},
                {"title": "甲二", "url": "https://example.com/a2"},
                {"title": "甲三", "url": "https://example.com/a3"},
            ]},
            {"group_id": "group-1", "question": "问题乙", "refs": [
                {"title": "乙一", "url": "https://example.com/b1"},
                {"title": "乙二", "url": "https://example.com/b2"},
                {"title": "乙三", "url": "https://example.com/b3"},
            ]},
            {"group_id": "group-1", "question": "问题丙", "refs": [
                {"title": "丙一", "url": "https://example.com/c1"},
                {"title": "丙二", "url": "https://example.com/c2"},
            ]},
            {"group_id": "group-1", "question": "问题丙", "refs": []},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            service = SelectionEvidenceService(Path(tmp), fetch_article=lambda url, **_kwargs: {
                "ok": True, "url": url, "html": f"<title>{url}</title><p>{'首段内容' * 100}</p>",
            })
            units = service.build_group_query_evidence("client-1", groups, records)

        self.assertEqual([unit["query"] for unit in units], ["问题甲", "问题乙"])
        self.assertEqual([item["url"] for item in units[0]["articles"]], [
            "https://example.com/a1", "https://example.com/a2", "https://example.com/a3",
        ])
        self.assertEqual([item["url"] for item in units[1]["articles"]], [
            "https://example.com/b1", "https://example.com/b2", "https://example.com/b3",
        ])

    def test_llm_error_keeps_existing_scene_terms_when_evidence_changes(self):
        from services.selection_evidence import SelectionEvidenceService

        groups = [{"id": "group-1", "name": "学历提升", "questions": ["评职称怎么提升学历？"]}]
        first_records = [{"group_id": "group-1", "question": "评职称怎么提升学历？", "refs": [
            {"title": "文章甲", "url": "https://example.com/a"},
            {"title": "文章乙", "url": "https://example.com/b"},
            {"title": "文章丙", "url": "https://example.com/c"},
        ]}]
        changed_records = [{"group_id": "group-1", "question": "评职称怎么提升学历？", "refs": [
            {"title": "文章丁", "url": "https://example.com/d"},
            {"title": "文章戊", "url": "https://example.com/e"},
            {"title": "文章己", "url": "https://example.com/f"},
        ]}]

        def fetch(url, **_kwargs):
            return {"ok": True, "url": url, "html": (
                f"<title>{url}</title><meta name='description' content='评职称场景'>"
                "<p>这是超过四十字的文章首段，用来构成稳定的场景词提取证据并测试异常保护行为。</p>"
            )}

        with tempfile.TemporaryDirectory() as tmp:
            service = SelectionEvidenceService(Path(tmp), fetch_article=fetch)
            service.refresh_query_scenes("client-1", groups, first_records, lambda *_args: {"items": [{
                "group_id": "group-1", "query": "评职称怎么提升学历？", "scene_terms": ["评职称"],
            }]})
            result = service.refresh_query_scenes(
                "client-1", groups, changed_records,
                lambda *_args: (_ for _ in ()).throw(RuntimeError("LLM unavailable")),
            )

        self.assertEqual(result["updated"], 0)
        self.assertIn("LLM unavailable", result["error"])
        self.assertEqual(result["rows"][0]["scene_terms"], ["评职称"])

    def test_refresh_hides_stale_cache_row_after_query_is_edited(self):
        from services.selection_evidence import SelectionEvidenceService

        records = [{"group_id": "group-1", "question": "旧问题", "refs": [
            {"title": "文章甲", "url": "https://example.com/a"},
            {"title": "文章乙", "url": "https://example.com/b"},
            {"title": "文章丙", "url": "https://example.com/c"},
        ]}, {"group_id": "group-1", "question": "新问题", "refs": [
            {"title": "文章丁", "url": "https://example.com/d"},
            {"title": "文章戊", "url": "https://example.com/e"},
            {"title": "文章己", "url": "https://example.com/f"},
        ]}]
        first_groups = [{"id": "group-1", "name": "问题组", "questions": ["旧问题"]}]
        edited_groups = [{"id": "group-1", "name": "问题组", "questions": ["新问题"]}]

        with tempfile.TemporaryDirectory() as tmp:
            service = SelectionEvidenceService(Path(tmp), fetch_article=lambda *_args, **_kwargs: {})
            service.refresh_query_scenes("client-1", first_groups, records, lambda *_args: {"items": [{
                "group_id": "group-1", "query": "旧问题", "scene_terms": ["旧场景"],
            }]})
            result = service.refresh_query_scenes("client-1", edited_groups, records, lambda *_args: {"items": [{
                "group_id": "group-1", "query": "新问题", "scene_terms": ["新场景"],
            }]})

        self.assertEqual([row["query"] for row in result["rows"]], ["新问题"])

    def test_dry_run_returns_scene_terms_without_creating_any_cache_file(self):
        from services.selection_evidence import SelectionEvidenceService

        groups = [{"id": "group-1", "name": "问题组", "questions": ["问题一"]}]
        records = [{"group_id": "group-1", "question": "问题一", "refs": [
            {"title": "文章甲", "url": "https://example.com/a"},
            {"title": "文章乙", "url": "https://example.com/b"},
            {"title": "文章丙", "url": "https://example.com/c"},
        ]}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = SelectionEvidenceService(root, fetch_article=lambda *_args, **_kwargs: {})
            result = service.refresh_query_scenes("client-1", groups, records, lambda *_args: {"items": [{
                "group_id": "group-1", "query": "问题一", "scene_terms": ["具体场景"],
            }]}, dry_run=True)

            self.assertTrue(result["dry_run"])
            self.assertEqual(result["rows"][0]["scene_terms"], ["具体场景"])
            self.assertFalse((root / "client-1" / "article_surfaces.json").exists())
            self.assertFalse((root / "client-1" / "query_scenes.json").exists())

    def test_builds_each_query_from_three_highest_cited_distinct_article_surfaces(self):
        from services.selection_evidence import SelectionEvidenceService

        groups = [{"id": "group-1", "name": "面部提升", "questions": ["下颌线松弛怎么办？"]}]
        records = [
            {"group_id": "group-1", "question": "下颌线松弛怎么办？", "refs": [
                {"title": "文章甲", "url": "https://example.com/a"},
                {"title": "文章乙", "url": "https://example.com/b"},
            ]},
            {"group_id": "group-1", "question": "下颌线松弛怎么办？", "refs": [
                {"title": "文章甲新标题", "url": "https://example.com/a"},
                {"title": "文章丙", "url": "https://example.com/c"},
            ]},
            {"group_id": "group-1", "question": "下颌线松弛怎么办？", "refs": [
                {"title": "文章甲", "url": "https://example.com/a"},
                {"title": "文章丁", "url": "https://example.com/d"},
            ]},
        ]

        def fetch(url, **_kwargs):
            return {"ok": True, "url": url, "html": (
                f"<title>{url} 标题</title><meta name='description' content='{url} 摘要'>"
                f"<p>{'首段内容' * 100}</p>"
            )}

        with tempfile.TemporaryDirectory() as tmp:
            service = SelectionEvidenceService(Path(tmp), fetch_article=fetch)
            units = service.build_group_query_evidence("client-1", groups, records)

        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["group_id"], "group-1")
        self.assertEqual(units[0]["query"], "下颌线松弛怎么办？")
        self.assertEqual([item["url"] for item in units[0]["articles"]], [
            "https://example.com/a", "https://example.com/b", "https://example.com/c",
        ])
        self.assertTrue(units[0]["articles"][0]["first_paragraph"].startswith("首段内容"))
        self.assertEqual(len(units[0]["articles"][0]["first_paragraph"]), 300)

    def test_skips_query_with_fewer_than_three_articles(self):
        from services.selection_evidence import SelectionEvidenceService

        groups = [{"id": "group-1", "name": "问题组", "questions": ["问题一"]}]
        records = [{"group_id": "group-1", "question": "问题一", "refs": [
            {"title": "文章甲", "url": "https://example.com/a"},
        ]}]

        with tempfile.TemporaryDirectory() as tmp:
            service = SelectionEvidenceService(Path(tmp), fetch_article=lambda *_args, **_kwargs: {})
            units = service.build_group_query_evidence("client-1", groups, records)

        self.assertEqual(units, [])


if __name__ == "__main__":
    unittest.main()
