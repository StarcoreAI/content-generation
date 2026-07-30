"""Editable customer knowledge masters built from existing material packages."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from services.storage import load_json, save_json


_SOURCE_FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*"
    r"(?:来源\s*(?:URL|网址|链接|性质|依据)|出处性质|时间锚点|地区锚点)"
    r"\s*[：:]\s*(?:\*\*)?\s*.*$",
    re.IGNORECASE,
)
_SOURCE_SECTION_RE = re.compile(r"^\s*#{1,6}\s*(?:来源清单|来源列表|来源索引)\s*$")


def clean_knowledge_markdown(content):
    """Remove traceability metadata while keeping usable facts and restrictions."""
    lines = str(content or "").splitlines()
    cleaned = []
    skipping_source_section = False
    source_section_level = 0
    for raw_line in lines:
        heading = re.match(r"^\s*(#{1,6})\s+", raw_line)
        if _SOURCE_SECTION_RE.match(raw_line):
            skipping_source_section = True
            source_section_level = len(heading.group(1)) if heading else 1
            continue
        if skipping_source_section:
            if heading and len(heading.group(1)) <= source_section_level:
                skipping_source_section = False
            else:
                continue
        if _SOURCE_FIELD_RE.match(raw_line):
            continue
        line = re.sub(r"[（(]\s*来源\s*[：:][^）)]*[）)]", "", raw_line).rstrip()
        if line:
            cleaned.append(line)
        elif cleaned and cleaned[-1]:
            cleaned.append("")
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned).strip()


def is_short_placeholder_section(content):
    text = re.sub(r"\s+", "", str(content or ""))
    return len(text) < 50 and any(marker in text for marker in ("暂无资料", "暂无合并资料", "暂无可合并资料"))


CUSTOMER_FACT_SECTIONS = (
    "品牌与服务主体",
    "产品与服务",
    "特有方法与服务逻辑",
    "服务对象与适配边界",
    "价格与费用",
    "信任与可核验信息",
)
CUSTOMER_FACT_FORBIDDEN_MARKERS = (
    "可用角度", "写作方向", "文章结构", "模板", "常见问题", "FAQ", "场景词",
    "示例问题", "问题组", "客服话术", "行业现象", "行业背景", "公开背景",
    "风险提示", "合规风险", "待核验", "待确认", "检索提示", "来源", "运营备注",
)


def validate_customer_content_facts(content):
    """Check that editable customer material remains a fact layer, not a content brief."""
    headings = [match.group(1).strip() for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", str(content or ""))]
    forbidden_headings = [
        heading for heading in headings
        if any(marker.lower() in heading.lower() for marker in CUSTOMER_FACT_FORBIDDEN_MARKERS)
    ]
    allowed_headings = [heading for heading in headings if heading in CUSTOMER_FACT_SECTIONS]
    has_required_fact_section = any(heading in {"品牌与服务主体", "产品与服务"} for heading in allowed_headings)
    return {
        "usable_for_generation": has_required_fact_section and not forbidden_headings,
        "forbidden_headings": forbidden_headings,
        "allowed_headings": allowed_headings,
    }


class KnowledgeBaseService:
    MASTER_FORMAT_VERSION = 4
    CUSTOMER_SECTIONS = CUSTOMER_FACT_SECTIONS
    CUSTOMER_SOURCES = (
        ("latest_injection.md", "客户资料解析"),
    )

    def __init__(self, root_dir, now_fn=None):
        self.root_dir = Path(root_dir)
        self.now_fn = now_fn or (lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _client_dir(self, client_id):
        return self.root_dir / str(client_id)

    def _master_path(self, client_id):
        return self._client_dir(client_id) / "customer_master.md"

    def _state_path(self, client_id):
        return self._client_dir(client_id) / "customer_state.json"

    def _competitor_master_path(self, client_id):
        return self._client_dir(client_id) / "competitor_master.md"

    def _competitor_state_path(self, client_id):
        return self._client_dir(client_id) / "competitor_state.json"

    @staticmethod
    def _digest(content):
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_source(path):
        path = Path(path)
        return path.read_text(encoding="utf-8", errors="ignore").strip() if path.exists() else ""

    @staticmethod
    def _read_master(path):
        path = Path(path)
        return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""

    def _empty_state(self):
        return {"source_hashes": {}, "edited_at": "", "source_update_available": False, "suppressed_customer_sections": []}

    def _load_state(self, client_id):
        path = self._state_path(client_id)
        state = load_json(path, self._empty_state()) if path.exists() else self._empty_state()
        return state if isinstance(state, dict) else self._empty_state()

    def _save_state(self, client_id, state):
        save_json(self._state_path(client_id), state)

    @staticmethod
    def _section_name(heading):
        key = re.sub(r"[\s:：/／、·.-]+", "", str(heading or "").lower())
        if any(word in key for word in ("品牌", "主体", "公司", "机构", "基础信息")):
            return "品牌与服务主体"
        if any(word in key for word in ("优势", "特色", "特点", "能力", "卖点", "方法", "技术", "逻辑", "机制", "流程")):
            return "特有方法与服务逻辑"
        if any(word in key for word in ("人群", "适配", "边界", "范围", "对象")):
            return "服务对象与适配边界"
        if any(word in key for word in ("价格", "费用", "收费", "报价")):
            return "价格与费用"
        if any(word in key for word in ("信任", "资质", "案例", "口碑", "团队", "证明", "荣誉")):
            return "信任与可核验信息"
        if any(word in key for word in ("产品", "服务", "业务", "项目", "课程")):
            return "产品与服务"
        return None

    def _split_source(self, content):
        sections = {name: [] for name in self.CUSTOMER_SECTIONS}
        matches = list(re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", content))
        if not matches:
            return sections
        for index, match in enumerate(matches):
            body_start = match.end()
            body_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            body = content[body_start:body_end].strip()
            section = self._section_name(match.group(1))
            if body and section in sections and not is_short_placeholder_section(body):
                sections[section].append(body)
        return sections

    def _source_material(self, package_dir):
        values = []
        hashes = {}
        for filename, label in self.CUSTOMER_SOURCES:
            content = self._read_source(Path(package_dir) / filename)
            hashes[filename] = self._digest(content)
            values.append((label, self._split_source(clean_knowledge_markdown(content))))
        web_path = Path(package_dir) / "latest_web_supplement.md"
        web_content = self._read_source(web_path)
        hashes[web_path.name] = self._digest(web_content)
        if self._is_customer_web_fact_candidate(web_content):
            values.append(("客户联网事实候选", self._split_source(clean_knowledge_markdown(web_content))))
        return values, hashes

    @staticmethod
    def _is_customer_web_fact_candidate(content):
        text = str(content or "").strip()
        if not text.startswith("# 客户联网事实候选"):
            return False
        headings = [match.group(1).strip() for match in re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", text)]
        return bool(headings) and all(heading in CUSTOMER_FACT_SECTIONS for heading in headings)

    def _build_customer_master(self, source_material, suppressed_sections=()):
        suppressed = set(suppressed_sections or ())
        chunks = ["# 客户内容资料"]
        for section in self.CUSTOMER_SECTIONS:
            if section in suppressed:
                continue
            entries = []
            for _label, source_sections in source_material:
                entries.extend(entry for entry in source_sections[section] if not is_short_placeholder_section(entry))
            if entries:
                chunks.extend(["", f"## {section}", "", "\n\n".join(entries)])
        return "\n".join(chunks).strip() + "\n"

    @staticmethod
    def _fact_blocks(content):
        blocks, paragraph = [], []
        for raw_line in str(content or "").splitlines():
            line = raw_line.strip()
            if not line:
                if paragraph:
                    blocks.append("\n".join(paragraph).strip())
                    paragraph = []
                continue
            if re.match(r"^(?:[-*]|\d+[.)])\s+", line):
                if paragraph:
                    blocks.append("\n".join(paragraph).strip())
                    paragraph = []
                blocks.append(line)
            else:
                paragraph.append(line)
        if paragraph:
            blocks.append("\n".join(paragraph).strip())
        return [block for block in blocks if block]

    def _merge_customer_content(self, current, candidate, suppressed_sections=()):
        current = str(current or "").strip()
        suppressed = set(suppressed_sections or ())
        candidate_sections = self._split_source(clean_knowledge_markdown(candidate))
        if not current:
            return self._build_customer_master([("候选事实", candidate_sections)], suppressed), sum(
                len(self._fact_blocks(body)) for bodies in candidate_sections.values() for body in bodies
            ), 0

        matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", current))
        preamble = current[:matches[0].start()].strip() if matches else current
        sections, order = {}, []
        for index, match in enumerate(matches):
            name = match.group(1).strip()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(current)
            body = current[match.end():end].strip()
            normalized_name = self._section_name(name) or name
            if normalized_name not in sections:
                sections[normalized_name] = []
                order.append(normalized_name)
            if body:
                sections[normalized_name].append(body)

        added = skipped = 0
        for section in self.CUSTOMER_SECTIONS:
            if section in suppressed:
                continue
            existing = sections.setdefault(section, [])
            if section not in order:
                order.append(section)
            seen = {re.sub(r"\s+", " ", block).strip() for body in existing for block in self._fact_blocks(body)}
            for body in candidate_sections[section]:
                for block in self._fact_blocks(body):
                    normalized = re.sub(r"\s+", " ", block).strip()
                    if normalized in seen:
                        skipped += 1
                    else:
                        existing.append(block)
                        seen.add(normalized)
                        added += 1

        chunks = [preamble or "# 客户内容资料"]
        for section in order:
            body = "\n\n".join(sections.get(section) or []).strip()
            if body:
                chunks.extend(["", f"## {section}", "", body])
        return "\n".join(chunks).strip() + "\n", added, skipped

    def merge_customer_fact_candidate(self, client_id, candidate_markdown):
        path = self._master_path(client_id)
        state = self._load_state(client_id)
        content, merged_count, skipped_count = self._merge_customer_content(
            self._read_master(path), candidate_markdown, state.get("suppressed_customer_sections") or [],
        )
        if merged_count or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return {"content": content, "merged_count": merged_count, "skipped_count": skipped_count}

    def load_customer_master(self, client_id):
        path = self._master_path(client_id)
        state = self._load_state(client_id)
        return {
            "content": self._read_master(path),
            "source_update_available": bool(state.get("source_update_available")),
            "edited_at": str(state.get("edited_at") or ""),
        }

    def sync_customer_master(self, client_id, package_dir, overwrite=False):
        source_material, source_hashes = self._source_material(package_dir)
        candidate = self._build_customer_master(source_material)
        merged = self.merge_customer_fact_candidate(client_id, candidate)
        state = self._load_state(client_id)
        state.update({
            "source_hashes": source_hashes,
            "source_update_available": False,
            "synced_at": self.now_fn(),
            "master_format_version": self.MASTER_FORMAT_VERSION,
        })
        self._save_state(client_id, state)
        return {**self.load_customer_master(client_id), **merged}

    def save_customer_master(self, client_id, content, removed_sections=None):
        content = clean_knowledge_markdown(content)
        if not content:
            raise ValueError("knowledge_content_required")
        path = self._master_path(client_id)
        present = {
            self._section_name(match.group(1))
            for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", content)
            if self._section_name(match.group(1))
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        state = self._load_state(client_id)
        suppressed = set(state.get("suppressed_customer_sections") or [])
        suppressed.update(
            section for section in (self._section_name(name) for name in (removed_sections or [])) if section
        )
        state["suppressed_customer_sections"] = sorted(suppressed - present)
        state["edited_at"] = self.now_fn()
        self._save_state(client_id, state)
        return self.load_customer_master(client_id)

    def prepare_customer_fact_migration(self, client_id, package_dir):
        """Build a candidate fact layer without touching an editable master."""
        source_material, _source_hashes = self._source_material(package_dir)
        current = self._read_master(self._master_path(client_id))
        validation = validate_customer_content_facts(current)
        return {
            "current_content": current,
            "candidate_content": self._build_customer_master(source_material),
            "deletion_headings": validation["forbidden_headings"],
            "migration_required": not validation["usable_for_generation"],
        }

    def confirm_customer_fact_migration(self, client_id, content, package_dir):
        cleaned = clean_knowledge_markdown(content)
        validation = validate_customer_content_facts(cleaned)
        if not validation["usable_for_generation"]:
            raise ValueError("customer_content_facts_invalid")
        _source_material, source_hashes = self._source_material(package_dir)
        path = self._master_path(client_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cleaned, encoding="utf-8")
        self._save_state(client_id, {
            "source_hashes": source_hashes,
            "edited_at": self.now_fn(),
            "source_update_available": False,
            "synced_at": self.now_fn(),
            "master_format_version": self.MASTER_FORMAT_VERSION,
        })
        return self.load_customer_master(client_id)

    def _load_competitor_state(self, client_id):
        path = self._competitor_state_path(client_id)
        state = load_json(path, self._empty_state()) if path.exists() else self._empty_state()
        return state if isinstance(state, dict) else self._empty_state()

    def load_competitor_master(self, client_id):
        state = self._load_competitor_state(client_id)
        return {
            "content": self._read_master(self._competitor_master_path(client_id)),
            "source_update_available": bool(state.get("source_update_available")),
            "edited_at": str(state.get("edited_at") or ""),
        }

    def sync_competitor_master(self, client_id, content, overwrite=False):
        content = clean_knowledge_markdown(content)
        path = self._competitor_master_path(client_id)
        state = self._load_competitor_state(client_id)
        current = self._read_master(path)
        source_hash = self._digest(content)
        from services.competitor_knowledge import merge_competitor_master_markdown

        def fact_lines(markdown):
            sections = re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown)
            matches = list(sections)
            lines = set()
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
                for line in markdown[match.end():end].splitlines():
                    normalized = re.sub(r"\s+", " ", line).strip()
                    if normalized:
                        lines.add(normalized)
            return lines

        existing_lines = fact_lines(current)
        incoming_lines = fact_lines(content)
        merged_count = len(incoming_lines - existing_lines)
        skipped_count = len(incoming_lines & existing_lines)
        merged_content = merge_competitor_master_markdown(current, content)
        if merged_content != current:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(merged_content, encoding="utf-8")
        state.update({
            "source_hash": source_hash,
            "source_update_available": False,
            "synced_at": self.now_fn(),
        })
        save_json(self._competitor_state_path(client_id), state)
        return {**self.load_competitor_master(client_id), "merged_count": merged_count, "skipped_count": skipped_count}

    def save_competitor_master(self, client_id, content):
        content = clean_knowledge_markdown(content)
        if not content:
            raise ValueError("knowledge_content_required")
        path = self._competitor_master_path(client_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        state = self._load_competitor_state(client_id)
        state["edited_at"] = self.now_fn()
        save_json(self._competitor_state_path(client_id), state)
        return self.load_competitor_master(client_id)
