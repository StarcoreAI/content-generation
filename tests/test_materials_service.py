import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from services.materials import MaterialService, PARSE_FAILED, TEXT_TOO_SHORT


def make_service(tmp_path):
    return MaterialService(
        root_dir=tmp_path,
        upload_dir=tmp_path / "uploads",
        index_path=tmp_path / "materials_index.json",
        cache_dir=tmp_path / "material_cache",
    )


def write_minimal_xlsx(path, rows):
    row_xml = []
    for r_index, row in enumerate(rows, start=1):
        cells = []
        for c_index, value in enumerate(row, start=1):
            col = chr(ord("A") + c_index - 1)
            cells.append(
                f'<c r="{col}{r_index}" t="inlineStr">'
                f"<is><t>{value}</t></is></c>"
            )
        row_xml.append(f'<row r="{r_index}">{"".join(cells)}</row>')
    dimension = f'A1:{chr(ord("A") + len(rows[0]) - 1)}{len(rows)}'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>',
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="{dimension}"/>'
            f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>',
        )


def test_save_uploaded_material_copies_file_and_records_metadata(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "client_profile.txt"
    source.write_text("Yishengxue provides adult education enrollment planning.", encoding="utf-8")

    material = service.save_uploaded_material("client-1", source, "client_profile.txt")

    assert material["client_id"] == "client-1"
    assert material["original_name"] == "client_profile.txt"
    assert material["source"] == "upload"
    assert material["confirmed"] is False
    assert Path(material["path"]).exists()
    assert Path(material["path"]).read_text(encoding="utf-8") == "Yishengxue provides adult education enrollment planning."


def test_parse_material_cleans_repeated_lines_and_auto_confirms(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "profile.txt"
    source.write_text(
        "\n".join(
            [
                "Common footer",
                "Yishengxue provides adult education enrollment planning.",
                "Common footer",
                "The profile mentions application timelines, policy checks, and consultation process.",
                "Common footer",
            ]
        ),
        encoding="utf-8",
    )
    material = service.save_uploaded_material("client-1", source, "profile.txt")

    parsed = service.parse_material("client-1", material["id"])

    assert parsed["confirmed"] is True
    assert "Common footer\nCommon footer" not in parsed["clean_text"]
    assert "Yishengxue provides adult education enrollment planning." in parsed["clean_text"]
    legacy_key = "fact_" + "card"
    assert legacy_key not in parsed

    cache_dir = tmp_path / "material_cache" / "client-1" / material["id"]
    assert (cache_dir / "raw_text.txt").exists()
    assert (cache_dir / "clean_text.txt").exists()
    assert not (cache_dir / f"{legacy_key}.json").exists()


def test_build_generation_bundle_uses_auto_confirmed_materials(tmp_path):
    service = make_service(tmp_path)
    first_source = tmp_path / "a.txt"
    second_source = tmp_path / "b.txt"
    first_source.write_text("Yishengxue provides adult education enrollment planning.", encoding="utf-8")
    second_source.write_text("Second profile includes policy checks and consultation process.", encoding="utf-8")
    first = service.save_uploaded_material("client-1", first_source, "a.txt")
    second = service.save_uploaded_material("client-1", second_source, "b.txt")
    service.parse_material("client-1", first["id"])
    service.parse_material("client-1", second["id"])

    bundle = service.build_generation_bundle("client-1")

    assert bundle["confirmed_count"] == 2
    assert bundle["material_count"] == 2
    assert bundle["used_unconfirmed_fallback"] is False
    assert "Yishengxue provides adult education enrollment planning" in bundle["text"]
    assert "Second profile includes policy checks" in bundle["text"]


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


def test_parse_material_reuses_package_extractor_for_xlsx(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "catalog.xlsx"
    write_minimal_xlsx(
        source,
        [
            ["Brand", "Service", "Region"],
            ["Yishengxue", "adult education planning", "Hebei"],
        ],
    )
    material = service.save_uploaded_material("client-1", source, "catalog.xlsx")

    parsed = service.parse_material("client-1", material["id"])

    assert parsed["confirmed"] is True
    assert parsed["diagnostics"]["extractor"] == "material_package_extractor"
    assert "Yishengxue" in parsed["clean_text"]
    assert "adult education planning" in parsed["clean_text"]


def test_parse_legacy_doc_reports_missing_tool_instead_of_text_too_short(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"\xd0\xcf\x11\xe0 legacy Word binary")
    material = service.save_uploaded_material("client-1", source, "legacy.doc")

    with patch("services.materials.shutil.which", return_value=None):
        parsed = service.parse_material("client-1", material["id"])

    assert parsed["confirmed"] is False
    assert parsed["status"] == PARSE_FAILED
    assert parsed["status"] != TEXT_TOO_SHORT
    assert "antiword" in parsed["diagnostics"]["dependency_error"]
    assert "catdoc" in parsed["diagnostics"]["dependency_error"]


def test_parse_legacy_doc_uses_antiword_when_available(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"\xd0\xcf\x11\xe0 legacy Word binary")
    material = service.save_uploaded_material("client-1", source, "legacy.doc")

    class Completed:
        stdout = b"Yishengxue legacy DOC services and policy checks"
        stderr = b""
        returncode = 0

    with patch("services.materials.shutil.which", side_effect=lambda tool: tool if tool == "antiword" else None):
        with patch("subprocess.run", return_value=Completed()) as run:
            parsed = service.parse_material("client-1", material["id"])

    assert parsed["confirmed"] is True
    assert parsed["diagnostics"]["extractor"] == "antiword"
    assert "legacy DOC services" in parsed["clean_text"]
    run.assert_called_once()


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

    def test_parse_material_reuses_package_extractor_for_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_parse_material_reuses_package_extractor_for_xlsx(Path(tmp))

    def test_parse_legacy_doc_reports_missing_tool_instead_of_text_too_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_parse_legacy_doc_reports_missing_tool_instead_of_text_too_short(Path(tmp))

    def test_parse_legacy_doc_uses_antiword_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_parse_legacy_doc_uses_antiword_when_available(Path(tmp))
