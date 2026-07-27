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


class KnowledgeBaseService:
    MASTER_FORMAT_VERSION = 3
    CUSTOMER_SECTIONS = (
        "品牌基础",
        "产品/服务",
        "优势",
        "目标人群/痛点",
        "价格",
        "信任",
        "合规风险",
        "公开背景",
    )
    CUSTOMER_SOURCES = (
        ("latest_injection.md", "客户资料解析"),
        ("latest_web_supplement.md", "AI 联网补充"),
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
        return {"source_hashes": {}, "edited_at": "", "source_update_available": False}

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
            return "品牌基础"
        if any(word in key for word in ("产品", "服务", "业务", "项目", "课程")):
            return "产品/服务"
        if any(word in key for word in ("优势", "特色", "特点", "能力", "卖点")):
            return "优势"
        if any(word in key for word in ("人群", "痛点", "需求", "场景", "顾虑")):
            return "目标人群/痛点"
        if any(word in key for word in ("价格", "费用", "收费", "报价")):
            return "价格"
        if any(word in key for word in ("信任", "资质", "案例", "口碑", "团队", "证明")):
            return "信任"
        if any(word in key for word in ("合规", "风险", "限制", "禁", "注意")):
            return "合规风险"
        if any(word in key for word in ("引用", "运营", "判断", "情报", "口径", "备注")):
            return None
        return "公开背景"

    def _split_source(self, content):
        sections = {name: [] for name in self.CUSTOMER_SECTIONS}
        matches = list(re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", content))
        if not matches:
            if content:
                sections["公开背景"].append(content)
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
        return values, hashes

    def _build_customer_master(self, source_material):
        chunks = ["# 客户总资料", "", "以下内容供模型生产和人工维护；人工编辑后不会被上游资料自动覆盖。"]
        for section in self.CUSTOMER_SECTIONS:
            entries = []
            for _label, source_sections in source_material:
                entries.extend(entry for entry in source_sections[section] if not is_short_placeholder_section(entry))
            if entries:
                chunks.extend(["", f"## {section}", "", "\n\n".join(entries)])
        return "\n".join(chunks).strip() + "\n"

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
        path = self._master_path(client_id)
        state = self._load_state(client_id)
        current = self._read_master(path)
        source_changed = (
            source_hashes != state.get("source_hashes", {})
            or state.get("master_format_version") != self.MASTER_FORMAT_VERSION
        )
        if current and state.get("edited_at") and source_changed and not overwrite:
            state["source_update_available"] = True
            self._save_state(client_id, state)
            return self.load_customer_master(client_id)
        if not current or source_changed or overwrite:
            content = self._build_customer_master(source_material)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            state = {
                "source_hashes": source_hashes,
                "edited_at": "",
                "source_update_available": False,
                "synced_at": self.now_fn(),
                "master_format_version": self.MASTER_FORMAT_VERSION,
            }
            self._save_state(client_id, state)
        return self.load_customer_master(client_id)

    def save_customer_master(self, client_id, content):
        content = clean_knowledge_markdown(content)
        if not content:
            raise ValueError("knowledge_content_required")
        path = self._master_path(client_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        state = self._load_state(client_id)
        state["edited_at"] = self.now_fn()
        self._save_state(client_id, state)
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
        source_changed = source_hash != state.get("source_hash")
        if current and state.get("edited_at") and source_changed and not overwrite:
            state["source_update_available"] = True
            save_json(self._competitor_state_path(client_id), state)
            return self.load_competitor_master(client_id)
        if not current or source_changed or overwrite:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            save_json(self._competitor_state_path(client_id), {
                "source_hash": source_hash,
                "edited_at": "",
                "source_update_available": False,
                "synced_at": self.now_fn(),
            })
        return self.load_competitor_master(client_id)

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
