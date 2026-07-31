"""One-off synchronization of the Hefei Yicheng customer knowledge base."""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


SOURCE_NAME = "合肥翼程教育"
TARGET_KEYWORD = "翼程教育"
KNOWLEDGE_FILES = ("customer_master.md", "customer_state.json")


def client_name(client):
    return str(client.get("name") or client.get("brand") or "").strip()


def find_source_and_targets(clients):
    source_matches = [
        client for client in clients
        if SOURCE_NAME in {str(client.get("name") or "").strip(), str(client.get("brand") or "").strip()}
    ]
    if len(source_matches) != 1:
        raise ValueError(f"source_client_not_unique:{len(source_matches)}")
    source = source_matches[0]
    source_id = str(source.get("id") or "").strip()
    if not source_id:
        raise ValueError("source_client_id_missing")
    targets = [
        client for client in clients
        if str(client.get("id") or "").strip() != source_id and TARGET_KEYWORD in client_name(client)
    ]
    if not targets:
        raise ValueError("target_clients_not_found")
    return source, targets


def sync(data_dir, apply=False):
    data_dir = Path(data_dir)
    clients = json.loads((data_dir / "clients.json").read_text(encoding="utf-8"))
    if not isinstance(clients, list):
        raise ValueError("clients_data_invalid")
    source, targets = find_source_and_targets(clients)
    source_dir = data_dir / "knowledge_base" / str(source["id"])
    missing = [name for name in KNOWLEDGE_FILES if not (source_dir / name).is_file()]
    if missing:
        raise ValueError("source_knowledge_files_missing:" + ",".join(missing))

    print(f"源客户：{source['id']} | {client_name(source)}")
    print("目标客户：")
    for target in targets:
        print(f"- {target['id']} | {client_name(target)}")
    if not apply:
        print("预览完成；确认后请带 --apply --yes 执行。")
        return None

    backup_dir = data_dir / "knowledge_base" / f"_manual_backup_yicheng_{datetime.now():%Y%m%d-%H%M%S}"
    for target in targets:
        target_id = str(target["id"])
        target_dir = data_dir / "knowledge_base" / target_id
        backup_target = backup_dir / target_id
        target_dir.mkdir(parents=True, exist_ok=True)
        backup_target.mkdir(parents=True, exist_ok=True)
        for filename in KNOWLEDGE_FILES:
            target_file = target_dir / filename
            if target_file.exists():
                shutil.copy2(target_file, backup_target / filename)
            shutil.copy2(source_dir / filename, target_file)
        print(f"已同步：{target_id} | {client_name(target)}")
    print(f"同步完成。目标原资料备份在：{backup_dir}")
    return backup_dir


def main():
    parser = argparse.ArgumentParser(description="一次性同步合肥翼程教育客户资料知识库")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--apply", action="store_true", help="实际执行复制；默认只预览")
    parser.add_argument("--yes", action="store_true", help="与 --apply 一起使用，确认覆盖目标客户资料")
    args = parser.parse_args()
    if args.apply and not args.yes:
        parser.error("实际执行需同时传入 --apply --yes")
    try:
        sync(args.data_dir, apply=args.apply)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"同步失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
