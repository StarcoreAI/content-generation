import random
import unittest


class ContentChoiceTests(unittest.TestCase):
    def test_legacy_choices_migrate_and_disabled_choices_are_not_active(self):
        from services.content_choices import active_choice_texts, choice_state, normalize_choice_items

        migrated = normalize_choice_items(["异地在职者", "异地在职者", "时间紧张者"])

        self.assertEqual(
            [
                {"text": "异地在职者", "enabled": True, "source": "manual"},
                {"text": "时间紧张者", "enabled": True, "source": "manual"},
            ],
            migrated,
        )
        self.assertEqual(["异地在职者", "时间紧张者"], active_choice_texts(migrated))
        self.assertEqual("all_disabled", choice_state([{"text": "异地在职者", "enabled": False}]))

    def test_competitor_rules_select_required_exclude_banned_and_filter_markdown(self):
        from services.content_choices import filter_competitor_markdown, select_competitor_names

        candidates = ["甲机构", "乙机构", "丙机构", "丁机构"]
        selected = select_competitor_names(
            candidates,
            {"must_use": ["乙机构"], "banned": ["丙机构"]},
            rng=random.Random(7),
        )
        markdown = "# 甲机构\n甲资料\n# 乙机构\n乙资料\n# 丙机构\n丙资料\n# 丁机构\n丁资料"

        self.assertIn("乙机构", selected)
        self.assertNotIn("丙机构", selected)
        self.assertGreaterEqual(len(selected), 2)
        filtered = filter_competitor_markdown(markdown, selected, candidates)
        self.assertIn("# 乙机构", filtered)
        self.assertNotIn("# 丙机构", filtered)
        self.assertTrue(all(name in filtered for name in selected))


if __name__ == "__main__":
    unittest.main()
