"""
Automated Test Suite for Prompt 16: Admin Dashboard, Authentication,
FAQ Knowledge Base Management, Dynamic NLP Refresh & Unanswered Tracking.

Uses temporary SQLite databases only (never modifies the development DB)
and tests all 30 required scenarios from Section 14.
"""

import importlib
import os
from pathlib import Path
import tempfile

import app as backend_app
from database import (
    AdminAuthRepository,
    ConversationRepository,
    Database,
    DocumentRepository,
    KnowledgeBaseRepository,
    UnansweredRepository,
)
from nlp.document_retriever import DocumentRetriever


def _setup_isolated_env(db_path: Path):
    db = Database(db_path)
    db.initialize()
    conv_mgr = backend_app.ConversationManager(database=db)
    kb_repo = KnowledgeBaseRepository(db)
    auth_repo = AdminAuthRepository(db)
    unans_repo = UnansweredRepository(db)
    doc_repo = DocumentRepository(db)

    kb_repo.seed_from_json_if_empty()
    auth_repo.ensure_initial_admin(username="admin", password="TestAdmin!Password123")

    backend_app.conversation_manager = conv_mgr
    backend_app.kb_repository = kb_repo
    backend_app.admin_auth_repository = auth_repo
    backend_app.unanswered_repository = unans_repo
    backend_app.document_repository = doc_repo
    backend_app.document_retriever = DocumentRetriever(
        preprocessor=(
            backend_app.chatbot.preprocessor if backend_app.chatbot else None
        )
    )
    backend_app.refresh_chatbot_index()
    backend_app.refresh_document_index()
    return db, conv_mgr, kb_repo, auth_repo, unans_repo


