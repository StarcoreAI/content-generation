import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX_HTML = os.path.join(ROOT, "templates", "index.html")


class FrontendCrawlOrderTests(unittest.TestCase):
    def test_frontend_defaults_to_groups_and_removes_retired_modules(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('class="page on" id="page-groups"', html)
        self.assertNotIn('class="page on" id="page-dashboard"', html)
        for retired in [
            "数据总览",
            "AI引用情报",
            "数据看板",
            "平台库工具箱",
            "page-dashboard",
            "page-intel",
            "page-dashboard_full",
            "page-platform",
            "navTo('dashboard'",
            "navTo('intel'",
            "navTo('dashboard_full'",
            "navTo('platform'",
        ]:
            self.assertNotIn(retired, html)

    def test_client_switch_clears_open_group_detail(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("function clearActiveGroupSelection()", html)
        match = re.search(
            r"function onClientChange\(\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        self.assertIn("clearActiveGroupSelection();", match.group("body"))

    def test_crawl_platform_order_puts_doubao_last_for_all_entry_points(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn(
            "const CRAWL_PLATFORM_ORDER = ['deepseek', 'yuanbao', 'qwen', 'kimi', 'doubao'];",
            html,
        )
        self.assertIn("kimi:'Kimi'", html)
        self.assertIn("function sortCrawlPlatforms(platforms)", html)

        job_choice_body = re.search(
            r"function getGroupCrawlPlatformChoicesForJobs\(\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(job_choice_body)
        self.assertIn("return sortCrawlPlatforms(", job_choice_body.group("body"))
        self.assertIn("getSelectedGroupCrawlPlatformIds()", job_choice_body.group("body"))

    def test_group_crawl_repeat_selector_includes_two_rounds(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="grpRepeat"', html)
        self.assertIn('<option value="2">2次</option>', html)

    def test_direct_platform_crawl_frontend_is_removed(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        for retired in [
            "CRAWL_PLATFORM_CONCURRENCY",
            "async function runCrawlPlatformPool(",
            "async function runGroupCrawlForPlatform(",
            "function getLoggedInCrawlPlatforms()",
            "function getTargetCrawlPlatforms(",
            "fetch('/api/platform/crawl'",
        ]:
            self.assertNotIn(retired, html)

    def test_group_crawl_can_enqueue_local_worker_jobs(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertNotIn('id="btnQueueLocalCrawl"', html)
        self.assertIn('id="btnCrawlGroup" onclick="enqueueGroupCrawlJobs()"', html)
        self.assertIn("async function enqueueGroupCrawlJobs()", html)
        self.assertIn("fetch('/api/crawl_jobs'", html)
        self.assertIn("group_id: currentGroupId", html)
        self.assertIn("platform: platform.id", html)
        self.assertIn("repeat_count: repeat", html)

    def test_group_questions_use_batch_add_textarea(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="groupBatchQuestionInput"', html)
        self.assertIn("function parseBatchQuestions", html)
        self.assertIn("async function addBatchQuestions()", html)
        self.assertIn("currentGroupQuestions.push(...additions)", html)
        self.assertIn("new Set(currentGroupQuestions)", html)
        self.assertNotIn("prompt(", html)

    def test_global_platform_selector_is_removed_for_contract_platform_flow(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertNotIn('id="globalPlatform"', html)
        self.assertNotIn("onPlatformChange()", html)
        self.assertNotIn("顶部当前平台", html)
        self.assertNotIn('id="grpPlatformScope"', html)
        self.assertIn('id="cl-platforms"', html)
        self.assertIn('id="grpPlatformModeContract"', html)
        self.assertIn('id="grpPlatformModeCustom"', html)
        self.assertIn('id="grpPlatformChoices"', html)
        self.assertIn("groupPlatformMode", html)
        self.assertIn("contract_platforms", html)
        self.assertIn("saveClientPlatforms", html)

    def test_batch_task_filters_are_wired_into_records_and_daily_pages(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="rec-task-filter"', html)
        self.assertNotIn('id="dailyTaskFilter"', html)
        self.assertNotIn('id="dailyGroupFilter"', html)
        self.assertIn('data-fixed-scope="daily-group"', html)
        self.assertIn('data-fixed-scope="daily-task"', html)
        self.assertIn("function updateTaskFilterOptions(", html)
        self.assertIn("task_id=${encodeURIComponent(taskId)}", html)
        self.assertIn("task_id: taskId", html)

    def test_daily_insights_sections_are_wired(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="dailyAiPlatformCompare"', html)
        self.assertIn('id="dailyEntityMentions"', html)
        self.assertNotIn('id="dailyPlatformBars"', html)
        self.assertNotIn('id="dailyRefPlatformList"', html)
        self.assertIn("async function loadDailyInsights(", html)
        self.assertIn("async function loadDailyTopArticles(", html)
        self.assertNotIn("async function loadDailyRefStats(", html)
        self.assertIn("/api/daily/insights", html)
        self.assertIn("p.ref_platforms", html)
        self.assertIn("来源平台分布", html)
        self.assertNotIn("zero_ref_records", html)

    def test_daily_entity_mentions_can_be_deleted_from_aggregate_list(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("function renderDailyEntityDeleteButton(", html)
        self.assertIn("async function deleteDailyEntity(", html)
        self.assertIn("/api/daily/entities/delete", html)
        self.assertIn("renderDailyEntityDeleteButton(e.name)", html)
        self.assertIn("deleteDailyEntity(decodeURIComponent", html)

    def test_daily_entity_status_is_shown_near_mentions(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="dailyEntityStatus"', html)
        self.assertIn("async function loadDailyEntityStatus(", html)
        self.assertIn("function renderDailyEntityStatus(", html)
        self.assertIn("/api/daily/entity_status", html)
        self.assertIn("实体识别", html)

    def test_reference_intelligence_page_is_wired(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("引用情报分析", html)
        self.assertIn("navTo('reference'", html)
        self.assertIn('id="page-reference"', html)
        self.assertIn('id="referencePluginList"', html)
        self.assertIn("async function loadReferenceIntelligence(", html)
        self.assertIn("async function analyzeReferenceIntelligence(", html)
        self.assertIn("/api/reference_intelligence/plugins", html)
        self.assertIn("/api/reference_intelligence/analyze", html)
        self.assertIn("/api/reference_intelligence/analyze_status", html)
        self.assertIn("/api/reference_intelligence/analyze_cancel", html)
        self.assertIn("subtype_name", html)
        self.assertIn("prompt_text", html)
        self.assertIn("few_shot", html)
        self.assertIn("source_articles", html)
        self.assertIn("基于", html)
        self.assertIn("篇文章合并", html)
        self.assertIn('id="referenceAnalyzeProgress"', html)
        self.assertIn("cancelReferenceAnalysis", html)

    def test_retired_agent_precise_and_platform_compare_frontend_is_removed(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        for retired in [
            "agentBall",
            "agentPanel",
            "agentState",
            "/api/agent/",
            "/api/precise/",
            "/api/platform/compare",
            "loadPlatformCompare",
            "compareChart",
            "crawlByGroup",
            "autoCheckPlatforms",
        ]:
            self.assertNotIn(retired, html)

    def test_daily_top_articles_show_ai_platform_coverage(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("a.ai_platforms", html)
        self.assertIn("CRAWL_PLATFORM_NAMES[pid]", html)

    def test_daily_top_articles_are_grouped_inside_top_articles_section(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("stats.top_articles_by_ai", html)
        self.assertIn("renderDailyTopArticleRows", html)
        self.assertIn("Top12", html)

    def test_daily_top_articles_show_competitor_match_status(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("competitor_match_status", html)
        self.assertIn("competitor_matched_entities", html)
        self.assertIn("提到目标竞品", html)
        self.assertIn("未提到目标竞品", html)
        self.assertIn("正文未确认", html)

    def test_daily_competitor_articles_separate_area_is_removed(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertNotIn("优质竞品宣传文章（人工挑选）", html)
        self.assertNotIn('id="dailyCompetitorArticles"', html)
        self.assertNotIn("function renderDailyCompetitorArticles(", html)
        self.assertNotIn("insights.competitor_articles", html)
        self.assertNotIn("selected_competitors", html)

    def test_daily_kpi_mention_rate_uses_insights_scope(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("insights.mention_rate", html)
        self.assertIn("document.getElementById('dk-mention').textContent", html)

    def test_daily_record_rows_do_not_show_mention_or_geo_badges(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        match = re.search(
            r"function renderDailyRecord\(r\) \{(?P<body>.*?)\n\}\n\nfunction renderDailyRecordPage",
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertNotIn("未提及", body)
        self.assertNotIn("已提及", body)
        self.assertNotIn("GEO ${geoScore}", body)
        self.assertNotIn("brand_mentioned", body)

    def test_content_page_uses_simplified_ops_opinion_generation_flow(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="contentOpinion"', html)
        self.assertIn('id="contentSampleLinks"', html)
        self.assertIn('id="contentTop20Samples"', html)
        self.assertIn('id="contentArticleTypeCompare"', html)
        self.assertIn('id="contentArticleTypeIntro"', html)
        self.assertIn('id="contentArticleSubtypeWrap"', html)
        self.assertIn('id="contentArticleSubtypes"', html)
        self.assertIn("文章子类型", html)
        self.assertIn("parent_type", html)
        self.assertIn("filter(p => (p.parent_type || '对比型') === selectedContentArticleType)", html)
        self.assertIn("攻略对比型", html)
        self.assertIn('id="contentHistoryDate"', html)
        self.assertIn("selectContentArticleType('对比型')", html)
        self.assertIn("selectContentArticleType('介绍型')", html)
        self.assertIn("loadContentSubtypePlugins()", html)
        self.assertIn("/api/reference_intelligence/plugins", html)
        self.assertIn("getContentHistoryDate()", html)
        self.assertIn("history_date: getContentHistoryDate()", html)
        self.assertIn("article_type: selectedContentArticleType", html)
        self.assertIn("article_subtype: selectedContentArticleSubtype", html)
        self.assertIn("article_subtype_plugin: getSelectedContentSubtypePlugin()", html)
        self.assertNotIn("selectedContentArticleType !== '对比型'", html)
        self.assertNotIn("<label>对比型子类型</label>", html)
        self.assertIn("loadContentTop20Samples()", html)
        self.assertIn("getSelectedContentTopArticles()", html)
        self.assertIn("generateContentArticle()", html)
        self.assertIn('id="contentArticleList"', html)
        self.assertIn("调用模型：${a.model || '未知模型'}", html)
        self.assertIn("${a.article_type || '未标记类型'}", html)
        self.assertIn("function contentGenerationSubtypeLabel(a)", html)
        self.assertIn("子类型：${escHtml(subtypeLabel)}", html)
        self.assertIn("文章子类型：${escHtml(subtypeLabel)}", html)
        self.assertIn("deleteContentGeneration('${a.id}')", html)
        self.assertIn("async function deleteContentGeneration(id)", html)
        self.assertIn("'/api/content/generations/' + encodeURIComponent(id)", html)
        self.assertIn("/api/content/generate", html)
        self.assertIn("/api/content/generations", html)
        self.assertIn("/api/daily/ref_stats", html)
        self.assertNotIn('id="ct-topics"', html)
        self.assertNotIn('id="ct-platform-checks"', html)
        self.assertNotIn('id="ct-brand"', html)
        self.assertNotIn('id="topicInstruction"', html)

    def test_content_material_library_auto_parses_and_only_exposes_delete(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="materialUpload"', html)
        self.assertIn("multiple", html)
        self.assertIn('id="localMaterialList"', html)
        self.assertIn("loadLocalMaterials()", html)
        self.assertIn("importSelectedLocalMaterials()", html)
        self.assertIn("/api/materials/local", html)
        self.assertIn("/import-local", html)
        self.assertNotIn("parseMaterial(", html)
        self.assertNotIn("confirmMaterial(", html)
        self.assertIn("delMaterial(", html)
        self.assertIn("materialDisplayStatus(", html)

    def test_retired_content_and_dashboard_api_calls_are_removed(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        retired_snippets = [
            "/api/articles",
            "/api/intel/",
            "/api/platforms",
            "/api/stats/",
            "/api/content/gen_topics",
            "batchGenerate(",
            "loadArticles(",
            "setStatus(",
            "formatArticle(",
            "viewArticle(",
            "delArticle(",
            "genSmartTopics(",
            "ct-topics",
            "ct-platform-checks",
            "art-filter",
            "articleList",
            "formatModal",
        ]
        for snippet in retired_snippets:
            self.assertNotIn(snippet, html)


if __name__ == "__main__":
    unittest.main()
