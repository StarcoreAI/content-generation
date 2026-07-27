import unittest

from services.brief_builder import build_planning_brief_prompt
from services.competitor_knowledge import build_high_frequency_competitor_prompt
from services.competitor_materials import build_upload_competitor_prompt, build_web_competitor_prompt
from services.content_prompts import build_content_generation_messages


class PersonCompetitorPromptTests(unittest.TestCase):
    def test_competitor_prompts_allow_real_individuals(self):
        article = {
            "title": "医美专家介绍",
            "url": "https://example.com/expert",
            "content": "李医生提供面诊服务。",
        }
        high_frequency = build_high_frequency_competitor_prompt(["李医生"], [article])
        upload = build_upload_competitor_prompt(["李医生"], [])
        web = build_web_competitor_prompt({}, {"name": "李医生", "sources": []})

        self.assertIn("专家、医生、设计师、顾问等真实个人名称", high_frequency)
        self.assertIn("专家、医生、设计师、顾问等真实个人名称", upload)
        self.assertIn("其他对比对象的简评", web)
        self.assertIn("执业或从业背景", web)

    def test_content_prompts_allow_comparing_people_with_organizations(self):
        sample = {
            "skeleton": {"payload": {"parent_type": "对比型", "sections": [{"id": 1, "功能": "对比"}]}},
            "audience_angle": "初次面诊者",
        }
        brief_prompt = build_planning_brief_prompt(sample, competitor_markdown="## 李医生\n\n面诊服务。")
        writer_prompt = build_content_generation_messages(
            client={"name": "崔红蕾", "brand": "崔红蕾"},
            brief={"sections": [], "bans": []},
        )[1]["content"]

        self.assertIn("多家真实对比对象（机构或个人）", brief_prompt)
        self.assertIn("对比对象名称", brief_prompt)
        self.assertIn("其他机构或个人", writer_prompt)
        self.assertIn("机构或个人名称", writer_prompt)


if __name__ == "__main__":
    unittest.main()
