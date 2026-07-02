import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from base_crawler import extract_platform


SUPPORTED_NODE_PLATFORMS = {"doubao", "deepseek", "qwen", "yuanbao", "kimi", "wenxin"}


class NodeCrawlerBridgeError(RuntimeError):
    pass


def default_node_crawler_root(project_root=None):
    """Return the sibling Node crawler path used during local migration."""
    root = Path(project_root or Path(__file__).resolve().parents[1])
    return root.parent / "ai-search-crawler（进阶API处理）"


def _project_root():
    return Path(__file__).resolve().parents[1]


def _platform_state_path(platform, project_root=None):
    return Path(project_root or _project_root()) / "data" / f"{platform}_state.json"


def _platform_cookie_path(platform, project_root=None):
    return Path(project_root or _project_root()) / "data" / f"{platform}_cookies.json"


def prepare_storage_state_for_node(platform, work_dir, project_root=None):
    """Return a storage_state file path usable by the Node crawler if one exists.

    Python crawlers historically saved either full Playwright storage_state files
    or legacy cookies-only files. Node Playwright expects full storage_state, so
    legacy cookies are wrapped into a temporary storage_state object.
    """
    state_path = _platform_state_path(platform, project_root)
    if state_path.exists():
        return str(state_path)

    cookie_path = _platform_cookie_path(platform, project_root)
    if not cookie_path.exists():
        return ""

    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception:
        return ""
    if not isinstance(cookies, list) or not cookies:
        return ""

    temp_state = Path(work_dir) / f"{platform}_state_from_cookies.json"
    with open(temp_state, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "origins": []}, f, ensure_ascii=False, indent=2)
    return str(temp_state)


def normalize_citation(item):
    url = str(item.get("url") or item.get("href") or "").strip()
    title = str(item.get("title") or item.get("text") or url).strip()
    text = str(item.get("text") or title).strip()
    return {
        "title": title,
        "url": url,
        "platform": item.get("platform") or extract_platform(url),
        "text": text,
    }


def normalize_node_payload(payload, platform="", citations_limit=10):
    """Normalize future JSON output from the Node crawler into Python crawler shape."""
    if not isinstance(payload, dict):
        raise NodeCrawlerBridgeError("Node crawler JSON output must be an object")

    items = payload.get("results")
    if items is None:
        items = payload.get("items", [])
    if not isinstance(items, list):
        raise NodeCrawlerBridgeError("Node crawler JSON output has no results/items list")

    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("query") or "").strip()
        answer = str(item.get("answer") or "").strip()
        error = str(item.get("error") or "").strip()
        raw_refs = item.get("refs")
        if raw_refs is None:
            raw_refs = item.get("citations", [])
        refs = [normalize_citation(ref) for ref in raw_refs if isinstance(ref, dict)]
        refs = [ref for ref in refs if ref["url"]][:citations_limit]
        normalized.append({
            "ok": bool(answer or refs) and not error,
            "question": question,
            "answer": answer,
            "refs": refs,
            "error": error,
            "source_platform": item.get("source_platform") or payload.get("platform") or platform,
        })

    return {
        "ok": True,
        "platform": payload.get("platform") or platform,
        "total": len(normalized),
        "success": sum(1 for item in normalized if item["ok"]),
        "results": normalized,
    }


