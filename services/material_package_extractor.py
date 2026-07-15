import re
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from services.materials import extract_docx_text, extract_pdf_text


TEXT_EXTENSIONS = {".txt", ".md"}
DOC_EXTENSIONS = {".docx", ".pdf"}
SPREADSHEET_EXTENSIONS = {".xlsx"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls"}
RTF_EXTENSIONS = {".rtf"}

SPREADSHEET_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
WORKBOOK_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def extract_material_package(package_path, sample_chars=800, max_text_chars=20000, max_sheet_rows=80):
    root = Path(package_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(root)

    files = [path for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()) if path.is_file()]
    manifest_files = []
    units = []
    for path in files:
        file_record, file_units = _extract_file(root, path, sample_chars, max_text_chars, max_sheet_rows)
        manifest_files.append(file_record)
        units.extend(file_units)

    return {
        "manifest": {
            "package_name": root.name,
            "root_path": str(root),
            "file_count": len(files),
            "folders": _folder_summary(root, files),
            "files": manifest_files,
        },
        "units": units,
    }


def _extract_file(root, path, sample_chars, max_text_chars, max_sheet_rows):
    rel_path = _relative_path(root, path)
    ext = path.suffix.lower()
    base = {
        "path": rel_path,
        "name": path.name,
        "extension": ext.lstrip("."),
        "size": path.stat().st_size,
        "category_from_path": _category_from_path(rel_path),
    }
    if ext in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return _text_file(base, rel_path, text, "ok", "plain_text", sample_chars, max_text_chars)
    if ext in DOC_EXTENSIONS:
        text, diagnostics = _extract_document_text(path)
        status = "ok" if text.strip() else "empty_text"
        file_record, units = _text_file(
            base, rel_path, text, status, diagnostics.get("extractor", ""), sample_chars, max_text_chars
        )
        file_record["diagnostics"] = diagnostics
        return file_record, units
    if ext in RTF_EXTENSIONS:
        text = _extract_rtf_text(path)
        return _text_file(base, rel_path, text, "ok" if text.strip() else "empty_text", "rtf", sample_chars, max_text_chars)
    if ext in SPREADSHEET_EXTENSIONS:
        return _extract_xlsx(base, rel_path, path, sample_chars, max_sheet_rows)
    if ext in IMAGE_EXTENSIONS:
        width, height = _image_size(path)
        file_record = {
            **base,
            "extract_status": "image_metadata_only",
            "image_width": width,
            "image_height": height,
        }
        return file_record, [
            {
                "unit_id": rel_path,
                "path": rel_path,
                "kind": "image",
                "extract_status": "image_metadata_only",
                "image_width": width,
                "image_height": height,
            }
        ]
    if ext in LEGACY_OFFICE_EXTENSIONS:
        sample = _binary_probe(path, sample_chars)
        file_record = {
            **base,
            "extract_status": "needs_conversion",
            "sample": sample,
            "text_chars": len(sample),
        }
        return file_record, [
            {
                "unit_id": rel_path,
                "path": rel_path,
                "kind": "legacy_office",
                "extract_status": "needs_conversion",
                "text": sample,
                "sample": sample,
            }
        ]
    return {**base, "extract_status": "unsupported"}, []


def _text_file(base, rel_path, text, status, extractor, sample_chars, max_text_chars):
    clean = _clean_text(text)
    file_record = {
        **base,
        "extract_status": status,
        "extractor": extractor,
        "text_chars": len(clean),
        "sample": clean[:sample_chars],
    }
    return file_record, [
        {
            "unit_id": rel_path,
            "path": rel_path,
            "kind": "text",
            "extract_status": status,
            "extractor": extractor,
            "text": clean[:max_text_chars],
            "sample": clean[:sample_chars],
        }
    ]


def _extract_document_text(path):
    diagnostics = {
        "file_type": path.suffix.lower().lstrip("."),
        "extractor": "",
        "dependency_error": "",
        "page_count": 0,
        "is_scanned_pdf": False,
    }
    if path.suffix.lower() == ".docx":
        return extract_docx_text(path, diagnostics), diagnostics
    if path.suffix.lower() == ".pdf":
        return extract_pdf_text(path, diagnostics), diagnostics
    return "", diagnostics


def _extract_xlsx(base, rel_path, path, sample_chars, max_sheet_rows):
    try:
        sheets = _read_xlsx_sheets(path, max_sheet_rows)
    except Exception as exc:
        return {**base, "extract_status": "parse_failed", "error": f"{type(exc).__name__}: {exc}"}, []

    sheet_records = []
    units = []
    for sheet in sheets:
        text = _format_sheet_text(sheet)
        sheet_record = {
            "name": sheet["name"],
            "dimension": sheet["dimension"],
            "row_count": sheet["row_count"],
            "column_count": sheet["column_count"],
            "columns": sheet["columns"],
            "sample": text[:sample_chars],
        }
        sheet_records.append(sheet_record)
        units.append(
            {
                "unit_id": f"{rel_path}::{sheet['name']}",
                "path": rel_path,
                "kind": "spreadsheet_sheet",
                "extract_status": "ok",
                "sheet_name": sheet["name"],
                "dimension": sheet["dimension"],
                "row_count": sheet["row_count"],
                "column_count": sheet["column_count"],
                "columns": sheet["columns"],
                "text": text,
                "sample": text[:sample_chars],
            }
        )
    return {
        **base,
        "extract_status": "ok",
        "sheet_count": len(sheet_records),
        "sheets": sheet_records,
    }, units


def _read_xlsx_sheets(path, max_sheet_rows):
    with zipfile.ZipFile(path) as zf:
        shared_strings = _read_shared_strings(zf)
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib.get("Id"): rel.attrib.get("Target") for rel in rels}
        sheets = []
        for sheet in workbook.findall(".//a:sheet", SPREADSHEET_NS):
            name = sheet.attrib.get("name", "")
            rel_id = sheet.attrib.get(WORKBOOK_REL_ID)
            target = rel_targets.get(rel_id, "")
            sheet_path = "xl/" + target.lstrip("/")
            if sheet_path not in zf.namelist():
                continue
            sheet_xml = ET.fromstring(zf.read(sheet_path))
            dimension = ""
            dimension_node = sheet_xml.find("a:dimension", SPREADSHEET_NS)
            if dimension_node is not None:
                dimension = dimension_node.attrib.get("ref", "")
            rows, row_count, column_count = _read_sheet_rows(sheet_xml, shared_strings, max_sheet_rows)
            columns = _guess_columns(rows)
            sheets.append(
                {
                    "name": name,
                    "dimension": dimension,
                    "row_count": row_count,
                    "column_count": column_count,
                    "columns": columns,
                    "rows": rows,
                }
            )
        return sheets


