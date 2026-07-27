"""Run a no-write competitor-knowledge experiment from a trusted server shell."""
import argparse
import sys
from pathlib import Path


def run_experiment(client_id, geo_app):
    if not any(client.get("id") == client_id for client in geo_app.load(geo_app.F_CLIENTS, [])):
        raise ValueError(f"client_not_found: {client_id}")
    records = geo_app.load_client_records(client_id)
    source_date = max((str(record.get("today") or "").strip() for record in records), default="")
    return {
        "client_id": client_id,
        "source_date": source_date,
        "content": geo_app.competitor_knowledge_input(client_id, persist_cache=False),
    }


def main():
    parser = argparse.ArgumentParser(description="试运行竞品知识库整理，不写入知识库或文章缓存")
    parser.add_argument("--client-id", required=True, help="客户 ID")
    parser.add_argument("--output", required=True, help="试跑 Markdown 产物路径")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import app as geo_app

    result = run_experiment(args.client_id.strip(), geo_app)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result["content"], encoding="utf-8")
    print(f"试跑完成：客户={result['client_id']}，数据日={result['source_date'] or '无'}，产物={output}")


if __name__ == "__main__":
    main()
