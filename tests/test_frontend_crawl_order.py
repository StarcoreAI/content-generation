import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX_HTML = os.path.join(ROOT, "templates", "index.html")


class FrontendCrawlOrderTests(unittest.TestCase):
    def test_crawl_platform_order_puts_doubao_last_for_all_entry_points(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn(
            "const CRAWL_PLATFORM_ORDER = ['deepseek', 'yuanbao', 'qwen', 'doubao'];",
            html,
        )
        self.assertIn("function sortCrawlPlatforms(platforms)", html)

        logged_in_body = re.search(
            r"async function getLoggedInCrawlPlatforms\(\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(logged_in_body)
        self.assertIn("return sortCrawlPlatforms(", logged_in_body.group("body"))

        target_body = re.search(
            r"async function getTargetCrawlPlatforms\(scope='current'\) \{(?P<body>.*?)\n\}",
            html,
            re.S,
        )
        self.assertIsNotNone(target_body)
        self.assertIn("getSelectedGroupCrawlPlatformIds()", target_body.group("body"))

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
        self.assertNotIn('id="dailyRefPlatformList"', html)
        self.assertIn("async function loadDailyInsights(", html)
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

    def test_daily_top_articles_show_ai_platform_coverage(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("a.ai_platforms", html)
        self.assertIn("CRAWL_PLATFORM_NAMES[pid]", html)

    def test_daily_top_articles_show_competitor_match_status(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("competitor_match_status", html)
        self.assertIn("competitor_matched_entities", html)
        self.assertIn("提到目标竞品", html)
        self.assertIn("未提到目标竞品", html)
        self.assertIn("正文未确认", html)

    def test_daily_competitor_articles_have_separate_render_area(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("优质竞品宣传文章（人工挑选）", html)
        self.assertIn('id="dailyCompetitorArticles"', html)
        self.assertIn("function renderDailyCompetitorArticles(", html)
        self.assertIn("insights.competitor_articles", html)
        self.assertIn("selected_competitors", html)

    def test_daily_kpi_mention_rate_uses_insights_scope(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("insights.mention_rate", html)
        self.assertIn("document.getElementById('dk-mention').textContent", html)

    def test_content_page_uses_simplified_ops_opinion_generation_flow(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="contentOpinion"', html)
        self.assertIn('id="contentSampleLinks"', html)
        self.assertIn('id="contentTop20Samples"', html)
        self.assertIn("loadContentTop20Samples()", html)
        self.assertIn("getSelectedContentTopArticles()", html)
        self.assertIn("generateContentArticle()", html)
        self.assertIn('id="contentArticleList"', html)
        self.assertIn("/api/content/generate", html)
        self.assertIn("/api/content/generations", html)
        self.assertIn("/api/daily/ref_stats", html)
        self.assertNotIn('id="ct-topics"', html)
        self.assertNotIn('id="ct-platform-checks"', html)
        self.assertNotIn('id="ct-brand"', html)
        self.assertNotIn('id="topicInstruction"', html)


if __name__ == "__main__":
    unittest.main()
