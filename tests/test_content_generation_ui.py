import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContentGenerationUiTests(unittest.TestCase):
    def test_distribution_pages_are_independent_navigation_pages(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("navTo('publish'", template)
        self.assertIn("navTo('resources'", template)
        self.assertIn('id="page-publish"', template)
        self.assertIn('id="page-resources"', template)
        self.assertIn("loadPublishPage", script)
        self.assertIn("loadResourcePage", script)

    def test_resource_page_uses_operator_local_catalog(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="distributionCatalogSearch"', template)
        self.assertIn("/api/distribution/catalog", script)

    def test_resource_status_is_shown_as_operator_friendly_text(self):
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function distributionResourceStatusLabel", script)
        self.assertIn("可发布", script)
        self.assertNotIn("状态 ${escHtml(x.status)}", script)

    def test_distribution_ui_selects_and_submits_news_media_type(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("供应商资源库", template)
        self.assertIn("distributionResourceTypeLabel", script)
        self.assertIn("resource_type: resource.resource_type", script)

    def test_resource_page_has_per_operator_distribution_credentials(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="distributionSecretId"', template)
        self.assertIn('id="distributionSecretKey"', template)
        self.assertIn("loadDistributionCredentials", script)
        self.assertIn("/api/distribution/credentials", script)

    def test_resource_page_includes_operator_favorite_list_management(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("我的常用发布平台", template)
        self.assertIn("loadDistributionFavorites", script)
        self.assertIn("/api/distribution/favorites", script)

    def test_resource_page_hides_catalog_sync_control_from_operators(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('onclick="startDistributionCatalogSync()"', template)
        self.assertNotIn('id="resourceList"', template)
        self.assertIn('id="distributionCatalogStatus"', template)
        self.assertIn("loadDistributionCatalogStatus", script)

    def test_resource_page_uses_catalog_search_not_manual_id_matching(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="distributionCatalogSearch"', template)
        self.assertIn("刷新常用平台信息", template)
        self.assertNotIn("匹配供应商资源", template)
        self.assertNotIn("distributionFavoriteResourceId", template)
        self.assertIn("searchDistributionCatalog", script)

    def test_publish_page_supports_direct_article_file_and_folder_upload(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="publicationFileUpload"', template)
        self.assertIn('id="publicationFolderUpload"', template)
        self.assertIn("uploadPublicationFiles", script)
        self.assertIn("/api/distribution/drafts/upload", script)

    def test_publish_page_replaces_order_button_with_supplier_processing_status(self):
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/distribution/orders?client_id=", script)
        self.assertIn("订单已提交，等待供应商处理", script)
        self.assertIn("orderByDraft", script)
        self.assertIn("refreshDistributionOrder", script)

    def test_quality_gate_can_explicitly_create_publish_draft(self):
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("createDistributionDraft", script)
        self.assertIn("/api/distribution/drafts", script)

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
