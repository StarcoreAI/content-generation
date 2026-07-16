import io
import os
import tempfile
import unittest
from contextlib import contextmanager

import app as geo_app


@contextmanager
def isolated_material_app():
    original = {
        "D": geo_app.D,
        "UPLOAD_FOLDER": getattr(geo_app, "UPLOAD_FOLDER", None),
        "F_MATERIALS_INDEX": getattr(geo_app, "F_MATERIALS_INDEX", None),
        "MATERIAL_CACHE_FOLDER": getattr(geo_app, "MATERIAL_CACHE_FOLDER", None),
        "CONTENT_UPLOAD_FOLDER": getattr(geo_app, "CONTENT_UPLOAD_FOLDER", None),
        "F_CONTENT_MATERIALS_INDEX": getattr(geo_app, "F_CONTENT_MATERIALS_INDEX", None),
        "CONTENT_MATERIAL_CACHE_FOLDER": getattr(geo_app, "CONTENT_MATERIAL_CACHE_FOLDER", None),
        "F_CLIENTS": getattr(geo_app, "F_CLIENTS", None),
        "F_SETTINGS": getattr(geo_app, "F_SETTINGS", None),
        "F_RAW_RECORDS": getattr(geo_app, "F_RAW_RECORDS", None),
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.D = tmp
        geo_app.UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        geo_app.F_MATERIALS_INDEX = os.path.join(tmp, "materials_index.json")
        geo_app.MATERIAL_CACHE_FOLDER = os.path.join(tmp, "material_cache")
        if hasattr(geo_app, "CONTENT_UPLOAD_FOLDER"):
            geo_app.CONTENT_UPLOAD_FOLDER = os.path.join(tmp, "content_uploads")
        if hasattr(geo_app, "F_CONTENT_MATERIALS_INDEX"):
            geo_app.F_CONTENT_MATERIALS_INDEX = os.path.join(tmp, "content_materials_index.json")
        if hasattr(geo_app, "CONTENT_MATERIAL_CACHE_FOLDER"):
            geo_app.CONTENT_MATERIAL_CACHE_FOLDER = os.path.join(tmp, "content_material_cache")
        geo_app.F_CLIENTS = os.path.join(tmp, "clients.json")
        geo_app.F_SETTINGS = os.path.join(tmp, "settings.json")
        geo_app.F_RAW_RECORDS = os.path.join(tmp, "raw_records.json")
        geo_app.app.config["AUTH_DISABLED"] = True
        try:
            yield tmp
        finally:
            if original["AUTH_DISABLED"] is None:
                geo_app.app.config.pop("AUTH_DISABLED", None)
            else:
                geo_app.app.config["AUTH_DISABLED"] = original["AUTH_DISABLED"]
            for key, value in original.items():
                if key == "AUTH_DISABLED":
                    continue
                if value is None and hasattr(geo_app, key):
                    delattr(geo_app, key)
                else:
                    setattr(geo_app, key, value)


class MaterialApiTests(unittest.TestCase):
    def test_local_pdf_import_endpoints_are_removed(self):
        with isolated_material_app():
            client = geo_app.app.test_client()

            self.assertEqual(client.get("/api/materials/local").status_code, 404)
            response = client.post(
                "/api/materials/client-1/import-local",
                json={"filenames": ["client_profile.txt"]},
            )
            self.assertIn(response.status_code, {404, 405})

    def test_upload_accepts_multiple_files_and_auto_parses(self):
        with isolated_material_app():
            client = geo_app.app.test_client()
            response = client.post(
                "/api/materials/client-1/upload",
                data={
                    "file": [
                        (io.BytesIO(b"First material has enough text for parsing."), "a.txt"),
                        (io.BytesIO(b"Second material also has enough usable text."), "b.md"),
                    ]
                },
                content_type="multipart/form-data",
            )

            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertEqual(len(body["materials"]), 2)
            self.assertEqual([m["original_name"] for m in body["materials"]], ["a.txt", "b.md"])
            self.assertTrue(all(m["confirmed"] for m in body["materials"]))
            self.assertTrue(all(m.get("cache_dir") for m in body["materials"]))

    def test_upload_accepts_xlsx_for_package_analysis(self):
        with isolated_material_app():
            client = geo_app.app.test_client()
            response = client.post(
                "/api/materials/client-1/upload",
                data={
                    "file": [
                        (io.BytesIO(b"not a real workbook but saved for package extractor"), "params.xlsx"),
                    ]
                },
                content_type="multipart/form-data",
            )

            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["materials"][0]["original_name"], "params.xlsx")

    def test_content_materials_are_separate_from_customer_materials(self):
        with isolated_material_app():
            client = geo_app.app.test_client()
            customer = client.post(
                "/api/materials/client-1/upload",
                data={"file": [(io.BytesIO(b"Customer material text is only for customer analysis."), "customer.txt")]},
                content_type="multipart/form-data",
            )
            content = client.post(
                "/api/content/materials/client-1/upload",
                data={"file": [(io.BytesIO(b"Content production material text is only for generation."), "content.txt")]},
                content_type="multipart/form-data",
            )

            self.assertEqual(customer.status_code, 200)
            self.assertEqual(content.status_code, 200)
            content_body = content.get_json()
            self.assertEqual(content_body["materials"][0]["original_name"], "content.txt")
            self.assertTrue(content_body["materials"][0]["confirmed"])

            customer_list = client.get("/api/materials/client-1").get_json()
            content_list = client.get("/api/content/materials/client-1").get_json()
            self.assertEqual([m["original_name"] for m in customer_list], ["customer.txt"])
            self.assertEqual([m["original_name"] for m in content_list], ["content.txt"])

            material_id = content_list[0]["id"]
            deleted = client.delete(f"/api/content/materials/client-1/{material_id}")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(client.get("/api/content/materials/client-1").get_json(), [])
            self.assertEqual([m["original_name"] for m in client.get("/api/materials/client-1").get_json()], ["customer.txt"])

    def test_analyze_package_returns_preview_and_download(self):
        original_runner = geo_app.run_material_package_pipeline
        try:
            def fake_runner(package_dir, output_dir, **_kwargs):
                from pathlib import Path
                from services.storage import save_json

                output = Path(output_dir)
                output.mkdir(parents=True, exist_ok=True)
                markdown = "# 客户资料注入包\n\n测试结果"
                (output / "latest_injection.md").write_text(markdown, encoding="utf-8")
                status = {
                    "ok": True,
                    "status": "completed",
                    "filter": {"readable_units": 1, "kept_units": 1, "errors": 0},
                    "reducer": {"input_units": 1, "reduced_units": 1, "errors": 0},
                    "output": {"markdown_chars": len(markdown), "errors": 0},
                    "outputs": {
                        "filter": str(output / "latest_filter.json"),
                        "reducer": str(output / "latest_reducer.json"),
                        "markdown": str(output / "latest_injection.md"),
                        "status": str(output / "latest_status.json"),
                    },
                }
                save_json(output / "latest_status.json", status)
                return status

            geo_app.run_material_package_pipeline = fake_runner
            with isolated_material_app():
                client = geo_app.app.test_client()
                client.post(
                    "/api/materials/client-1/upload",
                    data={"file": [(io.BytesIO(b"Client profile text for package."), "profile.txt")]},
                    content_type="multipart/form-data",
                )

                analyzed = client.post("/api/materials/client-1/analyze-package")
                self.assertEqual(analyzed.status_code, 200)
                analyzed_body = analyzed.get_json()
                self.assertTrue(analyzed_body["ok"])
                self.assertIn("测试结果", analyzed_body["markdown"])

                latest = client.get("/api/materials/client-1/package-result")
                self.assertEqual(latest.status_code, 200)
                self.assertIn("测试结果", latest.get_json()["markdown"])

                download = client.get("/api/materials/client-1/injection.md")
                self.assertEqual(download.status_code, 200)
                self.assertIn("测试结果", download.get_data(as_text=True))
                download.close()
        finally:
            geo_app.run_material_package_pipeline = original_runner

    def test_competitor_entities_default_to_top_daily_mentions(self):
        with isolated_material_app():
            geo_app.save(geo_app.F_CLIENTS, [{"id": "client-1", "name": "客户", "brand": "客户品牌"}])
            geo_app.save(geo_app.F_RAW_RECORDS, [
                {
                    "id": "r1",
                    "client_id": "client-1",
                    "today": "2026-07-16",
                    "crawl_time": "2026-07-16 10:00:00",
                    "brand": "客户品牌",
                    "mentioned_entities": [
                        {"name": "第一竞品", "type": "品牌", "evidence": "第一竞品"},
                        {"name": "第二竞品", "type": "品牌", "evidence": "第二竞品"},
                    ],
                },
                {
                    "id": "r2",
                    "client_id": "client-1",
                    "today": "2026-07-16",
                    "crawl_time": "2026-07-16 11:00:00",
                    "brand": "客户品牌",
                    "mentioned_entities": [
                        {"name": "第一竞品", "type": "品牌", "evidence": "第一竞品"},
                    ],
                },
            ])

            response = geo_app.app.test_client().get("/api/competitors/client-1/entities?date=2026-07-16")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual([item["name"] for item in body["entities"]], ["第一竞品", "第二竞品"])

    def test_competitor_expand_web_uses_manual_qualifier(self):
        original = geo_app.expand_competitor_web_package
        try:
            captured = {}

            def fake_expand(client, competitors, qualifier, output_dir, ask_text, search_fn):
                captured["client"] = client
                captured["competitors"] = competitors
                captured["qualifier"] = qualifier
                return {
                    "ok": True,
                    "queries": [{"competitor": "第一竞品", "query": "第一竞品 牙齿矫正"}],
                    "source_count": 1,
                    "competitors": [],
                    "markdown": "# 竞品联网资料补充包",
                    "path": str(output_dir / "latest_web_competitors.md"),
                }

            geo_app.expand_competitor_web_package = fake_expand
            with isolated_material_app():
                geo_app.save(geo_app.F_CLIENTS, [{"id": "client-1", "name": "客户", "industry": "口腔"}])
                geo_app.save(geo_app.F_SETTINGS, {"tavily_api_key": "tvly-test", "api_key": "model-key"})

                response = geo_app.app.test_client().post(
                    "/api/competitors/client-1/expand-web",
                    json={"competitors": ["第一竞品"], "qualifier": "牙齿矫正"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured["competitors"], ["第一竞品"])
            self.assertEqual(captured["qualifier"], "牙齿矫正")
            self.assertEqual(captured["client"]["industry"], "口腔")
        finally:
            geo_app.expand_competitor_web_package = original

    def test_competitor_analyze_upload_accepts_files_and_competitor_names(self):
        original = geo_app.analyze_competitor_upload_package
        try:
            captured = {}

            def fake_analyze(package_dir, output_dir, competitors, ask_text):
                captured["package_dir"] = package_dir
                captured["competitors"] = competitors
                return {
                    "ok": True,
                    "status": "completed",
                    "markdown": "# 竞品上传资料整理包\n\n## 第一竞品",
                    "path": str(output_dir / "latest_upload_competitors.md"),
                }

            geo_app.analyze_competitor_upload_package = fake_analyze
            with isolated_material_app():
                geo_app.save(geo_app.F_CLIENTS, [{"id": "client-1", "name": "客户"}])

                response = geo_app.app.test_client().post(
                    "/api/competitors/client-1/analyze-upload",
                    data={
                        "competitors": "第一竞品\n第二竞品",
                        "file": [(io.BytesIO(b"Competitor material body with enough text."), "competitors.txt")],
                    },
                    content_type="multipart/form-data",
                )

                self.assertTrue(os.path.exists(captured["package_dir"]))

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["ok"])
            self.assertEqual(captured["competitors"], ["第一竞品", "第二竞品"])
        finally:
            geo_app.analyze_competitor_upload_package = original


if __name__ == "__main__":
    unittest.main()
