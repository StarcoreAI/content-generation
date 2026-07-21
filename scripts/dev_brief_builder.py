# -*- coding: utf-8 -*-
import argparse
import random
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.brief_builder import build_brief_sample, generate_planning_brief
from services.materials import MaterialService
from services.pattern_library import PatternLibrary
from services.storage import load_json, save_json


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _read_text(path):
    path = Path(path)
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def _client(data_dir, client_id):
    clients = load_json(Path(data_dir) / "clients.json", [])
    return next((item for item in clients if isinstance(item, dict) and item.get("id") == client_id), None)


def _competitor_text(data_dir, client_id):
    root = Path(data_dir) / "competitor_material_packages" / client_id
    return "\n\n---\n\n".join(filter(None, [
        _read_text(root / "latest_upload_competitors.md"),
        _read_text(root / "latest_web_competitors.md"),
    ]))


def run_brief_builder(client_id, parent_type, count=1, date=None, data_dir=None, industry="",
                      include_injection=True, include_web_supplement=True, include_content_uploads=True,
                      include_competitors=True, ai_json_fn=None, rng=None):
    data_dir = Path(data_dir or ROOT / "data")
    date = date or _today()
    client = _client(data_dir, client_id)
    if not client:
        raise ValueError("client_not_found")
    industry = str(industry or client.get("industry") or "").strip()
    if not industry:
        raise ValueError("missing_industry")
    if ai_json_fn is None:
        import app as geo_app
        ai_json_fn = geo_app.ai_json
    rng = rng or random.Random()
    package_dir = data_dir / "material_packages" / client_id
    customer_material = "\n\n---\n\n".join(filter(None, [
        _read_text(package_dir / "latest_injection.md") if include_injection else "",
        _read_text(package_dir / "latest_web_supplement.md") if include_web_supplement else "",
    ]))
    content_upload_text = ""
    if include_content_uploads:
        material_service = MaterialService(
            root_dir=data_dir,
            upload_dir=data_dir / "uploads",
            index_path=data_dir / "materials_index.json",
            cache_dir=data_dir / "material_cache",
        )
        content_upload_text = material_service.build_generation_bundle(client_id).get("text") or ""
    competitor_markdown = _competitor_text(data_dir, client_id) if include_competitors else ""
    library = PatternLibrary(data_dir / "pattern_library")
    recent_combos = []
    items = []
    for _ in range(max(1, int(count or 1))):
        sample = build_brief_sample(
            library=library,
            scopes=[f"client:{client_id}", f"industry:{industry}", "global"],
            parent_type=parent_type,
            audience_angles=[],
            faq_questions=[],
            recent_combos=recent_combos,
            rng=rng,
        )
        brief = generate_planning_brief(
            sample,
            customer_material_text=customer_material,
            content_upload_text=content_upload_text,
            competitor_markdown=competitor_markdown,
            ai_json_fn=ai_json_fn,
        )
        items.append({"sampling": sample, "brief": brief})
        recent_combos.append(sample["sampling_meta"]["fingerprint"])
    output_path = data_dir / "briefs" / client_id / date / "planning_briefs.json"
    payload = {
        "client_id": client_id,
        "date": date,
        "parent_type": parent_type,
        "industry": industry,
        "items": items,
    }
    if not save_json(output_path, payload):
        raise RuntimeError("brief_output_save_failed")
    return {"count": len(items), "output_path": str(output_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate planning briefs for manual review.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--parent-type", required=True, choices=["对比型", "介绍型"])
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--industry", default="")
    parser.add_argument("--no-injection", action="store_true")
    parser.add_argument("--no-web-supplement", action="store_true")
    parser.add_argument("--no-content-uploads", action="store_true")
    parser.add_argument("--no-competitors", action="store_true")
    args = parser.parse_args(argv)
    result = run_brief_builder(
        client_id=args.client_id,
        parent_type=args.parent_type,
        count=args.count,
        date=args.date,
        data_dir=args.data_dir,
        industry=args.industry,
        include_injection=not args.no_injection,
        include_web_supplement=not args.no_web_supplement,
        include_content_uploads=not args.no_content_uploads,
        include_competitors=not args.no_competitors,
    )
    print(f"[GEO] planning briefs={result['count']}")
    print(f"[GEO] output: {result['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
