#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

source scripts/operator_log.sh
start_operator_log stop-worker-mac

echo "[GEO] stopping local crawl worker..."

pkill -f "scripts/local_crawl_worker.py" 2>/dev/null || true
pkill -f "node_auth_preflight.mjs" 2>/dev/null || true
pkill -f "ai-search-crawler.*src/index.js" 2>/dev/null || true

echo "[GEO] local crawl worker stopped."
