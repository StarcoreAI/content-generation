import json
import os
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from services.storage import save_json


ALLOWED_MATERIAL_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".doc", ".xlsx", ".xls"}
LEGACY_MATERIAL_CARD_KEY = "fact_" + "card"
UNPARSED = "未解析"
PARSED_PENDING_CONFIRM = "等待人工确认"
PARSE_FAILED = "解析失败"
TEXT_TOO_SHORT = "文本过少"
SCANNED_PDF = "疑似扫描件"
CONFIRMED = "已确认参与生成"


class MaterialService:
    def __init__(
        self,
        root_dir=".",
        upload_dir="data/uploads",
        index_path="data/materials_index.json",
        cache_dir="data/material_cache",
    ):
        self.root_dir = Path(root_dir)
        self.upload_dir = Path(upload_dir)
        self.index_path = Path(index_path)
        self.cache_dir = Path(cache_dir)

    def _load_index(self):
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_index(self, data):
        save_json(self.index_path, data)

    def _client_materials(self, data, client_id):
        items = data.get(client_id)
        if not isinstance(items, list):
            items = []
            data[client_id] = items
        return items

    def _new_id(self):
        return time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:8]

    def _now(self):
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _safe_stored_name(self, material_id, original_filename):
        suffix = Path(original_filename).suffix.lower()
        stem = Path(original_filename).stem.strip() or "material"
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
        return f"{material_id}_{cleaned[:80]}{suffix}"

    def _normalize_path(self, path):
        return str(Path(path))

    def _find_material(self, data, client_id, material_id_or_name):
        for material in self._client_materials(data, client_id):
            if material.get("id") == material_id_or_name:
                return material
            if material.get("stored_name") == material_id_or_name:
                return material
            if material.get("original_name") == material_id_or_name:
                return material
            if material.get("name") == material_id_or_name:
                return material
        return None

    def _is_allowed(self, filename):
        return Path(filename).suffix.lower() in ALLOWED_MATERIAL_EXTENSIONS

    def list_client_materials(self, client_id):
        data = self._load_index()
        items = self._client_materials(data, client_id)
        return sorted(items, key=lambda item: item.get("uploaded_at", ""), reverse=True)

    def save_uploaded_material(self, client_id, storage_file, original_filename, source="upload"):
        if not original_filename or not self._is_allowed(original_filename):
            raise ValueError("不支持的文件格式，请上传 txt/pdf/md/doc/docx/xlsx/xls")
        material_id = self._new_id()
        stored_name = self._safe_stored_name(material_id, original_filename)
        client_dir = self.upload_dir / client_id
        client_dir.mkdir(parents=True, exist_ok=True)
        target = client_dir / stored_name
        if hasattr(storage_file, "save"):
            storage_file.save(str(target))
        else:
            shutil.copy2(storage_file, target)
        material = self._make_material_record(
            client_id=client_id,
            material_id=material_id,
            original_name=original_filename,
            stored_name=stored_name,
            path=target,
            source=source,
        )
        data = self._load_index()
        self._client_materials(data, client_id).append(material)
        self._save_index(data)
        return material

    def _make_material_record(
        self, client_id, material_id, original_name, stored_name, path, source
    ):
        size = Path(path).stat().st_size if Path(path).exists() else 0
        return {
            "id": material_id,
            "client_id": client_id,
            "name": stored_name,
            "stored_name": stored_name,
            "original_name": original_name,
            "size": size,
            "path": self._normalize_path(path),
            "source": source,
            "status": UNPARSED,
            "confirmed": False,
            "uploaded_at": self._now(),
            "uploaded": self._now()[:16],
            "diagnostics": {},
        }

    def delete_material(self, client_id, material_id_or_name):
        data = self._load_index()
        items = self._client_materials(data, client_id)
        material = self._find_material(data, client_id, material_id_or_name)
        if not material:
            return False
        data[client_id] = [item for item in items if item.get("id") != material.get("id")]
        self._save_index(data)
        path = Path(material.get("path", ""))
        if path.exists() and path.is_file():
            path.unlink()
        cache = self.cache_dir / client_id / material["id"]
        if cache.exists():
            shutil.rmtree(cache)
        return True

    def parse_material(self, client_id, material_id):
        data = self._load_index()
        material = self._find_material(data, client_id, material_id)
        if not material:
            raise KeyError(material_id)
        path = Path(material["path"])
        raw_text, diagnostics = self.extract_text_with_diagnostics(path)
        clean_text = clean_material_text(raw_text)
        status = PARSED_PENDING_CONFIRM
        if diagnostics.get("dependency_error"):
            status = PARSE_FAILED
        elif diagnostics.get("is_scanned_pdf"):
            status = SCANNED_PDF
        elif len(clean_text.strip()) < 10:
            status = TEXT_TOO_SHORT

        cache = self.cache_dir / client_id / material["id"]
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "raw_text.txt").write_text(raw_text, encoding="utf-8")
        (cache / "clean_text.txt").write_text(clean_text, encoding="utf-8")
        (cache / "diagnostics.json").write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        parse_ok = status == PARSED_PENDING_CONFIRM
        material["status"] = CONFIRMED if parse_ok else status
        material["confirmed"] = parse_ok
        if parse_ok:
            material["confirmed_at"] = self._now()
        material["parsed_at"] = self._now()
        material["diagnostics"] = diagnostics
        material["cache_dir"] = self._normalize_path(cache)
        material["text_chars"] = len(clean_text)
        material.pop(LEGACY_MATERIAL_CARD_KEY, None)
        self._save_index(data)

        result = dict(material)
        result["raw_text"] = raw_text
        result["clean_text"] = clean_text
        return result

    def confirm_material(self, client_id, material_id, confirmed=True):
        data = self._load_index()
        material = self._find_material(data, client_id, material_id)
        if not material:
            raise KeyError(material_id)
        material["confirmed"] = bool(confirmed)
        if confirmed:
            material["status"] = CONFIRMED
            material["confirmed_at"] = self._now()
        elif material.get("cache_dir"):
            material["status"] = PARSED_PENDING_CONFIRM
        else:
            material["status"] = UNPARSED
        self._save_index(data)
        return material

    def build_generation_bundle(self, client_id, max_chars=None):
        data = self._load_index()
        materials = self._client_materials(data, client_id)
        confirmed = [m for m in materials if m.get("cache_dir") and m.get("confirmed")]
        selected = confirmed
        sections = []
        for material in selected:
            clean_text = self._load_clean_text(material)
            sections.append(format_material_section(material, clean_text))
        combined = "\n\n---\n\n".join(section for section in sections if section)
        return {
            "text": combined if max_chars is None else combined[:max_chars],
            "files": selected,
            "all_files": materials,
            "material_count": len(selected),
            "confirmed_count": len(confirmed),
            "used_unconfirmed_fallback": False,
        }

    def _load_clean_text(self, material):
        cache_dir = material.get("cache_dir")
        if cache_dir:
            path = Path(cache_dir) / "clean_text.txt"
            if path.exists():
                return path.read_text(encoding="utf-8", errors="ignore")
        return ""

    def extract_text_with_diagnostics(self, path):
        ext = path.suffix.lower()
        diagnostics = {
            "file_type": ext.lstrip("."),
            "text_chars": 0,
            "page_count": 0,
            "extractor": "",
            "dependency_error": "",
            "is_scanned_pdf": False,
        }
        try:
            if ext in {".txt", ".md"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                diagnostics["extractor"] = "plain_text"
            elif ext == ".docx":
                text = extract_docx_text(path, diagnostics)
            elif ext == ".doc":
                text = extract_legacy_doc_text(path, diagnostics)
            elif ext == ".pdf":
                text = extract_pdf_text(path, diagnostics)
            elif ext == ".xlsx":
                text = extract_xlsx_text(path, diagnostics)
            elif ext == ".xls":
                diagnostics["dependency_error"] = "legacy .xls extraction requires conversion to .xlsx before upload"
                text = ""
            else:
                text = ""
        except Exception as exc:
            diagnostics["dependency_error"] = f"{type(exc).__name__}: {exc}"
            text = ""
        diagnostics["text_chars"] = len(text)
        if ext == ".pdf" and len(text.strip()) < 30:
            diagnostics["is_scanned_pdf"] = True
        return text, diagnostics


def extract_docx_text(path, diagnostics):
    try:
        import docx

        doc = docx.Document(str(path))
        diagnostics["extractor"] = "python-docx"
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        diagnostics["extractor"] = "ooxml"
        return "\n".join(node.text for node in root.iter() if node.text)


def extract_pdf_text(path, diagnostics):
    dependency_errors = []
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            diagnostics["extractor"] = "pdfplumber"
            diagnostics["page_count"] = len(pdf.pages)
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError as exc:
        dependency_errors.append(f"pdfplumber: {exc}")
    except Exception as exc:
        dependency_errors.append(f"pdfplumber: {type(exc).__name__}: {exc}")
    try:
        import fitz

        doc = fitz.open(path)
        diagnostics["extractor"] = "PyMuPDF"
        diagnostics["page_count"] = len(doc)
        return "\n".join(page.get_text("text") or "" for page in doc)
    except ImportError as exc:
        dependency_errors.append(f"PyMuPDF: {exc}")
    except Exception as exc:
        dependency_errors.append(f"PyMuPDF: {type(exc).__name__}: {exc}")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        diagnostics["extractor"] = "pypdf"
        diagnostics["page_count"] = len(reader.pages)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError as exc:
        dependency_errors.append(f"pypdf: {exc}")
    except Exception as exc:
        dependency_errors.append(f"pypdf: {type(exc).__name__}: {exc}")
    diagnostics["dependency_error"] = "; ".join(dependency_errors)
    return ""


def extract_legacy_doc_text(path, diagnostics):
    errors = []
    for tool in ("antiword", "catdoc"):
        executable = shutil.which(tool)
        if not executable:
            continue
        try:
            import subprocess

            result = subprocess.run(
                [executable, str(path)],
                capture_output=True,
                timeout=20,
            )
        except Exception as exc:
            errors.append(f"{tool}: {type(exc).__name__}: {exc}")
            continue
        output = _decode_tool_output(result.stdout).strip()
        if output:
            diagnostics["extractor"] = tool
            return output
        stderr = _decode_tool_output(result.stderr).strip()
        detail = f"{tool}: exit {result.returncode}"
        if stderr:
            detail += f" {stderr[:200]}"
        errors.append(detail)
    message = "legacy .doc extractor unavailable: install antiword or catdoc"
    if errors:
        message += "; " + "; ".join(errors)
    diagnostics["dependency_error"] = message
    return ""


def extract_xlsx_text(path, diagnostics):
    from services.material_package_extractor import extract_xlsx_file_text

    text, file_record, units = extract_xlsx_file_text(path)
    diagnostics["extractor"] = "material_package_extractor"
    diagnostics["sheet_count"] = file_record.get("sheet_count", 0)
    diagnostics["unit_count"] = len(units)
    if file_record.get("extract_status") == "parse_failed":
        diagnostics["dependency_error"] = file_record.get("error") or "xlsx parse failed"
    return text


def _decode_tool_output(data):
    if not data:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def clean_material_text(text):
    lines = []
    counts = {}
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        counts[line] = counts.get(line, 0) + 1
        if counts[line] > 2 and len(line) <= 30:
            continue
        if line in {"感谢聆听", "谢谢观看", "目录"}:
            continue
        lines.append(line)
    clean = "\n".join(lines)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()




def format_material_section(material, clean_text):
    lines = [
        f"[Customer material] {material.get('original_name') or material.get('name')}",
        f"Status: {'confirmed' if material.get('confirmed') else 'unconfirmed'}",
    ]
    excerpt = (clean_text or '').strip()
    if excerpt:
        lines.append("Excerpt:")
        lines.append(excerpt)
    return "\n".join(lines)
