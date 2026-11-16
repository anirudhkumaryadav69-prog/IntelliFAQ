"""
Dedicated SQLite Persistence & Repository Test Suite for IntelliFAQ 2.0.

Uses temporary SQLite database files only (never modifies the development DB)
to verify all 17 required database scenarios:
 1. Database initialization
 2. New conversation creation
 3. Saving user messages
 4. Saving assistant messages
 5. Retrieving conversation snapshots
 6. Persistence after closing and reopening the database connection
 7. Persistence after recreating the Flask application using the same database file
 8. Restoring resolved FAQ context
 9. Restoring pending clarification candidates
10. Saving and retrieving multi-intent sub-responses
11. Conversation isolation
12. Resetting one conversation without affecting another
13. Unknown conversation handling
14. Invalid UUID handling
15. Foreign-key integrity
16. Database transaction rollback on failure
17. Sensitive-data redaction
"""

import importlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import uuid

import app as backend_app
from database import (
    SCHEMA_VERSION,
    ConversationRepository,
    Database,
    DatabaseError,
    redact_sensitive_text,
)
from nlp.chatbot import MATCH_AMBIGUOUS, MATCH_CLEAR, MATCH_NONE


def run_database_tests() -> None:
    """Execute all 17 SQLite persistence verification scenarios."""
    passed = 0
    total = 17

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # -----------------------------------------------------------------
        # 1. Database initialization
        # -----------------------------------------------------------------
        db_file = tmp_path / "test_conv.db"
        db = Database(db_file)
        db.initialize()
        assert db.is_initialized is True
        assert db.health_check() is True
        assert db_file.exists()
        with db.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert version == SCHEMA_VERSION
        assert {"conversations", "messages"}.issubset(tables)
        passed += 1

        # -----------------------------------------------------------------
        # 2. New conversation creation
        # -----------------------------------------------------------------
        repo = ConversationRepository(db)
        conv1 = repo.create_conversation(max_conversations=50)
        conv_id_1 = conv1["conversation_id"]
        assert str(uuid.UUID(conv_id_1)) == conv_id_1
        assert conv1["is_active"] is True
        assert conv1["history"] == []
        assert conv1["pending_candidates"] == []
        passed += 1

        # -----------------------------------------------------------------
        # 3 & 4. Saving user messages & saving assistant messages
        # -----------------------------------------------------------------
        ok = repo.record_exchange(
            conv_id_1,
            "What are the admission requirements?",
            {
                "match_type": MATCH_CLEAR,
                "faq_id": 1,
                "matched_question": "What are the admission requirements for undergraduate programs?",
                "category": "Admissions",
                "confidence": 92.5,
                "answer": "Completion of higher secondary education.",
                "fallback": False,
                "needs_clarification": False,
                "candidates": [
                    {
                        "faq_id": 1,
                        "question": "What are the admission requirements for undergraduate programs?",
                        "category": "Admissions",
                        "similarity": 92.5,
                    }
                ],
                "is_multi_intent": False,
                "sub_responses": [],
            },
            max_stored_exchanges=50,
        )
        assert ok is True
        stored_msgs = repo.get_messages(conv_id_1)
        assert len(stored_msgs) == 2
        assert stored_msgs[0]["role"] == "user"
        assert stored_msgs[0]["message_text"] == "What are the admission requirements?"
        passed += 1  # 3. Saving user messages

        assert stored_msgs[1]["role"] == "assistant"
        assert stored_msgs[1]["faq_id"] == 1
        assert stored_msgs[1]["category"] == "Admissions"
        assert stored_msgs[1]["reply_to_message_id"] == stored_msgs[0]["message_id"]
        passed += 1  # 4. Saving assistant messages

        # -----------------------------------------------------------------
        # 5. Retrieving conversation snapshots (independent dict snapshots)
        # -----------------------------------------------------------------
        snap1 = repo.get_conversation(conv_id_1, history_limit=10)
        assert snap1 is not None
        assert len(snap1["history"]) == 1
        snap1["last_category"] = "MutatedLocally"
        snap2 = repo.get_conversation(conv_id_1, history_limit=10)
        assert snap2 is not None
        assert snap2["last_category"] == "Admissions"
        passed += 1

        # -----------------------------------------------------------------
        # 6. Persistence after closing and reopening the database connection
        # -----------------------------------------------------------------
        reopened_db = Database(db_file)
        reopened_repo = ConversationRepository(reopened_db)
        reopened_snap = reopened_repo.get_conversation(conv_id_1, history_limit=10)
        assert reopened_snap is not None
        assert reopened_snap["last_faq_id"] == 1
        assert reopened_snap["last_category"] == "Admissions"
        assert len(reopened_snap["history"]) == 1
        passed += 1

        # -----------------------------------------------------------------
        # 7. Persistence after recreating the Flask app using the same DB file
        # -----------------------------------------------------------------
        restart_db_file = tmp_path / "restart_app.db"
        prev_env = os.environ.get("INTELLIFAQ_DB_PATH")
        try:
            os.environ["INTELLIFAQ_DB_PATH"] = str(restart_db_file)
            reloaded_app = importlib.reload(backend_app)
            client1 = reloaded_app.app.test_client()

            r_turn1 = client1.post(
                "/api/chat",
                json={"message": "How can I apply for admission online?"},
            )
            assert r_turn1.status_code == 200
            d_turn1 = r_turn1.get_json()
            persisted_cid = d_turn1["conversation_id"]
            assert d_turn1["category"] == "Admissions"

            # Simulate full Flask process restart by reloading app against same DB
            reloaded_app_2 = importlib.reload(reloaded_app)
            client2 = reloaded_app_2.app.test_client()

            r_turn2 = client2.post(
                "/api/chat",
                json={
                    "message": "What documents do I need?",
                    "conversation_id": persisted_cid,
                },
            )
            assert r_turn2.status_code == 200
            d_turn2 = r_turn2.get_json()
            assert d_turn2["conversation_id"] == persisted_cid
            assert d_turn2["category"] == "Admissions"
            assert d_turn2["faq_id"] == 3
        finally:
            if prev_env is None:
                os.environ.pop("INTELLIFAQ_DB_PATH", None)
            else:
                os.environ["INTELLIFAQ_DB_PATH"] = prev_env
            importlib.reload(backend_app)
        passed += 1

        # -----------------------------------------------------------------
        # 8. Restoring resolved FAQ context
        # -----------------------------------------------------------------
        assert reopened_snap["last_faq_id"] == 1
        assert (
            reopened_snap["last_question"]
            == "What are the admission requirements for undergraduate programs?"
        )
        assert reopened_snap["last_category"] == "Admissions"
        passed += 1

        # -----------------------------------------------------------------
        # 9. Restoring pending clarification candidates
        # -----------------------------------------------------------------
        candidates_payload = [
            {
                "faq_id": 60,
                "question": "What types of scholarships are available?",
                "category": "Scholarships",
                "similarity": 41.0,
            },
            {
                "faq_id": 61,
                "question": "How do I apply for scholarships?",
                "category": "Scholarships",
                "similarity": 39.5,
            },
        ]
        reopened_repo.record_exchange(
            conv_id_1,
            "scholarship",
            {
                "match_type": MATCH_AMBIGUOUS,
                "faq_id": None,
                "matched_question": None,
                "category": "Scholarships",
                "confidence": 41.0,
                "answer": "Please clarify.",
                "fallback": False,
                "needs_clarification": True,
                "clarification_message": "Did you mean one of these?",
                "candidates": candidates_payload,
                "is_multi_intent": False,
                "sub_responses": [],
            },
            max_stored_exchanges=50,
        )
        after_ambig = reopened_repo.get_conversation(conv_id_1, history_limit=10)
        assert after_ambig is not None
        assert after_ambig["last_faq_id"] == 1  # Prior resolved context preserved
        assert len(after_ambig["pending_candidates"]) == 2
        assert after_ambig["pending_candidates"][0]["faq_id"] == 60
        passed += 1

        # -----------------------------------------------------------------
        # 10. Saving and retrieving multi-intent sub-responses
        # -----------------------------------------------------------------
        conv_mi = reopened_repo.create_conversation(max_conversations=50)
        mi_cid = conv_mi["conversation_id"]
        sub_responses_payload = [
            {
                "query": "Tell me about hostel facilities",
                "answer": "Hostel accommodation is available.",
                "matched_question": "How can I apply for hostel?",
                "category": "Campus Facilities",
                "confidence": 56.2,
                "faq_id": 75,
                "fallback": False,
                "match_type": MATCH_CLEAR,
                "candidates": [],
                "needs_clarification": False,
                "clarification_message": None,
            },
            {
                "query": "What is the examination timetable?",
                "answer": "Timetables are published on the portal.",
                "matched_question": "Where can I check the examination timetable?",
                "category": "Examinations",
                "confidence": 41.2,
                "faq_id": 45,
                "fallback": False,
                "match_type": MATCH_CLEAR,
                "candidates": [],
                "needs_clarification": False,
                "clarification_message": None,
            },
        ]
        reopened_repo.record_exchange(
            mi_cid,
            "Tell me about hostel facilities and examination timetables.",
            {
                "match_type": MATCH_CLEAR,
                "faq_id": 75,
                "matched_question": "How can I apply for hostel?",
                "category": "Examinations",
                "confidence": 48.7,
                "answer": "Combined answer",
                "fallback": False,
                "needs_clarification": False,
                "candidates": [],
                "is_multi_intent": True,
                "sub_responses": sub_responses_payload,
            },
            max_stored_exchanges=50,
        )
        mi_snap = reopened_repo.get_conversation(mi_cid, history_limit=10)
        assert mi_snap is not None
        assert mi_snap["history"][0]["is_multi_intent"] is True
        assert len(mi_snap["history"][0]["sub_responses"]) == 2
        assert mi_snap["history"][0]["sub_responses"][1]["faq_id"] == 45
        assert mi_snap["last_faq_id"] == 45  # Last clear sub-answer adopted
        passed += 1

        # -----------------------------------------------------------------
        # 11. Conversation isolation
        # -----------------------------------------------------------------
        assert reopened_repo.get_conversation(conv_id_1, 10)["last_category"] == "Admissions"
        assert reopened_repo.get_conversation(mi_cid, 10)["last_category"] == "Examinations"
        passed += 1

        # -----------------------------------------------------------------
        # 12. Resetting one conversation without affecting another
        # -----------------------------------------------------------------
        assert reopened_repo.reset_conversation(conv_id_1) is True
        assert reopened_repo.reset_conversation(conv_id_1) is False  # Repeated reset safe
        assert reopened_repo.get_conversation(conv_id_1, 10) is None
        assert reopened_repo.get_messages(conv_id_1) == []
        assert reopened_repo.get_conversation(mi_cid, 10) is not None
        passed += 1

        # -----------------------------------------------------------------
        # 13. Unknown conversation handling
        # -----------------------------------------------------------------
        unknown_uuid = str(uuid.uuid4())
        assert reopened_repo.get_conversation(unknown_uuid, 10) is None
        assert (
            reopened_repo.record_exchange(
                unknown_uuid,
                "hello",
                {"match_type": MATCH_NONE},
                max_stored_exchanges=50,
            )
            is False
        )
        assert reopened_repo.reset_conversation(unknown_uuid) is False
        passed += 1

        # -----------------------------------------------------------------
        # 14. Invalid UUID handling
        # -----------------------------------------------------------------
        for bad_id in ("", "   ", "not-a-uuid", "12345", None, 999):
            assert reopened_repo.get_conversation(bad_id, 10) is None
            assert reopened_repo.reset_conversation(bad_id) is False
        passed += 1

        # -----------------------------------------------------------------
        # 15. Foreign-key integrity
        # -----------------------------------------------------------------
        fk_failed = False
        try:
            with reopened_db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, message_text, created_at)
                    VALUES (?, 'user', 'orphan', '2026-01-01T00:00:00Z')
                    """,
                    (str(uuid.uuid4()),),
                )
        except DatabaseError:
            fk_failed = True
        assert fk_failed is True
        passed += 1

        # -----------------------------------------------------------------
        # 16. Database transaction rollback on failure
        # -----------------------------------------------------------------
        before_count = reopened_repo.count_conversations(active_only=False)
        rollback_triggered = False
        try:
            with reopened_db.transaction() as conn:
                bad_cid = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id, created_at, updated_at,
                        pending_candidates, is_active, last_activity_seq
                    ) VALUES (?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '[]', 1, 999)
                    """,
                    (bad_cid,),
                )
                # Force a constraint error inside the same transaction
                conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, message_text, created_at)
                    VALUES (?, 'invalid_role', 'fail', '2026-01-01T00:00:00Z')
                    """,
                    (bad_cid,),
                )
        except DatabaseError:
            rollback_triggered = True
        assert rollback_triggered is True
        assert reopened_repo.count_conversations(active_only=False) == before_count
        passed += 1

        # -----------------------------------------------------------------
        # 17. Sensitive-data redaction
        # -----------------------------------------------------------------
        sample_secret = (
            "my password is superSecret99 and api_key: sk-1234567890abcdef1234 "
            "and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        )
        redacted = redact_sensitive_text(sample_secret)
        assert "superSecret99" not in redacted
        assert "sk-1234567890abcdef1234" not in redacted
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
        assert "[REDACTED]" in redacted
        passed += 1

    print("=" * 82)
    print(f"DATABASE TEST SUITE SUMMARY: {passed} / {total} SCENARIOS PASSED")
    print("=" * 82)


def test_database_suite() -> None:
    """Entrypoint for pytest/unittest runners."""
    run_database_tests()


if __name__ == "__main__":
    run_database_tests()