def _extract_markdown_section(text, heading):
    pattern = re.compile(
        rf"^###\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^###\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group("body").strip() if match else ""


def _parse_markdown_refs(section, citations_limit=10):
    refs = []
    lines = [line.rstrip() for line in section.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = re.match(r"^\d+\.\s+(?P<title>.+?)\s*$", line)
        if not match:
            i += 1
            continue

        title = match.group("title").strip()
        url = ""
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if re.match(r"^https?://", next_line, re.I):
                url = next_line
                i += 1
        if url:
            refs.append(normalize_citation({"title": title, "url": url}))
        if len(refs) >= citations_limit:
            break
        i += 1
    return refs


def parse_node_markdown(markdown_text, platform="", citations_limit=10):
    """Parse current Node crawler Markdown output as a temporary compatibility path."""
    text = str(markdown_text or "")
    platform_match = re.search(r"^- Platform:\s+`([^`]+)`", text, re.MULTILINE)
    detected_platform = platform_match.group(1).strip() if platform_match else platform

    heading_re = re.compile(r"^##\s+\d+\.\s+(?P<query>.+?)\s*$", re.MULTILINE)
    matches = list(heading_re.finditer(text))
    results = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end]
        query = match.group("query").strip()
        answer = _extract_markdown_section(block, "主问题回答")
        refs_section = _extract_markdown_section(block, "参考来源")
        refs = _parse_markdown_refs(refs_section, citations_limit=citations_limit)
        error_match = re.search(r"^- Error:\s*(?P<error>.+)$", block, re.MULTILINE)
        error = error_match.group("error").strip() if error_match else ""
        if answer == "(empty)":
            answer = ""
        results.append({
            "ok": bool(answer or refs) and not error,
            "question": query,
            "answer": answer,
            "refs": refs,
            "error": error,
            "source_platform": detected_platform,
        })

    return {
        "ok": True,
        "platform": detected_platform,
        "total": len(results),
        "success": sum(1 for item in results if item["ok"]),
        "results": results,
    }


def run_node_crawler(
    platform,
    questions,
    crawler_root=None,
    timeout_s=1800,
    citations_limit=10,
    output_dir=None,
):
    """Run the external Node crawler CLI and normalize its Markdown output.

    This is intentionally a bridge, not a replacement for the Python crawler modules.
    """
    platform = str(platform or "").strip()
    if platform not in SUPPORTED_NODE_PLATFORMS:
        raise NodeCrawlerBridgeError(f"Unsupported Node crawler platform: {platform}")
    questions = [str(q).strip() for q in questions if str(q).strip()]
    if not questions:
        raise NodeCrawlerBridgeError("No questions provided for Node crawler")

    root = Path(crawler_root or os.environ.get("GEO_NODE_CRAWLER_ROOT") or default_node_crawler_root())
    index_js = root / "src" / "index.js"
    if not index_js.exists():
        raise NodeCrawlerBridgeError(f"Node crawler entry not found: {index_js}")

    with tempfile.TemporaryDirectory(prefix="geo-node-crawler-") as tmp:
        tmp_path = Path(tmp)
        query_file = tmp_path / "queries.txt"
        output_path = Path(output_dir) if output_dir else tmp_path / "output"
        output_path.mkdir(parents=True, exist_ok=True)
        query_file.write_text("\n".join(questions) + "\n", encoding="utf-8")

        env = os.environ.copy()
        env["OUTPUT_DIR"] = str(output_path)
        env["GEO_NODE_BRIDGE"] = "1"
        env["FOLLOWUP_API_ENABLED"] = os.environ.get("GEO_NODE_CRAWLER_FOLLOWUP_API", "false")
        storage_state_path = prepare_storage_state_for_node(platform, tmp_path)
        if storage_state_path and not env.get("STORAGE_STATE_PATH"):
            env["STORAGE_STATE_PATH"] = storage_state_path
        cmd = [
            "node",
            str(index_js),
            "--platform",
            platform,
            "--query-file",
            str(query_file),
            "--citations-limit",
            str(citations_limit),
        ]
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise NodeCrawlerBridgeError(
                f"Node crawler timed out after {timeout_s}s: {str(exc)[:500]}"
            ) from exc
        except OSError as exc:
            raise NodeCrawlerBridgeError(f"Failed to start Node crawler: {exc}") from exc

        (output_path / "node-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
        (output_path / "node-stderr.log").write_text(completed.stderr or "", encoding="utf-8")

        if completed.returncode != 0:
            raise NodeCrawlerBridgeError(
                f"Node crawler failed with exit code {completed.returncode}: "
                f"{(completed.stderr or completed.stdout or '').strip()[:1000]}"
            )

        md_files = sorted(output_path.glob(f"{platform}-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not md_files:
            raise NodeCrawlerBridgeError("Node crawler completed but no Markdown output was found")
        return parse_node_markdown(md_files[0].read_text(encoding="utf-8"), platform, citations_limit)


def load_node_json_result(json_path, platform="", citations_limit=10):
    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return normalize_node_payload(payload, platform=platform, citations_limit=citations_limit)
