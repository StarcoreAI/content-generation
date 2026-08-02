"""Ordered, bounded concurrency for independent article work."""
from concurrent.futures import ThreadPoolExecutor


def _run(items, fn, max_workers):
    items = list(items or [])
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as executor:
        return list(executor.map(fn, items))


def fetch_articles(items, fetch_fn, max_workers=3):
    return _run(items, fetch_fn, max_workers)


def analyze_articles(items, analyze_fn, semaphore, max_workers=2):
    def run(item):
        with semaphore:
            return analyze_fn(item)

    return _run(items, run, max_workers)
