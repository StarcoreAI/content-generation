import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_BASE_URL = "http://127.0.0.1:5000"
DEFAULT_CLIENT_ID = "20260701152718423132"
DEFAULT_GROUP_ID = "20260701152826201973"
PLATFORM_ORDER = ["deepseek", "yuanbao", "qwen", "doubao"]


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_platforms(value):
    requested = [item.strip().lower() for item in value.split(",") if item.strip()]
    if requested == ["all"]:
        return list(PLATFORM_ORDER)
    unknown = [item for item in requested if item not in PLATFORM_ORDER]
    if unknown:
        raise ValueError(f"Unsupported platform(s): {', '.join(unknown)}")
    return requested


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_probe_payload(data_dir, client_id, group_id, question_index):
    clients = read_json(data_dir / "clients.json", [])
    groups_by_client = read_json(data_dir / "probe_groups.json", {})

    client = next((item for item in clients if item.get("id") == client_id), None)
    if not client:
        raise ValueError(f"Client not found: {client_id}")

    groups = groups_by_client.get(client_id, [])
    group = next((item for item in groups if item.get("id") == group_id), None)
    if not group:
        raise ValueError(f"Question group not found: {group_id}")

    questions = group.get("questions") or []
    if question_index < 1 or question_index > len(questions):
        raise ValueError(
            f"Question index out of range: {question_index}; available 1-{len(questions)}"
        )

    question = questions[question_index - 1]
    return {
        "client_id": client_id,
        "client_name": client.get("name", ""),
        "brand": client.get("brand", ""),
        "group_id": group_id,
        "group_name": group.get("name", ""),
        "question_index": question_index,
        "question": question,
        "questions": [question],
    }


def request_json(base_url, method, path, body=None, timeout=1800):
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else None
            return {
                "ok": 200 <= resp.status < 300,
                "status": resp.status,
                "data": parsed,
                "raw": raw,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = None
        return {
            "ok": False,
            "status": exc.code,
            "data": parsed,
            "raw": raw,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "data": None,
            "raw": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def build_crawl_payload(probe, platform, repeat_count, parallel):
    return {
        "client_id": probe["client_id"],
        "brand": probe["brand"],
        "group_id": probe["group_id"],
        "platform": platform,
        "questions": list(probe["questions"]),
        "repeat_count": repeat_count,
        "parallel": parallel,
    }


def summarize_response(platform, elapsed_sec, payload, response):
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    results = data.get("results") if isinstance(data.get("results"), list) else []
    ref_count = sum((item.get("ref_count") or 0) for item in results if isinstance(item, dict))
    ok = bool(response.get("ok") and data.get("ok"))
    return {
        "platform": platform,
        "ok": ok,
        "http_status": response.get("status"),
        "elapsed_sec": elapsed_sec,
        "task_id": data.get("task_id"),
        "task_report": data.get("task_report"),
        "crawler_engine": data.get("crawler_engine"),
        "analyzed": data.get("analyzed"),
        "errors": data.get("errors"),
        "ref_count": ref_count,
        "error": data.get("error") or response.get("error"),
        "message": data.get("message"),
        "request_payload": payload,
        "response": response,
    }


def run_platform(base_url, probe, platform, repeat_count, parallel, timeout):
    payload = build_crawl_payload(probe, platform, repeat_count, parallel)
    started = time.monotonic()
    response = request_json(base_url, "POST", "/api/platform/crawl", payload, timeout=timeout)
    elapsed_sec = round(time.monotonic() - started, 2)
    return summarize_response(platform, elapsed_sec, payload, response)


def write_report(report, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("crawler_smoke_%Y%m%d_%H%M%S.json")
    path = output_dir / name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Run a manual crawler smoke test against the local GEO Flask service."
    )
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--data-dir", default=str(root / "data"))
    parser.add_argument("--output-dir", default=str(root / "data" / "tasks" / "manual_smoke"))
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    parser.add_argument("--group-id", default=DEFAULT_GROUP_ID)
    parser.add_argument("--question-index", type=int, default=1)
    parser.add_argument("--platform", default="qwen", help="qwen, deepseek, yuanbao, doubao, or all")
    parser.add_argument("--repeat-count", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=1800)
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        platforms = parse_platforms(args.platform)
        data_dir = Path(args.data_dir)
        output_dir = Path(args.output_dir)
        probe = load_probe_payload(
            data_dir,
            client_id=args.client_id,
            group_id=args.group_id,
            question_index=args.question_index,
        )
    except Exception as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 2

    report = {
        "started_at": timestamp(),
        "base_url": args.base_url,
        "probe": probe,
        "platforms": platforms,
        "preflight": {
            "health": request_json(args.base_url, "GET", "/api/health", timeout=10),
            "platform_list": request_json(args.base_url, "GET", "/api/platform/list", timeout=30),
        },
        "platform_results": [],
    }

    print(f"Question #{probe['question_index']}: {probe['question']}")
    for platform in platforms:
        print(f"[{platform}] start")
        result = run_platform(
            args.base_url,
            probe,
            platform,
            repeat_count=args.repeat_count,
            parallel=args.parallel,
            timeout=args.timeout,
        )
        report["platform_results"].append(result)
        status = "OK" if result["ok"] else "FAIL"
        print(
            f"[{platform}] {status} http={result['http_status']} "
            f"elapsed={result['elapsed_sec']}s task={result.get('task_id')} "
            f"refs={result.get('ref_count')}"
        )

    report["finished_at"] = timestamp()
    report["ok"] = all(item.get("ok") for item in report["platform_results"])
    path = write_report(report, Path(output_dir))
    print(f"REPORT: {path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
