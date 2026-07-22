import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime


class PublicationStore:
    def __init__(self, db_path):
        self.db_path = os.fspath(db_path)

    def create_draft(self, client_id, article, created_by=""):
        article = dict(article or {})
        now = self._now()
        draft = {
            "id": uuid.uuid4().hex,
            "client_id": str(client_id),
            "article_id": str(article.get("id") or ""),
            "article_title": str(article.get("title") or ""),
            "article_content": str(article.get("content") or ""),
            "gate_verdict": str((article.get("gate_report") or {}).get("verdict") or ""),
            "preview_token": secrets.token_urlsafe(32),
            "status": "draft",
            "created_by": str(created_by or ""),
            "created_at": now,
            "updated_at": now,
        }
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO publication_drafts VALUES
                    (:id, :client_id, :article_id, :article_title, :article_content,
                     :gate_verdict, :preview_token, :status, :created_by, :created_at, :updated_at)""",
                    draft,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return draft

    def get_draft(self, client_id, draft_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM publication_drafts WHERE client_id = ? AND id = ?", (client_id, draft_id)
            ).fetchone()
        return dict(row) if row else None

    def create_supplier_order(self, client_id, draft_id, provider_order_no, resource_type,
                              resource_id, resource_name, price):
        now = self._now()
        order = {
            "id": uuid.uuid4().hex,
            "client_id": str(client_id),
            "draft_id": str(draft_id),
            "provider": "rwmeiti",
            "provider_order_no": str(provider_order_no),
            "resource_type": str(resource_type),
            "resource_id": str(resource_id),
            "resource_name": str(resource_name),
            "price": float(price),
            "status": "pending",
            "provider_url": "",
            "provider_reason": "",
            "created_at": now,
            "updated_at": now,
        }
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO supplier_orders VALUES
                    (:id, :client_id, :draft_id, :provider, :provider_order_no, :resource_type,
                     :resource_id, :resource_name, :price, :status, :provider_url,
                     :provider_reason, :created_at, :updated_at)""",
                    order,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return order

    def record_completed_publication(self, client_id, order_id, channel_name, url, title, published_at):
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT * FROM publication_records WHERE client_id = ? AND provider_order_id = ?",
                    (client_id, order_id),
                ).fetchone()
                if existing:
                    conn.commit()
                    return dict(existing)
                order = conn.execute(
                    "SELECT * FROM supplier_orders WHERE client_id = ? AND id = ?", (client_id, order_id)
                ).fetchone()
                if not order:
                    conn.rollback()
                    return None
                draft = conn.execute(
                    "SELECT * FROM publication_drafts WHERE client_id = ? AND id = ?", (client_id, order["draft_id"])
                ).fetchone()
                if not draft:
                    conn.rollback()
                    return None
                record = {
                    "id": uuid.uuid4().hex,
                    "client_id": str(client_id),
                    "article_id": draft["article_id"],
                    "draft_id": draft["id"],
                    "provider_order_id": order_id,
                    "channel_name": str(channel_name),
                    "url": str(url),
                    "title": str(title),
                    "published_at": str(published_at),
                    "advertising_labeled": 0,
                    "source": "rwmeiti",
                    "created_at": self._now(),
                }
                conn.execute(
                    """INSERT INTO publication_records VALUES
                    (:id, :client_id, :article_id, :draft_id, :provider_order_id, :channel_name,
                     :url, :title, :published_at, :advertising_labeled, :source, :created_at)""", record
                )
                conn.commit()
                return record
            except Exception:
                conn.rollback()
                raise

    def list_publications(self, client_id):
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM publication_records WHERE client_id = ? ORDER BY published_at DESC", (client_id,)
            )
            return [dict(row) for row in rows]

    def article_has_publication_state(self, client_id, article_id):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM publication_drafts WHERE client_id = ? AND article_id = ? LIMIT 1",
                (client_id, article_id),
            ).fetchone()
        return bool(row)

    @contextmanager
    def _connection(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            self._ensure_schema(conn)
            conn.commit()
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self, conn):
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS publication_drafts (
            id TEXT PRIMARY KEY, client_id TEXT NOT NULL, article_id TEXT NOT NULL,
            article_title TEXT NOT NULL, article_content TEXT NOT NULL,
            gate_verdict TEXT NOT NULL DEFAULT '', preview_token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'draft', created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplier_resources (
            client_id TEXT NOT NULL, provider TEXT NOT NULL, resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', price REAL,
            status TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL DEFAULT '{}', synced_at TEXT NOT NULL,
            PRIMARY KEY (client_id, provider, resource_type, resource_id)
        );
        CREATE TABLE IF NOT EXISTS supplier_orders (
            id TEXT PRIMARY KEY, client_id TEXT NOT NULL, draft_id TEXT NOT NULL,
            provider TEXT NOT NULL, provider_order_no TEXT NOT NULL UNIQUE,
            resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, resource_name TEXT NOT NULL,
            price REAL, status TEXT NOT NULL, provider_url TEXT NOT NULL DEFAULT '',
            provider_reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS publication_records (
            id TEXT PRIMARY KEY, client_id TEXT NOT NULL, article_id TEXT NOT NULL,
            draft_id TEXT NOT NULL, provider_order_id TEXT NOT NULL UNIQUE,
            channel_name TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
            published_at TEXT NOT NULL, advertising_labeled INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'rwmeiti', created_at TEXT NOT NULL
        );
        """)

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