def run_admin_tests() -> None:
    """Execute all 30 Prompt 16 automated scenarios."""
    passed = 0
    total = 30

    with tempfile.TemporaryDirectory() as tmp_dir:
        orig_mgr = backend_app.conversation_manager
        orig_kb = backend_app.kb_repository
        orig_auth = backend_app.admin_auth_repository
        orig_unans = backend_app.unanswered_repository
        orig_doc_repo = backend_app.document_repository
        orig_doc_retriever = backend_app.document_retriever
        try:
            test_db = Path(tmp_dir) / "test_admin.db"
            db, conv_mgr, kb_repo, auth_repo, unans_repo = _setup_isolated_env(test_db)
            client = backend_app.app.test_client()

            # ---------------------------------------------------------
            # 27. Preserve existing 100 FAQs, 300 alternatives, 7 categories
            # ---------------------------------------------------------
            stats = kb_repo.get_dashboard_stats()
            assert stats["total_faqs"] == 100
            assert stats["total_categories"] == 7
            assert stats["total_alternatives"] == 300
            passed += 1  # #27

            # Create a student conversation beforehand to verify #28 later
            conv_before = client.post(
                "/api/chat", json={"message": "How can I pay my semester fees?"}
            ).get_json()["conversation_id"]

            # ---------------------------------------------------------
            # 3. Unauthenticated admin API access rejected (401)
            # ---------------------------------------------------------
            assert client.get("/api/admin/dashboard").status_code == 401
            assert client.get("/api/admin/faqs").status_code == 401
            assert client.post("/api/admin/faqs", json={}).status_code == 401
            passed += 1  # #3

            # ---------------------------------------------------------
            # 2. Invalid credentials rejected (401)
            # ---------------------------------------------------------
            r_bad = client.post(
                "/api/admin/login",
                json={"username": "admin", "password": "wrong-password"},
            )
            assert r_bad.status_code == 401
            passed += 1  # #2

            # ---------------------------------------------------------
            # 1 & 4. Valid administrator login + session persistence (/me)
            # ---------------------------------------------------------
            r_login = client.post(
                "/api/admin/login",
                json={"username": "admin", "password": "TestAdmin!Password123"},
            )
            assert r_login.status_code == 200
            d_login = r_login.get_json()
            assert d_login["success"] is True
            csrf_token = d_login["csrf_token"]
            passed += 1  # #1

            r_me = client.get("/api/admin/me")
            assert r_me.status_code == 200
            assert r_me.get_json()["admin"]["username"] == "admin"
            passed += 1  # #4

            # ---------------------------------------------------------
            # 6. Missing/invalid CSRF on state-changing requests rejected (403)
            # ---------------------------------------------------------
            r_no_csrf = client.post(
                "/api/admin/categories",
                json={"name": "ShouldFail"},
            )
            assert r_no_csrf.status_code == 403
            passed += 1  # #6

            headers = {"X-CSRF-Token": csrf_token}

            # ---------------------------------------------------------
            # 7. List FAQs
            # ---------------------------------------------------------
            r_faqs = client.get("/api/admin/faqs")
            assert r_faqs.status_code == 200
            assert r_faqs.get_json()["total_count"] == 100
            passed += 1  # #7

            # ---------------------------------------------------------
            # 14, 15, 16, 17. Categories: list, add, rename, prevent unsafe delete
            # ---------------------------------------------------------
            r_cats = client.get("/api/admin/categories")
            assert r_cats.status_code == 200
            cats = r_cats.get_json()["categories"]
            assert len(cats) == 7
            passed += 1  # #14

            r_add_cat = client.post(
                "/api/admin/categories",
                json={"name": "Research & Innovation"},
                headers=headers,
            )
            assert r_add_cat.status_code == 201
            new_cat_id = r_add_cat.get_json()["category"]["category_id"]
            # Duplicate case-insensitive rejected
            assert (
                client.post(
                    "/api/admin/categories",
                    json={"name": "research & innovation"},
                    headers=headers,
                ).status_code
                == 409
            )
            passed += 1  # #15

            r_ren_cat = client.patch(
                f"/api/admin/categories/{new_cat_id}",
                json={"name": "Research Labs"},
                headers=headers,
            )
            assert r_ren_cat.status_code == 200
            assert r_ren_cat.get_json()["category"]["name"] == "Research Labs"
            passed += 1  # #16

            # Unsafe delete of non-empty category ('Admissions') blocked with 409
            adm_cat_id = next(c["category_id"] for c in cats if c["name"] == "Admissions")
            assert (
                client.delete(
                    f"/api/admin/categories/{adm_cat_id}",
                    headers=headers,
                ).status_code
                == 409
            )
            passed += 1  # #17

            # ---------------------------------------------------------
            # 8, 11, 18, 21. Add FAQ + alternative questions + live NLP refresh
            # ---------------------------------------------------------
            r_add_faq = client.post(
                "/api/admin/faqs",
                json={
                    "category_id": new_cat_id,
                    "question": "How can students book the 3D printing robotics lab?",
                    "answer": "Students can reserve the 3D printing robotics lab via the Research Portal.",
                    "alternative_questions": [
                        "Where do I reserve the robotics 3D printer?",
                        "How to access the robotics fabrication workshop?",
                    ],
                },
                headers=headers,
            )
            assert r_add_faq.status_code == 201
            new_faq = r_add_faq.get_json()["faq"]
            new_faq_id = new_faq["faq_id"]
            assert len(new_faq["alternative_questions"]) == 2
            passed += 1  # #8
            passed += 1  # #11

            # Preview/chat immediately finds newly added FAQ without restart
            r_preview = client.post(
                "/api/admin/test-chatbot",
                json={"question": "How can students book the 3D printing robotics lab?"},
                headers=headers,
            )
            assert r_preview.status_code == 200
            assert r_preview.get_json()["preview"]["faq_id"] == new_faq_id
            passed += 1  # #18

            # Alternative question is also indexed and matched
            r_alt_chat = client.post(
                "/api/chat",
                json={"message": "Where do I reserve the robotics 3D printer?"},
            ).get_json()
            assert r_alt_chat["faq_id"] == new_faq_id
            assert r_alt_chat["category"] == "Research Labs"
            passed += 1  # #21

            # ---------------------------------------------------------
            # 9, 12, 19. Edit FAQ + edit/delete alternatives + updated answer returned
            # ---------------------------------------------------------
            r_edit_faq = client.patch(
                f"/api/admin/faqs/{new_faq_id}",
                json={
                    "answer": "Updated: Robotics lab bookings require faculty mentor approval on the Research Portal.",
                    "alternative_questions": ["Book robotics fabrication lab"],
                },
                headers=headers,
            )
            assert r_edit_faq.status_code == 200
            assert len(r_edit_faq.get_json()["faq"]["alternative_questions"]) == 1
            passed += 1  # #9
            passed += 1  # #12

            r_updated_chat = client.post(
                "/api/chat",
                json={"message": "Book robotics fabrication lab"},
            ).get_json()
            assert r_updated_chat["faq_id"] == new_faq_id
            assert "faculty mentor approval" in r_updated_chat["answer"]
            passed += 1  # #19

            # ---------------------------------------------------------
            # 13. Reject invalid or duplicate FAQ data
            # ---------------------------------------------------------
            assert (
                client.post(
                    "/api/admin/faqs",
                    json={"category_id": new_cat_id, "question": "", "answer": "Valid"},
                    headers=headers,
                ).status_code
                == 400
            )
            assert (
                client.post(
                    "/api/admin/faqs",
                    json={
                        "category_id": new_cat_id,
                        "question": "How can students book the 3D printing robotics lab?",
                        "answer": "Duplicate",
                    },
                    headers=headers,
                ).status_code
                == 409
            )
            passed += 1  # #13

            # ---------------------------------------------------------
            # 10, 20, 29. Delete FAQ + cascade alternatives + no longer matched
            # ---------------------------------------------------------
            r_del_faq = client.delete(
                f"/api/admin/faqs/{new_faq_id}", headers=headers
            )
            assert r_del_faq.status_code == 200
            assert client.get(f"/api/admin/faqs/{new_faq_id}").status_code == 404
            passed += 1  # #10

            with db.connection() as conn:
                orphan_alts = conn.execute(
                    "SELECT COUNT(*) FROM faq_alternatives WHERE faq_id = ?",
                    (new_faq_id,),
                ).fetchone()[0]
            assert orphan_alts == 0
            passed += 1  # #29

            r_after_del = client.post(
                "/api/chat",
                json={"message": "Book robotics fabrication lab"},
            ).get_json()
            assert r_after_del["faq_id"] != new_faq_id
            passed += 1  # #20

            # ---------------------------------------------------------
            # 22. Failed index rebuild retains previous working index
            # ---------------------------------------------------------
            before_count = len(backend_app.chatbot.faqs)
            ok_fail, err_fail = backend_app.chatbot.reload_from_records([])
            assert ok_fail is False
            assert err_fail is not None
            assert backend_app.chatbot.is_ready is True
            assert len(backend_app.chatbot.faqs) == before_count
            passed += 1  # #22

            # ---------------------------------------------------------
            # 23, 24, 25, 26. Unanswered questions tracking & review
            # ---------------------------------------------------------
            client.post(
                "/api/chat",
                json={"message": "Does campus have an aerospace wind tunnel facility?"},
            )
            r_unans = client.get("/api/admin/unanswered?status=unreviewed")
            assert r_unans.status_code == 200
            items = r_unans.get_json()["items"]
            assert any("wind tunnel" in it["query_text"].lower() for it in items)
            target_item = next(
                it for it in items if "wind tunnel" in it["query_text"].lower()
            )
            passed += 1  # #23

            r_unans_search = client.get("/api/admin/unanswered?q=wind%20tunnel")
            assert r_unans_search.get_json()["total_count"] >= 1
            passed += 1  # #24

            r_rev = client.patch(
                f"/api/admin/unanswered/{target_item['item_id']}",
                json={"status": "reviewed", "review_notes": "Checked with facilities"},
                headers=headers,
            )
            assert r_rev.status_code == 200
            assert r_rev.get_json()["item"]["status"] == "reviewed"
            passed += 1  # #25

            r_dis = client.patch(
                f"/api/admin/unanswered/{target_item['item_id']}",
                json={"status": "dismissed"},
                headers=headers,
            )
            assert r_dis.status_code == 200
            assert r_dis.get_json()["item"]["status"] == "dismissed"
            passed += 1  # #26

            # ---------------------------------------------------------
            # 28. Existing student conversation records preserved
            # ---------------------------------------------------------
            conv_detail = conv_mgr.get_conversation_detail(conv_before)
            assert conv_detail is not None
            assert len(conv_detail["messages"]) == 2
            passed += 1  # #28

            # ---------------------------------------------------------
            # 5. Logout invalidates session cookie
            # ---------------------------------------------------------
            r_logout = client.post("/api/admin/logout", headers=headers)
            assert r_logout.status_code == 200
            assert client.get("/api/admin/me").status_code == 401
            passed += 1  # #5

            # ---------------------------------------------------------
            # 5b. Multiple admin accounts & usernames with spaces
            # ---------------------------------------------------------
            assert auth_repo.upsert_admin_user("Second Admin User", "SecondPass!999") == "created"
            assert auth_repo.upsert_admin_user("Second Admin User", "SecondPass!999") == "unchanged"
            r_login_2 = client.post(
                "/api/admin/login",
                json={"username": "Second Admin User", "password": "SecondPass!999"},
            )
            assert r_login_2.status_code == 200
            assert client.get("/api/admin/me").get_json()["admin"]["username"] == "Second Admin User"
            assert client.get("/api/admin/dashboard").status_code == 200
            assert client.get("/api/admin/faqs").status_code == 200
            assert client.get("/api/admin/categories").status_code == 200
            assert client.get("/api/admin/unanswered").status_code == 200
            h2 = {"X-CSRF-Token": r_login_2.get_json()["csrf_token"]}
            assert client.post("/api/admin/test-chatbot", json={"question": "tuition fee"}, headers=h2).status_code == 200
            assert client.post("/api/admin/logout", headers=h2).status_code == 200
            assert client.get("/api/admin/dashboard").status_code == 401
            # Original admin still works
            assert client.post("/api/admin/login", json={"username": "admin", "password": "TestAdmin!Password123"}).status_code == 200
            client.post("/api/admin/logout", headers={"X-CSRF-Token": client.get("/api/admin/me").get_json()["csrf_token"]})

            # ---------------------------------------------------------
            # 30. Database restart persistence
            # ---------------------------------------------------------
            restart_db = Path(tmp_dir) / "restart_admin.db"
            prev_env = os.environ.get("INTELLIFAQ_DB_PATH")
            prev_user = os.environ.get("INTELLIFAQ_ADMIN_USERNAME")
            prev_pass = os.environ.get("INTELLIFAQ_ADMIN_PASSWORD")
            try:
                os.environ["INTELLIFAQ_DB_PATH"] = str(restart_db)
                os.environ["INTELLIFAQ_ADMIN_USERNAME"] = "admin"
                os.environ["INTELLIFAQ_ADMIN_PASSWORD"] = "RestartPass!456"
                app1 = importlib.reload(backend_app)
                c1 = app1.app.test_client()
                l1 = c1.post(
                    "/api/admin/login",
                    json={"username": "admin", "password": "RestartPass!456"},
                ).get_json()
                c1.post(
                    "/api/admin/faqs",
                    json={
                        "category_id": 1,
                        "question": "Persisted admin FAQ test question?",
                        "answer": "Persisted admin FAQ answer.",
                        "alternative_questions": ["Persisted alt phrasing"],
                    },
                    headers={"X-CSRF-Token": l1["csrf_token"]},
                )

                app2 = importlib.reload(app1)
                c2 = app2.app.test_client()
                res_persisted = c2.post(
                    "/api/chat",
                    json={"message": "Persisted alt phrasing"},
                ).get_json()
                assert "Persisted admin FAQ answer" in res_persisted["answer"]
            finally:
                for k, v in (
                    ("INTELLIFAQ_DB_PATH", prev_env),
                    ("INTELLIFAQ_ADMIN_USERNAME", prev_user),
                    ("INTELLIFAQ_ADMIN_PASSWORD", prev_pass),
                ):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                importlib.reload(backend_app)
            passed += 1  # #30

        finally:
            backend_app.conversation_manager = orig_mgr
            backend_app.kb_repository = orig_kb
            backend_app.admin_auth_repository = orig_auth
            backend_app.unanswered_repository = orig_unans
            backend_app.document_repository = orig_doc_repo
            backend_app.document_retriever = orig_doc_retriever
            try:
                backend_app.refresh_chatbot_index()
                backend_app.refresh_document_index()
            except Exception:
                pass

    print("=" * 82)
    print(f"ADMIN TEST SUITE SUMMARY: {passed} / {total} SCENARIOS PASSED")
    print("=" * 82)


def test_admin_suite() -> None:
    """Entrypoint for pytest/unittest runners."""
    run_admin_tests()


if __name__ == "__main__":
    run_admin_tests()
