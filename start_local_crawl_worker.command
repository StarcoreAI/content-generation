#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

source scripts/operator_log.sh
start_operator_log worker-mac

echo "[GEO] starting local crawl worker..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 was not found."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] node was not found."
  exit 1
fi

read -r -p "Cloud username: " GEO_WORKER_USERNAME
if [[ -z "$GEO_WORKER_USERNAME" ]]; then
  echo "[ERROR] Cloud username is required."
  exit 1
fi

read -r -s -p "Cloud password: " GEO_WORKER_PASSWORD
echo
if [[ -z "$GEO_WORKER_PASSWORD" ]]; then
  echo "[ERROR] Cloud password is required."
  exit 1
fi

export GEO_WORKER_USERNAME
export GEO_WORKER_PASSWORD
export GEO_WORKER_BASE_URL="${GEO_WORKER_BASE_URL:-http://8.160.116.86:18080}"
export GEO_WORKER_PLATFORMS="all"

echo "[GEO] detecting local crawler folder..."
GEO_NODE_CRAWLER_ROOT="$(python3 scripts/resolve_node_crawler_root.py)"
export GEO_NODE_CRAWLER_ROOT
echo "[GEO] crawler root: $GEO_NODE_CRAWLER_ROOT"

mkdir -p "$GEO_NODE_CRAWLER_ROOT/storage"
export STORAGE_STATE_PATH="$GEO_NODE_CRAWLER_ROOT/storage/state.json"

echo "[GEO] environment preflight check..."
python3 scripts/local_crawl_worker.py \
  --base-url "$GEO_WORKER_BASE_URL" \
  --username "$GEO_WORKER_USERNAME" \
  --password "$GEO_WORKER_PASSWORD" \
  --platforms "$GEO_WORKER_PLATFORMS" \
  --check \
  --auth-mode none

echo "[GEO] waiting for cloud crawl jobs..."
python3 scripts/local_crawl_worker.py \
  --base-url "$GEO_WORKER_BASE_URL" \
  --username "$GEO_WORKER_USERNAME" \
  --password "$GEO_WORKER_PASSWORD" \
  --platforms "$GEO_WORKER_PLATFORMS"
