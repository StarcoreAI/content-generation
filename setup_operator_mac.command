#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

source scripts/operator_log.sh
start_operator_log setup-mac

echo "[GEO] Mac operator setup..."

ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
  echo "[ERROR] This package is for Apple Silicon Mac (arm64). Current machine: $ARCH"
  echo "[ERROR] Ask support for the Intel Mac package if this is an Intel Mac."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 was not found. Install Python 3, then run this file again."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] node was not found. Install Node.js LTS, then run this file again."
  exit 1
fi

echo "[GEO] detecting local crawler folder..."
GEO_NODE_CRAWLER_ROOT="$(python3 scripts/resolve_node_crawler_root.py)"
export GEO_NODE_CRAWLER_ROOT
echo "[GEO] crawler root: $GEO_NODE_CRAWLER_ROOT"

if [[ ! -f "$GEO_NODE_CRAWLER_ROOT/package.json" ]]; then
  echo "[ERROR] Missing Node crawler package.json: $GEO_NODE_CRAWLER_ROOT/package.json"
  exit 1
fi

if [[ ! -f "$GEO_NODE_CRAWLER_ROOT/node_modules/playwright/package.json" ]]; then
  echo "[ERROR] Operator package is incomplete: missing node_modules/playwright/package.json"
  echo "[ERROR] Download the latest Mac operator package instead of running npm install manually."
  exit 1
fi

if [[ ! -f "$GEO_NODE_CRAWLER_ROOT/node_modules/playwright-core/package.json" ]]; then
  echo "[ERROR] Operator package is incomplete: missing node_modules/playwright-core/package.json"
  echo "[ERROR] Download the latest Mac operator package instead of running npm install manually."
  exit 1
fi

if ! find "$GEO_NODE_CRAWLER_ROOT/ms-playwright" -path "*/chrome-mac/Chromium.app/Contents/MacOS/Chromium" -type f -print -quit | grep -q .; then
  echo "[ERROR] Operator package is incomplete: missing packaged Playwright Chromium."
  echo "[ERROR] Expected a path like: $GEO_NODE_CRAWLER_ROOT/ms-playwright/chromium-*/chrome-mac/Chromium.app"
  exit 1
fi

mkdir -p "$GEO_NODE_CRAWLER_ROOT/storage"
export STORAGE_STATE_PATH="$GEO_NODE_CRAWLER_ROOT/storage/state.json"

chmod +x setup_operator_mac.command start_local_crawl_worker.command stop_local_crawl_worker.command scripts/first_login_all_platforms_mac.command

echo "[GEO] setup complete. Starting first platform login..."
"$(pwd)/scripts/first_login_all_platforms_mac.command"

echo "[GEO] setup and first login finished."
echo "[GEO] Next: run start_local_crawl_worker.command"
