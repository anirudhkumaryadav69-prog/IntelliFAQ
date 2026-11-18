"""
Automated tests for Phase 3 Dual-Database (SQLite + PostgreSQL),
Production Admin Bootstrap, Supabase Storage Abstraction, and Health Diagnostics.

Uses isolated temporary directories/databases and mocked PostgreSQL / Supabase
clients so the local `backend/instance/intellifaq.db` and real Supabase project
are never touched.
"""

from contextlib import contextmanager
from datetime import date, datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as flask_app_module
from database.db import (
    EXPECTED_TABLES,
    PG_MIGRATION_PATH,
    SCHEMA_VERSION,
    Database,
    DatabaseError,
    _CompatRow,
    _translate_placeholders,
)
from database.kb_repository import AdminAuthRepository, KnowledgeBaseRepository
from services.storage import (
    LocalDocumentStorage,
    StorageError,
    SupabaseDocumentStorage,
    get_document_storage,
)


class TestDualDatabaseAndStorage(unittest.TestCase):
    def test_01_translate_placeholders_preserves_quoted_literals(self) -> None:
        sql = "SELECT * FROM faqs WHERE question = ? AND note = 'why?' AND pct = '100%'"
        translated = _translate_placeholders(sql, has_params=True)
        self.assertEqual(
            translated,
            "SELECT * FROM faqs WHERE question = %s AND note = 'why?' AND pct = '100%'",
        )
        sql_with_pct = "SELECT 100%10, name FROM faq_categories WHERE LOWER(name) = LOWER(?)"
        self.assertEqual(
            _translate_placeholders(sql_with_pct, has_params=True),
            "SELECT 100%%10, name FROM faq_categories WHERE LOWER(name) = LOWER(%s)",
        )

    def test_02_compat_row_supports_dict_index_and_iso_dates(self) -> None:
        now = datetime(2026, 11, 16, 12, 30, tzinfo=timezone.utc)
        today = date(2026, 11, 16)
        row = _CompatRow({"id": 42, "created_at": now, "effective_date": today})
        self.assertEqual(row["id"], 42)
        self.assertEqual(row[0], 42)
        self.assertEqual(row["created_at"], now.isoformat())
        self.assertEqual(row["effective_date"], "2026-11-16")

    def test_03_sqlite_default_when_database_url_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "local_test.db"
            db = Database(path=db_path)
            self.assertEqual(db.backend, "sqlite")
            db.initialize()
            self.assertTrue(db.health_check())

    def test_04_postgresql_selected_when_database_url_configured(self) -> None:
        prev = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/testdb"
            db = Database()
            self.assertEqual(db.backend, "postgresql")
            # Explicit SQLite path still overrides env DATABASE_URL for local tests
            with tempfile.TemporaryDirectory() as tmpdir:
                sqlite_db = Database(path=Path(tmpdir) / "override.db")
                self.assertEqual(sqlite_db.backend, "sqlite")
        finally:
            if prev is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = prev

    def test_05_postgresql_migration_file_contains_all_tables_and_rls(self) -> None:
        self.assertTrue(PG_MIGRATION_PATH.exists())
        sql_text = PG_MIGRATION_PATH.read_text(encoding="utf-8")
        for table in EXPECTED_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql_text)
            self.assertIn(f"ALTER TABLE {table}", sql_text)
            self.assertIn("ENABLE ROW LEVEL SECURITY", sql_text)
        self.assertIn("schema_migrations", sql_text)
        self.assertIn("uq_admin_users_username_lower", sql_text)
        self.assertIn("uq_faq_categories_name_lower", sql_text)

    def test_06_postgresql_initialization_and_health_check_mocked(self) -> None:
        init_cursor = MagicMock()
        init_cursor.fetchone.return_value = (SCHEMA_VERSION,)

        query_cursor = MagicMock()
        query_cursor.fetchone.return_value = {"?column?": 1}
        query_cursor.fetchall.return_value = [
            {"table_name": t} for t in sorted(EXPECTED_TABLES)
        ]

        mock_pg_conn = MagicMock()
        mock_pg_conn.cursor.return_value = query_cursor
        mock_pg_conn.cursor.return_value.__enter__.return_value = init_cursor

        with patch("database.db.psycopg") as mock_psycopg:
            mock_psycopg.Error = RuntimeError
            mock_psycopg.OperationalError = RuntimeError
            mock_psycopg.connect.return_value = mock_pg_conn

            db = Database(database_url="postgresql://user:pass@localhost:5432/testdb")
            db.initialize()
            self.assertTrue(db.is_initialized)
            self.assertTrue(db.health_check())
            executed_sql = " ".join(
                call.args[0] for call in query_cursor.execute.call_args_list
            )
            self.assertIn("information_schema.tables", executed_sql)
            self.assertNotIn("sqlite_master", executed_sql)

    def test_07_postgresql_insert_returning_id_and_reset_sequence(self) -> None:
        db = Database(database_url="postgresql://user:pass@localhost:5432/testdb")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = _CompatRow({"faq_id": 101})

        new_id = db.insert_returning_id(
            mock_conn,
            "INSERT INTO faqs (category_id, question, answer, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (1, "Q?", "A.", "2026-01-01", "2026-01-01"),
            "faq_id",
        )
        self.assertEqual(new_id, 101)
        sql_sent = mock_conn.execute.call_args[0][0]
        self.assertIn("RETURNING faq_id", sql_sent)

        db.reset_sequence(mock_conn, "faqs", "faq_id")
        seq_sql = mock_conn.execute.call_args[0][0]
        self.assertIn("pg_get_serial_sequence", seq_sql)

    def test_08_production_admin_bootstrap_requires_env_on_postgresql(self) -> None:
        db = Database(database_url="postgresql://user:pass@localhost:5432/testdb")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (0,)

        @contextmanager
        def fake_tx():
            yield mock_conn

        db.transaction = fake_tx  # type: ignore[method-assign]
        repo = AdminAuthRepository(db)

        prev_keys = {
            k: os.environ.pop(k, None)
            for k in (
                "INTELLIFAQ_ADMIN_USERNAME",
                "INTELLIFAQ_ADMIN_PASSWORD",
                "ADMIN_USERNAME",
                "ADMIN_PASSWORD",
            )
        }
        try:
            with self.assertRaises(DatabaseError):
                repo.ensure_initial_admin()

            os.environ["ADMIN_USERNAME"] = "prod_admin"
            os.environ["ADMIN_PASSWORD"] = "StrongProdPass!999"
            generated = repo.ensure_initial_admin()
            self.assertIsNone(generated)
            insert_call = mock_conn.execute.call_args_list[-1]
            self.assertIn("INSERT INTO admin_users", insert_call.args[0])
            self.assertEqual(insert_call.args[1][0], "prod_admin")
            self.assertNotEqual(insert_call.args[1][1], "StrongProdPass!999")
        finally:
            for k, v in prev_keys.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_09_faq_json_contains_100_faqs_300_alts_7_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(path=Path(tmpdir) / "seed_test.db")
            db.initialize()
            kb = KnowledgeBaseRepository(db)
            seeded = kb.seed_from_json_if_empty()
            self.assertTrue(seeded)
            self.assertFalse(kb.seed_from_json_if_empty())  # idempotent
            records = kb.export_for_chatbot()
            self.assertEqual(len(records), 100)
            total_alts = sum(len(r.get("alternative_questions", [])) for r in records)
            self.assertEqual(total_alts, 300)
            categories = {r["category"] for r in records}
            self.assertEqual(len(categories), 7)

    def test_10_local_and_supabase_storage_abstraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local = LocalDocumentStorage(upload_dir=Path(tmpdir))
            local.save("sample.txt", b"hello world", "text/plain")
            self.assertEqual(local.read_bytes("sample.txt"), b"hello world")
            self.assertTrue(local.delete("sample.txt"))
            self.assertIsNone(local.read_bytes("sample.txt"))
            with self.assertRaises(StorageError):
                local.read_bytes("../escape.txt")
            self.assertEqual(local.status()["backend"], "local")

        mock_bucket = MagicMock()
        mock_bucket.download.return_value = b"%PDF-1.4 sample"
        mock_client = MagicMock()
        mock_client.storage.from_.return_value = mock_bucket

        supa = SupabaseDocumentStorage(
            url="https://example.supabase.co",
            service_role_key="service-role-test-placeholder",
            bucket="intellifaq-documents",
            client=mock_client,
        )
        supa.save("abc.pdf", b"%PDF-1.4 sample", "application/pdf")
        mock_bucket.upload.assert_called_once()
        self.assertEqual(supa.read_bytes("abc.pdf"), b"%PDF-1.4 sample")
        self.assertTrue(supa.delete("abc.pdf"))
        mock_bucket.remove.assert_called_once_with(["abc.pdf"])

        status = supa.status()
        self.assertEqual(status, {"backend": "supabase", "configured": True, "bucket": "intellifaq-documents"})
        # Verify status() did not perform any upload/delete
        self.assertEqual(mock_bucket.upload.call_count, 1)
        self.assertEqual(mock_bucket.remove.call_count, 1)

    def test_11_get_document_storage_selection(self) -> None:
        prev_url = os.environ.pop("SUPABASE_URL", None)
        prev_key = os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
        try:
            self.assertIsInstance(get_document_storage(), LocalDocumentStorage)
            os.environ["SUPABASE_URL"] = "https://example.supabase.co"
            os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-key"
            selected = get_document_storage()
            self.assertIsInstance(selected, SupabaseDocumentStorage)
            self.assertEqual(selected.bucket, "intellifaq-documents")
        finally:
            if prev_url is None:
                os.environ.pop("SUPABASE_URL", None)
            else:
                os.environ["SUPABASE_URL"] = prev_url
            if prev_key is None:
                os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
            else:
                os.environ["SUPABASE_SERVICE_ROLE_KEY"] = prev_key

    def test_12_health_endpoint_reports_db_and_storage_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Database(path=Path(tmpdir) / "health_test.db")
            temp_db.initialize()
            orig_db = flask_app_module.conversation_manager.database
            flask_app_module.conversation_manager.database = temp_db
            try:
                with patch.dict(
                    os.environ,
                    {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""},
                    clear=False,
                ):
                    client = flask_app_module.app.test_client()
                    resp = client.get("/api/health")
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertTrue(data["success"])
                self.assertEqual(data["status"], "ok")
                self.assertEqual(data["chatbot_status"], "ready")
                self.assertGreaterEqual(data["faq_count"], 100)
                self.assertTrue(data["database"]["connected"])
                self.assertEqual(data["database"]["backend"], "sqlite")
                self.assertEqual(data["storage"]["backend"], "local")
                # Never expose secrets or connection strings
                serialized = str(data)
                self.assertNotIn("password", serialized.lower())
                self.assertNotIn("service_role", serialized.lower())
            finally:
                flask_app_module.conversation_manager.database = orig_db

    def test_13_reset_sequence_handles_empty_nonempty_and_validates_identifiers(self) -> None:
        db = Database(database_url="postgresql://user:pass@localhost:5432/testdb")

        def simulate_next_id(max_id):
            mock_conn = MagicMock()
            db.reset_sequence(mock_conn, "faqs", "faq_id")
            sql_sent, params = mock_conn.execute.call_args[0]
            self.assertEqual(params, ("faqs", "faq_id"))
            self.assertIn("COALESCE(m.max_id, 1)", sql_sent)
            self.assertIn("m.max_id IS NOT NULL", sql_sent)
            self.assertIn("FROM (SELECT MAX(faq_id) AS max_id FROM faqs) AS m", sql_sent)
            # Simulate PostgreSQL setval(seq, COALESCE(max_id, 1), max_id IS NOT NULL)
            val = 1 if max_id is None else max_id
            is_called = max_id is not None
            return val + 1 if is_called else val

        # Empty table -> next generated ID must be 1
        self.assertEqual(simulate_next_id(None), 1)
        # Non-empty table -> next generated ID must be MAX(id) + 1
        self.assertEqual(simulate_next_id(100), 101)

        # Reject unsafe SQL identifiers
        mock_conn = MagicMock()
        with self.assertRaises(DatabaseError):
            db.reset_sequence(mock_conn, "faqs; DROP TABLE faqs", "faq_id")
        with self.assertRaises(DatabaseError):
            db.reset_sequence(mock_conn, "faqs", "faq_id); --")
        mock_conn.execute.assert_not_called()

    def test_14_proxy_fix_and_https_cookie_creation_deletion(self) -> None:
        from database.kb_repository import AdminAuthRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Database(path=Path(tmpdir) / "cookie_proxy_test.db")
            temp_db.initialize()
            auth_repo = AdminAuthRepository(temp_db)
            auth_repo.ensure_initial_admin(username="admin", password="ProxyCookie!123")
            orig_auth = flask_app_module.admin_auth_repository
            flask_app_module.admin_auth_repository = auth_repo
            try:
                with patch.dict(os.environ, {"INTELLIFAQ_COOKIE_SECURE": ""}, clear=False):
                    client = flask_app_module.app.test_client()
                    login_resp = client.post(
                        "/api/admin/login",
                        json={"username": "admin", "password": "ProxyCookie!123"},
                        headers={
                            "X-Forwarded-Proto": "https",
                            "X-Forwarded-For": "203.0.113.42",
                        },
                    )
                    self.assertEqual(login_resp.status_code, 200)
                    login_cookie = login_resp.headers.get("Set-Cookie", "")
                    self.assertIn("HttpOnly", login_cookie)
                    self.assertIn("Secure", login_cookie)
                    self.assertIn("SameSite=None", login_cookie)
                    self.assertIn("Path=/", login_cookie)

                    csrf_token = login_resp.get_json()["csrf_token"]
                    logout_resp = client.post(
                        "/api/admin/logout",
                        headers={
                            "X-Forwarded-Proto": "https",
                            "X-CSRF-Token": csrf_token,
                        },
                    )
                    self.assertEqual(logout_resp.status_code, 200)
                    logout_cookie = logout_resp.headers.get("Set-Cookie", "")
                    self.assertIn("Secure", logout_cookie)
                    self.assertIn("SameSite=None", logout_cookie)
                    self.assertIn("Path=/", logout_cookie)
            finally:
                flask_app_module.admin_auth_repository = orig_auth

    def test_15_local_http_cookie_and_env_secure_override(self) -> None:
        from database.kb_repository import AdminAuthRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Database(path=Path(tmpdir) / "cookie_local_test.db")
            temp_db.initialize()
            auth_repo = AdminAuthRepository(temp_db)
            auth_repo.ensure_initial_admin(username="admin", password="LocalCookie!123")
            orig_auth = flask_app_module.admin_auth_repository
            flask_app_module.admin_auth_repository = auth_repo
            try:
                with patch.dict(os.environ, {"INTELLIFAQ_COOKIE_SECURE": ""}, clear=False):
                    client = flask_app_module.app.test_client()
                    resp_http = client.post(
                        "/api/admin/login",
                        json={"username": "admin", "password": "LocalCookie!123"},
                    )
                    self.assertEqual(resp_http.status_code, 200)
                    cookie_http = resp_http.headers.get("Set-Cookie", "")
                    self.assertIn("SameSite=Lax", cookie_http)
                    self.assertNotIn("Secure", cookie_http)

                with patch.dict(os.environ, {"INTELLIFAQ_COOKIE_SECURE": "1"}, clear=False):
                    client = flask_app_module.app.test_client()
                    resp_env = client.post(
                        "/api/admin/login",
                        json={"username": "admin", "password": "LocalCookie!123"},
                    )
                    self.assertEqual(resp_env.status_code, 200)
                    cookie_env = resp_env.headers.get("Set-Cookie", "")
                    self.assertIn("Secure", cookie_env)
                    self.assertIn("SameSite=None", cookie_env)
            finally:
                flask_app_module.admin_auth_repository = orig_auth

    def _make_mock_pg_db(self, execute_side_effect):
        db = Database(database_url="postgresql://user:pass@localhost:5432/testdb")
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = execute_side_effect

        @contextmanager
        def fake_tx():
            try:
                yield mock_conn
            except BaseException:
                mock_conn.rollback()
                raise
            mock_conn.commit()

        db.transaction = fake_tx  # type: ignore[method-assign]
        return db, mock_conn

    def _clear_rate_limiters(self) -> None:
        with flask_app_module._login_attempts_lock:
            flask_app_module._failed_login_attempts.clear()
        with flask_app_module._recovery_attempts_lock:
            flask_app_module._failed_recovery_attempts.clear()

    def test_16_admin_recovery_success_advisory_lock_and_no_secret_leak(self) -> None:
        from werkzeug.security import check_password_hash
        from database.kb_repository import AdminAuthRepository

        self._clear_rate_limiters()
        token = "R" * 40
        new_password = "StrongRecoveryPassword!2026"
        executed_sql: list[tuple[str, object]] = []

        def fake_execute(sql, params=None):
            executed_sql.append((sql, params))
            cur = MagicMock()
            normalized = " ".join(sql.split())
            if "FROM admin_activity_log" in normalized:
                cur.fetchone.return_value = None
            elif "SELECT admin_id FROM admin_users WHERE admin_id = ?" in normalized:
                cur.fetchone.return_value = {"admin_id": 1}
            elif "LOWER(username) = LOWER(?)" in normalized:
                cur.fetchone.return_value = None
            elif "UPDATE admin_users" in normalized:
                cur.rowcount = 1
            return cur

        db, mock_conn = self._make_mock_pg_db(fake_execute)
        repo = AdminAuthRepository(db)
        orig_auth = flask_app_module.admin_auth_repository
        flask_app_module.admin_auth_repository = repo
        try:
            with patch.dict(
                os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": token}, clear=False
            ), self.assertLogs(flask_app_module.logger, level="INFO") as captured_logs:
                client = flask_app_module.app.test_client()
                resp = client.post(
                    "/api/admin/recovery",
                    json={"username": "  Anirudh Kumar Yadav  ", "password": new_password},
                    headers={
                        "X-Forwarded-Proto": "https",
                        "X-Admin-Recovery-Token": token,
                    },
                )
        finally:
            flask_app_module.admin_auth_repository = orig_auth

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["admin"], {"admin_id": 1, "username": "Anirudh Kumar Yadav"})
        raw_text = resp.get_data(as_text=True)
        self.assertNotIn(new_password, raw_text)
        self.assertNotIn("pbkdf2", raw_text)
        self.assertNotIn("scrypt", raw_text)
        self.assertNotIn(token, raw_text)

        log_blob = "\n".join(captured_logs.output)
        self.assertNotIn(new_password, log_blob)
        self.assertNotIn(token, log_blob)
        self.assertNotIn("pbkdf2", log_blob)
        self.assertNotIn("scrypt", log_blob)

        # Advisory lock must execute before completion-marker query
        self.assertIn("pg_advisory_xact_lock(918273645)", executed_sql[0][0])
        self.assertIn("FROM admin_activity_log", executed_sql[1][0])

        update_calls = [c for c in executed_sql if "UPDATE admin_users" in c[0]]
        self.assertEqual(len(update_calls), 1)
        stored_hash = update_calls[0][1][1]
        self.assertNotEqual(stored_hash, new_password)
        self.assertTrue(check_password_hash(stored_hash, new_password))

        delete_calls = [c for c in executed_sql if "DELETE FROM admin_sessions" in c[0]]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(delete_calls[0][1], (1,))

        marker_calls = [c for c in executed_sql if "INSERT INTO admin_activity_log" in c[0]]
        self.assertEqual(len(marker_calls), 1)
        self.assertEqual(marker_calls[0][1][:3], ("admin_recovery_completed", "admin_users", "admin_id:1"))

        mock_conn.commit.assert_called_once()
        mock_conn.rollback.assert_not_called()

    def test_17_admin_recovery_auth_gate_https_and_sqlite_refusal(self) -> None:
        from database.kb_repository import AdminAuthRepository

        self._clear_rate_limiters()
        client = flask_app_module.app.test_client()

        # Disabled when secret absent or too short
        with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": ""}, clear=False):
            r_absent = client.post(
                "/api/admin/recovery",
                json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                headers={"X-Forwarded-Proto": "https"},
            )
            self.assertEqual(r_absent.status_code, 404)

        with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": "short"}, clear=False):
            r_short = client.post(
                "/api/admin/recovery",
                json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                headers={"X-Forwarded-Proto": "https", "X-Admin-Recovery-Token": "short"},
            )
            self.assertEqual(r_short.status_code, 404)

        token = "S" * 40
        with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": token}, clear=False):
            # Non-HTTPS rejected
            r_http = client.post(
                "/api/admin/recovery",
                json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                headers={"X-Admin-Recovery-Token": token},
            )
            self.assertEqual(r_http.status_code, 403)

            # Missing token -> 401
            r_missing = client.post(
                "/api/admin/recovery",
                json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                headers={"X-Forwarded-Proto": "https"},
            )
            self.assertEqual(r_missing.status_code, 401)

            # Invalid token -> 401
            r_invalid = client.post(
                "/api/admin/recovery",
                json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                headers={"X-Forwarded-Proto": "https", "X-Admin-Recovery-Token": "wrong" * 8},
            )
            self.assertEqual(r_invalid.status_code, 401)

            # SQLite refused
            with tempfile.TemporaryDirectory() as tmpdir:
                sqlite_db = Database(path=Path(tmpdir) / "sqlite_refusal.db")
                sqlite_db.initialize()
                sqlite_repo = AdminAuthRepository(sqlite_db)
                with self.assertRaises(DatabaseError):
                    sqlite_repo.recover_primary_admin(
                        "Anirudh Kumar Yadav", "StrongRecoveryPassword!2026"
                    )
                orig_auth = flask_app_module.admin_auth_repository
                flask_app_module.admin_auth_repository = sqlite_repo
                try:
                    r_sqlite = client.post(
                        "/api/admin/recovery",
                        json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                        headers={"X-Forwarded-Proto": "https", "X-Admin-Recovery-Token": token},
                    )
                    self.assertEqual(r_sqlite.status_code, 403)
                finally:
                    flask_app_module.admin_auth_repository = orig_auth

    def test_18_admin_recovery_conflict_missing_repeated_and_rollback(self) -> None:
        from database.kb_repository import AdminAuthRepository

        self._clear_rate_limiters()
        token = "T" * 40
        client = flask_app_module.app.test_client()
        orig_auth = flask_app_module.admin_auth_repository

        try:
            # 1. Repeated use -> 410
            def exec_already_used(sql, params=None):
                cur = MagicMock()
                if "FROM admin_activity_log" in sql:
                    cur.fetchone.return_value = (1,)
                return cur

            db_used, _ = self._make_mock_pg_db(exec_already_used)
            flask_app_module.admin_auth_repository = AdminAuthRepository(db_used)
            with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": token}, clear=False):
                r_used = client.post(
                    "/api/admin/recovery",
                    json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                    headers={"X-Forwarded-Proto": "https", "X-Admin-Recovery-Token": token},
                )
            self.assertEqual(r_used.status_code, 410)

            # 2. Missing admin_id = 1 -> 404
            def exec_missing_admin(sql, params=None):
                cur = MagicMock()
                normalized = " ".join(sql.split())
                if "FROM admin_activity_log" in normalized:
                    cur.fetchone.return_value = None
                elif "SELECT admin_id FROM admin_users WHERE admin_id = ?" in normalized:
                    cur.fetchone.return_value = None
                return cur

            db_missing, _ = self._make_mock_pg_db(exec_missing_admin)
            flask_app_module.admin_auth_repository = AdminAuthRepository(db_missing)
            with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": token}, clear=False):
                r_missing = client.post(
                    "/api/admin/recovery",
                    json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                    headers={"X-Forwarded-Proto": "https", "X-Admin-Recovery-Token": token},
                )
            self.assertEqual(r_missing.status_code, 404)

            # 3. Username conflict -> 409
            def exec_conflict(sql, params=None):
                cur = MagicMock()
                normalized = " ".join(sql.split())
                if "FROM admin_activity_log" in normalized:
                    cur.fetchone.return_value = None
                elif "SELECT admin_id FROM admin_users WHERE admin_id = ?" in normalized:
                    cur.fetchone.return_value = {"admin_id": 1}
                elif "LOWER(username) = LOWER(?)" in normalized:
                    cur.fetchone.return_value = {"admin_id": 2}
                return cur

            db_conflict, _ = self._make_mock_pg_db(exec_conflict)
            flask_app_module.admin_auth_repository = AdminAuthRepository(db_conflict)
            with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": token}, clear=False):
                r_conflict = client.post(
                    "/api/admin/recovery",
                    json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                    headers={"X-Forwarded-Proto": "https", "X-Admin-Recovery-Token": token},
                )
            self.assertEqual(r_conflict.status_code, 409)

            # 4. Failed DB operation causes rollback -> 500
            def exec_fail_on_delete(sql, params=None):
                cur = MagicMock()
                normalized = " ".join(sql.split())
                if "FROM admin_activity_log" in normalized:
                    cur.fetchone.return_value = None
                elif "SELECT admin_id FROM admin_users WHERE admin_id = ?" in normalized:
                    cur.fetchone.return_value = {"admin_id": 1}
                elif "LOWER(username) = LOWER(?)" in normalized:
                    cur.fetchone.return_value = None
                elif "UPDATE admin_users" in normalized:
                    cur.rowcount = 1
                elif "DELETE FROM admin_sessions" in normalized:
                    raise DatabaseError("Simulated session delete failure")
                return cur

            db_fail, mock_conn_fail = self._make_mock_pg_db(exec_fail_on_delete)
            flask_app_module.admin_auth_repository = AdminAuthRepository(db_fail)
            with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": token}, clear=False):
                r_fail = client.post(
                    "/api/admin/recovery",
                    json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                    headers={"X-Forwarded-Proto": "https", "X-Admin-Recovery-Token": token},
                )
            self.assertEqual(r_fail.status_code, 500)
            mock_conn_fail.rollback.assert_called_once()
            mock_conn_fail.commit.assert_not_called()
        finally:
            flask_app_module.admin_auth_repository = orig_auth

    def test_19_recovery_rate_limit_isolated_from_admin_login(self) -> None:
        from database.kb_repository import AdminAuthRepository

        self._clear_rate_limiters()
        token = "U" * 40
        client = flask_app_module.app.test_client()

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Database(path=Path(tmpdir) / "rate_limit_isolation.db")
            temp_db.initialize()
            auth_repo = AdminAuthRepository(temp_db)
            auth_repo.ensure_initial_admin(username="admin", password="ValidLoginPass!123")
            orig_auth = flask_app_module.admin_auth_repository
            flask_app_module.admin_auth_repository = auth_repo
            try:
                with patch.dict(os.environ, {"INTELLIFAQ_ADMIN_RECOVERY_TOKEN": token}, clear=False):
                    for _ in range(5):
                        r_bad = client.post(
                            "/api/admin/recovery",
                            json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                            headers={
                                "X-Forwarded-Proto": "https",
                                "X-Admin-Recovery-Token": "bad" * 12,
                                "X-Forwarded-For": "198.51.100.10",
                            },
                        )
                        self.assertEqual(r_bad.status_code, 401)

                    r_limited = client.post(
                        "/api/admin/recovery",
                        json={"username": "Anirudh Kumar Yadav", "password": "StrongRecoveryPassword!2026"},
                        headers={
                            "X-Forwarded-Proto": "https",
                            "X-Admin-Recovery-Token": token,
                            "X-Forwarded-For": "198.51.100.10",
                        },
                    )
                    self.assertEqual(r_limited.status_code, 429)

                    # Normal admin login from the same IP must NOT be rate-limited
                    r_login = client.post(
                        "/api/admin/login",
                        json={"username": "admin", "password": "ValidLoginPass!123"},
                        headers={"X-Forwarded-For": "198.51.100.10"},
                    )
                    self.assertEqual(r_login.status_code, 200)
            finally:
                flask_app_module.admin_auth_repository = orig_auth
                self._clear_rate_limiters()


if __name__ == "__main__":
    unittest.main(verbosity=2)
