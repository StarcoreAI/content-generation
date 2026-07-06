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
        "LOCAL_PDF_FOLDER": getattr(geo_app, "LOCAL_PDF_FOLDER", None),
        "F_MATERIALS_INDEX": getattr(geo_app, "F_MATERIALS_INDEX", None),
        "MATERIAL_CACHE_FOLDER": getattr(geo_app, "MATERIAL_CACHE_FOLDER", None),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.D = tmp
        geo_app.UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        geo_app.LOCAL_PDF_FOLDER = os.path.join(tmp, "pdf")
        geo_app.F_MATERIALS_INDEX = os.path.join(tmp, "materials_index.json")
        geo_app.MATERIAL_CACHE_FOLDER = os.path.join(tmp, "material_cache")
        os.makedirs(geo_app.LOCAL_PDF_FOLDER, exist_ok=True)
        try:
            yield tmp
        finally:
            for key, value in original.items():
                if value is None and hasattr(geo_app, key):
                    delattr(geo_app, key)
                else:
                    setattr(geo_app, key, value)


class MaterialApiTests(unittest.TestCase):
    def test_local_list_import_auto_parses_confirms_and_delete(self):
        with isolated_material_app():
            with open(os.path.join(geo_app.LOCAL_PDF_FOLDER, "client_profile.txt"), "w", encoding="utf-8") as f:
                f.write("Rabbit Dental has clinics, doctors, orthodontics, and implant services.")
            client = geo_app.app.test_client()

            local = client.get("/api/materials/local")
            self.assertEqual(local.status_code, 200)
            self.assertEqual(local.get_json()["files"][0]["name"], "client_profile.txt")

            imported = client.post(
                "/api/materials/client-1/import-local",
                json={"filenames": ["client_profile.txt"]},
            )
            self.assertEqual(imported.status_code, 200)
            material = imported.get_json()["materials"][0]
            self.assertEqual(material["source"], "local_pdf_folder")
            self.assertEqual(material["original_name"], "client_profile.txt")
            self.assertTrue(material["confirmed"])
            self.assertIn("cache_dir", material)
            self.assertGreater(material["text_chars"], 10)

            listed = client.get("/api/materials/client-1")
            self.assertEqual(listed.status_code, 200)
            listed_material = listed.get_json()[0]
            self.assertEqual(listed_material["id"], material["id"])
            self.assertTrue(listed_material["confirmed"])

            deleted = client.delete(f"/api/materials/client-1/{material['id']}")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(client.get("/api/materials/client-1").get_json(), [])

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


if __name__ == "__main__":
    unittest.main()
