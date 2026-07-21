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

    def get_article(self, client_id, article_id):
        with self._connection() as conn:
            self._import_legacy_client(conn, client_id)
            conn.commit()
            row = conn.execute(
                "SELECT * FROM content_articles WHERE client_id = ? AND id = ?",
                (client_id, article_id),
            ).fetchone()
        return self._article_from_row(row) if row else None

    def update_article_content(self, client_id, article_id, content, title=None, gate_report=None,
                               generation_status=None):
        content = str(content or "").strip()
        if not content:
            return None
        title = str(title or content.splitlines()[0] or "未命名文章").strip()[:80]
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    """
                    UPDATE content_articles
                    SET title = ?, content = ?, gate_report_json = ?, generation_status = ?
                    WHERE client_id = ? AND id = ?
                    """,
                    (title, content, self._dumps_optional(gate_report), str(generation_status or ""), client_id, article_id),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    return None
                row = conn.execute(
                    "SELECT * FROM content_articles WHERE client_id = ? AND id = ?",
                    (client_id, article_id),
                ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._article_from_row(row)

    def update_article_gate_report(self, client_id, article_id, gate_report):
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    "UPDATE content_articles SET gate_report_json = ? WHERE client_id = ? AND id = ?",
                    (self._dumps_optional(gate_report), client_id, article_id),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    return None
                row = conn.execute(
                    "SELECT * FROM content_articles WHERE client_id = ? AND id = ?",
                    (client_id, article_id),
                ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._article_from_row(row)

    def load_revision_lineage(self, client_id, article_id):
        article = self.get_article(client_id, article_id)
        lineage, seen = [], set()
        while article and article["id"] not in seen:
            lineage.append(article)
            seen.add(article["id"])
            parent_id = str(article.get("parent_id") or "")
            article = self.get_article(client_id, parent_id) if parent_id else None
        return list(reversed(lineage))

    def delete_generation(self, client_id, article_id):
        client_id = str(client_id or "")
        article_id = str(article_id or "")
        if not client_id or not article_id:
            return False
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if not conn.execute(
                    "SELECT 1 FROM content_articles WHERE client_id = ? AND id = ?",
                    (client_id, article_id),
                ).fetchone():
                    conn.rollback()
                    return False
                linked_message_ids = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM content_messages WHERE client_id = ? AND article_id = ? AND role = 'assistant'",
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
                for message_id in linked_message_ids:
                    conn.execute(
                        "DELETE FROM content_messages WHERE client_id = ? AND id = ? AND role = 'user' AND article_id = ''",
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
                model TEXT NOT NULL DEFAULT '',
                material_count INTEGER NOT NULL DEFAULT 0,
                article_type TEXT NOT NULL DEFAULT '',
                article_subtype TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                parent_id TEXT,
                root_id TEXT,
                batch_id TEXT,
                brief_json TEXT,
                provenance_json TEXT,
                gate_report_json TEXT,
                generation_status TEXT,
                modify_instruction TEXT,
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
        self._ensure_column(conn, "content_articles", "article_subtype", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "content_articles", "parent_id", "TEXT")
        self._ensure_column(conn, "content_articles", "root_id", "TEXT")
        self._ensure_column(conn, "content_articles", "batch_id", "TEXT")
        self._ensure_column(conn, "content_articles", "brief_json", "TEXT")
        self._ensure_column(conn, "content_articles", "provenance_json", "TEXT")
        self._ensure_column(conn, "content_articles", "gate_report_json", "TEXT")
        self._ensure_column(conn, "content_articles", "generation_status", "TEXT")
        self._ensure_column(conn, "content_articles", "modify_instruction", "TEXT")
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
                id, client_id, sequence, title, content, model,
                material_count, article_type, article_subtype, created_at,
                parent_id, root_id, batch_id, brief_json, provenance_json, gate_report_json, generation_status, modify_instruction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(article.get("id") or ""),
                client_id,
                int(article.get("sequence") or 0),
                str(article.get("title") or ""),
                str(article.get("content") or ""),
                str(article.get("model") or ""),
                int(article.get("material_count") or 0),
                self._normalize_article_type(article.get("article_type")),
                str(article.get("article_subtype") or "").strip(),
                str(article.get("created_at") or ""),
                self._optional_text(article.get("parent_id")),
                self._optional_text(article.get("root_id")),
                self._optional_text(article.get("batch_id")),
                self._dumps_optional(article.get("brief")),
                self._dumps_optional(article.get("provenance")),
                self._dumps_optional(article.get("gate_report")),
                str(article.get("generation_status") or ""),
                self._optional_text(article.get("modify_instruction")),
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
            "model": row["model"],
            "material_count": row["material_count"],
            "article_type": row["article_type"],
            "article_subtype": row["article_subtype"],
            "created_at": row["created_at"],
            "parent_id": row["parent_id"],
            "root_id": row["root_id"],
            "batch_id": row["batch_id"],
            "brief": self._loads_optional(row["brief_json"]),
            "provenance": self._loads_optional(row["provenance_json"]),
            "gate_report": self._loads_optional(row["gate_report_json"]),
            "generation_status": row["generation_status"],
            "modify_instruction": row["modify_instruction"],
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

    def _dumps_optional(self, value):
        return json.dumps(value, ensure_ascii=False) if value is not None else None

    def _loads_optional(self, value):
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    def _optional_text(self, value):
        value = str(value or "").strip()
        return value or None
