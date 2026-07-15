import json
import tempfile
import unittest
from pathlib import Path

from services.materials import MaterialService


def make_service(tmp_path):
    return MaterialService(
        root_dir=tmp_path,
        upload_dir=tmp_path / "uploads",
        index_path=tmp_path / "materials_index.json",
        cache_dir=tmp_path / "material_cache",
    )


def test_save_uploaded_material_copies_file_and_records_metadata(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "client_profile.txt"
    source.write_text("Rabbit Dental was founded in 2003.", encoding="utf-8")

    material = service.save_uploaded_material("client-1", source, "client_profile.txt")

    assert material["client_id"] == "client-1"
    assert material["original_name"] == "client_profile.txt"
    assert material["source"] == "upload"
    assert material["confirmed"] is False
    assert Path(material["path"]).exists()
    assert Path(material["path"]).read_text(encoding="utf-8") == "Rabbit Dental was founded in 2003."


def test_parse_material_cleans_repeated_lines_and_auto_confirms(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "profile.txt"
    source.write_text(
        "\n".join(
            [
                "Common footer",
                "Rabbit Dental was founded in 2003.",
                "Common footer",
                "The profile mentions clinics, doctors, orthodontics, and implant services.",
                "Common footer",
            ]
        ),
        encoding="utf-8",
    )
    material = service.save_uploaded_material("client-1", source, "profile.txt")

    parsed = service.parse_material("client-1", material["id"])

    assert parsed["confirmed"] is True
    assert "Common footer\nCommon footer" not in parsed["clean_text"]
    assert "Rabbit Dental was founded in 2003." in parsed["clean_text"]
    assert parsed["fact_card"]

    cache_dir = tmp_path / "material_cache" / "client-1" / material["id"]
    assert (cache_dir / "raw_text.txt").exists()
    assert (cache_dir / "clean_text.txt").exists()
    assert json.loads((cache_dir / "fact_card.json").read_text(encoding="utf-8")) is not None


def test_build_generation_bundle_uses_auto_confirmed_materials(tmp_path):
    service = make_service(tmp_path)
    first_source = tmp_path / "a.txt"
    second_source = tmp_path / "b.txt"
    first_source.write_text("Rabbit Dental offers orthodontics and implant services.", encoding="utf-8")
    second_source.write_text("Second profile includes doctors and clinic service process.", encoding="utf-8")
    first = service.save_uploaded_material("client-1", first_source, "a.txt")
    second = service.save_uploaded_material("client-1", second_source, "b.txt")
    service.parse_material("client-1", first["id"])
    service.parse_material("client-1", second["id"])

    bundle = service.build_generation_bundle("client-1")

    assert bundle["confirmed_count"] == 2
    assert bundle["material_count"] == 2
    assert bundle["used_unconfirmed_fallback"] is False
    assert "Rabbit Dental offers orthodontics" in bundle["text"]
    assert "Second profile includes doctors" in bundle["text"]


def test_build_generation_bundle_excludes_unusable_materials(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "short.txt"
    source.write_text("too short", encoding="utf-8")
    material = service.save_uploaded_material("client-1", source, "short.txt")
    parsed = service.parse_material("client-1", material["id"])

    bundle = service.build_generation_bundle("client-1")

    assert parsed["confirmed"] is False
    assert bundle["confirmed_count"] == 0
    assert bundle["material_count"] == 0
    assert bundle["used_unconfirmed_fallback"] is False
    assert "too short" not in bundle["text"]


class MaterialServiceTests(unittest.TestCase):
    def test_save_uploaded_material_copies_file_and_records_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_save_uploaded_material_copies_file_and_records_metadata(Path(tmp))

    def test_parse_material_cleans_repeated_lines_and_auto_confirms(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_parse_material_cleans_repeated_lines_and_auto_confirms(Path(tmp))

    def test_build_generation_bundle_uses_auto_confirmed_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_build_generation_bundle_uses_auto_confirmed_materials(Path(tmp))

    def test_build_generation_bundle_excludes_unusable_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_build_generation_bundle_excludes_unusable_materials(Path(tmp))
