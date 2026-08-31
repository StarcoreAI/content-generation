import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from base_crawler import extract_platform


SUPPORTED_NODE_PLATFORMS = {"doubao", "deepseek", "qwen", "yuanbao", "kimi", "wenxin"}


class NodeCrawlerBridgeError(RuntimeError):
    pass


class NodeCrawlerStopped(NodeCrawlerBridgeError):
    pass


def default_node_crawler_root(project_root=None):
    """Return the sibling Node crawler path used during local migration."""
    root = Path(project_root or Path(__file__).resolve().parents[1])
    return root.parent / "ai-search-crawler（进阶API处理）"


def _project_root():
    return Path(__file__).resolve().parents[1]


def _node_adapter_override(platform):
    override = _project_root() / "node_adapter_overrides" / f"{platform}AdapterOverride.mjs"
    return override if override.exists() else None


def _node_command(entry_path, platforms=()):
    cmd = ["node"]
    if isinstance(platforms, str):
        platforms = [platforms]
    for platform in dict.fromkeys(platforms or []):
        override = _node_adapter_override(platform)
        if override:
            cmd.extend(["--import", override.resolve().as_uri()])
    cmd.append(str(entry_path))
    return cmd


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


def _read_log_tail(path, max_chars=1000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_chars * 4))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def _latest_markdown_file(output_path, platform):
    md_files = sorted(output_path.glob(f"{platform}-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return md_files[0] if md_files else None


def _node_output_is_final(stdout_path, output_path, platform):
    return bool(_latest_markdown_file(output_path, platform)) and "Crawl done:" in _read_log_tail(stdout_path, 2000)


def _packaged_browser_root(crawler_root):
    browser_root = Path(crawler_root) / "ms-playwright"
    if not browser_root.exists():
        return None
    for chromium_dir in browser_root.glob("chromium-*"):
        if (chromium_dir / "chrome-win64" / "chrome.exe").exists():
            return browser_root
        if (chromium_dir / "chrome-win" / "chrome.exe").exists():
            return browser_root
        if any(chromium_dir.glob("chrome-mac*/*.app/Contents/MacOS/*")):
            return browser_root
    return None


def _set_packaged_browser_path(env, crawler_root):
    packaged_root = _packaged_browser_root(crawler_root)
    if packaged_root:
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(packaged_root)
    else:
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    return env


def _positive_int(value, default=1):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _effective_node_concurrency(platform, requested_concurrency, question_count):
    if platform == "doubao":
        return 1
    return min(requested_concurrency, question_count)


def _write_parallel_accounts_file(storage_state_path, work_dir, concurrency):
    if concurrency <= 1 or not storage_state_path:
        return ""
    source = Path(storage_state_path)
    if not source.exists():
        return ""

    try:
        accounts_file = Path(work_dir) / "accounts.txt"
        account_paths = []
        for index in range(concurrency):
            if index == 0:
                account_paths.append(str(source))
                continue
            account_path = Path(work_dir) / f"account-{index + 1}.json"
            shutil.copyfile(source, account_path)
            account_paths.append(str(account_path))
        accounts_file.write_text("\n".join(account_paths) + "\n", encoding="utf-8")
        return str(accounts_file)
    except OSError:
        return ""


def run_node_auth_preflight(
    platforms,
    crawler_root=None,
    storage_state_path=None,
    timeout_s=1800,
    mode="strict",
    runner=subprocess.run,
):
    platforms = [str(item).strip() for item in (platforms or []) if str(item).strip()]
    unsupported = [platform for platform in platforms if platform not in SUPPORTED_NODE_PLATFORMS]
    if unsupported:
        return {"ok": False, "status": "unsupported", "message": f"Unsupported platform(s): {', '.join(unsupported)}"}
    if not platforms:
        return {"ok": False, "status": "missing_platforms", "message": "No platforms provided"}
    mode = str(mode or "strict").strip().lower()
    if mode not in {"strict", "soft", "manual"}:
        mode = "strict"

    root = Path(crawler_root or os.environ.get("GEO_NODE_CRAWLER_ROOT") or default_node_crawler_root())
    adapter_entry = root / "src" / "adapters" / "index.js"
    if not adapter_entry.exists():
        return {"ok": False, "status": "missing_crawler", "message": f"Node crawler adapters not found: {adapter_entry}"}

    storage_value = storage_state_path or os.environ.get("STORAGE_STATE_PATH")
    if not storage_value:
        return {"ok": False, "status": "missing_state", "message": "STORAGE_STATE_PATH is not set"}
    storage_state = Path(storage_value)
    storage_state.parent.mkdir(parents=True, exist_ok=True)

    script_path = _project_root() / "scripts" / "node_auth_preflight.mjs"
    if not script_path.exists():
        return {"ok": False, "status": "missing_probe", "message": f"Auth preflight not found: {script_path}"}

    cmd = _node_command(script_path, platforms) + [
        "--platforms",
        ",".join(platforms),
        "--crawler-root",
        str(root),
        "--storage-state",
        str(storage_state),
        "--timeout-ms",
        str(max(1, int(timeout_s)) * 1000),
        "--mode",
        mode,
    ]
    env = os.environ.copy()
    env["GEO_NODE_BRIDGE"] = "1"
    env["GEO_NODE_CRAWLER_ROOT"] = str(root)
    _set_packaged_browser_path(env, root)
    try:
        completed = runner(
            cmd,
            cwd=str(root),
            env=env,
            timeout=timeout_s + 30,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout", "message": f"auth preflight timed out after {timeout_s}s"}
    except OSError as exc:
        return {"ok": False, "status": "start_failed", "message": str(exc)}
    return {
        "ok": completed.returncode == 0,
        "status": "ready" if completed.returncode == 0 else "failed",
        "message": "ready" if completed.returncode == 0 else "auth preflight failed",
    }


def _stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            process.wait(timeout=5)
            return
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
            return
        except Exception:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=5)
                return
            except Exception:
                pass
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass


def _run_node_process(
    cmd,
    *,
    cwd,
    env,
    stdout_path,
    stderr_path,
    timeout_s,
    output_path,
    platform,
    progress_callback=None,
    progress_total=0,
):
    start = time.monotonic()
    last_progress = -1
    last_heartbeat = 0.0
    with open(stdout_path, "w", encoding="utf-8", errors="replace") as stdout_log, \
            open(stderr_path, "w", encoding="utf-8", errors="replace") as stderr_log:
        popen_group_kwargs = (
            {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=stdout_log,
            stderr=stderr_log,
            **popen_group_kwargs,
        )
        while True:
            returncode = process.poll()
            if returncode is not None:
                return subprocess.CompletedProcess(cmd, returncode)
            now = time.monotonic()
            if progress_callback and (now - last_heartbeat >= 10 or last_progress < 0):
                text = ""
                try:
                    text = Path(stdout_path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
                matches = re.findall(r"\[保存\]\s*已写入\s*(\d+)\s*条", text)
                completed_count = int(matches[-1]) if matches else max(0, last_progress)
                if completed_count != last_progress or now - last_heartbeat >= 10:
                    stop_reason = ""
                    try:
                        stop_reason = progress_callback({
                            "completed": completed_count,
                            "total": max(0, int(progress_total or 0)),
                            "message": "本地浏览器正在爬取",
                        })
                    except Exception:
                        pass
                    if stop_reason:
                        _stop_process(process)
                        raise NodeCrawlerStopped(str(stop_reason))
                    last_progress = completed_count
                    last_heartbeat = now
            if _node_output_is_final(stdout_path, output_path, platform):
                _stop_process(process)
                return subprocess.CompletedProcess(cmd, 0)
            if time.monotonic() - start > timeout_s:
                _stop_process(process)
                raise subprocess.TimeoutExpired(cmd, timeout_s)
            time.sleep(0.5)


def _next_node_log_paths(output_path):
    output_path = Path(output_path)
    for index in range(1, 1000):
        suffix = "" if index == 1 else f"-{index}"
        stdout_path = output_path / f"node-stdout{suffix}.log"
        stderr_path = output_path / f"node-stderr{suffix}.log"
        if not stdout_path.exists() and not stderr_path.exists():
            return stdout_path, stderr_path
    timestamp = int(time.time())
    return output_path / f"node-stdout-{timestamp}.log", output_path / f"node-stderr-{timestamp}.log"


def run_node_crawler(
    platform,
    questions,
    crawler_root=None,
    timeout_s=1800,
    citations_limit=10,
    output_dir=None,
    concurrency=None,
    progress_callback=None,
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
        if output_dir:
            output_path = Path(output_dir)
            if not output_path.is_absolute():
                output_path = Path.cwd() / output_path
            output_path = output_path.resolve()
        else:
            output_path = tmp_path / "output"
        output_path.mkdir(parents=True, exist_ok=True)
        query_file.write_text("\n".join(questions) + "\n", encoding="utf-8")

        env = os.environ.copy()
        env["OUTPUT_DIR"] = str(output_path)
        env["GEO_NODE_BRIDGE"] = "1"
        env["FOLLOWUP_API_ENABLED"] = os.environ.get("GEO_NODE_CRAWLER_FOLLOWUP_API", "false")
        env["GEO_NODE_NEW_CONVERSATION_EVERY"] = os.environ.get(
            "GEO_NODE_NEW_CONVERSATION_EVERY", "1"
        )
        storage_state_path = prepare_storage_state_for_node(platform, tmp_path)
        if not storage_state_path and platform == "doubao":
            storage_state_path = str(_platform_state_path(platform))
        if storage_state_path:
            env["STORAGE_STATE_PATH"] = storage_state_path
        else:
            env.pop("STORAGE_STATE_PATH", None)
        _set_packaged_browser_path(env, root)
        requested_concurrency = _positive_int(
            concurrency if concurrency is not None else os.environ.get("GEO_NODE_CRAWLER_CONCURRENCY"),
            1,
        )
        effective_concurrency = _effective_node_concurrency(platform, requested_concurrency, len(questions))
        accounts_file = _write_parallel_accounts_file(storage_state_path, tmp_path, effective_concurrency)
        env["GEO_NODE_CRAWLER_ROOT"] = str(root)
        cmd = _node_command(index_js, platform) + [
            "--platform",
            platform,
            "--query-file",
            str(query_file),
            "--citations-limit",
            str(citations_limit),
        ]
        viewport = str(os.environ.get("GEO_NODE_VIEWPORT") or "").strip()
        if viewport:
            cmd.extend(["--viewport", viewport])
        if accounts_file:
            cmd.extend(["--accounts-file", accounts_file, "--concurrency", str(effective_concurrency)])
        stdout_path, stderr_path = _next_node_log_paths(output_path)
        try:
            completed = _run_node_process(
                cmd,
                cwd=str(root),
                env=env,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_s=timeout_s,
                output_path=output_path,
                platform=platform,
                progress_callback=progress_callback,
                progress_total=len(questions),
            )
        except subprocess.TimeoutExpired as exc:
            raise NodeCrawlerBridgeError(
                f"Node crawler timed out after {timeout_s}s: {str(exc)[:500]}"
            ) from exc
        except OSError as exc:
            raise NodeCrawlerBridgeError(f"Failed to start Node crawler: {exc}") from exc

        if completed.returncode != 0:
            error_log = (_read_log_tail(stderr_path) or _read_log_tail(stdout_path)).strip()
            raise NodeCrawlerBridgeError(
                f"Node crawler failed with exit code {completed.returncode}: "
                f"{error_log[:1000]}"
            )

        md_file = _latest_markdown_file(output_path, platform)
        if not md_file:
            raise NodeCrawlerBridgeError("Node crawler completed but no Markdown output was found")
        return parse_node_markdown(md_file.read_text(encoding="utf-8"), platform, citations_limit)


def load_node_json_result(json_path, platform="", citations_limit=10):
    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return normalize_node_payload(payload, platform=platform, citations_limit=citations_limit)
