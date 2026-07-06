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


ALLOWED_MATERIAL_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".doc"}
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
        local_pdf_dir="pdf",
        index_path="data/materials_index.json",
        cache_dir="data/material_cache",
    ):
        self.root_dir = Path(root_dir)
        self.upload_dir = Path(upload_dir)
        self.local_pdf_dir = Path(local_pdf_dir)
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

    def list_local_materials(self):
        if not self.local_pdf_dir.exists():
            return []
        files = []
        for path in sorted(self.local_pdf_dir.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_file() or not self._is_allowed(path.name):
                continue
            files.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)
                    ),
                }
            )
        return files

    def list_client_materials(self, client_id):
        data = self._load_index()
        items = self._client_materials(data, client_id)
        return sorted(items, key=lambda item: item.get("uploaded_at", ""), reverse=True)

    def save_uploaded_material(self, client_id, storage_file, original_filename, source="upload"):
        if not original_filename or not self._is_allowed(original_filename):
            raise ValueError("不支持的文件格式，请上传 txt/pdf/md/docx")
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

    def import_local_material(self, client_id, filename):
        if not filename or Path(filename).name != filename or not self._is_allowed(filename):
            raise ValueError("不支持的本地资料文件")
        source = self.local_pdf_dir / filename
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(filename)
        return self.save_uploaded_material(
            client_id, source, source.name, source="local_pdf_folder"
        )

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
        fact_card = build_fact_card(clean_text, material.get("original_name", ""))
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
        (cache / "fact_card.json").write_text(
            json.dumps(fact_card, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
        material["fact_card"] = fact_card
        self._save_index(data)

        result = dict(material)
        result["raw_text"] = raw_text
        result["clean_text"] = clean_text
        result["fact_card"] = fact_card
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

    def build_generation_bundle(self, client_id, max_chars=12000):
        data = self._load_index()
        materials = self._client_materials(data, client_id)
        confirmed = [m for m in materials if m.get("cache_dir") and m.get("confirmed")]
        selected = confirmed
        sections = []
        for material in selected:
            card = self._load_fact_card(material)
            clean_text = self._load_clean_text(material)
            sections.append(format_fact_card_section(material, card, clean_text))
        combined = "\n\n---\n\n".join(section for section in sections if section)
        return {
            "text": combined[:max_chars],
            "files": selected,
            "all_files": materials,
            "material_count": len(selected),
            "confirmed_count": len(confirmed),
            "used_unconfirmed_fallback": False,
        }

    def _load_fact_card(self, material):
        card = material.get("fact_card")
        if isinstance(card, dict):
            return card
        cache_dir = material.get("cache_dir")
        if cache_dir:
            path = Path(cache_dir) / "fact_card.json"
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    return empty_fact_card()
        return empty_fact_card()

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
            elif ext == ".pdf":
                text = extract_pdf_text(path, diagnostics)
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


def empty_fact_card():
    return {
        "brand_names": [],
        "organization_background": [],
        "locations_and_regions": [],
        "services": [],
        "departments_or_specialties": [],
        "doctors_or_team": [],
        "credentials_and_honors": [],
        "equipment_or_technology": [],
        "service_process": [],
        "brand_tone": [],
        "usable_claims": [],
        "uncertain_claims": [],
        "risk_warnings": [],
        "forbidden_claims": [],
    }


def build_fact_card(text, filename=""):
    card = empty_fact_card()
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    full_text = "\n".join(lines)
    for name in extract_brand_names(full_text, filename):
        add_unique(card["brand_names"], name)
    service_terms = [
        "正畸",
        "牙齿矫正",
        "种植牙",
        "根管治疗",
        "洗牙",
        "美白",
        "补牙",
        "拔牙",
        "儿童口腔",
        "牙周",
        "修复",
        "瓷贴面",
        "隐形矫正",
        "口腔检查",
    ]
    credential_terms = ["认证", "会员", "主任医师", "主治医师", "副主任医师", "博士", "硕士", "学会", "医保定点", "上市"]
    equipment_terms = ["设备", "数字化", "CT", "显微镜", "一线品牌", "材料", "技术"]
    process_terms = ["流程", "服务", "到院", "顾客", "标准化", "6S"]
    risk_terms = ["医疗", "治疗", "病例", "患者", "儿童", "青少年", "成人"]
    forbidden_terms = ["保证治愈", "全市第一", "最低价", "无风险", "根治", "包治", "保证效果"]
    for line in lines:
        if re.search(r"(成立于|创办|升级|品牌|集团|医院|门诊|分院|牙椅|员工|顾客|上市|使命|愿景)", line):
            add_unique(card["organization_background"], line)
        if re.search(r"(陕西|甘肃|新疆|河南|西安|安康|区域|城市|门诊|分院|总院)", line):
            add_unique(card["locations_and_regions"], line)
        if any(term in line for term in service_terms):
            add_unique(card["services"], line)
        if re.search(r"(学科|专业|牙体牙髓|种植|正畸|儿童口腔|修复|护理)", line):
            add_unique(card["departments_or_specialties"], line)
        if re.search(r"[\u4e00-\u9fa5]{2,4}(医生|院长|主任|教授|专家)", line):
            add_unique(card["doctors_or_team"], line)
        if any(term in line for term in credential_terms):
            add_unique(card["credentials_and_honors"], line)
        if any(term in line for term in equipment_terms):
            add_unique(card["equipment_or_technology"], line)
        if any(term in line for term in process_terms):
            add_unique(card["service_process"], line)
        if re.search(r"(使命|愿景|价值观|定位|口号|文化|没有看不了的牙)", line):
            add_unique(card["brand_tone"], line)
        if any(term in line for term in risk_terms):
            add_unique(card["risk_warnings"], "医疗内容需避免效果承诺，资质、案例和治疗描述应保守表达。")
        for term in forbidden_terms:
            if term in line or term in full_text:
                add_unique(card["forbidden_claims"], term)
    for key in card:
        card[key] = card[key][:12]
    if not card["forbidden_claims"] and card["risk_warnings"]:
        card["forbidden_claims"] = ["保证治愈", "绝对效果", "全市第一", "最低价", "无风险"]
    return card


def extract_brand_names(text, filename=""):
    candidates = []
    source = f"{filename}\n{text}"
    patterns = [
        r"([\u4e00-\u9fa5A-Za-z0-9]{2,24}(?:口腔医疗科技集团|口腔|医院|门诊|集团|品牌))",
        r"(兔博士)",
        r"(小白兔)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, source):
            value = match.strip(" ，。；:：")
            if 2 <= len(value) <= 28:
                candidates.append(value)
    result = []
    for item in candidates:
        add_unique(result, item)
    return result[:8]


def add_unique(items, value):
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)


def format_fact_card_section(material, card, clean_text):
    lines = [
        f"【客户事实卡】{material.get('original_name') or material.get('name')}",
        f"资料状态：{'已确认' if material.get('confirmed') else '未确认'}",
    ]
    labels = [
        ("brand_names", "品牌/机构"),
        ("organization_background", "机构背景"),
        ("locations_and_regions", "区域/门店"),
        ("services", "服务项目"),
        ("departments_or_specialties", "学科/专业"),
        ("doctors_or_team", "医生/团队"),
        ("credentials_and_honors", "资质/认证/荣誉"),
        ("equipment_or_technology", "设备/技术"),
        ("service_process", "服务流程"),
        ("brand_tone", "品牌调性"),
        ("risk_warnings", "风险提示"),
        ("forbidden_claims", "禁用表达"),
    ]
    for key, label in labels:
        values = card.get(key) or []
        if values:
            lines.append(f"{label}：")
            lines.extend(f"- {item}" for item in values[:8])
    excerpt = clean_text[:1200].strip()
    if excerpt:
        lines.append("原文摘要片段：")
        lines.append(excerpt)
    return "\n".join(lines)
