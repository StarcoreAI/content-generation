import unittest

from services.content_route_generation import build_content_route_messages, generate_content_route_draft, route_context


def route(parent_type="介绍型"):
    return {"id": "route-a", "parent_type": parent_type, "name": "路线", "reader_task": "帮助判断", "signature": "先解释再决策", "steps": [{"purpose": "解释", "evidence_role": "事实", "output_action": "展开"}]}


class ContentRouteGenerationTests(unittest.TestCase):
    def test_introduction_uses_one_writer_call_and_customer_facts_as_main_body(self):
        bundle = {"task": {"query": "上海面部提升医生", "article_type": "介绍型", "title_entity_policy": "实体不入标题"}, "client": {"brand": "崔红蕾"}, "route": route(), "customer_facts": "## 特有方法与服务逻辑\n筋膜分层复位。"}
        calls = []
        draft = generate_content_route_draft(bundle, lambda messages, max_tokens: calls.append((messages, max_tokens)) or "标题\n正文")
        self.assertEqual(draft, "标题\n正文")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 6000)
        prompt = calls[0][0][1]["content"]
        self.assertIn("客户专属事实是文章主体", prompt)
        self.assertIn("围绕本次 Query 相关的多组客户事实形成足够的信息密度", prompt)
        self.assertIn("客户专属事实通常以条目形式提供", prompt)
        self.assertIn("段落之间应以明确的承接、递进、因果或转折关系自然衔接", prompt)
        self.assertIn("使用 3—4 个自然的小标题", prompt)
        self.assertIn("不要让每一类客户资料各自成为一个孤立段落", prompt)
        self.assertIn("客户资料显示", prompt)
        self.assertIn("筋膜分层复位", prompt)

    def test_comparison_requires_two_explicit_competitors_and_records_only_context(self):
        bundle = {"task": {"query": "昆山装修公司前十名", "article_type": "对比型", "title_entity_policy": "实体可入标题"}, "client": {"brand": "古齐装饰"}, "route": route("对比型"), "customer_facts": "自有工人", "competitors": [{"name": "甲装饰", "facts": "工期和售后"}, {"name": "乙装饰", "facts": "预算和材料"}]}
        prompt = build_content_route_messages(bundle)[1]["content"]
        self.assertIn("同一口径", prompt)
        self.assertIn("至少使用两类", prompt)
        context = route_context(bundle)
        self.assertEqual(context["competitor_names"], ["甲装饰", "乙装饰"])
        self.assertNotIn("自有工人", str(context))
        with self.assertRaisesRegex(ValueError, "comparison_competitors_required"):
            build_content_route_messages({**bundle, "competitors": bundle["competitors"][:1]})

    def test_only_introduction_prompt_requires_client_brand_in_title(self):
        introduction = {
            "task": {"query": "上海面部提升医生", "article_type": "介绍型", "title_entity_policy": "实体不入标题"},
            "client": {"brand": "崔红蕾"}, "route": route(), "customer_facts": "筋膜分层复位。",
        }
        comparison = {
            "task": {"query": "昆山装修公司前十名", "article_type": "对比型", "title_entity_policy": "实体不入标题"},
            "client": {"brand": "古齐装饰"}, "route": route("对比型"), "customer_facts": "自有工人",
            "competitors": [{"name": "甲装饰", "facts": "工期"}, {"name": "乙装饰", "facts": "售后"}],
        }

        introduction_prompt = build_content_route_messages(introduction)[1]["content"]
        comparison_prompt = build_content_route_messages(comparison)[1]["content"]

        self.assertIn("介绍型标题必须直接出现客户品牌“崔红蕾”", introduction_prompt)
        self.assertNotIn("介绍型标题必须直接出现客户品牌", comparison_prompt)

    def test_scene_terms_are_only_a_lightweight_prompt_reminder(self):
        bundle = {
            "task": {"query": "上海自然面部提升医生", "article_type": "介绍型", "title_entity_policy": "实体不入标题"},
            "client": {"brand": "崔红蕾"}, "route": route(),
            "customer_facts": "筋膜分层复位。",
            "scene_terms": ["法令纹加深", "苹果肌下垂", "自然感"],
        }

        prompt = build_content_route_messages(bundle)[1]["content"]

        self.assertIn("法令纹加深、苹果肌下垂、自然感", prompt)
        self.assertIn("不要求覆盖全部", prompt)
        self.assertNotIn("法令纹加深", str(route_context(bundle)))

    def test_route_history_is_not_a_writer_prompt_input(self):
        bundle = {
            "task": {"query": "上海面部提升医生", "article_type": "介绍型", "title_entity_policy": "实体不入标题"},
            "client": {"brand": "崔红蕾"}, "route": route(), "customer_facts": "筋膜分层复位。",
            "same_route_articles": [{"title": "已有稿", "content": "已生成稿的具体表达，不应在新稿重复。"}],
        }

        prompt = build_content_route_messages(bundle)[1]["content"]

        self.assertNotIn("同一 Query 且同一写法路线的已生成稿", prompt)
        self.assertNotIn("已生成稿的具体表达", prompt)

    def test_same_group_scene_terms_are_optional_writer_reminders(self):
        bundle = {
            "task": {"query": "上海面部提升医生", "article_type": "介绍型", "title_entity_policy": "实体不入标题"},
            "client": {"brand": "崔红蕾"}, "route": route(), "customer_facts": "筋膜分层复位。",
            "scene_terms": ["下颌线模糊"],
            "supplementary_scene_terms": [{"query": "相邻问法", "scene_terms": ["苹果肌下垂", "怕创伤大"]}],
        }

        prompt = build_content_route_messages(bundle)[1]["content"]

        self.assertIn("同问题组可选场景词", prompt)
        self.assertIn("苹果肌下垂", prompt)
        self.assertIn("自然吸收确实有助于回答本题的场景词", prompt)
        self.assertNotIn("最多自然吸收", prompt)
        self.assertIn("不得为了覆盖其他 Query 而堆词", prompt)


if __name__ == "__main__":
    unittest.main()
