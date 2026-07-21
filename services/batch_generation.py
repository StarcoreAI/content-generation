"""In-memory, strictly serial content-generation batch jobs."""

from copy import deepcopy
import threading


class BatchGenerationJobs:
    def __init__(self, uid_fn, now_fn, run_generation_fn, prepare_fn=None):
        self._uid_fn = uid_fn
        self._now_fn = now_fn
        self._run_generation_fn = run_generation_fn
        self._prepare_fn = prepare_fn
        self._jobs = {}
        self._lock = threading.RLock()

    def create(self, payload, count, created_by=""):
        job_id = self._uid_fn()
        batch_id = self._uid_fn()
        job = {
            "job_id": job_id,
            "batch_id": batch_id,
            "client_id": str((payload or {}).get("client_id") or ""),
            "count": int(count),
            "status": "queued",
            "cancel_requested": False,
            "created_by": created_by,
            "created_at": self._now_fn(),
            "updated_at": self._now_fn(),
            "items": [
                {"index": index, "status": "排队", "article_id": "", "title": "", "error": ""}
                for index in range(1, int(count) + 1)
            ],
            "payload": dict(payload or {}),
        }
        with self._lock:
            self._jobs[job_id] = job
        return self.get(job_id)

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            return deepcopy(job) if job else None

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            if not job:
                return None
            if job["status"] not in {"completed", "cancelled"}:
                job["cancel_requested"] = True
                job["updated_at"] = self._now_fn()
            return deepcopy(job)

    def run(self, job_id):
        used_pairs, used_competitors = [], []
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            if not job:
                return None
            if job["status"] in {"completed", "cancelled"}:
                return deepcopy(job)
            job["status"] = "running"
            job["updated_at"] = self._now_fn()

        if self._prepare_fn:
            try:
                self._prepare_fn(dict(job["payload"]))
            except Exception:
                pass

        for item_index in range(len(job["items"])):
            with self._lock:
                if job["cancel_requested"]:
                    job["status"] = "cancelled"
                    job["updated_at"] = self._now_fn()
                    return deepcopy(job)
                item = job["items"][item_index]
                item["status"] = "生成中"
                job["updated_at"] = self._now_fn()
                payload = dict(job["payload"])
                batch_id = job["batch_id"]
                created_by = job["created_by"]

            try:
                article = self._run_generation_fn(
                    payload,
                    batch_id=batch_id,
                    avoid_skeleton_opening_pairs=list(used_pairs),
                    avoid_competitor_names=list(used_competitors),
                    skip_lazy_choices=True,
                    created_by=created_by,
                )
            except Exception as exc:
                with self._lock:
                    item["status"] = "失败"
                    item["error"] = str(exc)
                    job["updated_at"] = self._now_fn()
                continue

            pair = _sample_pair(article)
            if pair:
                used_pairs.append(pair)
            used_competitors.extend(
                name for name in ((article.get("provenance") or {}).get("competitor_names") or [])
                if name not in used_competitors
            )
            with self._lock:
                item["article_id"] = str(article.get("id") or "")
                item["title"] = str(article.get("title") or "")
                item["status"] = "门禁拦截" if article.get("generation_status") == "门禁拦截" else "完成"
                job["updated_at"] = self._now_fn()

        with self._lock:
            job["status"] = "cancelled" if job["cancel_requested"] else "completed"
            job["updated_at"] = self._now_fn()
            return deepcopy(job)


def _sample_pair(article):
    entries = ((article or {}).get("provenance") or {}).get("entries") or {}
    skeleton_id = str((entries.get("skeleton") or {}).get("id") or "")
    opening_id = str((entries.get("opening_module") or {}).get("id") or "")
    return (skeleton_id, opening_id) if skeleton_id else None
