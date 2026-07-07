# GEO Content Generation Deployment

This deployment path is for the internal content-generation trial. It does not
promise stable cloud crawling. Run the app with one worker until mutable storage
is moved fully to a database or protected by cross-process locks.

## Docker

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

Install Python 3.12 and create a virtual environment:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p data pdf logs
export GEO_SECRET_KEY="replace-with-a-long-random-secret"
export GEO_HOST="0.0.0.0"
export GEO_PORT="5000"
gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 1 --timeout 1800 app:app
```

Use exactly one worker for the trial. 云端试用阶段只启动一个 worker。
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

## Backup And Rollback Notes

Before risky changes, back up at least `data/`, `pdf/`, and `logs/`. The
content-generation SQLite database lives under `data/` and is included in that
backup set.

Docker rollback usually means checking out the previous commit and running:

```bash
docker compose up -d --build
```
