import json
import os
import sqlite3
from contextlib import contextmanager


class ContentGenerationStore:
    def __init__(self, db_path, legacy_json_path=None):
        self.db_path = os.fspath(db_path)
        self.legacy_json_path = os.fspath(legacy_json_path) if legacy_json_path else None

    def load_session(self, client_id, date=None):
        with self._connection() as conn:
            self._import_legacy_client(conn, client_id)
            conn.commit()
            day = self._normalize_date(date)
            messages = self._load_messages(conn, client_id, date=day)
            params = [client_id]
            where = "client_id = ?"
            if day:
                where += " AND created_at LIKE ?"
                params.append(f"{day}%")
            articles = [
                self._article_from_row(row)
                for row in conn.execute(
                    f"""
                    SELECT *
                    FROM content_articles
                    WHERE {where}
                    ORDER BY sequence ASC, created_at ASC
                    """,
                    params,
                )
            ]
        return {"messages": messages, "articles": articles}

    def load_messages(self, client_id, article_type=None, date=None):
        with self._connection() as conn:
            self._import_legacy_client(conn, client_id)
            conn.commit()
            return self._load_messages(conn, client_id, article_type=article_type, date=date)

    def append_generation(self, client_id, article, user_message, assistant_message):
        article = dict(article or {})
        user_message = dict(user_message or {})
        assistant_message = dict(assistant_message or {})
        article_type = self._normalize_article_type(article.get("article_type"))
        article["article_type"] = article_type
        user_message["article_type"] = article_type
        assistant_message["article_type"] = article_type
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._import_legacy_client(conn, client_id)
                sequence = conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM content_articles WHERE client_id = ?",
                    (client_id,),
                ).fetchone()[0]
                article["client_id"] = client_id
                article["sequence"] = int(sequence)
                self._insert_article(conn, client_id, article)
                self._insert_message(conn, client_id, user_message)
                self._insert_message(conn, client_id, assistant_message)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return article

    def delete_generation(self, client_id, article_id):
        client_id = str(client_id or "")
        article_id = str(article_id or "")
        if not client_id or not article_id:
            return False
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                article = conn.execute(
                    """
                    SELECT operator_opinion, created_at
                    FROM content_articles
                    WHERE client_id = ? AND id = ?
                    """,
                    (client_id, article_id),
                ).fetchone()
                if not article:
                    conn.rollback()
                    return False
                linked_message_ids = [
                    row["id"]
                    for row in conn.execute(
                        """
                        SELECT id
                        FROM content_messages
                        WHERE client_id = ? AND article_id = ? AND role = 'assistant'
                        """,
                        (client_id, article_id),
                    )
                ]
                conn.execute(
                    "DELETE FROM content_articles WHERE client_id = ? AND id = ?",
                    (client_id, article_id),
                )
                conn.execute(
                    "DELETE FROM content_messages WHERE client_id = ? AND article_id = ?",
                    (client_id, article_id),
                )
                conn.execute(
                    """
                    DELETE FROM content_messages
                    WHERE client_id = ?
                      AND role = 'user'
                      AND article_id = ''
                      AND created_at = ?
                      AND content = ?
                    """,
                    (client_id, article["created_at"], article["operator_opinion"]),
                )
                for message_id in linked_message_ids:
                    conn.execute(
                        """
                        DELETE FROM content_messages
                        WHERE client_id = ?
                          AND id = ?
                          AND role = 'user'
                          AND article_id = ''
                        """,
                        (client_id, int(message_id) - 1),
                    )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _connect(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema(conn)
        conn.commit()
        return conn

    def _ensure_schema(self, conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_articles (
                id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                operator_opinion TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                material_count INTEGER NOT NULL DEFAULT 0,
                sample_link_count INTEGER NOT NULL DEFAULT 0,
                selected_article_count INTEGER NOT NULL DEFAULT 0,
                sample_links_json TEXT NOT NULL DEFAULT '[]',
                selected_articles_json TEXT NOT NULL DEFAULT '[]',
                article_type TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (client_id, id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                article_id TEXT NOT NULL DEFAULT '',
                article_type TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._ensure_column(conn, "content_articles", "article_type", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "content_messages", "article_type", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_content_articles_client_order
            ON content_articles(client_id, sequence DESC, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_content_messages_client_order
            ON content_messages(client_id, id ASC)
            """
        )

    def _import_legacy_client(self, conn, client_id):
        if not self.legacy_json_path or not os.path.exists(self.legacy_json_path):
            return
        existing = conn.execute(
            """
            SELECT 1 FROM content_articles WHERE client_id = ?
            UNION ALL
            SELECT 1 FROM content_messages WHERE client_id = ?
            LIMIT 1
            """,
            (client_id, client_id),
        ).fetchone()
        if existing:
            return
        try:
            with open(self.legacy_json_path, "r", encoding="utf-8") as f:
                legacy = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            return
        session = legacy.get(client_id) if isinstance(legacy, dict) else None
        if not isinstance(session, dict):
            return
        for index, item in enumerate(session.get("articles") or [], 1):
            if isinstance(item, dict):
                article = dict(item)
                article.setdefault("id", f"{client_id}-legacy-{index}")
                article.setdefault("sequence", index)
                self._insert_article(conn, client_id, article)
        for item in session.get("messages") or []:
            if isinstance(item, dict):
                self._insert_message(conn, client_id, item)

    def _load_messages(self, conn, client_id, article_type=None, date=None):
        article_type = self._normalize_article_type(article_type)
        day = self._normalize_date(date)
        params = [client_id]
        where = "client_id = ?"
        if article_type:
            where += " AND article_type = ?"
            params.append(article_type)
        if day:
            where += " AND created_at LIKE ?"
            params.append(f"{day}%")
        return [
            self._message_from_row(row)
            for row in conn.execute(
                f"""
                SELECT role, content, created_at, article_id, article_type
                FROM content_messages
                WHERE {where}
                ORDER BY id ASC
                """,
                params,
            )
        ]

    def _ensure_column(self, conn, table, column, definition):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _insert_article(self, conn, client_id, article):
        conn.execute(
            """
            INSERT OR REPLACE INTO content_articles (
                id, client_id, sequence, title, content, operator_opinion, model,
                material_count, sample_link_count, selected_article_count,
                sample_links_json, selected_articles_json, article_type, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(article.get("id") or ""),
                client_id,
                int(article.get("sequence") or 0),
                str(article.get("title") or ""),
                str(article.get("content") or ""),
                str(article.get("operator_opinion") or ""),
                str(article.get("model") or ""),
                int(article.get("material_count") or 0),
                int(article.get("sample_link_count") or 0),
                int(article.get("selected_article_count") or 0),
                json.dumps(article.get("sample_links") or [], ensure_ascii=False),
                json.dumps(article.get("selected_articles") or [], ensure_ascii=False),
                self._normalize_article_type(article.get("article_type")),
                str(article.get("created_at") or ""),
            ),
        )

    def _insert_message(self, conn, client_id, message):
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not content:
            return
        conn.execute(
            """
            INSERT INTO content_messages (client_id, role, content, created_at, article_id, article_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                role,
                str(content),
                str(message.get("created_at") or ""),
                str(message.get("article_id") or ""),
                self._normalize_article_type(message.get("article_type")),
            ),
        )

    def _article_from_row(self, row):
        return {
            "id": row["id"],
            "client_id": row["client_id"],
            "sequence": row["sequence"],
            "title": row["title"],
            "content": row["content"],
            "operator_opinion": row["operator_opinion"],
            "model": row["model"],
            "material_count": row["material_count"],
            "sample_link_count": row["sample_link_count"],
            "selected_article_count": row["selected_article_count"],
            "sample_links": self._loads_list(row["sample_links_json"]),
            "selected_articles": self._loads_list(row["selected_articles_json"]),
            "article_type": row["article_type"],
            "created_at": row["created_at"],
        }

    def _message_from_row(self, row):
        message = {
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        if row["article_id"]:
            message["article_id"] = row["article_id"]
        if row["article_type"]:
            message["article_type"] = row["article_type"]
        return message

    def _normalize_article_type(self, article_type):
        return article_type if article_type in {"对比型", "介绍型"} else ""

    def _normalize_date(self, value):
        value = str(value or "").strip()
        if len(value) != 10 or value[4] != "-" or value[7] != "-":
            return ""
        y, m, d = value[:4], value[5:7], value[8:10]
        return value if y.isdigit() and m.isdigit() and d.isdigit() else ""

    def _loads_list(self, value):
        try:
            data = json.loads(value or "[]")
        except (json.JSONDecodeError, ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []
