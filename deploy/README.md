# GEO Content Generation Deployment

This deployment path is for the internal content-generation trial. It does not
promise stable cloud crawling. Run the app with one worker until mutable storage
is moved fully to a database or protected by cross-process locks.

Current production-trial choice: use Ubuntu + conda + gunicorn + systemd. Do
not install Docker for the first cloud trial unless the deployment plan changes.

## Current ECS Trial Server

- Provider: Alibaba Cloud ECS
- Region label observed in console: North China 6
- Hostname: `iZ0jl4w2flouy3m8qid1o9Z`
- SSH user: `geosystem`
- Local SSH alias: `geo-content-v2`
- Public IP: `8.160.116.86`
- Private IP: `172.18.209.124`
- App directory for this trial: `/srv/geo-content-v2`
- Planned app port: `18080`
- Conda env: `/home/geosystem/miniconda3/envs/geo-content-v2`
- Isolation rule: do not touch `/srv/geo-system`, `/srv/geo-system-staging`,
  `/opt/face-recovery-v2`, or existing ports `80`, `443`, `3000`, `8000`,
  and `3101` while deploying this trial.

## Current Server State

Already completed on 2026-07-07:

- Uploaded package: `/home/geosystem/geo-content-v2-20260707-182422.zip`.
- Unzipped into `/srv/geo-content-v2`.
- Created conda env `geo-content-v2` with Python `3.12.13`.
- Installed `requirements.txt`.
- Created `.env`, `data/`, `pdf/`, and `logs/`.
- Manual gunicorn smoke test succeeded on `18080`.
- Manual gunicorn process was stopped; `18080` should be free before creating
  the systemd service.

Verify before continuing:

```bash
hostname
whoami
ss -lntp | grep 18080 || echo "18080 not listening"
```

Expected host/user:

```text
iZ0jl4w2flouy3m8qid1o9Z
geosystem
```

## Current Non-Docker Runbook

Connect from the Windows laptop:

```powershell
ssh geo-content-v2
```

If SakuraCat/VPN blocks new SSH connections, turn the VPN off, connect SSH,
then turn the VPN back on after the shell is established.

Create the systemd unit:

```bash
sudo tee /etc/systemd/system/geo-content-v2.service >/dev/null <<'EOF'
[Unit]
Description=GEO Content Generation Trial
After=network.target

[Service]
Type=simple
User=geosystem
Group=geosystem
WorkingDirectory=/srv/geo-content-v2
EnvironmentFile=/srv/geo-content-v2/.env
ExecStart=/home/geosystem/miniconda3/envs/geo-content-v2/bin/gunicorn --bind 0.0.0.0:18080 --workers 1 --threads 8 --timeout 1800 app:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Start and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now geo-content-v2.service
sudo systemctl status geo-content-v2.service --no-pager
curl -s http://127.0.0.1:18080/api/health
curl -I http://127.0.0.1:18080/
```

Expected:

- `/api/health` returns JSON with `ok=true`.
- `/` returns a redirect to `/login`.
- Existing services on ports `80`, `443`, `3000`, `8000`, and `3101` still
  behave as before.

Create the first admin user after the service is healthy. Do not paste the
password into chat logs. Operators may use the register form to create their own
non-admin accounts.

```bash
cd /srv/geo-content-v2
/home/geosystem/miniconda3/envs/geo-content-v2/bin/python scripts/create_user.py --username <name> --role admin
```

Useful service commands:

```bash
sudo systemctl status geo-content-v2.service --no-pager
sudo journalctl -u geo-content-v2.service -n 120 --no-pager
sudo systemctl restart geo-content-v2.service
sudo systemctl stop geo-content-v2.service
```

## Git Deploy For Current Trial

The current preferred deploy path is Git, not a zip package. Keep runtime data
out of the repo and pull code only:

```bash
cd /srv/geo-content-v2
git status --short --branch
git pull --ff-only
sudo systemctl restart geo-content-v2.service
curl -fsS http://127.0.0.1:18080/api/health
```

If `git status --short` shows local changes other than expected untracked
runtime files such as `.env`, stop and inspect before pulling. Do not overwrite
cloud `data/`, `pdf/`, `logs/`, or `.env`.

