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
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.D = tmp
        geo_app.UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        geo_app.F_MATERIALS_INDEX = os.path.join(tmp, "materials_index.json")
        geo_app.MATERIAL_CACHE_FOLDER = os.path.join(tmp, "material_cache")
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


if __name__ == "__main__":
    unittest.main()
