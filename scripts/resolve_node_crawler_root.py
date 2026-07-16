#!/usr/bin/env python3
import os
import sys
from pathlib import Path


def is_crawler_root(path):
    return bool(path) and (Path(path) / "src" / "adapters" / "index.js").exists()


def add_candidate(candidates, seen, path):
    if not path:
        return
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return
    key = str(resolved).casefold()
    if key not in seen:
        seen.add(key)
        candidates.append(resolved)


def main():
    project_root = Path(__file__).resolve().parents[1]
    candidates = []
    seen = set()

    search_bases = [
        project_root,
        project_root.parent,
        project_root.parent.parent,
        Path.home() / "OneDrive" / "programing",
        Path.home() / "OneDrive" / "programming",
        Path.home() / "Documents",
        Path.home() / "Desktop",
    ]

    for base in search_bases:
        if not base.exists():
            continue
        for child in base.glob("ai-search-crawler*"):
            if child.is_dir():
                add_candidate(candidates, seen, child)

    add_candidate(candidates, seen, os.environ.get("GEO_NODE_CRAWLER_ROOT"))

    for candidate in candidates:
        if is_crawler_root(candidate):
            print(candidate)
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
