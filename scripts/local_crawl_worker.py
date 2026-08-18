import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.node_crawler_bridge import (
    SUPPORTED_NODE_PLATFORMS,
    default_node_crawler_root,
    run_node_auth_preflight,
    run_node_crawler,
)


DEFAULT_BASE_URL = "http://127.0.0.1:18080"
DEFAULT_PLATFORMS = ["deepseek", "yuanbao", "qwen", "kimi", "doubao"]
DEFAULT_CRAWLER_CONCURRENCY = 2
LOGIN_RECOVERY_MARKERS = [
    "need_login",
    "cookie_expired",
    "login action",
    "login required",
    "saved state is missing",
    "no longer valid",
]
ACCOUNT_VERIFICATION_RECOVERY_MARKERS = [
    "verification_required",
    "verification",
    "captcha",
    "security check",
    "account abnormal",
    "account exception",
    "账号异常",
    "访问异常",
    "风险验证",
    "人机验证",
    "安全验证",
    "请完成验证",
]


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message):
    print(f"[{timestamp()}] {message}", flush=True)


class CloudClient:
    def __init__(self, base_url, username="", password="", timeout=30):
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
        )

    def request_json(self, method, path, body=None):
        url = urllib.parse.urljoin(self.base_url, path.lstrip("/"))
        data = None
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"message": raw}
            raise RuntimeError(payload.get("message") or payload.get("error") or f"HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"cloud request failed: {exc}") from exc

    def login(self):
        if not self.username:
            return
        self.request_json("POST", "/api/auth/login", {
            "username": self.username,
            "password": self.password,
        })

    def health(self):
        return self.request_json("GET", "/api/health")

    def list_jobs(self):
        payload = self.request_json("GET", "/api/crawl_jobs")
        return payload.get("jobs") or []

    def is_job_canceled(self, job_id):
        query = urllib.parse.urlencode({"job_id": job_id})
        payload = self.request_json("GET", f"/api/crawl_jobs?{query}")
        for job in payload.get("jobs") or []:
            if job.get("id") == job_id:
                return job.get("status") == "canceled"
        return False

    def claim_next(self, worker_id, platform):
        query = urllib.parse.urlencode({"worker_id": worker_id, "platform": platform})
        payload = self.request_json("GET", f"/api/crawl_jobs/next?{query}")
        return payload.get("job")

    def submit_result(self, job_id, payload):
        return self.request_json("POST", f"/api/crawl_jobs/{urllib.parse.quote(job_id)}/result", payload)

    def update_progress(self, job_id, payload):
        return self.request_json(
            "POST",
            f"/api/crawl_jobs/{urllib.parse.quote(job_id)}/progress",
            payload,
        )


def parse_platforms(value):
    if not value or value.strip().lower() == "all":
        return list(DEFAULT_PLATFORMS)
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def expand_job_questions(job):
    questions = [str(item).strip() for item in job.get("questions") or [] if str(item).strip()]
    try:
        repeat_count = max(1, min(int(job.get("repeat_count") or 1), 10))
    except (TypeError, ValueError):
        repeat_count = 1
    expanded = []
    for question in questions:
        expanded.extend([question] * repeat_count)
    return expanded


def _check(name, ok, message=""):
    return {"name": name, "ok": bool(ok), "message": message}


def check_environment(
    cloud_client,
    platforms,
    node_root=None,
    storage_state_path=None,
):
    checks = []
    try:
        health = cloud_client.health()
        checks.append(_check("cloud", health.get("ok"), f"version={health.get('version', '')}".strip("=")))
    except Exception as exc:
        checks.append(_check("cloud", False, str(exc)))

    node_root = Path(node_root or os.environ.get("GEO_NODE_CRAWLER_ROOT") or default_node_crawler_root())
    checks.append(_check("node_root", node_root.exists(), str(node_root)))

    storage_state_path = storage_state_path or os.environ.get("STORAGE_STATE_PATH")
    if storage_state_path:
        storage_state_path = Path(storage_state_path)
        parent = storage_state_path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            ok = parent.exists()
        except OSError:
            ok = False
        checks.append(_check("storage_state", ok, str(storage_state_path)))
    else:
        checks.append(_check("storage_state", False, "STORAGE_STATE_PATH is not set"))

    unsupported = [platform for platform in platforms if platform not in SUPPORTED_NODE_PLATFORMS]
    checks.append(_check("platforms", not unsupported, ",".join(unsupported) if unsupported else ",".join(platforms)))
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def print_check_result(result):
    for item in result["checks"]:
        mark = "OK" if item["ok"] else "FAIL"
        suffix = f" - {item['message']}" if item.get("message") else ""
        log(f"[{mark}] {item['name']}{suffix}")
    log("preflight basic checks passed" if result["ok"] else "preflight basic checks failed")


def is_login_recovery_error(error):
    message = str(error or "").lower()
    return any(marker in message for marker in LOGIN_RECOVERY_MARKERS + ACCOUNT_VERIFICATION_RECOVERY_MARKERS)


def is_account_verification_recovery_error(error):
    message = str(error or "").lower()
    return any(marker in message for marker in ACCOUNT_VERIFICATION_RECOVERY_MARKERS)


def platform_storage_state_path(platform):
    return ROOT / "data" / f"{platform}_state.json"


def run_job(
    job,
    run_crawler=run_node_crawler,
    run_login=None,
    output_root=None,
    timeout_s=1800,
    crawler_concurrency=DEFAULT_CRAWLER_CONCURRENCY,
    progress_callback=None,
):
    platform = job.get("platform", "")
    questions = expand_job_questions(job)
    output_root = Path(output_root or Path("logs") / "local-worker")
    output_dir = output_root / str(job.get("id") or "unknown-job") / platform
    output_dir.mkdir(parents=True, exist_ok=True)
    run_login = run_login or run_login_job

    def crawl_once(concurrency=None):
        effective_concurrency = crawler_concurrency if concurrency is None else concurrency
        result = run_crawler(
            platform,
            questions,
            timeout_s=timeout_s,
            output_dir=output_dir,
            concurrency=effective_concurrency,
            progress_callback=progress_callback,
        )
        return {
            "status": "completed",
            "summary": {
                "total": result.get("total", len(questions)),
                "success": result.get("success", 0),
            },
            "results": result.get("results") or [],
            "logs": [str(output_dir)],
            "crawler_engine": "node",
        }

    try:
        return crawl_once()
    except Exception as exc:
        first_error = str(exc)
        if is_login_recovery_error(first_error):
            log(f"{platform} login expired during crawl; opening manual login and retrying job once")
            login_payload = run_login(job, timeout_s=timeout_s)
            if login_payload.get("status") == "completed":
                try:
                    retry_concurrency = 1 if is_account_verification_recovery_error(first_error) else crawler_concurrency
                    log(
                        f"{platform} login recovered; retrying current job "
                        f"with {retry_concurrency} browser window(s)"
                    )
                    return crawl_once(concurrency=retry_concurrency)
                except Exception as retry_exc:
                    return {
                        "status": "failed",
                        "summary": {"total": len(questions), "success": 0},
                        "error": str(retry_exc),
                        "results": [],
                        "logs": [str(output_dir)],
                        "crawler_engine": "node",
                    }
            login_error = login_payload.get("error") or "manual login failed"
            first_error = f"{first_error}; login recovery failed: {login_error}"
        return {
            "status": "failed",
            "summary": {"total": len(questions), "success": 0},
            "error": first_error,
            "results": [],
            "logs": [str(output_dir)],
            "crawler_engine": "node",
        }


def run_login_job(job, timeout_s=1800):
    platform = job.get("platform", "")
    try:
        storage_state_path = platform_storage_state_path(platform)
        result = run_node_auth_preflight(
            [platform],
            timeout_s=timeout_s,
            mode="manual",
            storage_state_path=str(storage_state_path),
        )
        if result.get("ok"):
            return {
                "status": "completed",
                "summary": {"total": 1, "success": 1},
                "results": [],
                "logs": [f"manual login completed: {platform}"],
                "crawler_engine": "node_auth",
            }
        return {
            "status": "failed",
            "summary": {"total": 1, "success": 0},
            "error": result.get("message") or "manual login failed",
            "results": [],
            "logs": [f"manual login failed: {platform}"],
            "crawler_engine": "node_auth",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "summary": {"total": 1, "success": 0},
            "error": str(exc),
            "results": [],
            "logs": [f"manual login failed: {platform}"],
            "crawler_engine": "node_auth",
        }


def submit_result_with_retry(cloud_client, job_id, payload, attempts=3, delay_s=5):
    last_error = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            log(
                f"submitting crawl result: {job_id} / {payload.get('status')} / "
                f"success={payload.get('summary', {}).get('success', 0)} / attempt={attempt}"
            )
            response = cloud_client.submit_result(job_id, payload)
            persisted = (response or {}).get("persisted") or {}
            log(
                f"submitted crawl result: {job_id} / saved={persisted.get('saved', 0)} / "
                f"errors={persisted.get('errors', 0)} / skipped={persisted.get('skipped', False)}"
            )
            return response
        except Exception as exc:
            last_error = exc
            log(f"submit failed: {job_id} / attempt={attempt} / {exc}")
            if attempt < attempts:
                time.sleep(max(1, delay_s))
    raise RuntimeError(f"submit_result failed after {attempts} attempts: {last_error}") from last_error


def run_once(
    cloud_client,
    worker_id,
    platforms,
    run_crawler=run_node_crawler,
    output_root=None,
    timeout_s=1800,
    crawler_concurrency=DEFAULT_CRAWLER_CONCURRENCY,
):
    for platform in platforms:
        job = cloud_client.claim_next(worker_id, platform)
        if not job:
            continue
        job_type = job.get("job_type") or "crawl"
        log(
            f"claimed job: {job.get('id')} / {platform} / {job_type} / "
            f"client={job.get('client_id', '')} / brand={job.get('brand', '')} / "
            f"group={job.get('group_id', '')} / batch={job.get('batch_id', '')} / "
            f"{len(job.get('questions') or [])} questions"
        )
        if job_type == "login":
            payload = run_login_job(job, timeout_s=timeout_s)
        else:
            update_progress = getattr(cloud_client, "update_progress", None)

            def report_progress(progress):
                if not callable(update_progress):
                    return
                try:
                    update_progress(job["id"], progress)
                except Exception as exc:
                    log(f"failed to report crawl progress: {job.get('id')} / {exc}")

            payload = run_job(
                job,
                run_crawler=run_crawler,
                output_root=output_root,
                timeout_s=timeout_s,
                crawler_concurrency=crawler_concurrency,
                progress_callback=report_progress,
            )
        try:
            canceled = cloud_client.is_job_canceled(job["id"])
        except Exception as exc:
            canceled = False
            log(f"failed to check cancellation state, submitting result anyway: {exc}")
        if canceled:
            log(f"job was canceled; skip submit: {job.get('id')}")
            return True
        submit_result_with_retry(cloud_client, job["id"], payload)
        log(f"job submitted: {job.get('id')} / {payload['status']}")
        return True
    return False


def run_once_parallel(
    cloud_client_factory,
    worker_id,
    platforms,
    run_crawler=run_node_crawler,
    output_root=None,
    timeout_s=1800,
    crawler_concurrency=DEFAULT_CRAWLER_CONCURRENCY,
):
    platforms = list(platforms or [])
    if not platforms:
        return False

    def run_platform(platform):
        platform_worker_id = f"{worker_id}-{platform}"
        return run_once(
            cloud_client_factory(),
            worker_id=platform_worker_id,
            platforms=[platform],
            run_crawler=run_crawler,
            output_root=output_root,
            timeout_s=timeout_s,
            crawler_concurrency=crawler_concurrency,
        )

    with ThreadPoolExecutor(max_workers=len(platforms)) as executor:
        futures = [executor.submit(run_platform, platform) for platform in platforms]
        return any(future.result() for future in as_completed(futures))


def build_cloud_client(args):
    cloud = CloudClient(args.base_url, username=args.username, password=args.password)
    cloud.login()
    return cloud


def run_platform_loop(args, platform):
    cloud = None
    platform_worker_id = f"{args.worker_id}-{platform}"
    log(f"platform worker started: {platform_worker_id}")
    while True:
        try:
            if cloud is None:
                cloud = build_cloud_client(args)
            worked = run_once(
                cloud,
                worker_id=platform_worker_id,
                platforms=[platform],
                output_root=Path("logs") / "local-worker",
                timeout_s=args.timeout,
                crawler_concurrency=args.crawler_concurrency,
            )
        except Exception as exc:
            log(f"{platform} worker cycle failed: {exc}")
            cloud = None
            worked = False
        if not worked:
            log(f"{platform} has no job; polling again in {args.poll_interval}s")
            time.sleep(max(1, args.poll_interval))


def build_parser():
    parser = argparse.ArgumentParser(description="GEO local crawler worker")
    parser.add_argument("--base-url", default=os.environ.get("GEO_WORKER_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--username", default=os.environ.get("GEO_WORKER_USERNAME", ""))
    parser.add_argument("--password", default=os.environ.get("GEO_WORKER_PASSWORD", ""))
    parser.add_argument(
        "--worker-id",
        default=os.environ.get("GEO_WORKER_ID")
        or os.environ.get("COMPUTERNAME")
        or os.environ.get("HOSTNAME")
        or "local-worker",
    )
    parser.add_argument("--platforms", default=os.environ.get("GEO_WORKER_PLATFORMS", "all"))
    parser.add_argument("--poll-interval", type=int, default=int(os.environ.get("GEO_WORKER_POLL_INTERVAL", "10")))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("GEO_WORKER_CRAWL_TIMEOUT", "1800")))
    parser.add_argument(
        "--crawler-concurrency",
        type=int,
        default=positive_int(os.environ.get("GEO_WORKER_CRAWLER_CONCURRENCY"), DEFAULT_CRAWLER_CONCURRENCY),
        help="Node crawler windows per platform job",
    )
    parser.add_argument("--once", action="store_true", help="claim and run one job only")
    parser.add_argument("--check", action="store_true", help="run local worker preflight only")
    parser.add_argument(
        "--auth-mode",
        choices=["soft", "strict", "manual", "none"],
        default=os.environ.get("GEO_WORKER_AUTH_MODE", "soft"),
        help="login preflight mode for --check",
    )
    parser.add_argument("--local-login-only", action="store_true", help="open each platform and wait for local login setup")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    platforms = parse_platforms(args.platforms)
    output_root = Path("logs") / "local-worker"
    log(f"cloud base url: {args.base_url}")
    log(f"local worker: {args.worker_id}; platforms: {', '.join(platforms)}")
    log(f"crawler concurrency per platform job: {args.crawler_concurrency}")
    if args.local_login_only:
        failed_platforms = []
        for platform in platforms:
            storage_state_path = platform_storage_state_path(platform)
            log(f"opening local login setup: {platform} -> {storage_state_path}")
            auth_result = run_node_auth_preflight(
                [platform],
                timeout_s=args.timeout,
                mode="manual",
                storage_state_path=str(storage_state_path),
            )
            if not auth_result.get("ok"):
                log(f"local login setup failed: {platform}: {auth_result.get('message', '')}")
                failed_platforms.append(platform)
        if failed_platforms:
            log(f"local login setup finished with failures: {', '.join(failed_platforms)}")
            return 1
        log("local login setup passed")
        return 0
    if args.check:
        try:
            cloud = build_cloud_client(args)
        except Exception as exc:
            log(f"cloud login failed: {exc}")
            return 1
        result = check_environment(cloud, platforms)
        print_check_result(result)
        if not result["ok"]:
            return 1

        if args.auth_mode == "none":
            log("auth preflight skipped")
            return 0
        auth_result = run_node_auth_preflight(platforms, timeout_s=args.timeout, mode=args.auth_mode)
        if not auth_result.get("ok"):
            log(f"auth preflight failed: {auth_result.get('message', '')}")
            return 1
        log("auth preflight passed")
        return 0
    if args.once:
        worked = run_once_parallel(
            lambda: build_cloud_client(args),
            worker_id=args.worker_id,
            platforms=platforms,
            output_root=output_root,
            timeout_s=args.timeout,
            crawler_concurrency=args.crawler_concurrency,
        )
        return 0 if worked else 2
    if len(platforms) > 1:
        threads = []
        for platform in platforms:
            thread = threading.Thread(
                target=run_platform_loop,
                args=(args, platform),
                name=f"geo-worker-{platform}",
            )
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        return 0

    cloud = build_cloud_client(args)
    while True:
        worked = run_once(
            cloud,
            worker_id=args.worker_id,
            platforms=platforms,
            output_root=output_root,
            timeout_s=args.timeout,
            crawler_concurrency=args.crawler_concurrency,
        )
        if args.once:
            return 0 if worked else 2
        if not worked:
            log(f"no job; polling again in {args.poll_interval}s")
            time.sleep(max(1, args.poll_interval))


if __name__ == "__main__":
    raise SystemExit(main())
