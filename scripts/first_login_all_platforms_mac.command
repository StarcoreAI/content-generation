#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[GEO] first login for all crawler platforms..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 was not found. Run setup_operator_mac.command first."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] node was not found. Run setup_operator_mac.command first."
  exit 1
fi

export GEO_WORKER_PLATFORMS="all"

echo "[GEO] detecting local crawler folder..."
GEO_NODE_CRAWLER_ROOT="$(python3 scripts/resolve_node_crawler_root.py)"
export GEO_NODE_CRAWLER_ROOT
echo "[GEO] crawler root: $GEO_NODE_CRAWLER_ROOT"

mkdir -p "$GEO_NODE_CRAWLER_ROOT/storage"
export STORAGE_STATE_PATH="$GEO_NODE_CRAWLER_ROOT/storage/state.json"

echo "[GEO] opening each platform for login..."
echo "[GEO] Finish login in the browser. The next platform opens automatically."
python3 scripts/local_crawl_worker.py --platforms "$GEO_WORKER_PLATFORMS" --local-login-only

echo "[GEO] first login finished."
