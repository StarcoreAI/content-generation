import tempfile
import unittest
from pathlib import Path

from services.content_route_analysis import analyze_content_route_article, ingest_content_route_analysis
from services.content_route_library import ContentRouteLibrary


EXCERPT = "文章先把读者真正需要比较的交付维度讲清，再把候选对象放进同一维度里逐项说明。"


def raw():
    return {
        "classification": "对比型",
        "source_evidence": [{"role": "比较框架", "finding": "先建立统一判断维度。", "excerpt": EXCERPT}],
        "route": {"name": "先定维度再比较的路线", "parent_type": "对比型", "reader_task": "帮助读者比较候选对象", "signature": "统一口径", "risk_notes": "", "steps": [{"purpose": "定义维度", "evidence_role": "比较框架", "output_action": "再逐项比较"}]},
        "library_decision": {"eligible": True, "reason": "可核对且可复用。"},
    }


class ContentRouteAnalysisTests(unittest.TestCase):
    def test_only_operator_confirmed_full_article_can_create_route_without_status(self):
        article = {"confirmed_for_route_analysis": True, "url": "https://example.com/a", "title": "文章 A", "content": "前文。" + EXCERPT + "后文。"}
        analysis = analyze_content_route_article({"query": "昆山装修交付"}, article, lambda _prompt, tokens: self.assertEqual(tokens, 4000) or raw())
        with tempfile.TemporaryDirectory() as tmp:
            library = ContentRouteLibrary(Path(tmp))
            entry = ingest_content_route_analysis(analysis, "装修", library)
        self.assertNotIn("status", entry)
        self.assertEqual(entry["sources"][0]["url"], article["url"])

    def test_unconfirmed_article_is_refused_and_second_source_is_explicitly_consolidated(self):
        with self.assertRaisesRegex(ValueError, "confirmed_article_required"):
            analyze_content_route_article({"query": "问题"}, {"url": "https://example.com/a", "content": EXCERPT}, lambda *_args: raw())
        first = {"source": {"url": "https://example.com/a", "title": "A"}, **{key: value for key, value in raw().items() if key != "source_evidence"}, "source_evidence": raw()["source_evidence"]}
        second = {"source": {"url": "https://example.com/b", "title": "B"}, **{key: value for key, value in raw().items() if key != "source_evidence"}, "source_evidence": raw()["source_evidence"]}
        with tempfile.TemporaryDirectory() as tmp:
            library = ContentRouteLibrary(Path(tmp))
            route = ingest_content_route_analysis(first, "装修", library)
            updated = ingest_content_route_analysis(second, "装修", library, route["id"])
        self.assertNotIn("status", updated)


if __name__ == "__main__":
    unittest.main()
