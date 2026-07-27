import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_content_research_samples import export_content_research_samples


class ExportContentResearchSamplesTests(unittest.TestCase):
    def _write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _seed_data(self, root):
        self._write_json(root / "clients.json", [
            {"id": "cui", "name": "崔红蕾", "brand": "崔红蕾", "industry": "医美"},
            {"id": "gu", "name": "古齐装饰", "brand": "古齐装饰", "industry": "装修"},
            {"id": "other", "name": "其他客户", "brand": "其他品牌"},
        ])
        self._write_json(root / "probe_groups.json", {
            "cui": [{"id": "cui-group", "questions": ["崔红蕾怎么样"]}],
            "gu": [{"id": "gu-group", "questions": ["昆山装修怎么选"]}],
            "other": [{"id": "other-group", "questions": ["不应导出"]}],
        })
        self._write_json(root / "raw_records.json", [{"client_id": "other", "question": "不应导出"}])
        for client_id in ("cui", "gu", "other"):
            for folder, filename in (
                ("material_packages", "latest_injection.md"),
                ("competitor_material_packages", "latest_web_competitors.md"),
                ("selection_surface_reports", "sample_selection_surface.md"),
                ("selection_evidence", "query_scenes.json"),
                ("reference_intelligence", "fetched_articles.json"),
            ):
                path = root / folder / client_id / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{client_id}-{folder}", encoding="utf-8")
            knowledge_dir = root / "knowledge_base" / client_id
            knowledge_dir.mkdir(parents=True, exist_ok=True)
            (knowledge_dir / "customer_master.md").write_text(
                f"{client_id}-客户总资料", encoding="utf-8"
            )
            (knowledge_dir / "competitor_master.md").write_text(
                f"{client_id}-竞品总资料", encoding="utf-8"
            )
            (knowledge_dir / "customer_state.json").write_text("{}", encoding="utf-8")

    def test_exports_only_selected_clients_and_research_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            output_dir = Path(tmp) / "export"
            self._seed_data(data_dir)

            summary = export_content_research_samples(data_dir, output_dir, ["崔红蕾", "古齐装饰"])

            self.assertEqual(summary["client_ids"], ["cui", "gu"])
            exported_clients = json.loads((output_dir / "clients.json").read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in exported_clients], ["cui", "gu"])
            exported_groups = json.loads((output_dir / "probe_groups.json").read_text(encoding="utf-8"))
            self.assertEqual(set(exported_groups), {"cui", "gu"})
            self.assertTrue((output_dir / "material_packages" / "cui" / "latest_injection.md").exists())
            self.assertTrue((output_dir / "reference_intelligence" / "gu" / "fetched_articles.json").exists())
            self.assertEqual(
                (output_dir / "knowledge_base" / "cui" / "customer_master.md").read_text(encoding="utf-8"),
                "cui-客户总资料",
            )
            self.assertTrue((output_dir / "knowledge_base" / "gu" / "competitor_master.md").exists())
            self.assertFalse((output_dir / "knowledge_base" / "cui" / "customer_state.json").exists())
            self.assertFalse((output_dir / "material_packages" / "other").exists())
            self.assertFalse((output_dir / "raw_records.json").exists())

    def test_missing_client_does_not_create_partial_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            output_dir = Path(tmp) / "export"
            self._seed_data(data_dir)

            with self.assertRaisesRegex(ValueError, "missing_client_selectors: 不存在"):
                export_content_research_samples(data_dir, output_dir, ["崔红蕾", "不存在"])

            self.assertFalse(output_dir.exists())

    def test_ambiguous_client_does_not_create_partial_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            output_dir = Path(tmp) / "export"
            self._seed_data(data_dir)
            clients = json.loads((data_dir / "clients.json").read_text(encoding="utf-8"))
            clients.append({"id": "cui-duplicate", "name": "崔红蕾", "brand": "另一个品牌"})
            self._write_json(data_dir / "clients.json", clients)

            with self.assertRaisesRegex(ValueError, "ambiguous_client_selector: 崔红蕾"):
                export_content_research_samples(data_dir, output_dir, ["崔红蕾"])

            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
