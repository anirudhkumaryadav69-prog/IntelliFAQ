"""
Knowledge Base, Admin Authentication, and Unanswered Questions Repositories
for IntelliFAQ 2.0.

Reuses the shared SQLite `Database` manager and parameterized transactions.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
from typing import Any, Dict, List, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from .conversation_repository import redact_sensitive_text
from .db import Database

logger = logging.getLogger(__name__)

DEFAULT_FAQ_JSON_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "faqs.json"
)
VALID_UNANSWERED_STATUSES = {"unreviewed", "reviewed", "resolved", "dismissed"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


class ConflictError(ValueError):
    """Raised when an operation conflicts with existing data (e.g. non-empty category delete)."""


class AdminAuthRepository:
    """SQLite-backed administrator authentication and HttpOnly session store."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def ensure_initial_admin(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Optional[str]:
        """
        Ensure at least one admin account exists without hardcoding passwords.
        Uses `INTELLIFAQ_ADMIN_USERNAME` (default 'admin') and
        `INTELLIFAQ_ADMIN_PASSWORD` (or generates a one-time random password).
        Returns the generated one-time password only if one was generated.
        """
        with self.db.transaction() as conn:
            count = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
            if count > 0:
                return None

            resolved_user = (
                (username or os.environ.get("INTELLIFAQ_ADMIN_USERNAME", "admin"))
                .strip()
                or "admin"
            )
            env_pass = password or os.environ.get("INTELLIFAQ_ADMIN_PASSWORD", "")
            generated: Optional[str] = None
            if not env_pass:
                generated = secrets.token_urlsafe(12)
                env_pass = generated
                logger.warning(
                    "Initial admin account '%s' created with a generated one-time "
                    "password (set INTELLIFAQ_ADMIN_PASSWORD in production).",
                    resolved_user,
                )

            now_iso = _utc_now_iso()
            conn.execute(
                """
                INSERT INTO admin_users (username, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (resolved_user, generate_password_hash(env_pass), now_iso, now_iso),
            )
            return generated

    def upsert_admin_user(self, username: str, password: str) -> str:
        """
        Idempotently create or update an administrator account without
        affecting other existing administrator accounts.
        Returns 'created', 'updated', or 'unchanged'.
        """
        cleaned_user = username.strip() if isinstance(username, str) else ""
        if not cleaned_user or len(cleaned_user) > 120:
            raise ValueError("Username must be between 1 and 120 characters.")
        if not isinstance(password, str) or len(password) < 6:
            raise ValueError("Password must be at least 6 characters.")

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT admin_id, password_hash
                FROM admin_users
                WHERE username = ? COLLATE NOCASE
                """,
                (cleaned_user,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO admin_users (username, password_hash, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (cleaned_user, generate_password_hash(password), now_iso, now_iso),
                )
                return "created"

            if check_password_hash(row["password_hash"], password):
                return "unchanged"

            conn.execute(
                """
                UPDATE admin_users
                SET password_hash = ?, updated_at = ?
                WHERE admin_id = ?
                """,
                (generate_password_hash(password), now_iso, int(row["admin_id"])),
            )
            return "updated"

    def verify_credentials(
        self, username: str, password: str
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        cleaned_user = username.strip()
        if not cleaned_user or not password:
            return None

        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT admin_id, username, password_hash
                FROM admin_users
                WHERE username = ? COLLATE NOCASE
                """,
                (cleaned_user,),
            ).fetchone()
        if row is None or not check_password_hash(row["password_hash"], password):
            return None
        return {"admin_id": row["admin_id"], "username": row["username"]}

    def create_session(
        self, admin_id: int, ttl_hours: int = 12
    ) -> Dict[str, Any]:
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        now = _utc_now()
        expires = now + timedelta(hours=max(1, int(ttl_hours)))

        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?",
                (now.isoformat(),),
            )
            conn.execute(
                """
                INSERT INTO admin_sessions (session_id, admin_id, csrf_token, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    int(admin_id),
                    csrf_token,
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
        return {
            "session_id": session_id,
            "csrf_token": csrf_token,
            "expires_at": expires.isoformat(),
        }

    def get_session(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        now_iso = _utc_now_iso()
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT s.session_id, s.admin_id, s.csrf_token, s.expires_at, u.username
                FROM admin_sessions AS s
                JOIN admin_users AS u ON u.admin_id = s.admin_id
                WHERE s.session_id = ? AND s.expires_at > ?
                """,
                (session_id.strip(), now_iso),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def delete_session(self, session_id: Optional[str]) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            return
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM admin_sessions WHERE session_id = ?",
                (session_id.strip(),),
            )


class KnowledgeBaseRepository:
    """SQLite-backed FAQ and category repository with idempotent JSON migration."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def _log_activity(
        self, conn: Any, action: str, entity_type: str, entity_label: str
    ) -> None:
        conn.execute(
            """
            INSERT INTO admin_activity_log (action, entity_type, entity_label, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (action, entity_type, entity_label[:200], _utc_now_iso()),
        )

    def seed_from_json_if_empty(
        self, json_path: Optional[Path] = None
    ) -> bool:
        """
        Idempotently migrate FAQs, categories, and alternative phrasings from
        `faqs.json` into SQLite if `faqs` is empty. Creates a `.bak` backup of
        the original JSON file if one does not already exist.
        """
        source = Path(json_path) if json_path is not None else DEFAULT_FAQ_JSON_PATH
        if not source.exists() or not source.is_file():
            return False

        with self.db.connection() as conn:
            existing_count = conn.execute("SELECT COUNT(*) FROM faqs").fetchone()[0]
            if existing_count > 0:
                return False

        backup_path = source.with_suffix(".json.bak")
        if not backup_path.exists():
            try:
                shutil.copy2(source, backup_path)
            except OSError as exc:
                logger.warning("Could not create JSON backup (%s): %s", backup_path, exc)

        records = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(records, list) or not records:
            return False

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            # Re-check inside transaction
            if conn.execute("SELECT COUNT(*) FROM faqs").fetchone()[0] > 0:
                return False

            cat_cache: Dict[str, int] = {}
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                faq_id = rec.get("id")
                cat_name = str(rec.get("category") or "").strip()
                question = str(rec.get("question") or "").strip()
                answer = str(rec.get("answer") or "").strip()
                if faq_id is None or not cat_name or not question or not answer:
                    continue

                if cat_name.lower() not in cat_cache:
                    row = conn.execute(
                        "SELECT category_id FROM faq_categories WHERE name = ? COLLATE NOCASE",
                        (cat_name,),
                    ).fetchone()
                    if row is None:
                        cur = conn.execute(
                            """
                            INSERT INTO faq_categories (name, created_at, updated_at)
                            VALUES (?, ?, ?)
                            """,
                            (cat_name, now_iso, now_iso),
                        )
                        cat_cache[cat_name.lower()] = int(cur.lastrowid)
                    else:
                        cat_cache[cat_name.lower()] = int(row["category_id"])

                cat_id = cat_cache[cat_name.lower()]
                conn.execute(
                    """
                    INSERT INTO faqs (faq_id, category_id, question, answer, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (int(faq_id), cat_id, question, answer, now_iso, now_iso),
                )

                alts = rec.get("alternative_questions", [])
                if isinstance(alts, list):
                    for alt in alts:
                        if isinstance(alt, str) and alt.strip():
                            conn.execute(
                                """
                                INSERT INTO faq_alternatives (faq_id, question, created_at, updated_at)
                                VALUES (?, ?, ?, ?)
                                """,
                                (int(faq_id), alt.strip(), now_iso, now_iso),
                            )

        logger.info("Migrated %d FAQs from JSON into SQLite knowledge base.", len(records))
        return True

    def export_for_chatbot(self) -> List[Dict[str, Any]]:
        """Return all FAQs in the format expected by `FAQChatbot.reload_from_records`."""
        with self.db.connection() as conn:
            faq_rows = conn.execute(
                """
                SELECT f.faq_id, f.question, f.answer, c.name AS category
                FROM faqs AS f
                JOIN faq_categories AS c ON c.category_id = f.category_id
                ORDER BY f.faq_id ASC
                """
            ).fetchall()
            alt_rows = conn.execute(
                """
                SELECT faq_id, question
                FROM faq_alternatives
                ORDER BY alt_id ASC
                """
            ).fetchall()

        alts_by_faq: Dict[int, List[str]] = {}
        for a in alt_rows:
            alts_by_faq.setdefault(int(a["faq_id"]), []).append(a["question"])

        return [
            {
                "id": int(r["faq_id"]),
                "category": r["category"],
                "question": r["question"],
                "answer": r["answer"],
                "alternative_questions": alts_by_faq.get(int(r["faq_id"]), []),
            }
            for r in faq_rows
        ]

    # ------------------------------------------------------------------
    # Dashboard Statistics
    # ------------------------------------------------------------------
    def get_dashboard_stats(self) -> Dict[str, Any]:
        with self.db.connection() as conn:
            total_faqs = int(conn.execute("SELECT COUNT(*) FROM faqs").fetchone()[0])
            total_categories = int(
                conn.execute("SELECT COUNT(*) FROM faq_categories").fetchone()[0]
            )
            total_alternatives = int(
                conn.execute("SELECT COUNT(*) FROM faq_alternatives").fetchone()[0]
            )
            total_unanswered = int(
                conn.execute(
                    "SELECT COUNT(*) FROM unanswered_questions WHERE status = 'unreviewed'"
                ).fetchone()[0]
            )
            dist_rows = conn.execute(
                """
                SELECT c.category_id, c.name AS category, COUNT(f.faq_id) AS count
                FROM faq_categories AS c
                LEFT JOIN faqs AS f ON f.category_id = c.category_id
                GROUP BY c.category_id
                ORDER BY c.name ASC
                """
            ).fetchall()
            recent_created = conn.execute(
                """
                SELECT f.faq_id, f.question, c.name AS category, f.created_at, f.updated_at
                FROM faqs AS f
                JOIN faq_categories AS c ON c.category_id = f.category_id
                ORDER BY f.created_at DESC, f.faq_id DESC
                LIMIT 5
                """
            ).fetchall()
            recent_updated = conn.execute(
                """
                SELECT f.faq_id, f.question, c.name AS category, f.created_at, f.updated_at
                FROM faqs AS f
                JOIN faq_categories AS c ON c.category_id = f.category_id
                ORDER BY f.updated_at DESC, f.faq_id DESC
                LIMIT 5
                """
            ).fetchall()
            activity_rows = conn.execute(
                """
                SELECT activity_id, action, entity_type, entity_label, created_at
                FROM admin_activity_log
                ORDER BY activity_id DESC
                LIMIT 10
                """
            ).fetchall()

        return {
            "total_faqs": total_faqs,
            "total_categories": total_categories,
            "total_alternatives": total_alternatives,
            "total_unanswered": total_unanswered,
            "category_distribution": [dict(r) for r in dist_rows],
            "recently_added_faqs": [dict(r) for r in recent_created],
            "recently_updated_faqs": [dict(r) for r in recent_updated],
            "recent_activity": [dict(r) for r in activity_rows],
        }

    # ------------------------------------------------------------------
    # Categories CRUD
    # ------------------------------------------------------------------
    def list_categories(self) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.category_id, c.name, c.created_at, c.updated_at,
                       COUNT(f.faq_id) AS faq_count
                FROM faq_categories AS c
                LEFT JOIN faqs AS f ON f.category_id = c.category_id
                GROUP BY c.category_id
                ORDER BY c.name ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def create_category(self, name: str) -> Dict[str, Any]:
        cleaned = name.strip() if isinstance(name, str) else ""
        if not cleaned or len(cleaned) > 80:
            raise ValueError("Category name must be between 1 and 80 characters.")

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            dup = conn.execute(
                "SELECT 1 FROM faq_categories WHERE name = ? COLLATE NOCASE",
                (cleaned,),
            ).fetchone()
            if dup is not None:
                raise ConflictError(f"Category '{cleaned}' already exists.")

            cur = conn.execute(
                """
                INSERT INTO faq_categories (name, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (cleaned, now_iso, now_iso),
            )
            cat_id = int(cur.lastrowid)
            self._log_activity(conn, "created", "category", cleaned)
        return {
            "category_id": cat_id,
            "name": cleaned,
            "faq_count": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }

    def rename_category(
        self, category_id: int, new_name: str
    ) -> Optional[Dict[str, Any]]:
        cleaned = new_name.strip() if isinstance(new_name, str) else ""
        if not cleaned or len(cleaned) > 80:
            raise ValueError("Category name must be between 1 and 80 characters.")

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT category_id, name FROM faq_categories WHERE category_id = ?",
                (int(category_id),),
            ).fetchone()
            if existing is None:
                return None

            dup = conn.execute(
                """
                SELECT 1 FROM faq_categories
                WHERE name = ? COLLATE NOCASE AND category_id != ?
                """,
                (cleaned, int(category_id)),
            ).fetchone()
            if dup is not None:
                raise ConflictError(f"Category '{cleaned}' already exists.")

            conn.execute(
                """
                UPDATE faq_categories
                SET name = ?, updated_at = ?
                WHERE category_id = ?
                """,
                (cleaned, now_iso, int(category_id)),
            )
            self._log_activity(
                conn, "renamed", "category", f"{existing['name']} -> {cleaned}"
            )
            row = conn.execute(
                """
                SELECT c.category_id, c.name, c.created_at, c.updated_at,
                       COUNT(f.faq_id) AS faq_count
                FROM faq_categories AS c
                LEFT JOIN faqs AS f ON f.category_id = c.category_id
                WHERE c.category_id = ?
                GROUP BY c.category_id
                """,
                (int(category_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_category(
        self,
        category_id: int,
        reassign_to_category_id: Optional[int] = None,
    ) -> bool:
        with self.db.transaction() as conn:
            cat = conn.execute(
                "SELECT category_id, name FROM faq_categories WHERE category_id = ?",
                (int(category_id),),
            ).fetchone()
            if cat is None:
                return False

            faq_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM faqs WHERE category_id = ?",
                    (int(category_id),),
                ).fetchone()[0]
            )
            if faq_count > 0:
                if reassign_to_category_id is None:
                    raise ConflictError(
                        f"Category '{cat['name']}' contains {faq_count} FAQ(s). "
                        "Reassign them to another category before deleting."
                    )
                if int(reassign_to_category_id) == int(category_id):
                    raise ValueError("Cannot reassign FAQs to the category being deleted.")
                target = conn.execute(
                    "SELECT category_id FROM faq_categories WHERE category_id = ?",
                    (int(reassign_to_category_id),),
                ).fetchone()
                if target is None:
                    raise ValueError("Target reassignment category does not exist.")
                conn.execute(
                    "UPDATE faqs SET category_id = ?, updated_at = ? WHERE category_id = ?",
                    (int(reassign_to_category_id), _utc_now_iso(), int(category_id)),
                )

            conn.execute(
                "DELETE FROM faq_categories WHERE category_id = ?",
                (int(category_id),),
            )
            self._log_activity(conn, "deleted", "category", cat["name"])
        return True

    # ------------------------------------------------------------------
    # FAQs & Alternative Phrasings CRUD
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_alternatives(
        alternatives: Any, canonical_question: str
    ) -> List[str]:
        if alternatives is None:
            return []
        if not isinstance(alternatives, list):
            raise ValueError("alternative_questions must be a list of strings.")
        cleaned: List[str] = []
        seen = {canonical_question.lower()}
        for item in alternatives:
            if not isinstance(item, str):
                raise ValueError("Each alternative question must be a string.")
            text = item.strip()
            if not text:
                continue
            low = text.lower()
            if low in seen:
                continue
            seen.add(low)
            cleaned.append(text)
        return cleaned

    def list_faqs(
        self, search: str = "", category_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        where_clauses: List[str] = []
        params: List[Any] = []

        if category_id is not None:
            where_clauses.append("f.category_id = ?")
            params.append(int(category_id))

        cleaned_search = search.strip() if isinstance(search, str) else ""
        if cleaned_search:
            escaped = (
                cleaned_search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            where_clauses.append(
                "(LOWER(f.question) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(f.answer) LIKE LOWER(?) ESCAPE '\\' "
                "OR EXISTS (SELECT 1 FROM faq_alternatives AS a "
                "WHERE a.faq_id = f.faq_id AND LOWER(a.question) LIKE LOWER(?) ESCAPE '\\'))"
            )
            params.extend([pattern, pattern, pattern])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self.db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT f.faq_id, f.category_id, c.name AS category,
                       f.question, f.answer, f.created_at, f.updated_at,
                       COUNT(a.alt_id) AS alternative_count
                FROM faqs AS f
                JOIN faq_categories AS c ON c.category_id = f.category_id
                LEFT JOIN faq_alternatives AS a ON a.faq_id = f.faq_id
                {where_sql}
                GROUP BY f.faq_id
                ORDER BY f.faq_id ASC
                """,
                tuple(params),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_faq(self, faq_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT f.faq_id, f.category_id, c.name AS category,
                       f.question, f.answer, f.created_at, f.updated_at
                FROM faqs AS f
                JOIN faq_categories AS c ON c.category_id = f.category_id
                WHERE f.faq_id = ?
                """,
                (int(faq_id),),
            ).fetchone()
            if row is None:
                return None
            alt_rows = conn.execute(
                """
                SELECT alt_id, question, created_at, updated_at
                FROM faq_alternatives
                WHERE faq_id = ?
                ORDER BY alt_id ASC
                """,
                (int(faq_id),),
            ).fetchall()
        result = dict(row)
        result["alternative_questions"] = [dict(a) for a in alt_rows]
        return result

    def create_faq(
        self,
        question: str,
        answer: str,
        category_id: int,
        alternative_questions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        q_clean = question.strip() if isinstance(question, str) else ""
        a_clean = answer.strip() if isinstance(answer, str) else ""
        if not q_clean:
            raise ValueError("FAQ question cannot be empty.")
        if not a_clean:
            raise ValueError("FAQ answer cannot be empty.")

        alts_clean = self._clean_alternatives(alternative_questions, q_clean)
        now_iso = _utc_now_iso()

        with self.db.transaction() as conn:
            cat = conn.execute(
                "SELECT category_id, name FROM faq_categories WHERE category_id = ?",
                (int(category_id),),
            ).fetchone()
            if cat is None:
                raise ValueError("Selected FAQ category does not exist.")

            dup = conn.execute(
                "SELECT faq_id FROM faqs WHERE question = ? COLLATE NOCASE",
                (q_clean,),
            ).fetchone()
            if dup is not None:
                raise ConflictError("An FAQ with this exact question already exists.")

            cur = conn.execute(
                """
                INSERT INTO faqs (category_id, question, answer, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(category_id), q_clean, a_clean, now_iso, now_iso),
            )
            new_id = int(cur.lastrowid)

            for alt_text in alts_clean:
                conn.execute(
                    """
                    INSERT INTO faq_alternatives (faq_id, question, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (new_id, alt_text, now_iso, now_iso),
                )
            self._log_activity(conn, "created", "faq", q_clean)

        created = self.get_faq(new_id)
        assert created is not None
        return created

    def update_faq(
        self,
        faq_id: int,
        question: Optional[str] = None,
        answer: Optional[str] = None,
        category_id: Optional[int] = None,
        alternative_questions: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT faq_id, category_id, question, answer FROM faqs WHERE faq_id = ?",
                (int(faq_id),),
            ).fetchone()
            if existing is None:
                return None

            new_q = (
                question.strip()
                if question is not None and isinstance(question, str)
                else existing["question"]
            )
            new_a = (
                answer.strip()
                if answer is not None and isinstance(answer, str)
                else existing["answer"]
            )
            new_cat_id = (
                int(category_id)
                if category_id is not None
                else int(existing["category_id"])
            )

            if not new_q:
                raise ValueError("FAQ question cannot be empty.")
            if not new_a:
                raise ValueError("FAQ answer cannot be empty.")

            cat = conn.execute(
                "SELECT category_id FROM faq_categories WHERE category_id = ?",
                (new_cat_id,),
            ).fetchone()
            if cat is None:
                raise ValueError("Selected FAQ category does not exist.")

            dup = conn.execute(
                """
                SELECT faq_id FROM faqs
                WHERE question = ? COLLATE NOCASE AND faq_id != ?
                """,
                (new_q, int(faq_id)),
            ).fetchone()
            if dup is not None:
                raise ConflictError("Another FAQ with this exact question already exists.")

            conn.execute(
                """
                UPDATE faqs
                SET category_id = ?, question = ?, answer = ?, updated_at = ?
                WHERE faq_id = ?
                """,
                (new_cat_id, new_q, new_a, now_iso, int(faq_id)),
            )

            if alternative_questions is not None:
                alts_clean = self._clean_alternatives(alternative_questions, new_q)
                conn.execute(
                    "DELETE FROM faq_alternatives WHERE faq_id = ?",
                    (int(faq_id),),
                )
                for alt_text in alts_clean:
                    conn.execute(
                        """
                        INSERT INTO faq_alternatives (faq_id, question, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (int(faq_id), alt_text, now_iso, now_iso),
                    )

            self._log_activity(conn, "updated", "faq", new_q)

        return self.get_faq(int(faq_id))

    def delete_faq(self, faq_id: int) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT faq_id, question FROM faqs WHERE faq_id = ?",
                (int(faq_id),),
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM faqs WHERE faq_id = ?", (int(faq_id),))
            self._log_activity(conn, "deleted", "faq", row["question"])
        return True


class UnansweredRepository:
    """SQLite repository for tracking and reviewing unresolved student queries."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def record_unanswered(
        self,
        query_text: str,
        conversation_id: Optional[str],
        match_type: str,
    ) -> Optional[int]:
        if match_type not in {"no_reliable_match", "ambiguous_match"}:
            return None
        cleaned = redact_sensitive_text(query_text).strip()
        if not cleaned:
            return None

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            existing = conn.execute(
                """
                SELECT item_id, occurrence_count
                FROM unanswered_questions
                WHERE query_text = ? COLLATE NOCASE
                  AND status = 'unreviewed'
                LIMIT 1
                """,
                (cleaned,),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """
                    UPDATE unanswered_questions
                    SET occurrence_count = occurrence_count + 1,
                        match_type = ?,
                        conversation_id = COALESCE(?, conversation_id),
                        updated_at = ?
                    WHERE item_id = ?
                    """,
                    (match_type, conversation_id, now_iso, int(existing["item_id"])),
                )
                return int(existing["item_id"])

            cur = conn.execute(
                """
                INSERT INTO unanswered_questions (
                    query_text, conversation_id, match_type,
                    occurrence_count, status, review_notes, created_at, updated_at
                ) VALUES (?, ?, ?, 1, 'unreviewed', NULL, ?, ?)
                """,
                (cleaned, conversation_id, match_type, now_iso, now_iso),
            )
            return int(cur.lastrowid)

    def list_unanswered(
        self, search: str = "", status: str = ""
    ) -> List[Dict[str, Any]]:
        where_clauses: List[str] = []
        params: List[Any] = []

        cleaned_status = status.strip().lower() if isinstance(status, str) else ""
        if cleaned_status:
            if cleaned_status not in VALID_UNANSWERED_STATUSES:
                raise ValueError("Invalid status filter.")
            where_clauses.append("status = ?")
            params.append(cleaned_status)

        cleaned_search = search.strip() if isinstance(search, str) else ""
        if cleaned_search:
            escaped = (
                cleaned_search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            where_clauses.append("LOWER(query_text) LIKE LOWER(?) ESCAPE '\\'")
            params.append(f"%{escaped}%")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self.db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT item_id, query_text, conversation_id, match_type,
                       occurrence_count, status, review_notes,
                       created_at, updated_at
                FROM unanswered_questions
                {where_sql}
                ORDER BY updated_at DESC, item_id DESC
                LIMIT 200
                """,
                tuple(params),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_unanswered(
        self,
        item_id: int,
        status: Optional[str] = None,
        review_notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if status is not None and status not in VALID_UNANSWERED_STATUSES:
            raise ValueError(
                f"Status must be one of: {', '.join(sorted(VALID_UNANSWERED_STATUSES))}."
            )

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT item_id, status, review_notes FROM unanswered_questions WHERE item_id = ?",
                (int(item_id),),
            ).fetchone()
            if existing is None:
                return None

            new_status = status if status is not None else existing["status"]
            new_notes = (
                review_notes.strip()
                if isinstance(review_notes, str)
                else existing["review_notes"]
            )
            conn.execute(
                """
                UPDATE unanswered_questions
                SET status = ?, review_notes = ?, updated_at = ?
                WHERE item_id = ?
                """,
                (new_status, new_notes, now_iso, int(item_id)),
            )
            row = conn.execute(
                """
                SELECT item_id, query_text, conversation_id, match_type,
                       occurrence_count, status, review_notes,
                       created_at, updated_at
                FROM unanswered_questions
                WHERE item_id = ?
                """,
                (int(item_id),),
            ).fetchone()
        return dict(row) if row is not None else None


__all__ = [
    "AdminAuthRepository",
    "ConflictError",
    "DEFAULT_FAQ_JSON_PATH",
    "KnowledgeBaseRepository",
    "UnansweredRepository",
    "VALID_UNANSWERED_STATUSES",
]
