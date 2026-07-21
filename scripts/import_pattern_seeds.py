# -*- coding: utf-8 -*-
import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pattern_library import PatternLibrary


def import_pattern_seeds(library_root=None, seed_path=None):
    seed_path = Path(seed_path or ROOT / "docs" / "pattern-library-seeds-v1.json")
    library = PatternLibrary(library_root or ROOT / "data" / "pattern_library")
    seeds = json.loads(seed_path.read_text(encoding="utf-8")).get("seeds") or []
    existing_urls = {
        source.get("url")
        for entry in library.list_entries("global")
        for source in entry.get("sources") or []
    }
    stats = {"imported": 0, "skipped": 0}
    for seed in seeds:
        seed_id = str(seed.get("seed_id") or "").strip()
        source_url = f"seed://{seed_id}"
        if not seed_id or source_url in existing_urls:
            stats["skipped"] += 1
            continue
        library.create_candidate(
            "global",
            seed["kind"],
            seed["name"],
            seed.get("payload") or {},
            {"url": source_url, "title": f"{seed['name']} | {seed.get('origin', '')}"},
        )
        existing_urls.add(source_url)
        stats["imported"] += 1
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import shared pattern-library seeds.")
    parser.add_argument("--library-root", default=str(ROOT / "data" / "pattern_library"))
    parser.add_argument("--seed-file", default=str(ROOT / "docs" / "pattern-library-seeds-v1.json"))
    args = parser.parse_args(argv)
    stats = import_pattern_seeds(args.library_root, args.seed_file)
    print(f"[GEO] pattern seeds imported={stats['imported']} skipped={stats['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
