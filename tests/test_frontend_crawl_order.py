import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX_HTML = os.path.join(ROOT, "templates", "index.html")
APP_CSS = os.path.join(ROOT, "static", "css", "app.css")
APP_JS = os.path.join(ROOT, "static", "js", "app.js")


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_index_html():
    return read_file(INDEX_HTML)


def read_frontend_source():
    parts = [read_index_html()]
    for path in (APP_CSS, APP_JS):
        if os.path.exists(path):
            parts.append(read_file(path))
    return "\n".join(parts)


class FrontendCrawlOrderTests(unittest.TestCase):
    def test_content_generation_selects_query_from_a_question_group(self):
        html = read_frontend_source()

        content_page = html.split('id="page-content"', 1)[1].split('id="page-clients"', 1)[0]
        self.assertIn('id="contentGroupSelect"', content_page)
        self.assertIn('id="contentQuerySelect"', content_page)
        self.assertNotIn('id="contentQuery"', content_page)
        self.assertIn('id="useCustomerMaster"', content_page)
        self.assertIn('id="useContentUploads"', content_page)
        self.assertIn('id="contentCompetitorPicker"', content_page)
        self.assertIn("loadContentQueryOptions", html)
        self.assertIn("loadContentCompetitorPicker", html)
        self.assertIn("selectedContentCompetitorNames", html)
        self.assertIn("selected_competitor_names", html)
        self.assertNotIn('id="content-choice-options"', content_page)
    def test_frontend_css_and_js_are_static_assets(self):
        html = read_index_html()

        self.assertIn('href="{{ url_for(\'static\', filename=\'css/app.css\') }}"', html)
        self.assertIn('src="{{ url_for(\'static\', filename=\'js/app.js\') }}"', html)
        self.assertTrue(os.path.exists(APP_CSS))
        self.assertTrue(os.path.exists(APP_JS))
        self.assertNotIn("<style>", html)
        self.assertNotRegex(html, r"<script>\s*//")

    def test_settings_page_can_save_tavily_api_key(self):
        html = read_frontend_source()

        self.assertIn('id="set-tavily-key"', html)
        self.assertIn("has_tavily_key", html)
        self.assertIn("tavily_api_key:tavilyKey||'***'", html)

    def test_frontend_defaults_to_groups_and_removes_retired_modules(self):
        html = read_frontend_source()

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
        html = read_frontend_source()

        self.assertIn("function clearActiveGroupSelection()", html)
        match = re.search(
            r"function onClientChange\(\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        self.assertIn("clearActiveGroupSelection();", match.group("body"))

    def test_crawl_platform_order_puts_doubao_last_for_all_entry_points(self):
        html = read_frontend_source()

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
        html = read_frontend_source()

        self.assertIn('id="grpRepeat"', html)
        self.assertIn('<option value="2">2次</option>', html)

    def test_direct_platform_crawl_frontend_is_removed(self):
        html = read_frontend_source()

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
        html = read_frontend_source()

        self.assertNotIn('id="btnQueueLocalCrawl"', html)
        self.assertIn('id="btnCrawlGroup" onclick="enqueueGroupCrawlJobs()"', html)
        self.assertIn("async function enqueueGroupCrawlJobs()", html)
        self.assertIn("fetch('/api/crawl_jobs'", html)
        self.assertIn("group_id: currentGroupId", html)
        self.assertIn("platform: platform.id", html)
        self.assertIn("repeat_count: repeat", html)
        self.assertIn("const batchId = `batch-${Date.now()}-", html)
        self.assertIn("batch_id: batchId", html)

    def test_group_detail_only_offers_platform_relogin_actions(self):
        html = read_frontend_source()

        self.assertIn("平台重新登录：", html)
        for platform in ["doubao", "deepseek", "yuanbao", "qwen", "kimi"]:
            name = platform[:1].upper() + platform[1:]
            self.assertIn(f'id="btnLogin{name}"', html)
            self.assertIn(f"platformLogin('{platform}')", html)

        self.assertNotIn("检查状态", html)
        self.assertNotIn('id="platformLoginStatus"', html)

        open_group = re.search(
            r"async function openGroup\(gid\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(open_group)
        self.assertNotIn("checkAllLoginStatus", open_group.group("body"))

    def test_group_questions_use_batch_add_textarea(self):
        html = read_frontend_source()

        self.assertIn('id="groupBatchQuestionInput"', html)
        self.assertIn("function parseBatchQuestions", html)
        self.assertIn("async function addBatchQuestions()", html)
        self.assertIn("currentGroupQuestions.push(...additions)", html)
        self.assertIn("new Set(currentGroupQuestions)", html)
        add_batch = re.search(
            r"async function addBatchQuestions\(\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(add_batch)
        self.assertNotIn("prompt(", add_batch.group("body"))

    def test_global_platform_selector_is_removed_for_contract_platform_flow(self):
        html = read_frontend_source()

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

    def test_batch_task_filters_remain_only_in_daily_data_page(self):
        html = read_frontend_source()

        self.assertNotIn('id="rec-task-filter"', html)
        self.assertNotIn('id="dailyTaskFilter"', html)
        self.assertNotIn('id="dailyGroupFilter"', html)
        self.assertIn('data-fixed-scope="daily-group"', html)
        self.assertIn('data-fixed-scope="daily-task"', html)
        self.assertIn("function updateTaskFilterOptions(", html)
        self.assertIn("task_id=${encodeURIComponent(taskId)}", html)
        self.assertIn("task_id: taskId", html)

    def test_daily_insights_sections_are_wired(self):
        html = read_frontend_source()

        self.assertIn('id="dailyAiPlatformCompare"', html)
        self.assertIn('id="dailyCompetitorKnowledgeBtn"', html)
        self.assertIn('id="dailyCompetitorKnowledgeStatus"', html)
        self.assertNotIn('id="dailyEntityMentions"', html)
        self.assertNotIn('id="dailyPlatformBars"', html)
        self.assertNotIn('id="dailyRefPlatformList"', html)
        self.assertIn("async function loadDailyInsights(", html)
        self.assertIn("async function loadDailyTopArticles(", html)
        self.assertNotIn("async function loadDailyRefStats(", html)
        self.assertIn("/api/daily/insights", html)
        self.assertIn("p.ref_platforms", html)
        self.assertIn("来源平台分布", html)
        self.assertNotIn("zero_ref_records", html)

    def test_daily_high_frequency_competitor_extraction_replaces_entity_generation(self):
        html = read_frontend_source()

        self.assertIn("async function extractDailyCompetitorKnowledge(", html)
        self.assertIn("正在从高频引用文章提取竞品资料", html)
        self.assertIn("/api/knowledge/competitors/", html)
        self.assertIn("/sync', 'POST'", html)
        self.assertNotIn('id="dailyEntityGenerateBtn"', html)
        self.assertNotIn("async function generateDailyEntities(", html)
        self.assertNotIn("/api/daily/entities/generate", html)

    def test_reference_intelligence_page_uses_group_query_and_single_platform(self):
        html = read_frontend_source()

        self.assertIn("引用情报分析", html)
        self.assertIn("navTo('reference'", html)
        self.assertIn('id="page-reference"', html)
        self.assertNotIn('id="referencePluginList"', html)
        self.assertIn('id="routeAnalysisGroupSelect"', html)
        self.assertIn('id="routeAnalysisQuerySelect"', html)
        self.assertIn('id="routeAnalysisPlatformSelect"', html)
        self.assertNotIn('id="routeAnalysisUrl"', html)
        self.assertNotIn('id="routeAnalysisQuery"', html)
        self.assertNotIn('id="routeAnalysisTitle"', html)
        self.assertNotIn('id="routeAnalysisContent"', html)
        self.assertNotIn('id="routeAnalysisExisting"', html)
        self.assertNotIn('id="routeAnalysisConfirmed"', html)
        self.assertIn("async function runQueryPlatformReferenceAnalysis(", html)
        self.assertIn("/api/content-routes/analyze-query-platform", html)
        self.assertIn("loadRouteAnalysisQuestionOptions", html)
        self.assertIn("loadRouteAnalysisPlatformOptions", html)
        self.assertIn("async function loadContentRoutes(", html)
        self.assertNotIn('id="referenceAnalyzeProgress"', html)

    def test_content_route_library_is_embedded_in_reference_page_not_navigation(self):
        html = read_frontend_source()

        self.assertNotIn("navTo('pattern-library'", html)
        reference_start = html.index('id="page-reference"')
        reference_end = html.index('id="page-materials"')
        library_start = html.index('id="contentRouteList"')
        self.assertGreater(library_start, reference_start)
        self.assertLess(library_start, reference_end)

    def test_retired_agent_precise_and_platform_compare_frontend_is_removed(self):
        html = read_frontend_source()

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
        html = read_frontend_source()

        self.assertIn("a.ai_platforms", html)
        self.assertIn("CRAWL_PLATFORM_NAMES[pid]", html)

    def test_daily_top_articles_are_grouped_inside_top_articles_section(self):
        html = read_frontend_source()

        self.assertIn("stats.top_articles_by_ai", html)
        self.assertIn("renderDailyTopArticleRows", html)
        self.assertIn("Top20", html)

    def test_daily_top_articles_show_competitor_match_status(self):
        html = read_frontend_source()

        self.assertIn("competitor_match_status", html)
        self.assertIn("competitor_matched_entities", html)
        self.assertIn("提到目标竞品", html)
        self.assertIn("未提到目标竞品", html)
        self.assertIn("正文未确认", html)

    def test_daily_competitor_articles_separate_area_is_removed(self):
        html = read_frontend_source()

        self.assertNotIn("优质竞品宣传文章（人工挑选）", html)
        self.assertNotIn('id="dailyCompetitorArticles"', html)
        self.assertNotIn("function renderDailyCompetitorArticles(", html)
        self.assertNotIn("insights.competitor_articles", html)
        self.assertNotIn("selected_competitors", html)

    def test_daily_kpi_mention_rate_uses_insights_scope(self):
        html = read_frontend_source()

        self.assertIn("insights.mention_rate", html)
        self.assertIn("document.getElementById('dk-mention').textContent", html)

    def test_daily_record_rows_show_platform_and_brand_mention_badge(self):
        html = read_frontend_source()

        match = re.search(
            r"function renderDailyRecord\(r\) \{(?P<body>.*?)\n\}\n\nfunction renderDailyRecordPage",
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("function dailyRecordPlatformName", html)
        self.assertIn("r.source_platform", html)
        self.assertIn("dailyRecordPlatformName", body)
        self.assertIn("品牌已提及", body)
        self.assertIn("brand_mentioned", body)
        self.assertNotIn("未提及", body)
        self.assertNotIn("GEO ${geoScore}", body)

    def test_content_page_uses_simplified_ops_opinion_generation_flow(self):
        html = read_frontend_source()

        self.assertNotIn('id="contentOpinion"', html)
        self.assertNotIn('id="contentSampleLinks"', html)
        self.assertNotIn('id="contentTop20Samples"', html)
        self.assertIn('id="contentMaterialUpload"', html)
        self.assertIn('id="contentMaterialList"', html)
        self.assertIn("loadContentMaterials()", html)
        self.assertIn("uploadContentMaterial(this)", html)
        self.assertIn("delContentMaterial(", html)
        self.assertIn("/api/content/materials/", html)
        self.assertIn('id="contentArticleTypeCompare"', html)
        self.assertIn('id="contentArticleTypeIntro"', html)
        self.assertNotIn('id="contentArticleSubtypeWrap"', html)
        self.assertNotIn('id="contentArticleSubtypes"', html)
        self.assertIn('id="contentHistoryDate"', html)
        self.assertIn("selectContentArticleType('对比型')", html)
        self.assertIn("selectContentArticleType('介绍型')", html)
        self.assertNotIn("loadContentSubtypePlugins()", html)
        self.assertIn("getContentHistoryDate()", html)
        self.assertIn("history_date: getContentHistoryDate()", html)
        self.assertIn("article_type: selectedContentArticleType", html)
        self.assertNotIn("article_subtype: selectedContentArticleSubtype", html)
        self.assertNotIn("article_subtype_plugin: getSelectedContentSubtypePlugin()", html)
        self.assertIn('id="useCustomerMaster"', html)
        self.assertIn('id="useContentUploads"', html)
        self.assertIn("use_customer_master: document.getElementById('useCustomerMaster')?.checked === true", html)
        self.assertIn("use_content_uploads: document.getElementById('useContentUploads')?.checked === true", html)
        self.assertIn("selectedContentArticleType === '对比型'", html)
        self.assertNotIn("<label>对比型子类型</label>", html)
        self.assertNotIn("loadContentTop20Samples()", html)
        self.assertNotIn("getSelectedContentTopArticles()", html)
        self.assertIn("generateContentArticle()", html)
        self.assertIn('id="contentArticleList"', html)
        self.assertIn("const model = escHtml(a.model || '未知模型')", html)
        self.assertIn("调用模型：${model}", html)
        self.assertIn("const articleType = escHtml(a.article_type || '未标记类型')", html)
        self.assertIn("${articleType}", html)
        self.assertNotIn("contentGenerationSubtypeLabel", html)
        self.assertNotIn("子类型：", html)
        self.assertNotIn("文章子类型：", html)
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

    def test_content_generation_cards_escape_ai_text_and_copy_with_fallback(self):
        html = read_frontend_source()

        render_match = re.search(
            r"function renderContentGenerations\(articles\) \{(?P<body>.*?)\n\}\nfunction viewContentGeneration",
            html,
            re.S,
        )
        self.assertIsNotNone(render_match)
        render_body = render_match.group("body")
        self.assertIn("escHtml(a.title || '未命名文章')", render_body)
        self.assertIn("escHtml(a.model || '未知模型')", render_body)
        self.assertIn("escHtml(a.article_type || '未标记类型')", render_body)
        self.assertIn("escHtml((a.content || '').slice(0, 160))", render_body)

        view_match = re.search(
            r"function viewContentGeneration\(id\) \{(?P<body>.*?)\n\}\nfunction copyContentGeneration",
            html,
            re.S,
        )
        self.assertIsNotNone(view_match)
        view_body = view_match.group("body")
        self.assertIn("escHtml(a.title || '生成文章')", view_body)
        self.assertIn("<pre>${escHtml(a.content || '')}</pre>", view_body)

        copy_match = re.search(
            r"function copyContentGeneration\(id\) \{(?P<body>.*?)\n\}\nasync function deleteContentGeneration",
            html,
            re.S,
        )
        self.assertIsNotNone(copy_match)
        self.assertIn("function copyTextToClipboard", html)
        self.assertIn("fallbackCopyText", html)
        self.assertIn("copyTextToClipboard(a.content || '', '文章已复制", copy_match.group("body"))
        self.assertNotIn("navigator.clipboard.writeText(a.content || '').then", html)

    def test_quality_gate_cards_support_copy_and_use_shared_article_cache(self):
        html = read_frontend_source()
        quality_match = re.search(
            r"function renderQualityGateArticles\(articles\) \{(?P<body>.*?)\n\}\nfunction findContentGeneration",
            html,
            re.S,
        )
        self.assertIsNotNone(quality_match)
        self.assertIn("copyContentGeneration('${a.id}')", quality_match.group("body"))
        self.assertIn("人工已编辑", html)

        view_match = re.search(r"function viewContentGeneration\(id\) \{(?P<body>.*?)\n\}\nfunction copyContentGeneration", html, re.S)
        copy_match = re.search(r"function copyContentGeneration\(id\) \{(?P<body>.*?)\n\}\nasync function deleteContentGeneration", html, re.S)
        self.assertIn("findContentGeneration(id)", view_match.group("body"))
        self.assertIn("findContentGeneration(id)", copy_match.group("body"))
        self.assertIn("AI 修改中，含门禁重检（约 1-3 分钟）…", html)
        self.assertIn("确认关闭", html)

    def test_quality_gate_explains_checks_and_verdict_actions(self):
        html = read_frontend_source()

        self.assertIn("banned_words: '禁用词命中'", html)
        self.assertIn("fact_traceability: '数字与主张可溯源'", html)
        self.assertIn("审核提示", html)
        self.assertIn("人工判断", html)
        self.assertIn("可发布", html)

    def test_material_analysis_is_its_own_module_between_reference_and_content(self):
        html = read_frontend_source()

        self.assertLess(html.index("navTo('reference'"), html.index("navTo('materials'"))
        self.assertLess(html.index("navTo('materials'"), html.index("navTo('competitors'"))
        self.assertLess(html.index("navTo('competitors'"), html.index("navTo('content'"))
        self.assertIn('id="page-materials"', html)
        self.assertIn("客户资料解析", html)
        self.assertIn('id="materialUpload"', html)
        self.assertIn("multiple", html)
        self.assertIn(".xlsx", html)
        self.assertIn('id="btnAnalyzeMaterials"', html)
        self.assertIn('id="btnExpandMaterials"', html)
        self.assertIn('id="materialPackageResult"', html)
        self.assertIn('id="materialWebSupplementResult"', html)
        self.assertIn("analyzeMaterialPackage()", html)
        self.assertIn("expandMaterialPackage()", html)
        self.assertIn("loadMaterialPackageResult()", html)
        self.assertIn("loadMaterialWebSupplement()", html)
        self.assertIn("copyMaterialPackageMarkdown()", html)
        self.assertIn("copyMaterialWebSupplementMarkdown()", html)
        self.assertIn("downloadMaterialWebSupplementMarkdown()", html)
        self.assertIn("/analyze-package", html)
        self.assertIn("/package-result", html)
        self.assertIn("/web-supplement", html)
        self.assertIn("/web-supplement.md", html)
        self.assertIn("/injection.md", html)
        self.assertNotIn('id="localMaterialList"', html)
        self.assertNotIn("loadLocalMaterials()", html)
        self.assertNotIn("importSelectedLocalMaterials()", html)
        self.assertNotIn("/api/materials/local", html)
        self.assertNotIn("/import-local", html)
        self.assertNotIn("parseMaterial(", html)
        self.assertNotIn("toggleMaterialUsage(", html)
        self.assertIn("toggleContentMaterialUsage(", html)
        self.assertIn("/confirm", html)
        self.assertIn("delMaterial(", html)
        self.assertIn("materialDisplayStatus(", html)

        materials_page = html.split('id="page-materials"', 1)[1].split('id="page-competitors"', 1)[0]
        self.assertNotIn('id="competitorNames"', materials_page)
        self.assertNotIn('id="competitorUpload"', materials_page)
        self.assertNotIn('id="competitorMaterialResult"', materials_page)

        content_page = html.split('id="page-content"', 1)[1].split('id="page-clients"', 1)[0]
        self.assertNotIn('id="btnAnalyzeMaterials"', content_page)
        self.assertNotIn('id="materialPackageResult"', content_page)
        self.assertNotIn('id="materialWebSupplementResult"', content_page)
        self.assertNotIn('id="btnExpandMaterials"', content_page)

        web_render = re.search(
            r"function renderMaterialWebSupplement\([^)]*\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(web_render)
        self.assertNotIn("result?.queries", web_render.group("body"))
        self.assertNotIn("source_count", web_render.group("body"))

    def test_competitor_material_analysis_is_independent_and_grouped_by_entity(self):
        html = read_frontend_source()

        self.assertIn('id="page-competitors"', html)
        self.assertIn("竞品资料解析", html)
        self.assertIn("if (page === 'competitors') loadCompetitorAnalysis()", html)
        self.assertIn("page-competitors", html)
        self.assertIn('id="competitorNames"', html)
        self.assertIn('id="competitorQualifier"', html)
        self.assertIn('id="competitorUpload"', html)
        self.assertIn('id="competitorMaterialResult"', html)
        self.assertIn("analyzeCompetitorUpload(", html)
        self.assertIn("expandCompetitorWeb()", html)
        self.assertIn("loadCompetitorAnalysis()", html)
        self.assertIn("loadCompetitorEntities()", html)
        self.assertIn("el.dataset.clientId && el.dataset.clientId !== currentClientId", html)
        self.assertIn("el.dataset.clientId = currentClientId", html)
        self.assertIn("/api/competitors/", html)
        self.assertIn("/expand-web", html)
        self.assertIn("/analyze-upload", html)
        self.assertIn("/upload.md", html)
        self.assertIn("/web.md", html)

        competitor_page = html.split('id="page-competitors"', 1)[1].split('id="page-content"', 1)[0]
        self.assertIn("两个 Markdown 文件可分开下载", competitor_page)
        self.assertIn("上传并解析竞品资料", competitor_page)
        self.assertIn("联网搜索竞品资料", competitor_page)
        self.assertIn("重新搜索", html)
        self.assertIn("reSearchCompetitorWeb", html)
        self.assertIn("本次名单已覆盖更新", html)
        self.assertNotIn("已有资料的竞品已跳过", html)
        self.assertIn("/^##(?!#)\\s+\\S/.test(line)", html)

        render_match = re.search(
            r"function renderCompetitorMaterialResult\(result\) \{(?P<body>.*?)\n\}\n\nasync function loadCompetitorResult",
            html,
            re.S,
        )
        self.assertIsNotNone(render_match)
        render_body = render_match.group("body")
        self.assertIn("buildCompetitorEntityGroups", render_body)
        self.assertIn("renderCompetitorEntityGroups", render_body)
        self.assertIn("下载上传.md", render_body)
        self.assertIn("下载联网.md", render_body)
        self.assertNotIn("latestCompetitorUploadMarkdown ? `## 上传资料整理", render_body)

        self.assertIn("function extractCompetitorEntitySections(markdown, entityName)", html)
        self.assertIn("function buildCompetitorEntityGroups(entityNames, uploadMarkdown, webMarkdown)", html)
        self.assertIn("function formatCompetitorEntityGroupsMarkdown(groups)", html)
        self.assertIn("上传资料整理", html)
        self.assertIn("联网资料补充", html)

    def test_retired_content_and_dashboard_api_calls_are_removed(self):
        html = read_frontend_source()

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

    def test_legacy_deep_analysis_frontend_is_removed(self):
        html = read_frontend_source()

        retired_snippets = [
            "/api/raw_records/deep_analyze",
            "/api/daily/deep_analyze",
            "loadDeepAnalysis(",
            "startDailyAnalyze(",
            "renderDailyAnalysis(",
            "showPlatformDetail(",
            "copyDeepReport(",
            "copyDailyReport(",
            "importDailyToContent(",
            "importPlatformPrompt(",
            "copyPlatformPrompt(",
            "dailyAnalysisResult",
            "deepAnalysisCard",
            "dailyTemplateHint",
            "contentInstructionBox",
            "btnDailyAnalyze",
            "spDeep",
        ]
        for snippet in retired_snippets:
            self.assertNotIn(snippet, html)


if __name__ == "__main__":
    unittest.main()
