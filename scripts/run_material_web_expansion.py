import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_entities import read_json
from services.material_web_expansion import (
    build_query_prompt,
    build_supplement_prompt,
    filter_sources,
    parse_query_lines,
    tavily_search,
)


def choose_model(settings):
    return settings.get("material_web_model") or settings.get("model") or "deepseek-chat"


def complete_text(client, model, prompt):
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def stream_text(client, model, prompt, on_chunk):
    chunks = []
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = getattr(chunk.choices[0], "delta", None)
        piece = getattr(delta, "content", None) or ""
        if not piece:
            continue
        chunks.append(piece)
        on_chunk(piece)
    return "".join(chunks)


def load_client(clients_path, client_id):
    clients = read_json(clients_path, [])
    return next((item for item in clients if item.get("id") == client_id), {"id": client_id})


def load_sources(path):
    sources = read_json(path, [])
    if not isinstance(sources, list):
        raise ValueError("sources JSON must be a list")
    return sources


def default_injection_path(client_id):
    return Path("data") / "material_packages" / client_id / "latest_injection.md"


def default_output_dir(client_id):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(".tmp") / f"material_web_expansion_{client_id}_{timestamp}"


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_sources(queries, tavily_key, fetched_at, per_query_limit=2, source_limit=12):
    sources = []
    seen_urls = set()
    per_query = []
    for query in queries:
        raw_results = tavily_search(query, tavily_key)
        selected = []
        for source in filter_sources(raw_results, fetched_at=fetched_at, limit=per_query_limit):
            url = source.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(source)
            selected.append(source)
            if len(sources) >= source_limit:
                break
        per_query.append({
            "query": query,
            "raw_count": len(raw_results),
            "selected_count": len(selected),
            "sources": selected,
        })
        if len(sources) >= source_limit:
            break
    return sources, per_query


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run customer material web expansion without max_tokens.")
    parser.add_argument("client_id", help="Client id, for example 20260713110415475423")
    parser.add_argument("--settings", default="data/settings.json", help="Settings JSON path")
    parser.add_argument("--clients", default="data/clients.json", help="Clients JSON path")
    parser.add_argument("--injection", default="", help="latest_injection.md path; defaults to data/material_packages/<cid>/latest_injection.md")
    parser.add_argument("--output-dir", default="", help="Output directory; defaults to .tmp/material_web_expansion_<cid>_<timestamp>")
    parser.add_argument("--sources", default="", help="Existing sources.json path; skips query generation and search, then runs final summary only.")
    parser.add_argument("--stream", action="store_true", help="Use streaming final summary call. No max_tokens is sent either way.")
    parser.add_argument("--no-stream", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--search-only", action="store_true", help="Only generate queries and collect sources; skip final summary.")
    args = parser.parse_args()

    settings = read_json(args.settings, {})
    api_key = str(settings.get("api_key") or "").strip()
    tavily_key = str(settings.get("tavily_api_key") or "").strip()
    if not api_key:
        raise SystemExit("missing api_key in settings")
    if not tavily_key:
        raise SystemExit("missing tavily_api_key in settings")

    model = choose_model(settings)
    client = OpenAI(api_key=api_key, base_url=str(settings.get("base_url") or "").rstrip("/"))
    customer = load_client(args.clients, args.client_id)
    injection_path = Path(args.injection) if args.injection else default_injection_path(args.client_id)
    injection = injection_path.read_text(encoding="utf-8", errors="ignore")
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(args.client_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"Model: {model}")
    if args.sources:
        sources = load_sources(args.sources)
        write_json(output_dir / "sources.json", sources)
        print(f"Queries: skipped (--sources)")
    else:
        query_prompt = build_query_prompt(customer, injection)
        (output_dir / "query_prompt.txt").write_text(query_prompt, encoding="utf-8")
        query_text = complete_text(client, model, query_prompt)
        queries = parse_query_lines(query_text, limit=6)
        (output_dir / "query_text.txt").write_text(query_text, encoding="utf-8")
        (output_dir / "queries.txt").write_text("\n".join(queries) + "\n", encoding="utf-8")

        print(f"Queries: {len(queries)}")
        for query in queries:
            print(f"- {query}")

        sources, per_query = collect_sources(queries, tavily_key, fetched_at=fetched_at)
        write_json(output_dir / "sources_per_query.json", per_query)
        write_json(output_dir / "sources.json", sources)
    print(f"Sources: {len(sources)}")
    for source in sources:
        print(f"- {source.get('title')} | {source.get('url')}")

    if args.search_only:
        print(f"Search-only output: {output_dir}")
        return

    if not sources:
        markdown = "## 联网扩展资料\n\n暂无可用联网扩展资料。"
        (output_dir / "latest_web_supplement.md").write_text(markdown, encoding="utf-8")
        print(f"Wrote {output_dir / 'latest_web_supplement.md'}")
        return

    supplement_prompt = build_supplement_prompt(customer, injection, sources)
    (output_dir / "supplement_prompt.txt").write_text(supplement_prompt, encoding="utf-8")
    output_path = output_dir / "latest_web_supplement.md"
    if args.stream:
        with output_path.open("w", encoding="utf-8") as handle:
            markdown = stream_text(client, model, supplement_prompt, lambda piece: (handle.write(piece), handle.flush()))
    else:
        markdown = complete_text(client, model, supplement_prompt)
        output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"Markdown chars: {len(markdown)}")


if __name__ == "__main__":
    main()
