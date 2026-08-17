#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

clear_macos_quarantine() {
  if ! command -v xattr >/dev/null 2>&1; then
    return
  fi
  for target in "$@"; do
    [[ -e "$target" ]] || continue
    xattr -dr com.apple.quarantine "$target" 2>/dev/null || true
  done
}

clear_macos_quarantine "$(pwd)"

PACKAGED_NODE_BIN="$(pwd)/runtime/node/bin"
if [[ -x "$PACKAGED_NODE_BIN/node" ]]; then
  export PATH="$PACKAGED_NODE_BIN:$PATH"
fi

echo "[GEO] first login for all crawler platforms..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 was not found. Run setup_operator_mac.command first."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] node was not found in this operator package."
  echo "[ERROR] Download the latest Mac operator package instead of installing Node.js manually."
  exit 1
fi

export GEO_WORKER_PLATFORMS="all"

echo "[GEO] detecting local crawler folder..."
GEO_NODE_CRAWLER_ROOT="$(python3 scripts/resolve_node_crawler_root.py)"
export GEO_NODE_CRAWLER_ROOT
echo "[GEO] crawler root: $GEO_NODE_CRAWLER_ROOT"
clear_macos_quarantine "$GEO_NODE_CRAWLER_ROOT"
find "$GEO_NODE_CRAWLER_ROOT/ms-playwright" -path "*/chrome-mac*/*.app/Contents/MacOS/*" -type f -exec chmod +x {} \; 2>/dev/null || true

mkdir -p "$GEO_NODE_CRAWLER_ROOT/storage"
export STORAGE_STATE_PATH="$GEO_NODE_CRAWLER_ROOT/storage/state.json"

echo "[GEO] opening each platform for login..."
echo "[GEO] Finish login in the browser and DO NOT close it manually."
echo "[GEO] The browser closes only after the login state is saved, then the next platform opens."
python3 scripts/local_crawl_worker.py --platforms "$GEO_WORKER_PLATFORMS" --local-login-only

echo "[GEO] first login finished."
