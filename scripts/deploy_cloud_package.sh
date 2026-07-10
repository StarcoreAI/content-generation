#!/usr/bin/env bash
set -euo pipefail

APP=${APP:-/srv/geo-content-v2}
PY=${PY:-/home/geosystem/miniconda3/envs/geo-content-v2/bin/python}
PKG=${1:-}

if [ -z "$PKG" ]; then
  echo "Usage: bash scripts/deploy_cloud_package.sh /home/geosystem/package.zip"
  exit 2
fi

[ -f "$PKG" ] || { echo "missing package: $PKG"; exit 1; }
[ -x "$PY" ] || { echo "missing python: $PY"; exit 1; }
[ -d "$APP" ] || { echo "missing app dir: $APP"; exit 1; }

cd "$APP"

mkdir -p /srv/backups/geo-content-v2
BACKUP=/srv/backups/geo-content-v2/geo-content-v2-before-sync-$(date +%Y%m%d-%H%M%S).tgz
items=()
for p in data pdf logs .env; do
  [ -e "$p" ] && items+=("$p")
done
if [ ${#items[@]} -gt 0 ]; then
  tar -czf "$BACKUP" "${items[@]}"
  echo "backup=$BACKUP"
else
  echo "backup skipped"
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

# python -m zipfile -e keeps deployment independent of unzip.
"$PY" -m zipfile -e "$PKG" "$STAGE"
cp -a "$STAGE"/. "$APP"/

sudo chown -R geosystem:geosystem "$APP"
find "$APP" -type d -exec chmod 755 {} \;
find "$APP" -type f -exec chmod 644 {} \;

sudo systemctl restart geo-content-v2.service

healthy=0
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18080/api/health >/tmp/geo-content-v2-health.json; then
    healthy=1
    break
  fi
  sleep 1
done

if [ "$healthy" -ne 1 ]; then
  echo "health check failed"
  sudo systemctl status geo-content-v2.service --no-pager -l | sed -n '1,20p'
  sudo journalctl -u geo-content-v2.service -n 80 --no-pager
  exit 1
fi

cat /tmp/geo-content-v2-health.json
echo
grep -n "btnCrawlGroup" "$APP/templates/index.html" | head
sudo systemctl status geo-content-v2.service --no-pager -l | sed -n '1,16p'
