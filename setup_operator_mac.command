#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

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
if [[ -f "$PACKAGED_NODE_BIN/node" ]]; then
  chmod +x "$PACKAGED_NODE_BIN/node"
fi
if [[ -x "$PACKAGED_NODE_BIN/node" ]]; then
  export PATH="$PACKAGED_NODE_BIN:$PATH"
fi

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
  echo "[ERROR] node was not found in this operator package."
  echo "[ERROR] Download the latest Mac operator package instead of installing Node.js manually."
  exit 1
fi

echo "[GEO] detecting local crawler folder..."
GEO_NODE_CRAWLER_ROOT="$(python3 scripts/resolve_node_crawler_root.py)"
export GEO_NODE_CRAWLER_ROOT
echo "[GEO] crawler root: $GEO_NODE_CRAWLER_ROOT"
clear_macos_quarantine "$GEO_NODE_CRAWLER_ROOT"

install_packaged_chromium_archive() {
  local browser_root="$GEO_NODE_CRAWLER_ROOT/ms-playwright"
  local archive=""
  archive="$(find "$browser_root" -type f -name chrome-mac-arm64.zip -print -quit 2>/dev/null || true)"
  [[ -n "$archive" ]] || return

  local chromium_root="$(dirname "$archive")"
  local extract_root="$chromium_root/.chrome-mac-arm64.extracting-$$"
  local extracted="$extract_root/chrome-mac-arm64"
  local target="$chromium_root/chrome-mac-arm64"
  echo "[GEO] installing packaged macOS Chromium with the system archive tool..."
  rm -rf "$extract_root"
  mkdir -p "$extract_root"
  ditto -x -k "$archive" "$extract_root"
  if [[ ! -x "$extracted/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" ]]; then
    echo "[ERROR] Packaged macOS Chromium archive is incomplete or damaged: $archive"
    rm -rf "$extract_root"
    exit 1
  fi
  rm -rf "$target"
  mv "$extracted" "$target"
  rm -rf "$extract_root"
}

repair_packaged_chromium() {
  local browser_root="$GEO_NODE_CRAWLER_ROOT/ms-playwright"
  [[ -d "$browser_root" ]] || return

  find "$browser_root" -type f \( \
    -path "*/chrome-mac*/*.app/Contents/MacOS/*" -o \
    -name chrome_crashpad_handler -o \
    -name app_mode_loader -o \
    -name web_app_shortcut_copier \
  \) -exec chmod +x {} \; 2>/dev/null || true

  while IFS= read -r -d '' framework; do
    local versions="$framework/Versions"
    local version=""
    version="$(find "$versions" -mindepth 1 -maxdepth 1 -type d ! -name Current -print -quit 2>/dev/null || true)"
    [[ -n "$version" ]] || continue
    version="$(basename "$version")"

    if [[ ! -L "$versions/Current" ]]; then
      rm -f "$versions/Current"
      ln -s "$version" "$versions/Current"
    fi
    for name in "Google Chrome for Testing Framework" Helpers Libraries Resources; do
      if [[ ! -L "$framework/$name" ]]; then
        rm -f "$framework/$name"
        ln -s "Versions/Current/$name" "$framework/$name"
      fi
    done
  done < <(find "$browser_root" -type d -name "Google Chrome for Testing Framework.framework" -print0 2>/dev/null)
}

repair_packaged_playwright_tools() {
  local browser_root="$GEO_NODE_CRAWLER_ROOT/ms-playwright"
  local bin_dir="$GEO_NODE_CRAWLER_ROOT/node_modules/.bin"
  local tool=""

  find "$browser_root" -type f -name ffmpeg-mac -exec chmod +x {} \; 2>/dev/null || true

  mkdir -p "$bin_dir"
  for tool in playwright playwright-core; do
    if [[ -f "$GEO_NODE_CRAWLER_ROOT/node_modules/$tool/cli.js" ]]; then
      rm -f "$bin_dir/$tool"
      ln -s "../$tool/cli.js" "$bin_dir/$tool"
    fi
  done
}

install_packaged_chromium_archive
repair_packaged_chromium
repair_packaged_playwright_tools

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

if ! find "$GEO_NODE_CRAWLER_ROOT/ms-playwright" -path "*/chrome-mac*/*.app/Contents/MacOS/*" -type f -print -quit | grep -q .; then
  echo "[ERROR] Operator package is incomplete: missing packaged Playwright Chromium."
  echo "[ERROR] Expected a path like: $GEO_NODE_CRAWLER_ROOT/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app"
  exit 1
fi

mkdir -p "$GEO_NODE_CRAWLER_ROOT/storage"
export STORAGE_STATE_PATH="$GEO_NODE_CRAWLER_ROOT/storage/state.json"

chmod +x setup_operator_mac.command start_local_crawl_worker.command stop_local_crawl_worker.command scripts/first_login_all_platforms_mac.command

echo "[GEO] setup complete. Starting first platform login..."
"$(pwd)/scripts/first_login_all_platforms_mac.command"

echo "[GEO] setup and first login finished."
echo "[GEO] Next: run start_local_crawl_worker.command"
