import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from services.material_package_extractor import extract_material_package


def write_minimal_xlsx(path, sheets):
    sheet_entries = []
    rel_entries = []
    sheet_files = {}
    for index, (name, rows) in enumerate(sheets, start=1):
        sheet_entries.append(
            f'<sheet name="{name}" sheetId="{index}" '
            f'r:id="rId{index}"/>'
        )
        rel_entries.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
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
        sheet_files[f"xl/worksheets/sheet{index}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{chr(ord("A") + len(rows[0]) - 1)}{len(rows)}"/>'
            f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
        )
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
            f'<sheets>{"".join(sheet_entries)}</sheets></workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(rel_entries)}</Relationships>',
        )
        for file_name, xml in sheet_files.items():
            zf.writestr(file_name, xml)


def write_minimal_png(path, width=2, height=3):
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


class MaterialPackageExtractorTests(unittest.TestCase):
    def test_extracts_manifest_text_sheet_units_and_image_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            package.mkdir()
            (package / "profile.txt").write_text(
                "Wing School focuses on adult education services.",
                encoding="utf-8",
            )
            (package / "assets").mkdir()
            write_minimal_png(package / "assets" / "logo.png")
            write_minimal_xlsx(
                package / "catalog.xlsx",
                [
                    ("Hebei", [["School", "Major", "Fee"], ["A College", "CS", "5000"]]),
                    ("Jiangsu", [["School", "Major", "Fee"], ["B College", "MBA", "6750"]]),
                ],
            )

            result = extract_material_package(package)

        manifest = result["manifest"]
        units = result["units"]
        self.assertEqual(manifest["package_name"], "package")
        self.assertEqual(manifest["file_count"], 3)
        self.assertEqual(
            sorted(file["path"] for file in manifest["files"]),
            ["assets/logo.png", "catalog.xlsx", "profile.txt"],
        )
        xlsx_file = next(file for file in manifest["files"] if file["path"] == "catalog.xlsx")
        self.assertEqual([sheet["name"] for sheet in xlsx_file["sheets"]], ["Hebei", "Jiangsu"])
        self.assertEqual(xlsx_file["sheets"][0]["columns"], ["School", "Major", "Fee"])

        text_unit = next(unit for unit in units if unit["path"] == "profile.txt")
        self.assertEqual(text_unit["kind"], "text")
        self.assertIn("adult education", text_unit["text"])

        sheet_units = [unit for unit in units if unit["kind"] == "spreadsheet_sheet"]
        self.assertEqual([unit["sheet_name"] for unit in sheet_units], ["Hebei", "Jiangsu"])
        self.assertIn("A College", sheet_units[0]["text"])

        image_unit = next(unit for unit in units if unit["path"] == "assets/logo.png")
        self.assertEqual(image_unit["kind"], "image")
        self.assertEqual(image_unit["extract_status"], "image_metadata_only")
        self.assertEqual(image_unit["image_width"], 2)
        self.assertEqual(image_unit["image_height"], 3)

    def test_spreadsheet_row_count_is_not_truncated_by_preview_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            package.mkdir()
            write_minimal_xlsx(
                package / "catalog.xlsx",
                [
                    (
                        "Hebei",
                        [
                            ["School", "Major", "Fee"],
                            ["A College", "CS", "5000"],
                            ["B College", "MBA", "6750"],
                        ],
                    )
                ],
            )

            result = extract_material_package(package, max_sheet_rows=1)

        sheet = result["manifest"]["files"][0]["sheets"][0]
        unit = result["units"][0]
        self.assertEqual(sheet["row_count"], 3)
        self.assertEqual(unit["row_count"], 3)
        self.assertIn("School | Major | Fee", unit["text"])
        self.assertNotIn("A College", unit["text"])


if __name__ == "__main__":
    unittest.main()
