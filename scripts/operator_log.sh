#!/usr/bin/env bash

start_operator_log() {
  local name="$1"
  local project_root
  project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  local log_dir="$project_root/operator_logs"
  mkdir -p "$log_dir"

  find "$log_dir" -type f \( -name "*.log" -o -name "*.zip" \) -mtime +14 -delete 2>/dev/null || true

  local safe_name timestamp log_file
  safe_name="$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '-')"
  timestamp="$(date +%Y%m%d-%H%M%S)"
  log_file="$log_dir/$safe_name-$timestamp.log"

  echo "[GEO] log file: $log_file"
  echo "[GEO] old operator logs expire after 14 days."

  exec > >(tee -a "$log_file") 2>&1
}
