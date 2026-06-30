import argparse
import json
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_URL = "http://127.0.0.1:5000"
DEFAULT_QUESTION = "企业做AI搜索优化时，应该优先关注哪些监测指标？"


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_name(value):
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)


def request_json(method, path, body=None, timeout=30):
    url = BASE_URL + path
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= resp.status < 300,
                "status": resp.status,
                "data": json.loads(raw) if raw else None,
                "raw": raw,
            }
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        return {"ok": False, "status": e.code, "data": parsed, "raw": raw}
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "data": None,
            "raw": "",
            "error": f"{type(e).__name__}: {e}",
        }


def write_reports(report, reports_dir):
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"full_regression_{stamp}.json"
    md_path = reports_dir / f"full_regression_{stamp}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report):
    lines = []
    lines.append("# GEO Agent Full Regression Report")
    lines.append("")
    lines.append(f"- Started: {report.get('started_at')}")
    lines.append(f"- Finished: {report.get('finished_at')}")
    lines.append(f"- Duration: {report.get('duration_sec')}s")
    lines.append(f"- Base URL: `{BASE_URL}`")
    lines.append(f"- Test brand: `{report.get('setup', {}).get('brand', '')}`")
    lines.append(f"- Question: {report.get('question', '')}")
    lines.append("")

    health = report.get("preflight", {}).get("health", {})
    settings = report.get("preflight", {}).get("settings", {})
    lines.append("## Preflight")
    lines.append("")
    lines.append(f"- Service OK: `{health.get('ok')}`")
    lines.append(f"- API key configured: `{settings.get('has_key')}`")
    lines.append(f"- Model: `{settings.get('model', '')}`")
    lines.append("")

    lines.append("## Platform Results")
    lines.append("")
    lines.append("| Platform | Status | Duration | Analyzed | Samples | Error |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for item in report.get("platform_results", []):
        status = "PASS" if item.get("passed") else "FAIL"
        error = item.get("error") or item.get("message") or ""
        if len(error) > 120:
            error = error[:117] + "..."
        lines.append(
            f"| {item.get('platform')} | {status} | {item.get('duration_sec')}s | "
            f"{item.get('analyzed', 0)} | {item.get('total_samples', 0)} | {error} |"
        )
    lines.append("")

    checks = report.get("post_checks", {})
    lines.append("## Post Checks")
    lines.append("")
    lines.append(f"- Main records for test client: `{checks.get('records_count')}`")
    lines.append(f"- Raw records for test client: `{checks.get('raw_records_count')}`")
    lines.append(f"- Articles for test client: `{checks.get('articles_count')}`")
    lines.append(f"- Stats total records: `{checks.get('stats', {}).get('total_records')}`")
    lines.append(f"- Stats total articles: `{checks.get('stats', {}).get('total_articles')}`")
    lines.append("")

    content = report.get("content_generation", {})
    lines.append("## Content Generation")
    lines.append("")
    lines.append(f"- Status: `{'PASS' if content.get('passed') else 'FAIL'}`")
    if content.get("title"):
        lines.append(f"- Title: {content.get('title')}")
    if content.get("error"):
        lines.append(f"- Error: {content.get('error')}")
    lines.append("")

    cleanup = report.get("cleanup", {})
    lines.append("## Cleanup")
    lines.append("")
    lines.append(f"- Enabled: `{cleanup.get('enabled')}`")
    lines.append(f"- Client deleted: `{cleanup.get('client_deleted')}`")
    lines.append(f"- Platform deleted: `{cleanup.get('platform_deleted')}`")
    if cleanup.get("error"):
        lines.append(f"- Error: {cleanup.get('error')}")
    lines.append("")

    return "\n".join(lines)


def compute_passed(report):
    if report.get("fatal_error"):
        return False
    platform_results = report.get("platform_results", [])
    if not platform_results:
        return False
    if any(not item.get("passed") for item in platform_results):
        return False
    if not report.get("content_generation", {}).get("passed"):
        return False
    cleanup = report.get("cleanup", {})
    if cleanup.get("enabled") and (
        cleanup.get("client_deleted") is False
        or cleanup.get("platform_deleted") is False
    ):
        return False
    return True


def pick_platforms(all_platforms, requested):
    if requested and requested != ["auto"]:
        requested_set = set(requested)
        return [p for p in all_platforms if p.get("id") in requested_set]
    return [p for p in all_platforms if p.get("logged_in")]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run unattended GEO Agent full regression checks.")
    parser.add_argument("platforms", nargs="*", default=["auto"], help="Platform ids, or auto. Example: qwen deepseek")
    parser.add_argument("--timeout", type=int, default=420, help="Seconds per platform crawl request.")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--keep-data", action="store_true", help="Do not delete the temporary client/platform.")
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args(argv)

    start_ts = time.time()
    report = {
        "started_at": now_str(),
        "base_url": BASE_URL,
        "question": args.question,
        "preflight": {},
        "setup": {},
        "platform_results": [],
        "content_generation": {},
        "post_checks": {},
        "cleanup": {"enabled": not args.keep_data},
    }

    client_id = ""
    platform_id = ""

    try:
        health = request_json("GET", "/api/health", timeout=10)
        settings = request_json("GET", "/api/settings", timeout=10)
        platform_list_resp = request_json("GET", "/api/platform/list", timeout=10)

        report["preflight"]["health"] = health.get("data") or {"error": health.get("error") or health.get("raw")}
        report["preflight"]["settings"] = settings.get("data") or {"error": settings.get("error") or settings.get("raw")}
        all_platforms = platform_list_resp.get("data") or []
        report["preflight"]["platforms"] = all_platforms

        if not health.get("ok") or not (health.get("data") or {}).get("ok"):
            raise RuntimeError("Service health check failed.")
        if not (settings.get("data") or {}).get("has_key"):
            raise RuntimeError("API key is not configured.")

        selected_platforms = pick_platforms(all_platforms, args.platforms)
        report["selected_platforms"] = [p.get("id") for p in selected_platforms]
        if not selected_platforms:
            raise RuntimeError("No platforms selected. Login first or pass platform ids.")

        suffix = datetime.now().strftime("%Y%m%d%H%M%S")
        brand = f"GEO回归测试品牌{suffix}"
        client_resp = request_json(
            "POST",
            "/api/clients",
            {
                "name": f"回归测试客户{suffix}",
                "brand": brand,
                "industry": "AI搜索优化与企业服务软件",
                "goal": "无人值守完整回归测试",
            },
            timeout=20,
        )
        if not client_resp.get("ok"):
            raise RuntimeError(f"Create client failed: {client_resp.get('raw') or client_resp.get('error')}")
        client = client_resp["data"]["client"]
        client_id = client["id"]

        group_resp = request_json(
            "POST",
            f"/api/groups/{client_id}",
            {
                "name": "无人值守回归测试问题组",
                "description": "自动创建，测试结束默认删除",
                "questions": [args.question],
            },
            timeout=20,
        )
        if not group_resp.get("ok"):
            raise RuntimeError(f"Create group failed: {group_resp.get('raw') or group_resp.get('error')}")
        group = group_resp["data"]["group"]

        pub_platform_resp = request_json(
            "POST",
            "/api/platforms",
            {
                "name": f"无人值守回归发布平台{suffix}",
                "style": "专业、清晰、偏实操",
                "word_count": "300-500字",
                "title_rule": "标题包含明确问题和解决方向",
                "taboos": "避免夸大承诺",
                "notes": "自动化回归测试，可删除",
            },
            timeout=20,
        )
        if not pub_platform_resp.get("ok"):
            raise RuntimeError(f"Create publication platform failed: {pub_platform_resp.get('raw') or pub_platform_resp.get('error')}")
        platform_id = pub_platform_resp["data"]["platform"]["id"]

        report["setup"] = {
            "client_id": client_id,
            "brand": brand,
            "group_id": group["id"],
            "platform_id": platform_id,
        }

        for platform in selected_platforms:
            pid = platform["id"]
            item = {
                "platform": pid,
                "name": platform.get("name", pid),
                "started_at": now_str(),
                "passed": False,
            }
            t0 = time.time()
            crawl_resp = request_json(
                "POST",
                "/api/platform/crawl",
                {
                    "client_id": client_id,
                    "brand": brand,
                    "group_id": group["id"],
                    "platform": pid,
                    "questions": [args.question],
                    "repeat_count": 1,
                    "parallel": 1,
                },
                timeout=args.timeout,
            )
            item["duration_sec"] = round(time.time() - t0, 1)
            item["http_status"] = crawl_resp.get("status")
            data = crawl_resp.get("data")
            if crawl_resp.get("ok") and data and data.get("ok"):
                item.update({
                    "passed": (data.get("analyzed", 0) > 0 and data.get("errors", 0) == 0),
                    "analyzed": data.get("analyzed", 0),
                    "errors": data.get("errors", 0),
                    "total_samples": data.get("total_samples", 0),
                    "analysis_mode": data.get("analysis_mode"),
                    "first_result": (data.get("results") or [{}])[0],
                })
            else:
                details = (data or {}).get("details") or []
                detail_text = "; ".join(str(x) for x in details[:3])
                item["error"] = (
                    (data or {}).get("message")
                    or (data or {}).get("error")
                    or crawl_resp.get("error")
                    or crawl_resp.get("raw")
                    or "crawl request failed"
                )
                if detail_text:
                    item["error"] = f"{item['error']} ({detail_text})"
                item["response"] = data
            report["platform_results"].append(item)

        article_resp = request_json(
            "POST",
            "/api/articles/generate",
            {
                "client_id": client_id,
                "brand": brand,
                "platform_id": platform_id,
                "topic": "AI搜索优化监测指标怎么建立",
                "selling_points": "帮助企业监测AI回答中的品牌提及、引用来源和优化机会",
                "content_pattern": "先解释问题，再给指标清单，最后给执行建议",
                "title_pattern": "问题式标题",
            },
            timeout=90,
        )
        if article_resp.get("ok") and (article_resp.get("data") or {}).get("ok"):
            article = article_resp["data"]["article"]
            report["content_generation"] = {
                "passed": True,
                "article_id": article.get("id"),
                "title": article.get("title"),
            }
        else:
            report["content_generation"] = {
                "passed": False,
                "error": (article_resp.get("data") or {}).get("error") or article_resp.get("error") or article_resp.get("raw"),
            }

        records = request_json("GET", f"/api/intel/records?client_id={urllib.parse.quote(client_id)}", timeout=30)
        raw_records = request_json("GET", f"/api/raw_records?client_id={urllib.parse.quote(client_id)}", timeout=30)
        articles = request_json("GET", f"/api/articles?client_id={urllib.parse.quote(client_id)}", timeout=30)
        stats = request_json("GET", f"/api/stats/overview?client_id={urllib.parse.quote(client_id)}", timeout=30)
        report["post_checks"] = {
            "records_count": len(records.get("data") or []),
            "raw_records_count": len(raw_records.get("data") or []),
            "articles_count": len(articles.get("data") or []),
            "stats": stats.get("data") or {},
        }

    except Exception as e:
        report["fatal_error"] = f"{type(e).__name__}: {e}"
        report["traceback"] = traceback.format_exc()
    finally:
        if client_id and not args.keep_data:
            try:
                delete_client = request_json("DELETE", f"/api/clients/{urllib.parse.quote(client_id)}", timeout=30)
                report["cleanup"]["client_deleted"] = bool(delete_client.get("ok"))
                if not delete_client.get("ok"):
                    report["cleanup"]["client_delete_response"] = delete_client
            except Exception as e:
                report["cleanup"]["client_deleted"] = False
                report["cleanup"]["error"] = f"{type(e).__name__}: {e}"

        if platform_id and not args.keep_data:
            try:
                delete_platform = request_json("DELETE", f"/api/platforms/{urllib.parse.quote(platform_id)}", timeout=30)
                report["cleanup"]["platform_deleted"] = bool(delete_platform.get("ok"))
                if not delete_platform.get("ok"):
                    report["cleanup"]["platform_delete_response"] = delete_platform
            except Exception as e:
                report["cleanup"]["platform_deleted"] = False
                report["cleanup"]["error"] = f"{type(e).__name__}: {e}"

        report["finished_at"] = now_str()
        report["duration_sec"] = round(time.time() - start_ts, 1)
        report["passed"] = compute_passed(report)
        json_path, md_path = write_reports(report, Path(args.reports_dir))
        report["report_files"] = {"json": str(json_path), "markdown": str(md_path)}

        print(json.dumps({
            "passed": report.get("passed"),
            "report_json": str(json_path),
            "report_markdown": str(md_path),
            "fatal_error": report.get("fatal_error", ""),
            "content_generation_passed": report.get("content_generation", {}).get("passed"),
            "platform_results": [
                {
                    "platform": item.get("platform"),
                    "passed": item.get("passed"),
                    "duration_sec": item.get("duration_sec"),
                    "error": item.get("error", ""),
                }
                for item in report.get("platform_results", [])
            ],
        }, ensure_ascii=False, indent=2))

    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
