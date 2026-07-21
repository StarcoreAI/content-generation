import json
import unittest

from services.content_prompts import build_content_generation_messages


class ContentPromptTests(unittest.TestCase):
    def test_writer_prompt_uses_brief_sections_and_bans_without_legacy_structure_template(self):
        brief = {
            "title_candidates": ["标题一", "标题二"],
            "angle_statement": "面向异地在职者的选择主线",
            "sections": [{"id": 1, "功能": "开头功能", "要点": "引用客户资料", "引用": ["资料 > 原文"], "字数": 300}],
            "bans": ["禁令 A", "禁令 B"],
            "dedup_hints": "避免重复开头",
            "combo_warning": "自由槽位在结尾",
        }
        messages = build_content_generation_messages(
            client={"name": "客户", "brand": "品牌"},
            brief=brief,
            customer_material_text="客户资料原文",
            content_upload_text="上传资料原文",
            competitor_markdown="竞品资料原文",
            sample={"free_slot": "ending_module"},
        )

        prompt = json.dumps(messages, ensure_ascii=False)
        self.assertIn("简报逐节施工指令", prompt)
        self.assertIn("开头功能", prompt)
        self.assertIn("禁令 A", prompt)
        self.assertIn("不得使用推荐等级词汇和分档标签，机构介绍顺序不代表排名", prompt)
        self.assertIn("禁止出现“占位”“补充位”“待运营补充”“本节保留结构位置”", prompt)
        self.assertIn("禁止出现“竞品”一词", prompt)
        self.assertIn("客户资料/客户提供资料/竞品资料/资料包/现有资料", prompt)
        self.assertIn("表格只列有内容可填的维度", prompt)
        self.assertIn("不得为任何机构虚构价格、资质、服务承诺", prompt)
        self.assertIn("自由槽位在结尾", prompt)
        self.assertIn("自由自拟", prompt)
        self.assertNotIn("攻略对比型展开 few-shot 示例", prompt)
        self.assertNotIn("A1代表对象", prompt)
        self.assertNotIn("运营意见", prompt)


if __name__ == "__main__":
    unittest.main()