def _read_shared_strings(zf):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//a:t", SPREADSHEET_NS))
        for item in root.findall("a:si", SPREADSHEET_NS)
    ]


def _read_sheet_rows(sheet_xml, shared_strings, max_sheet_rows):
    rows = []
    row_count = 0
    column_count = 0
    for row_node in sheet_xml.findall(".//a:sheetData/a:row", SPREADSHEET_NS):
        values_by_col = {}
        for cell in row_node.findall("a:c", SPREADSHEET_NS):
            col_index = _cell_col_index(cell.attrib.get("r", ""))
            if col_index < 0:
                col_index = len(values_by_col)
            values_by_col[col_index] = _cell_value(cell, shared_strings)
        if not values_by_col:
            continue
        max_col = max(values_by_col)
        values = [_clean_cell(values_by_col.get(index, "")) for index in range(max_col + 1)]
        while values and not values[-1]:
            values.pop()
        if values:
            row_count += 1
            column_count = max(column_count, len(values))
            if len(rows) < max_sheet_rows:
                rows.append(values)
    return rows, row_count, column_count


def _cell_value(cell, shared_strings):
    value_node = cell.find("a:v", SPREADSHEET_NS)
    raw = "" if value_node is None else (value_node.text or "")
    cell_type = cell.attrib.get("t")
    if cell_type == "s" and raw.isdigit() and int(raw) < len(shared_strings):
        return shared_strings[int(raw)]
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", SPREADSHEET_NS))
    return raw


def _cell_col_index(reference):
    letters = "".join(ch for ch in reference if ch.isalpha())
    if not letters:
        return -1
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _guess_columns(rows):
    for row in rows[:10]:
        non_empty = [cell for cell in row if cell]
        if len(non_empty) >= 2:
            return row
    return rows[0] if rows else []


def _format_sheet_text(sheet):
    lines = [
        f"Sheet: {sheet['name']}",
        f"Dimension: {sheet['dimension'] or 'unknown'}",
        f"Rows: {sheet['row_count']}",
    ]
    if sheet["columns"]:
        lines.append("Columns: " + " | ".join(sheet["columns"]))
    lines.append("Preview:")
    for row in sheet["rows"]:
        lines.append("- " + " | ".join(row))
    return "\n".join(lines)


def _folder_summary(root, files):
    folders = {}
    for file_path in files:
        rel_parent = file_path.parent.relative_to(root).as_posix()
        if rel_parent == ".":
            rel_parent = ""
        entry = folders.setdefault(rel_parent, {"path": rel_parent, "file_count": 0, "types": {}})
        ext = file_path.suffix.lower().lstrip(".") or "none"
        entry["file_count"] += 1
        entry["types"][ext] = entry["types"].get(ext, 0) + 1
    return sorted(folders.values(), key=lambda item: item["path"])


def _category_from_path(rel_path):
    parent = Path(rel_path).parent.as_posix()
    return "" if parent == "." else parent


def _relative_path(root, path):
    return path.relative_to(root).as_posix()


def _clean_cell(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_text(text):
    lines = [_clean_cell(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _extract_rtf_text(path):
    text = path.read_text(encoding="gb18030", errors="ignore")

    def replace_unicode(match):
        code = int(match.group(1))
        if code < 0:
            code += 65536
        return chr(code)

    text = re.sub(r"\\u(-?\d+)\??", replace_unicode, text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    return _clean_text(text.replace("{", " ").replace("}", " "))


def _binary_probe(path, sample_chars):
    data = path.read_bytes()
    fragments = []
    for encoding in ("utf-16le", "gb18030", "utf-8"):
        text = data.decode(encoding, errors="ignore")
        for match in re.findall(r"[\u4e00-\u9fffA-Za-z0-9，。；：、（）()《》“”\-—_/\. ]{8,}", text):
            value = _clean_cell(match)
            if len(re.findall(r"[\u4e00-\u9fff]", value)) >= 3 and value not in fragments:
                fragments.append(value)
            if len("\n".join(fragments)) >= sample_chars:
                return "\n".join(fragments)[:sample_chars]
    return "\n".join(fragments)[:sample_chars]


def _image_size(path):
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        return _jpeg_size(data)
    return None, None


def _jpeg_size(data):
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index:index + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if index + 7 <= len(data):
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                return width, height
            break
        index += max(length, 2)
    return None, None
