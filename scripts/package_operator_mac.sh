#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

arch="$(uname -m)"
if [[ "$arch" != "arm64" ]]; then
  echo "[ERROR] This packager currently builds Apple Silicon packages only. Current machine: $arch"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 was not found."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] node was not found."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm was not found."
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "[ERROR] rsync was not found."
  exit 1
fi

if ! command -v zip >/dev/null 2>&1; then
  echo "[ERROR] zip was not found."
  exit 1
fi

crawler_root="$(python3 scripts/resolve_node_crawler_root.py)"
echo "[GEO] crawler root: $crawler_root"

echo "[GEO] preparing Mac Node dependencies..."
(
  cd "$crawler_root"
  npm install
  PLAYWRIGHT_BROWSERS_PATH="$crawler_root/ms-playwright" npx playwright install chromium
)

if [[ ! -f "$crawler_root/node_modules/playwright/package.json" ]]; then
  echo "[ERROR] missing packaged node_modules/playwright after npm install."
  exit 1
fi

if [[ ! -f "$crawler_root/node_modules/playwright-core/package.json" ]]; then
  echo "[ERROR] missing packaged node_modules/playwright-core after npm install."
  exit 1
fi

if ! find "$crawler_root/ms-playwright" -path "*/chrome-mac/Chromium.app/Contents/MacOS/Chromium" -type f -print -quit | grep -q .; then
  echo "[ERROR] missing packaged Playwright Chromium under $crawler_root/ms-playwright"
  exit 1
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
package_name="GEO-operator-worker-macos-arm64-$timestamp"
artifact_root="$project_root/deploy_artifacts"
stage="$artifact_root/$package_name"
zip_path="$artifact_root/$package_name.zip"

mkdir -p "$artifact_root"
rm -rf "$stage" "$zip_path"
mkdir -p "$stage/geo_v2-pro" "$stage/ai-search-crawler"

echo "[GEO] copying geo_v2-pro..."
rsync -a \
  --exclude .git \
  --exclude data \
  --exclude .venv \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude deploy_artifacts \
  --exclude logs \
  --exclude operator_logs \
  --exclude reports \
  "$project_root/" "$stage/geo_v2-pro/"

echo "[GEO] copying ai-search-crawler..."
rsync -a \
  --exclude .git \
  --exclude .agents \
  --exclude .DS_Store \
  --exclude .env \
  --exclude storage \
  --exclude logs \
  --exclude output \
  --exclude interviews \
  --exclude brands \
  --exclude test \
  --exclude __pycache__ \
  --exclude 'tmp-*' \
  --exclude '*.txt' \
  "$crawler_root/" "$stage/ai-search-crawler/"

chmod +x \
  "$stage/geo_v2-pro/setup_operator_mac.command" \
  "$stage/geo_v2-pro/start_local_crawl_worker.command" \
  "$stage/geo_v2-pro/stop_local_crawl_worker.command" \
  "$stage/geo_v2-pro/scripts/first_login_all_platforms_mac.command" \
  "$stage/geo_v2-pro/scripts/operator_log.sh" \
  "$stage/geo_v2-pro/scripts/package_operator_mac.sh" \
  "$stage/geo_v2-pro/scripts/resolve_node_crawler_root.py"

echo "[GEO] creating package..."
(
  cd "$artifact_root"
  zip -qry "$zip_path" "$package_name"
)

echo "[GEO] package ready: $zip_path"