Public browser test URL after the Alibaba Cloud security group allows `18080`:

```text
http://8.160.116.86:18080
```

Prefer allowing `18080` only from the office/home source IPs needed for the
trial. Do not change Nginx or ports `80`/`443` for the first validation.

## Docker

Not used for the current ECS trial. Keep this section as a future option only.

Prepare server files:

```bash
cp .env.example .env
mkdir -p data pdf logs
```

Edit `.env` and set a long random `GEO_SECRET_KEY`.

Start or update the service:

```bash
docker compose up -d --build
```

Local Docker maps host port `8080` to container port `5000`:

```bash
curl http://127.0.0.1:8080/api/health
```

The compose file mounts these persistent directories:

- `data/`: customers, users, settings, uploads metadata, generated history, and the SQLite content-generation database.
- `pdf/`: local PDF workspace if used by operators.
- `logs/`: runtime logs.

## Ubuntu Without Docker

Generic manual command pattern:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p data pdf logs
export GEO_SECRET_KEY="replace-with-a-long-random-secret"
export GEO_HOST="0.0.0.0"
export GEO_PORT="5000"
gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 8 --timeout 1800 app:app
```

The current ECS trial uses the conda/systemd runbook above instead of this
generic venv pattern.

Use exactly one worker for the trial. 云端试用阶段只启动一个 worker，可以用少量 threads 处理登录和页面请求并发。
Multiple workers can corrupt or race on JSON-backed state while parts of the app
still use local files.

## Server Checklist

1. Create `.env` from `.env.example`.
2. Create `data/`, `pdf/`, and `logs/`.
3. Start the app with Docker or Gunicorn.
4. Create the first admin user with `scripts/create_user.py`.
5. Configure model credentials in the web UI settings page.
6. Verify `/api/health` locally.
7. Verify browser access requires login.
8. Open Alibaba Cloud security group port `18080` only after local health checks
   pass.

## Backup And Rollback Notes

Before risky changes, back up at least `data/`, `pdf/`, and `logs/`. The
content-generation SQLite database lives under `data/` and is included in that
backup set.

Manual backup example on the ECS:

```bash
mkdir -p /srv/backups/geo-content-v2
tar -czf /srv/backups/geo-content-v2/geo-content-v2-$(date +%Y%m%d-%H%M%S).tgz -C /srv/geo-content-v2 data pdf logs .env
```

Docker rollback usually means checking out the previous commit and running:

```bash
docker compose up -d --build
```

## Zip Package Deploy Helper

For the current ECS trial, this is now a fallback path when Git is unavailable.
Prefer Git deploy first. If a zip package is necessary, use the checked-in
helper instead of pasting a long deployment block into SSH.

Upload the zip package to `/home/geosystem/`, then run:

```bash
cd /srv/geo-content-v2
bash scripts/deploy_cloud_package.sh /home/geosystem/<package>.zip
```

The helper backs up `data/`, `pdf/`, `logs/`, and `.env`, extracts the package,
repairs ownership and basic permissions, restarts `geo-content-v2.service`,
waits for `/api/health`, and prints the key frontend marker.

## Incremental Raw Records Import

Code deployment does not sync local crawler data. When local runs produced
records that are missing on the cloud, append only the missing raw records with
the import helper. Do not replace the cloud `data/raw_records.json` file.

Upload a zip that contains local `data/raw_records.json`, extract it to a temp
folder, then dry-run:

```bash
cd /srv/geo-content-v2
/home/geosystem/miniconda3/envs/geo-content-v2/bin/python \
  scripts/import_missing_raw_records.py \
  /tmp/geo-import/data/raw_records.json \
  --target data/raw_records.json
```

If the summary looks right, apply while the service is stopped so no request is
writing the same JSON file:

```bash
sudo systemctl stop geo-content-v2.service
/home/geosystem/miniconda3/envs/geo-content-v2/bin/python \
  scripts/import_missing_raw_records.py \
  /tmp/geo-import/data/raw_records.json \
  --target data/raw_records.json \
  --apply
sudo systemctl start geo-content-v2.service
curl -fsS http://127.0.0.1:18080/api/health
```

The helper creates a timestamped backup next to the target file before writing.
It deduplicates by record content, not only by `record_id`.
