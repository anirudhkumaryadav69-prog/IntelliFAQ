"""
SQLite connection management and schema initialization for IntelliFAQ 2.0.

Design notes:
- Uses only the Python standard-library `sqlite3` module (no new dependencies).
- Opens a short-lived connection per operation, which is safe across Flask's
  threaded request handling and lets transient failures recover automatically
  on the next request.
- Every connection enforces `PRAGMA foreign_keys = ON` (SQLite disables FK
  enforcement per-connection by default).
- Write operations run inside `BEGIN IMMEDIATE` transactions so multi-statement
  updates are atomic: they either fully commit or fully roll back.
- Raw `sqlite3` errors are logged server-side and re-raised as a sanitized
  `DatabaseError` that never carries SQL text or filesystem paths.
"""

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# Bump when the schema changes; stored in `PRAGMA user_version`.
SCHEMA_VERSION = 5

DB_PATH_ENV_VAR = "INTELLIFAQ_DB_PATH"
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "instance" / "intellifaq.db"

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS conversations (
        conversation_id        TEXT PRIMARY KEY
                               CHECK (length(conversation_id) = 36),
        created_at             TEXT NOT NULL,
        updated_at             TEXT NOT NULL,
        last_resolved_faq_id   INTEGER,
        last_resolved_question TEXT,
        last_resolved_category TEXT,
        pending_candidates     TEXT NOT NULL DEFAULT '[]',
        clarification_state    TEXT NOT NULL DEFAULT '{}',
        title                  TEXT NOT NULL DEFAULT 'New Conversation',
        is_title_custom        INTEGER NOT NULL DEFAULT 0
                               CHECK (is_title_custom IN (0, 1)),
        is_active              INTEGER NOT NULL DEFAULT 1
                               CHECK (is_active IN (0, 1)),
        last_activity_seq      INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        message_id            INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id       TEXT NOT NULL
                              REFERENCES conversations(conversation_id)
                              ON DELETE CASCADE,
        role                  TEXT NOT NULL
                              CHECK (role IN ('user', 'assistant')),
        message_text          TEXT NOT NULL,
        created_at            TEXT NOT NULL,
        match_type            TEXT
                              CHECK (match_type IS NULL OR match_type IN
                                     ('clear_match', 'ambiguous_match', 'no_reliable_match')),
        category              TEXT,
        faq_id                INTEGER,
        confidence            REAL,
        is_multi_intent       INTEGER NOT NULL DEFAULT 0
                              CHECK (is_multi_intent IN (0, 1)),
        matched_question      TEXT,
        fallback              INTEGER NOT NULL DEFAULT 0
                              CHECK (fallback IN (0, 1)),
        needs_clarification   INTEGER NOT NULL DEFAULT 0
                              CHECK (needs_clarification IN (0, 1)),
        clarification_message TEXT,
        candidates            TEXT NOT NULL DEFAULT '[]',
        sub_responses         TEXT NOT NULL DEFAULT '[]',
        reply_to_message_id   INTEGER
                              REFERENCES messages(message_id)
                              ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
        ON messages (conversation_id, created_at, message_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_reply_to
        ON messages (reply_to_message_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversations_created_at
        ON conversations (created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversations_activity
        ON conversations (is_active, last_activity_seq)
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_users (
        admin_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_sessions (
        session_id TEXT PRIMARY KEY,
        admin_id   INTEGER NOT NULL
                   REFERENCES admin_users(admin_id)
                   ON DELETE CASCADE,
        csrf_token TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires
        ON admin_sessions (expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS faq_categories (
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS faqs (
        faq_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL
                    REFERENCES faq_categories(category_id)
                    ON DELETE RESTRICT,
        question    TEXT NOT NULL,
        answer      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_faqs_category
        ON faqs (category_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS faq_alternatives (
        alt_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        faq_id     INTEGER NOT NULL
                   REFERENCES faqs(faq_id)
                   ON DELETE CASCADE,
        question   TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_faq_alternatives_faq
        ON faq_alternatives (faq_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS unanswered_questions (
        item_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        query_text       TEXT NOT NULL,
        conversation_id  TEXT,
        match_type       TEXT NOT NULL
                         CHECK (match_type IN ('no_reliable_match', 'ambiguous_match')),
        occurrence_count INTEGER NOT NULL DEFAULT 1,
        status           TEXT NOT NULL DEFAULT 'unreviewed'
                         CHECK (status IN ('unreviewed', 'reviewed', 'resolved', 'dismissed')),
        review_notes     TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_unanswered_status_updated
        ON unanswered_questions (status, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_activity_log (
        activity_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        action       TEXT NOT NULL,
        entity_type  TEXT NOT NULL,
        entity_label TEXT NOT NULL,
        created_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        title             TEXT NOT NULL,
        doc_type          TEXT NOT NULL,
        academic_year     TEXT NOT NULL,
        department        TEXT,
        description       TEXT,
        effective_date    TEXT,
        expiry_date       TEXT,
        original_filename TEXT NOT NULL,
        storage_filename  TEXT NOT NULL,
        mime_type         TEXT NOT NULL,
        file_size         INTEGER NOT NULL,
        sha256_hash       TEXT NOT NULL,
        version           INTEGER NOT NULL DEFAULT 1,
        superseded_by_id  INTEGER REFERENCES documents(document_id) ON DELETE SET NULL,
        page_count        INTEGER,
        chunk_count       INTEGER NOT NULL DEFAULT 0,
        extracted_preview TEXT,
        processing_status TEXT NOT NULL DEFAULT 'uploaded'
                          CHECK (processing_status IN ('uploaded', 'processing', 'processed', 'failed', 'OCR_REQUIRED', 'archived')),
        approval_status   TEXT NOT NULL DEFAULT 'pending_review'
                          CHECK (approval_status IN ('pending_review', 'approved', 'rejected')),
        uploaded_by       TEXT NOT NULL,
        error_message     TEXT,
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_documents_status
        ON documents (processing_status, approval_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_documents_sha256
        ON documents (sha256_hash)
    """,
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        chunk_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id       INTEGER NOT NULL
                          REFERENCES documents(document_id)
                          ON DELETE CASCADE,
        chunk_index       INTEGER NOT NULL,
        page_number       INTEGER,
        section_heading   TEXT,
        paragraph_ref     TEXT,
        chunk_text        TEXT NOT NULL,
        char_count        INTEGER NOT NULL,
        created_at        TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_document_chunks_doc
        ON document_chunks (document_id, chunk_index)
    """,
    """
    CREATE TABLE IF NOT EXISTS document_processing_logs (
        log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER NOT NULL
                    REFERENCES documents(document_id)
                    ON DELETE CASCADE,
        event_type  TEXT NOT NULL,
        status      TEXT NOT NULL,
        message     TEXT NOT NULL,
        actor       TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_document_logs_doc
        ON document_processing_logs (document_id, log_id)
    """,
)

EXPECTED_TABLES = {
    "conversations",
    "messages",
    "admin_users",
    "admin_sessions",
    "faq_categories",
    "faqs",
    "faq_alternatives",
    "unanswered_questions",
    "admin_activity_log",
    "documents",
    "document_chunks",
    "document_processing_logs",
}


class DatabaseError(Exception):
    """
    Sanitized persistence-layer error. The message is safe to log but is
    never forwarded verbatim to API clients.
    """


def resolve_database_path(explicit_path: Optional[os.PathLike] = None) -> Path:
    """
    Resolve the SQLite database file location, in priority order:
    1. An explicitly supplied path (used by tests).
    2. The `INTELLIFAQ_DB_PATH` environment variable.
    3. `backend/instance/intellifaq.db`.
    """
    if explicit_path:
        return Path(explicit_path)
    env_path = os.environ.get(DB_PATH_ENV_VAR, "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


class Database:
    """Thin, thread-safe wrapper around a single SQLite database file."""

    def __init__(
        self,
        path: Optional[os.PathLike] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.path: Path = resolve_database_path(path)
        self.timeout_seconds = float(timeout_seconds)
        self._init_lock = threading.Lock()
        self._initialized = False
        self.last_error: Optional[str] = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------
    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=self.timeout_seconds,
            isolation_level=None,  # explicit BEGIN/COMMIT management
            check_same_thread=True,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.timeout_seconds * 1000)}")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a short-lived connection for read-only work."""
        self.ensure_initialized()
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = self._open_connection()
            yield conn
        except sqlite3.Error as exc:
            self._record_failure("read", exc)
            raise DatabaseError("Conversation storage read failed.") from exc
        finally:
            if conn is not None:
                conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Yield a connection inside a `BEGIN IMMEDIATE` transaction. Commits on
        success and rolls back on any exception so partial writes never persist.
        """
        self.ensure_initialized()
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = self._open_connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self._record_failure("write", exc)
            raise DatabaseError("Conversation storage write failed.") from exc
        finally:
            if conn is not None:
                conn.close()

    def _record_failure(self, operation: str, exc: BaseException) -> None:
        # Log type + message server-side only (never returned to clients).
        self.last_error = f"{operation} failure ({type(exc).__name__})"
        logger.error("SQLite %s operation failed: %s: %s", operation, type(exc).__name__, exc)
        if isinstance(exc, sqlite3.OperationalError):
            # e.g. missing file/table or lock problems: re-run idempotent schema
            # initialization on the next operation so the service can self-heal.
            self._initialized = False

    # ------------------------------------------------------------------
    # Initialization & health
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """
        Create the database file, schema and indexes if they do not exist.
        Idempotent; safe to call on every startup. Never inserts data rows.
        """
        with self._init_lock:
            conn: Optional[sqlite3.Connection] = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = self._open_connection()

                current_version = conn.execute("PRAGMA user_version").fetchone()[0]
                if current_version > SCHEMA_VERSION:
                    raise DatabaseError(
                        "Database schema version is newer than this application supports."
                    )

                try:
                    conn.execute("PRAGMA journal_mode = WAL")
                except sqlite3.Error:
                    # WAL is an optimization; fall back to the default journal.
                    logger.warning("SQLite WAL journal mode unavailable; using default.")

                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in SCHEMA_STATEMENTS:
                        conn.execute(statement)
                    if 0 < current_version < 5:
                        cols = {
                            row["name"]
                            for row in conn.execute(
                                "PRAGMA table_info(conversations)"
                            ).fetchall()
                        }
                        if "clarification_state" not in cols:
                            conn.execute(
                                "ALTER TABLE conversations "
                                "ADD COLUMN clarification_state TEXT NOT NULL DEFAULT '{}'"
                            )
                        if "title" not in cols:
                            conn.execute(
                                "ALTER TABLE conversations "
                                "ADD COLUMN title TEXT NOT NULL DEFAULT 'New Conversation'"
                            )
                        if "is_title_custom" not in cols:
                            conn.execute(
                                "ALTER TABLE conversations "
                                "ADD COLUMN is_title_custom INTEGER NOT NULL DEFAULT 0"
                            )
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")

                self._initialized = True
                self.last_error = None
                logger.info("SQLite conversation storage initialized (schema v%d).", SCHEMA_VERSION)
            except sqlite3.Error as exc:
                self._initialized = False
                self._record_failure("initialize", exc)
                raise DatabaseError("Conversation storage initialization failed.") from exc
            except OSError as exc:
                self._initialized = False
                self._record_failure("initialize", exc)
                raise DatabaseError("Conversation storage initialization failed.") from exc
            finally:
                if conn is not None:
                    conn.close()

    def ensure_initialized(self) -> None:
        """Lazily (re)initialize so a failed startup can recover later."""
        if not self._initialized:
            self.initialize()

    def health_check(self) -> bool:
        """Return True when the database is reachable and the schema is present."""
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1").fetchone()
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                present = {row["name"] for row in rows}
                if not EXPECTED_TABLES.issubset(present):
                    self._initialized = False
                    return False
                fk_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
                return bool(fk_enabled)
        except DatabaseError:
            return False
