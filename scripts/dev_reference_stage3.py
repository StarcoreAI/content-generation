import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as geo_app
from services.reference_stage3 import analyze_stage3_plugins
from services.storage import load_json, save_json


def default_data_dir():
    return ROOT / "data"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _safe_path_part(value, default):
    return re.sub(r"[^0-9A-Za-z_.-]", "_", value or default)


def _live_reference_path(data_dir, client_id, date, task_id=""):
    safe_client = _safe_path_part(client_id, "unknown")
    safe_date = _safe_path_part(date, _today())
    safe_task = _safe_path_part(task_id, "all")
    return data_dir / "reference_intelligence" / safe_client / f"{safe_date}_{safe_task}.json"


def save_live_reference_plugins(data_dir, client_id, date, plugins, task_id=""):
    body = {
        "ok": True,
        "client_id": client_id,
        "date": date,
        "task_id": task_id,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "clusters": [],
        "plugins": geo_app.normalize_reference_plugins(plugins),
        "source_articles": [],
    }
    output_path = _live_reference_path(data_dir, client_id, date, task_id)
    save_json(output_path, body)
    return output_path


def _display_article_title(article):
    title = str(article.get("title") or "").strip()
    if title.lower() in {"403 forbidden", "404 not found", "just a moment..."}:
        title = ""
    return title or str(article.get("source_title") or "").strip()


def _article_sources(data_dir, client_id, date):
    stage1_path = data_dir / "reference_intelligence" / client_id / date / "stage1_article_structures.json"
    stage1 = load_json(stage1_path, {})
    if stage1.get("analyses"):
        sources = {}
        for index, article in enumerate(stage1.get("analyses") or [], 1):
            if not isinstance(article, dict):
                continue
            title = _display_article_title(article)
            url = str(article.get("url") or "").strip()
            if title or url:
                sources[index] = {"title": title, "url": url}
        return sources

    path = data_dir / "reference_intelligence" / client_id / date / "fetched_articles.json"
    fetched = load_json(path, {})
    sources = {}
    for index, article in enumerate(fetched.get("articles") or [], 1):
        if not isinstance(article, dict):
            continue
        title = _display_article_title(article)
        url = str(article.get("url") or "").strip()
        if title or url:
            sources[index] = {"title": title, "url": url}
    return sources


def _attach_source_articles(plugins, article_sources):
    enriched = []
    for plugin in plugins or []:
        item = dict(plugin)
        item["source_articles"] = [
            article_sources[index]
            for index in item.get("source_article_indexes") or []
            if index in article_sources
        ]
        enriched.append(item)
    return enriched


def run_stage3_prompt_plugins(
    client_id,
    date=None,
    data_dir=None,
    ai_json_fn=geo_app.ai_json,
    publish=False,
):
    date = date or _today()
    data_dir = Path(data_dir or default_data_dir())
    input_path = data_dir / "reference_intelligence" / client_id / date / "stage2_structure_clusters.json"
    stage2 = load_json(input_path, {})
    clusters = stage2.get("clusters") or []
    result = analyze_stage3_plugins(clusters, ai_json_fn)
    plugins = _attach_source_articles(result["plugins"], _article_sources(data_dir, client_id, date))
    output = {
        "client_id": client_id,
        "date": date,
        "source_path": str(input_path),
        "total_clusters": len(clusters),
        "total_plugins": len(plugins),
        "plugins": plugins,
    }
    output_path = data_dir / "reference_intelligence" / client_id / date / "stage3_prompt_plugins.json"
    save_json(output_path, output)
    result = {
        "clusters": len(clusters),
        "plugins": len(plugins),
        "output_path": str(output_path),
    }
    if publish:
        live_output_path = save_live_reference_plugins(data_dir, client_id, date, plugins)
        result["live_output_path"] = str(live_output_path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run reference intelligence stage 3 prompt plugin generation.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--date", default=_today())
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("--publish", action="store_true", help="Also write the formal reference intelligence JSON.")
    args = parser.parse_args(argv)

    result = run_stage3_prompt_plugins(
        client_id=args.client_id,
        date=args.date,
        data_dir=args.data_dir,
        publish=args.publish,
    )
    print(f"[GEO] stage3 plugins={result['plugins']} clusters={result['clusters']}")
    print(f"[GEO] output: {result['output_path']}")
    if result.get("live_output_path"):
        print(f"[GEO] live output: {result['live_output_path']}")
    return 0 if result["plugins"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
