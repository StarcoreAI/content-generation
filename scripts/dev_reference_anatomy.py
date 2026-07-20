import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as geo_app
from services.reference_anatomy import analyze_article_anatomy
from services.storage import load_json, save_json, update_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _ledger_default():
    return {"schema_version": 1, "successful_urls": []}


def _successful_urls(ledger_path):
    ledger = load_json(ledger_path, _ledger_default())
    return {
        str(url).strip()
        for url in ledger.get("successful_urls") or []
        if str(url).strip()
    }


def _record_success(ledger_path, url):
    url = str(url or "").strip()

    def add_url(ledger):
        ledger = dict(ledger or {})
        urls = [str(value).strip() for value in ledger.get("successful_urls") or [] if str(value).strip()]
        if url not in urls:
            urls.append(url)
        return {"schema_version": 1, "successful_urls": urls}, url

    update_json(ledger_path, _ledger_default(), add_url)


def run_reference_anatomy(client_id, date=None, data_dir=None, ai_json_fn=geo_app.ai_json, limit=0, ledger_path=None):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    stage_dir = data_dir / "reference_intelligence" / client_id / date
    ledger_path = Path(ledger_path or (stage_dir.parent / "stage1_anatomy_ledger.json"))
    successful_urls = _successful_urls(ledger_path)
    fetched = load_json(stage_dir / "fetched_articles.json", {})
    articles_by_url = {
        str(article.get("url") or "").strip(): article
        for article in fetched.get("articles") or []
        if isinstance(article, dict) and str(article.get("url") or "").strip()
    }
    stage0 = load_json(stage_dir / "stage0_filter_groups.json", {})
    groups = stage0.get("groups") or []
    if limit and limit > 0:
        groups = [group for group in groups if isinstance(group, dict) and group.get("learnable") is True][:limit]

    cards = []
    errors = []
    skipped = 0
    for group in groups:
        if not isinstance(group, dict) or group.get("learnable") is not True:
            skipped += 1
            continue
        representative = group.get("representative") or {}
        url = str(representative.get("url") or "").strip()
        if url in successful_urls:
            skipped += 1
            continue
        article = articles_by_url.get(url)
        if not article:
            errors.append({"group_id": group.get("group_id") or "", "error": "representative_article_missing"})
            continue
        try:
            card = analyze_article_anatomy({
                **article,
                "group_id": group.get("group_id") or "",
                "risk_marks": group.get("risk_marks") or [],
            }, ai_json_fn)
            cards.append(card)
            _record_success(ledger_path, url)
            successful_urls.add(url)
        except Exception as exc:
            errors.append({"group_id": group.get("group_id") or "", "error": str(exc)})

    output = {
        "client_id": client_id,
        "date": date,
        "total_input_groups": len(groups),
        "total_analyzed": len(cards),
        "total_skipped": skipped,
        "total_errors": len(errors),
        "cards": cards,
        "errors": errors,
    }
    output_path = stage_dir / "stage1_anatomy_cards.json"
    save_json(output_path, output)
    return {
        "input_groups": len(groups),
        "analyzed": len(cards),
        "skipped": skipped,
        "errors": len(errors),
        "output_path": str(output_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run reference anatomy stage 1 on stage-0 learnable groups.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    result = run_reference_anatomy(
        client_id=args.client_id,
        date=args.date,
        data_dir=args.data_dir,
        limit=args.limit,
    )
    print(
        f"[GEO] stage1 input_groups={result['input_groups']} analyzed={result['analyzed']} "
        f"skipped={result['skipped']} errors={result['errors']}"
    )
    print(f"[GEO] output: {result['output_path']}")
    return 0 if result["analyzed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
