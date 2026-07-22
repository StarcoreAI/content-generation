import tempfile
import unittest
import json
from pathlib import Path


class CompetitorMaterialsTests(unittest.TestCase):
    def test_build_search_queries_uses_manual_qualifier_before_client_industry(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(
            ["第一竞品", "第二竞品"],
            {"industry": "教育"},
            qualifier="成人学历提升",
        )

        self.assertEqual([item["query"] for item in queries], [
            "第一竞品 成人学历提升", "第一竞品 怎么样 靠谱", "第一竞品 简介",
            "第二竞品 成人学历提升", "第二竞品 怎么样 靠谱", "第二竞品 简介",
        ])

    def test_build_search_queries_falls_back_to_client_industry(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(["第一竞品"], {"industry": "汽车音响"}, qualifier="")

        self.assertEqual([item["query"] for item in queries], [
            "第一竞品 汽车音响", "第一竞品 怎么样 靠谱", "第一竞品 简介",
        ])

    def test_build_search_queries_prefers_client_category_before_industry(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(
            ["第一竞品"],
            {"category": "成人学历提升", "industry": "教育"},
            qualifier="",
        )

        self.assertEqual([item["query"] for item in queries], [
            "第一竞品 成人学历提升", "第一竞品 怎么样 靠谱", "第一竞品 简介",
        ])

    def test_build_search_queries_uses_competitor_name_without_scope(self):
        from services.competitor_materials import build_competitor_search_queries

        queries = build_competitor_search_queries(["第一竞品"], {}, qualifier="")

        self.assertEqual([item["query"] for item in queries], [
            "第一竞品", "第一竞品 怎么样 靠谱", "第一竞品 简介",
        ])

    def test_generated_search_queries_use_industry_and_business_angles(self):
        from services.competitor_materials import generate_competitor_search_queries

        prompts = []

        def ask_text(prompt, max_tokens):
            prompts.append((prompt, max_tokens))
            return "\n".join([
                "第一竞品 | 第一竞品 成人学历提升 服务流程",
                "第一竞品 | 第一竞品 成人学历提升 项目案例",
                "第二竞品 | 第二竞品 成人学历提升 课程服务",
            ])

        queries = generate_competitor_search_queries(
            ["第一竞品", "第二竞品"],
            {"industry": "教育", "category": "成人学历提升"},
            qualifier="",
            ask_text=ask_text,
            customer_context="# 客户资料注入包\n\n## 产品与服务\n- 提供报名规划、学习支持和节点提醒服务。",
            competitor_context="## 第一竞品\n- 昆山校区提供线下咨询和课程服务。",
        )

        self.assertEqual([item["query"] for item in queries], [
            "第一竞品 成人学历提升 服务流程",
            "第一竞品 成人学历提升 项目案例",
            "第二竞品 成人学历提升 课程服务",
        ])
        self.assertEqual(len(prompts), 1)
        self.assertIn("行业/品类", prompts[0][0])
        self.assertIn("业务、服务、项目、案例、流程", prompts[0][0])
        self.assertIn("报名规划、学习支持和节点提醒服务", prompts[0][0])
        self.assertIn("昆山校区提供线下咨询和课程服务", prompts[0][0])
        self.assertIn("客户资料只用于识别同行业的业务场景", prompts[0][0])
        self.assertIn("只取与该行竞品名称相同的分节", prompts[0][0])

    def test_generated_search_queries_fall_back_when_llm_output_is_invalid(self):
        from services.competitor_materials import generate_competitor_search_queries

        queries = generate_competitor_search_queries(
            ["第一竞品"], {"industry": "教育"}, qualifier="",
            ask_text=lambda *_args: "无法生成",
        )

        self.assertEqual([item["query"] for item in queries], [
            "第一竞品 教育", "第一竞品 怎么样 靠谱", "第一竞品 简介",
        ])

    def test_analyze_upload_package_writes_markdown_with_competitor_prompt_rules(self):
        from services.competitor_materials import analyze_competitor_upload_package

        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "package"
            output_dir = Path(tmp) / "out"
            package_dir.mkdir()
            (package_dir / "competitors.txt").write_text(
                "第一竞品主打本地服务。\n第二竞品公开资料强调流程透明。",
                encoding="utf-8",
            )
            prompts = []

            def ask_text(prompt, max_tokens):
                prompts.append(prompt)
                return "# 竞品上传资料整理包\n\n## 第一竞品\n- 主打本地服务。"

            result = analyze_competitor_upload_package(
                package_dir,
                output_dir,
                ["第一竞品", "第二竞品"],
                ask_text=ask_text,
            )

        self.assertTrue(result["ok"])
        self.assertIn("第一竞品", result["markdown"])
        self.assertEqual(len(prompts), 1)
        self.assertIn("竞品名称必须使用资料中出现的真实品牌名", prompts[0])
        self.assertIn("无法确定是否同一主体时，直接分开整理，不要猜测关系", prompts[0])
        self.assertIn("只客观整理其定位、业务侧重、适合人群、服务特点、限制和来源依据", prompts[0])
        self.assertIn("每个竞品的第一行用一句话概括定位与业务侧重", prompts[0])
        self.assertIn("宣传主张（仅记录，禁止在我方内容中复述）", prompts[0])
        self.assertIn("内部观点备注（仅内部参考，不入内容）", prompts[0])
        self.assertNotIn("疑似同主体", prompts[0])

    def test_expand_web_package_overwrites_requested_competitors_on_every_normal_search(self):
        from services.competitor_materials import expand_competitor_web_package

        calls = []
        prompts = []

        def search_fn(query):
            calls.append(query)
            name = query.split()[0]
            return [
                {"title": f"{name} 官网", "url": f"https://example.com/{name}/1", "content": f"{name} 服务介绍，公开页面包含足够正文内容。"},
                {"title": f"{name} 业务", "url": f"https://example.com/{name}/2", "content": f"{name} 业务范围，公开页面包含足够正文内容。"},
                {"title": f"{name} 多余", "url": f"https://example.com/{name}/3", "content": f"{name} 多余来源，公开页面包含足够正文内容。"},
            ]

        def ask_text(prompt, max_tokens):
            prompts.append((prompt, max_tokens))
            name = "第一竞品" if "第一竞品" in prompt else "第二竞品"
            return f"## {name}\n- 页面介绍。"

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            result = expand_competitor_web_package(
                {"industry": "教育"},
                ["第一竞品", "第二竞品"],
                qualifier="成人学历提升",
                output_dir=output_dir,
                ask_text=ask_text,
                search_fn=search_fn,
                fetched_at="2026-07-16 12:00",
            )
            markdown = (output_dir / "latest_web_competitors.md").read_text(encoding="utf-8")
            sources = json.loads((output_dir / "latest_web_sources.json").read_text(encoding="utf-8"))
            rerun = expand_competitor_web_package(
                {"industry": "教育"}, ["第一竞品", "第二竞品"],
                qualifier="成人学历提升", output_dir=output_dir, ask_text=ask_text,
                search_fn=search_fn, fetched_at="2026-07-16 12:01",
            )

        self.assertEqual(len(calls), 12)
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], ["第一竞品", "第二竞品"])
        self.assertEqual(result["source_count"], 6)
        self.assertEqual([item["source_count"] for item in result["competitors"]], [3, 3])
        self.assertIn("## 第一竞品", markdown)
        self.assertIn("## 第二竞品", markdown)
        self.assertEqual(set(sources["competitors"]), {"第一竞品", "第二竞品"})
        query_prompts = [(prompt, tokens) for prompt, tokens in prompts if "竞品联网检索词策划助手" in prompt]
        summary_prompts = [(prompt, tokens) for prompt, tokens in prompts if "竞品公开资料整理助手" in prompt]
        self.assertEqual(len(query_prompts), 2)
        self.assertTrue(all(tokens == 1600 for _prompt, tokens in query_prompts))
        self.assertEqual(len(summary_prompts), 4)
        self.assertTrue(all(tokens >= 4000 for _prompt, tokens in summary_prompts))
        self.assertIn("资料允许时写充分的结构化条目", summary_prompts[0][0])
        self.assertNotIn("300-800 字", summary_prompts[0][0])
        self.assertNotIn("宣传主张（仅记录，禁止在我方内容中复述）", summary_prompts[0][0])
        self.assertNotIn("来源没有的维度不要硬凑", summary_prompts[0][0])
        self.assertNotIn("重要信息必须带 URL", summary_prompts[0][0])
        self.assertNotIn("疑似投放来源的内容不作为该竞品的事实", summary_prompts[0][0])
        self.assertEqual(len(calls), 12)
        self.assertEqual(len(prompts), 6)
        self.assertEqual(rerun["skipped"], [])
        self.assertEqual(rerun["updated"], ["第一竞品", "第二竞品"])

    def test_expand_web_package_appends_force_replaces_and_keeps_failed_competitor_unchanged(self):
        from services.competitor_materials import expand_competitor_web_package

        def search_fn(query):
            if query.startswith("失败机构"):
                raise RuntimeError("search failed")
            name = query.split()[0]
            return [{"title": name, "url": f"https://example.com/{name}/{len(query)}", "content": f"{name} 的公开资料内容足够长，可用于竞品资料整理和后续描述。"}]

        def ask_text(prompt, _max_tokens):
            name = next(name for name in ["旧机构", "新机构"] if name in prompt)
            return f"## {name}\n- {name} 最新资料。"

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "latest_web_competitors.md").write_text(
                "# 竞品联网资料补充包\n\n## 旧机构\n- 旧资料。\n\n## 名称/特殊机构(测试)\n- 保留资料。\n",
                encoding="utf-8",
            )
            (output_dir / "latest_web_sources.json").write_text(json.dumps({"competitors": {"旧机构": {"queries": [], "sources": [], "fetched_at": "旧"}}}), encoding="utf-8")
            added = expand_competitor_web_package(
                {}, ["新机构", "失败机构"], "", output_dir, ask_text, search_fn,
                fetched_at="2026-07-16 12:00",
            )
            forced = expand_competitor_web_package(
                {}, ["旧机构"], "", output_dir, ask_text, search_fn,
                fetched_at="2026-07-16 12:01", force=["旧机构"],
            )
            markdown = (output_dir / "latest_web_competitors.md").read_text(encoding="utf-8")
            sources = json.loads((output_dir / "latest_web_sources.json").read_text(encoding="utf-8"))

        self.assertEqual(added["updated"], ["新机构"])
        self.assertEqual(added["failed"], ["失败机构"])
        self.assertEqual(forced["updated"], ["旧机构"])
        self.assertIn("## 新机构", markdown)
        self.assertIn("## 旧机构\n- 旧机构 最新资料。", markdown)
        self.assertNotIn("## 名称/特殊机构(测试)\n- 保留资料。", markdown)
        self.assertNotIn("## 失败机构", markdown)
        self.assertIn("旧机构", sources["competitors"])
        self.assertIn("新机构", sources["competitors"])
        self.assertNotIn("失败机构", sources["competitors"])

    def test_web_competitor_prompts_require_declarative_sentences(self):
        from services.competitor_materials import build_upload_competitor_prompt, build_web_competitor_prompt

        upload_prompt = build_upload_competitor_prompt(["机构A"], [{"text": "机构A资料", "path": "a.txt", "unit_id": "a"}])
        web_prompt = build_web_competitor_prompt({}, {"name": "机构A", "sources": []})

        self.assertIn("直接陈述句", upload_prompt)
        self.assertIn("直接陈述句", web_prompt)
        self.assertNotIn("宣传主张（仅记录，禁止在我方内容中复述）", web_prompt)
        self.assertNotIn("来源没有的维度不要硬凑", web_prompt)
        self.assertNotIn("重要信息必须带 URL", web_prompt)
        self.assertIn("4. 正文描述统一使用直接陈述句", web_prompt)
        self.assertNotIn("来源性质只保留在链接标注里", web_prompt)
        self.assertIn("不得输出链接、URL、来源标签或来源说明", web_prompt)
        self.assertNotIn("不采信", web_prompt)

    def test_web_competitor_prompt_includes_short_sources_when_fewer_than_three_long_sources(self):
        from services.competitor_materials import build_web_competitor_prompt

        web_prompt = build_web_competitor_prompt({}, {
            "name": "机构A",
            "sources": [
                {
                    "title": "长正文来源",
                    "url": "https://example.com/long",
                    "content": "机构A 的服务流程、项目案例和售后安排。" * 20,
                },
                {
                    "title": "短摘要来源",
                    "url": "https://example.com/short",
                    "content": "机构A 简短摘要。",
                },
            ],
        })

        self.assertIn("【可展开来源】", web_prompt)
        self.assertIn("机构A 的服务流程、项目案例和售后安排", web_prompt)
        self.assertNotIn("链接线索", web_prompt)
        self.assertNotIn("https://example.com/long", web_prompt)
        self.assertNotIn("https://example.com/short", web_prompt)
        self.assertIn("正文片段：机构A 简短摘要。", web_prompt)
        self.assertIn("不为了简洁省略", web_prompt)
        self.assertIn("不得输出链接、URL、来源标签或来源说明", web_prompt)

    def test_web_competitor_prompt_excludes_short_sources_when_at_least_three_long_sources(self):
        from services.competitor_materials import build_web_competitor_prompt

        web_prompt = build_web_competitor_prompt({}, {
            "name": "机构A",
            "sources": [
                {"title": f"长正文来源{i}", "content": "机构A 的服务流程和售后安排。" * 20}
                for i in range(3)
            ] + [{"title": "短摘要来源", "content": "机构A 简短摘要。"}],
        })

        self.assertIn("长正文来源0", web_prompt)
        self.assertNotIn("正文片段：机构A 简短摘要。", web_prompt)

    def test_competitor_section_removes_comparison_guidance_subsection(self):
        from services.competitor_materials import _competitor_section

        markdown = _competitor_section("机构A", """## 机构A

- 提供成人学历提升咨询服务。[官网](https://example.com)

### 适合对比关注的维度
- 可比较价格、服务和口碑。

### 来源
- [官网](https://example.com)
""")

        self.assertIn("提供成人学历提升咨询服务", markdown)
        self.assertIn("### 来源", markdown)
        self.assertNotIn("适合对比关注的维度", markdown)
        self.assertNotIn("可比较价格、服务和口碑", markdown)

    def test_expand_web_package_reports_all_failed_without_writing_a_shell(self):
        from services.competitor_materials import expand_competitor_web_package

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            result = expand_competitor_web_package(
                {}, ["失败机构"], "", output_dir,
                ask_text=lambda *_args: self.fail("empty searches must not call ask_text"),
                search_fn=lambda _query: [], fetched_at="2026-07-16 12:00",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["failed"], ["失败机构"])
        self.assertEqual(result["markdown"], "")
        self.assertFalse((output_dir / "latest_web_competitors.md").exists())

    def test_expand_web_package_keeps_other_competitors_when_one_llm_call_fails(self):
        from services.competitor_materials import expand_competitor_web_package

        def search_fn(query):
            name = query.split()[0]
            return [{"title": name, "url": f"https://example.com/{name}/{len(query)}", "content": f"{name} 的公开资料内容足够长，可用于竞品资料整理和后续描述。"}]

        def ask_text(prompt, _max_tokens):
            if "失败机构" in prompt:
                raise RuntimeError("llm failed")
            return "## 成功机构\n- 成功资料。"

        with tempfile.TemporaryDirectory() as tmp:
            result = expand_competitor_web_package(
                {}, ["成功机构", "失败机构"], "", Path(tmp), ask_text, search_fn,
                fetched_at="2026-07-16 12:00",
            )

        self.assertEqual(result["updated"], ["成功机构"])
        self.assertEqual(result["failed"], ["失败机构"])

    def test_expand_web_package_rejects_heading_only_model_output(self):
        from services.competitor_materials import expand_competitor_web_package

        with tempfile.TemporaryDirectory() as tmp:
            result = expand_competitor_web_package(
                {}, ["空壳机构"], "", Path(tmp),
                ask_text=lambda *_args: "## 空壳机构",
                search_fn=lambda _query: [{
                    "title": "公开资料", "url": "https://example.com/source",
                    "content": "空壳机构的公开资料内容足够长，可用于竞品资料整理。" * 10,
                }],
                fetched_at="2026-07-16 12:00",
            )

        self.assertEqual(result["updated"], [])
        self.assertEqual(result["failed"], ["空壳机构"])

    def test_expand_web_package_writes_run_report_with_query_search_and_summary_details(self):
        from services.competitor_materials import expand_competitor_web_package

        def ask_text(prompt, max_tokens):
            if "竞品联网检索词策划助手" in prompt:
                return "甲机构 | 甲机构 装修服务"
            if "甲机构" in prompt:
                return "## 甲机构\n- 甲机构提供装修服务。"
            raise RuntimeError("summary unavailable")

        def search_fn(query):
            if query.startswith("乙机构"):
                raise RuntimeError("tavily timeout")
            return [
                {"title": "甲机构官网", "url": "https://example.com/accepted", "content": "甲机构的公开服务资料足够长，可用于整理。"},
                {"title": "无关页面", "url": "https://example.com/rejected", "content": "这是一段足够长但没有竞品名称的内容。"},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            result = expand_competitor_web_package(
                {"industry": "家装"}, ["甲机构", "乙机构"], "", output_dir,
                ask_text, search_fn, fetched_at="2026-07-22 18:51",
            )
            report = json.loads((output_dir / "latest_web_run_report.json").read_text(encoding="utf-8"))

        self.assertEqual(result["updated"], ["甲机构"])
        self.assertEqual(result["failed"], ["乙机构"])
        self.assertEqual(report["query_generation"]["raw_output"], "甲机构 | 甲机构 装修服务")
        self.assertEqual(report["competitors"]["甲机构"]["searches"][0]["raw_result_count"], 2)
        self.assertEqual(report["competitors"]["甲机构"]["searches"][0]["selected_source_count"], 1)
        self.assertEqual(report["competitors"]["甲机构"]["summary"]["raw_output"], "## 甲机构\n- 甲机构提供装修服务。")
        self.assertEqual(report["competitors"]["乙机构"]["status"], "failed")
        self.assertEqual(report["competitors"]["乙机构"]["failure_stage"], "search")
        self.assertIn("tavily timeout", report["competitors"]["乙机构"]["error"])


if __name__ == "__main__":
    unittest.main()
