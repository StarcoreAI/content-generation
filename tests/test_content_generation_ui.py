import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContentGenerationUiTests(unittest.TestCase):
    def test_quality_gate_sidebar_and_article_actions_are_wired(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn('navTo(\'quality\'', template)
        self.assertIn('id="page-quality"', template)
        self.assertIn("renderQualityGateArticles", script)
        self.assertIn("manualEditContentGeneration", script)
        self.assertIn("aiModifyContentGeneration", script)

    def test_content_page_removes_legacy_sample_article_flow(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("优质样例文章", template)
        self.assertNotIn("contentSampleLinks", template)
        self.assertNotIn("contentTop20Samples", template)
        self.assertNotIn("loadContentTop20Samples", script)
        self.assertNotIn("getContentSampleLinks", script)

    def test_content_page_removes_operator_opinion_input(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('id="contentOpinion"', template)
        self.assertNotIn("运营修改意见", template)
        self.assertNotIn("contentOpinion", script)

    def test_content_page_defaults_batch_generation_to_five_and_keeps_single_path(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="contentGenerationCount"', template)
        self.assertIn('value="5" selected', template)
        self.assertIn("generateContentArticle()", script)
        self.assertIn("generateContentBatch", script)
        self.assertIn("/api/content/generate_batch", script)
        self.assertIn("cancelContentBatchGeneration", script)

    def test_content_generation_ui_no_longer_displays_article_subtype(self):
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("contentGenerationSubtypeLabel", script)
        self.assertNotIn("子类型：", script)
        self.assertNotIn("文章子类型：", script)
