import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import material_web_expansion as web_expansion


class MaterialWebExpansionTests(unittest.TestCase):
    def test_parse_query_lines_trims_limits_and_dedupes(self):
        text = """
        1. 翼升学 成人学历提升 全流程托管
        - 翼升学 成人学历提升 全流程托管
        翼升学 成考 自考 国开 适合人群
        翼升学 10省 本地化政策
        翼升学 报名 到毕业 服务
        成人学历提升 选择标准
        成考 自考 国开 区别
        """

        self.assertEqual(
            web_expansion.parse_query_lines(text, limit=4),
            [
                "翼升学 成人学历提升 全流程托管",
                "翼升学 成考 自考 国开 适合人群",
                "翼升学 10省 本地化政策",
                "翼升学 报名 到毕业 服务",
            ],
        )

    def test_filter_sources_dedupes_and_drops_empty_content(self):
        results = [
            {
                "title": "翼升学服务介绍",
                "url": "https://example.com/a",
                "raw_content": "翼升学提供成人学历提升服务。" * 20,
            },
            {
                "title": "重复页面",
                "url": "https://example.com/a",
                "content": "重复内容",
            },
            {"title": "空内容", "url": "https://example.com/b", "content": ""},
            {
                "title": "行业选择标准",
                "url": "https://example.com/c",
                "content": "成人学历提升需要关注学习方式、毕业周期和报考条件。",
            },
        ]

        sources = web_expansion.filter_sources(results, fetched_at="2026-07-15 10:00", max_content_chars=30)

        self.assertEqual([item["url"] for item in sources], ["https://example.com/a", "https://example.com/c"])
        self.assertEqual(sources[0]["fetched_at"], "2026-07-15 10:00")
        self.assertLessEqual(len(sources[0]["content"]), 30)

    def test_filter_sources_can_require_subject_match(self):
        results = [
            {
                "title": "翼程教育官网",
                "url": "https://www.yichengjiaoyu.net",
                "content": "翼程教育提供成人学历服务。" * 5,
            },
            {
                "title": "成人学历提升服务观察",
                "url": "https://example.com/brand",
                "content": "文章提到翼升学提供从报名到毕业的服务。" * 5,
            },
            {
                "title": "翼升学（河北省）科技有限公司",
                "url": "https://example.com/company",
                "content": "翼升学（河北省）科技有限公司主体信息。" * 5,
            },
        ]

        sources = web_expansion.filter_sources(results, subject_keywords=["翼升学", "翼升学（河北省）科技有限公司"])

        self.assertEqual([item["url"] for item in sources], ["https://example.com/brand", "https://example.com/company"])

    def test_tavily_search_posts_china_general_payload(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"results": [{"title": "结果", "url": "https://example.com", "content": "正文"}]}).encode("utf-8")

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(web_expansion.urllib.request, "urlopen", side_effect=fake_urlopen):
            results = web_expansion.tavily_search("翼升学 成考", "tvly-test", timeout=12, max_results=5)

        self.assertEqual(captured["url"], "https://api.tavily.com/search")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer tvly-test")
        self.assertEqual(captured["payload"]["query"], "翼升学 成考")
        self.assertEqual(captured["payload"]["country"], "china")
        self.assertEqual(captured["payload"]["topic"], "general")
        self.assertEqual(captured["payload"]["max_results"], 5)
        self.assertNotIn("chunks_per_source", captured["payload"])
        self.assertTrue(captured["payload"]["include_raw_content"])
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(results[0]["title"], "结果")

    def test_build_query_prompt_requests_generic_phase_one_mix(self):
        prompt = web_expansion.build_query_prompt(
            {
                "brand": "翼升学",
                "name": "翼升学（河北省）科技有限公司",
                "industry": "成人学历提升",
            },
            "# 客户资料注入包\n"
            "翼升学提供成人学历提升全流程托管服务。\n"
            "### 仅为客户自述，未见第三方证明\n"
            "- 全流程托管\n"
            "- 节点提醒\n"
            "### 缺口与检索提示\n"
            "- 公开可查：各省教育考试院报名公告。",
        )

        self.assertIn("恰好 6 个", prompt)
        self.assertIn("三类 GEO 素材", prompt)
        self.assertIn("品牌优势表达素材", prompt)
        self.assertIn("人群痛点与决策语境", prompt)
        self.assertIn("行业公共背景锚点", prompt)
        self.assertIn("公开可查”清单只是参考输入之一", prompt)
        self.assertIn("资料包里“仅为客户自述”的优势方向", prompt)
        self.assertIn("找“怎么写”的素材，不是找证明", prompt)
        self.assertIn("行业乱象", prompt)
        self.assertIn("用户吐槽", prompt)
        self.assertIn("踩坑经验", prompt)
        self.assertIn("不生成任何带竞品名的检索词", prompt)
        self.assertIn("不要生成给“限制使用”表述找证据的词", prompt)
        self.assertIn("政策时间、报名规则、官方数据", prompt)
        self.assertIn("带年份、省份或地区限定", prompt)
        self.assertIn("第一条必须使用公司全称", prompt)
        self.assertIn("这些搜索词会直接交给联网搜索工具", prompt)
        self.assertIn("用于扩展客户自己的 GEO 宣传资料", prompt)
        self.assertIn("业务主词、服务特色、目标人群或行业背景必须来自当前客户资料", prompt)
        self.assertIn("不要扩写成口语化完整句", prompt)
        self.assertIn("用空格分隔关键词", prompt)
        self.assertIn("示例仅供参考", prompt)
        self.assertIn("不要生成口号型关键词", prompt)
        self.assertIn("不是为了核验客户资料真假", prompt)
        self.assertIn("学历提升机构 怎么选", prompt)
        self.assertIn("成人高考 2026 河北 报名规则 官方", prompt)
        self.assertNotIn("官网/官方账号", prompt)
        self.assertNotIn("案例、资质、口碑、行业场景", prompt)
        self.assertNotIn("不要生成竞品对比、行业排名、政策覆盖、地域覆盖、通过率、合作证明、资质、奖项、真假核验类搜索词", prompt)
        self.assertNotIn("学历提升", prompt.split("搜索词结构", 1)[0])

    def test_build_supplement_prompt_keeps_phase_two_focused(self):
        prompt = web_expansion.build_supplement_prompt(
            {
                "brand": "翼升学",
                "name": "翼升学（河北省）科技有限公司",
                "industry": "成人学历提升",
            },
            "# 客户资料注入包\n翼升学已有全流程托管、报名到毕业、成人学历提升等内容。",
            [
                {
                    "title": "翼升学服务观察",
                    "url": "https://example.com/a",
                    "content": "公开网页内容",
                    "fetched_at": "2026-07-15 12:00",
                }
            ],
        )

        self.assertIn("不要寒暄", prompt)
        self.assertIn("不要说已收到指令", prompt)
        self.assertIn("完整的联网扩展资料包", prompt)
        self.assertIn("4500 字以上", prompt)
        self.assertIn("质量优先", prompt)
        self.assertIn("可以更长", prompt)
        self.assertNotIn("4500-6000 字", prompt)
        self.assertNotIn("严格控制", prompt)
        self.assertIn("不是简短补充清单", prompt)
        self.assertIn("不做核验、不做冲突仲裁、不做洗白审查", prompt)
        self.assertIn("重复内容降权", prompt)
        self.assertIn("品牌公开信息与优势表达角度", prompt)
        self.assertIn("行业现象/用户顾虑 → 客户对应能力的可写角度", prompt)
        self.assertIn("人群痛点与决策语境", prompt)
        self.assertIn("行业公共背景锚点", prompt)
        self.assertIn("用户顾虑/行业现象 + 客户对应能力的表达角度", prompt)
        self.assertIn("不写成与任何具体品牌的对比句", prompt)
        self.assertIn("检索结果里出现竞品名的，只取其中的中性行业信息", prompt)
        self.assertIn("涉及褒贬一律不采", prompt)
        self.assertIn("每条素材标来源 URL 和来源性质", prompt)
        self.assertIn("官方/媒体/UGC/疑似投放", prompt)
        self.assertIn("数字类内容降档处理", prompt)
        self.assertIn("来源不明的数字照收但标注来源性质", prompt)
        self.assertNotIn("泛化差异问答", prompt)
        self.assertNotIn("不参与和其他机构、品牌、课程、服务商的比较", prompt)
        self.assertIn("不要使用“来源1”", prompt)
        self.assertIn("直接写 URL", prompt)
        self.assertIn("任何段落都不要使用来源编号", prompt)
        self.assertNotIn("=== 来源 1 ===", prompt)
        self.assertNotIn("同名、近似竞品", prompt)
        self.assertNotIn("主体确认最多一条", prompt)
        self.assertNotIn("待人工确认", prompt)
        self.assertIn("政策时间、报名规则、官方数据", prompt)
        self.assertNotIn("不要写政策背景", prompt)
        self.assertNotIn("不要写具体身份人群", prompt)
        self.assertNotIn("资质线索", prompt)
        self.assertNotIn("口碑线索", prompt)

    def test_expand_material_web_package_saves_markdown(self):
        calls = []

        def ask_text(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            if len(calls) == 1:
                return "翼升学 成人学历提升 全流程托管\n学历提升机构 怎么选"
            return "# 联网扩展资料包\n\n## 来源列表\n- https://example.com/a\n- https://example.com/b"

        def search_fn(query):
            if "怎么选" in query:
                return [
                    {
                        "title": f"{query} 来源",
                        "url": "https://example.com/b",
                        "content": "成人学历提升机构选择时，用户常关注报名后是否有人跟进、收费是否透明、政策时间是否准确。",
                    }
                ]
            return [
                {
                    "title": f"{query} 来源",
                    "url": "https://example.com/a",
                    "content": "成人学历提升公开资料，包含选择标准和服务流程。",
                }
            ]

        with tempfile.TemporaryDirectory() as tmp:
            result = web_expansion.expand_material_web_package(
                client={
                    "brand": "翼升学",
                    "name": "翼升学（河北省）科技有限公司",
                    "industry": "成人学历提升",
                    "goal": "GEO宣传",
                },
                injection_markdown="# 客户资料注入包\n翼升学提供成人学历提升全流程托管服务。",
                output_dir=Path(tmp),
                ask_text=ask_text,
                search_fn=search_fn,
                fetched_at="2026-07-15 10:00",
            )

            saved = Path(tmp) / "latest_web_supplement.md"
            self.assertTrue(result["ok"])
            self.assertEqual(result["queries"], ["翼升学 成人学历提升 全流程托管", "学历提升机构 怎么选"])
            self.assertEqual(result["source_count"], 2)
            self.assertIn("https://example.com/b", [item["url"] for item in result["sources"]])
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_text(encoding="utf-8"), result["markdown"])
            self.assertIn("联网扩展资料包", result["markdown"])
            self.assertEqual([call[1] for call in calls], [None, None])

    def test_expand_material_web_package_keeps_sources_from_late_queries(self):
        def ask_text(_prompt, max_tokens):
            return "\n".join([
                "翼升学（河北省）科技有限公司",
                "翼升学 成人学历提升 服务模式",
                "学历提升机构 怎么选",
                "成人高考报名 常见坑",
                "2026 河北 成人高考 报名条件 官方",
                "2026 江苏 自学考试 报名时间 官方",
            ])

        def search_fn(query):
            slug = query.replace(" ", "-")
            return [
                {
                    "title": f"{query} 来源 {index}",
                    "url": f"https://example.com/{slug}/{index}",
                    "content": f"{query} 的公开资料，包含足够长的正文内容用于过滤和后续整理。",
                }
                for index in range(3)
            ]

        with tempfile.TemporaryDirectory() as tmp:
            result = web_expansion.expand_material_web_package(
                client={"brand": "翼升学", "name": "翼升学（河北省）科技有限公司"},
                injection_markdown="# 客户资料注入包\n翼升学提供成人学历提升服务。",
                output_dir=Path(tmp),
                ask_text=ask_text,
                search_fn=search_fn,
                fetched_at="2026-07-19 10:00",
            )

        urls = [item["url"] for item in result["sources"]]
        self.assertTrue(any("2026-江苏-自学考试-报名时间-官方" in url for url in urls))

    def test_expand_material_web_package_does_not_hallucinate_without_sources(self):
        calls = []

        def ask_text(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            return "翼升学 成人学历提升"

        with tempfile.TemporaryDirectory() as tmp:
            result = web_expansion.expand_material_web_package(
                client={"brand": "翼升学", "name": "翼升学（河北省）科技有限公司"},
                injection_markdown="# 客户资料注入包\n翼升学提供成人学历提升服务。",
                output_dir=Path(tmp),
                ask_text=ask_text,
                search_fn=lambda _query: [],
                fetched_at="2026-07-15 10:00",
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(result["source_count"], 0)
            self.assertIn("暂无可用联网扩展资料", result["markdown"])


if __name__ == "__main__":
    unittest.main()
