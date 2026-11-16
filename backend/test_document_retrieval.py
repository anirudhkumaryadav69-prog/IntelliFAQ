"""
Automated Test Suite for Approved Document Retrieval, Grounded Citations,
Conflict Detection, Index Refresh & Restart Persistence (Prompt 17 — Part 11).

Uses temporary files and temporary SQLite databases only.
"""

import importlib
import io
import os
from pathlib import Path
import tempfile

import app as backend_app
from database import (
    AdminAuthRepository,
    Database,
    DocumentRepository,
    KnowledgeBaseRepository,
    UnansweredRepository,
)
from test_documents import _build_minimal_pdf


def run_document_retrieval_tests() -> None:
    """Execute all 17 document retrieval, citation, and regression tests."""
    passed = 0
    total = 17

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        upload_dir = tmp_path / "uploads"
        prev_upload_env = os.environ.get("INTELLIFAQ_UPLOAD_DIR")

        orig_mgr = backend_app.conversation_manager
        orig_kb = backend_app.kb_repository
        orig_auth = backend_app.admin_auth_repository
        orig_unans = backend_app.unanswered_repository
        orig_doc_repo = backend_app.document_repository
        orig_doc_ret = backend_app.document_retriever

        try:
            os.environ["INTELLIFAQ_UPLOAD_DIR"] = str(upload_dir)
            db_file = tmp_path / "test_retrieval.db"
            db = Database(db_file)
            db.initialize()

            backend_app.conversation_manager = backend_app.ConversationManager(database=db)
            backend_app.kb_repository = KnowledgeBaseRepository(db)
            backend_app.admin_auth_repository = AdminAuthRepository(db)
            backend_app.unanswered_repository = UnansweredRepository(db)
            backend_app.document_repository = DocumentRepository(db)
            backend_app.kb_repository.seed_from_json_if_empty()
            backend_app.admin_auth_repository.ensure_initial_admin(
                username="admin", password="RetrievalTest!123"
            )
            backend_app.refresh_chatbot_index()
            backend_app.refresh_document_index()

            client = backend_app.app.test_client()
            login = client.post(
                "/api/admin/login",
                json={"username": "admin", "password": "RetrievalTest!123"},
            ).get_json()
            headers = {"X-CSRF-Token": login["csrf_token"]}

            # Upload a pending document about "Quantum Photonics Lab"
            pdf_pending = _build_minimal_pdf([
                "The Quantum Photonics Lab is open on Tuesdays and Thursdays for final-year research scholars."
            ])
            r_up = client.post(
                "/api/admin/documents",
                data={
                    "title": "Photonics Lab Policy",
                    "doc_type": "Official Notices",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(pdf_pending), "photonics.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            doc_id = r_up.get_json()["document"]["document_id"]

            # 1. Pending documents excluded from student retrieval
            res_pending = client.post(
                "/api/chat",
                json={"message": "When is the Quantum Photonics Lab open?"},
            ).get_json()
            assert res_pending["answer_source"] == "insufficient_evidence"
            assert res_pending["document_sources"] == []
            passed += 1

            # 2 & 3. Index refresh after approval + Approved document retrieval + 4. Citations
            assert (
                client.post(
                    f"/api/admin/documents/{doc_id}/approve", headers=headers
                ).status_code
                == 200
            )
            res_approved = client.post(
                "/api/chat",
                json={"message": "When is the Quantum Photonics Lab open?"},
            ).get_json()
            assert res_approved["answer_source"] == "document"
            assert res_approved["evidence_sufficient"] is True
            assert "Tuesdays and Thursdays" in res_approved["answer"]
            assert len(res_approved["document_sources"]) >= 1
            src0 = res_approved["document_sources"][0]
            assert src0["document_title"] == "Photonics Lab Policy"
            assert src0["page_number"] == 1
            assert "document_id" not in src0
            assert "storage_filename" not in src0
            passed += 1  # Index refresh after approval
            passed += 1  # Approved document retrieval
            passed += 1  # Source citation generation

            # 5. Insufficient evidence fallback
            res_none = client.post(
                "/api/chat",
                json={"message": "Does the university offer underwater basket weaving?"},
            ).get_json()
            assert res_none["answer_source"] == "insufficient_evidence"
            assert res_none["evidence_sufficient"] is False
            passed += 1

            # 6. Conflicting source detection
            pdf_conflict = _build_minimal_pdf([
                "The Quantum Photonics Lab requires 85% attendance, whereas older notices stated 75%."
            ])
            pdf_conflict_2 = _build_minimal_pdf([
                "Quantum Photonics Lab safety orientation requires 90% quiz score."
            ])
            r_c1 = client.post(
                "/api/admin/documents",
                data={
                    "title": "Photonics Safety Addendum A",
                    "doc_type": "Official Notices",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(pdf_conflict), "c1.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            ).get_json()["document"]["document_id"]
            r_c2 = client.post(
                "/api/admin/documents",
                data={
                    "title": "Photonics Safety Addendum B",
                    "doc_type": "Official Notices",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(pdf_conflict_2), "c2.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            ).get_json()["document"]["document_id"]
            client.post(f"/api/admin/documents/{r_c1}/approve", headers=headers)
            client.post(f"/api/admin/documents/{r_c2}/approve", headers=headers)

            res_conf = client.post(
                "/api/chat",
                json={"message": "What percentage is required for Quantum Photonics Lab?"},
            ).get_json()
            assert res_conf["source_conflict"] is True
            assert "differing details" in res_conf["answer"].lower()
            passed += 1

            # 7. Archived documents excluded from retrieval
            client.post(f"/api/admin/documents/{doc_id}/archive", headers=headers)
            client.post(f"/api/admin/documents/{r_c1}/archive", headers=headers)
            client.post(f"/api/admin/documents/{r_c2}/archive", headers=headers)
            res_arch = client.post(
                "/api/chat",
                json={"message": "When is the Quantum Photonics Lab open?"},
            ).get_json()
            assert res_arch["answer_source"] == "insufficient_evidence"
            assert res_arch["document_sources"] == []
            passed += 1

            # 8. Existing FAQ retrieval & 9. Eligibility workflow regression
            res_faq = client.post(
                "/api/chat",
                json={"message": "What are the admission requirements for undergraduate programs?"},
            ).get_json()
            assert res_faq["faq_id"] == 1
            assert res_faq["answer_source"] == "faq"
            passed += 1

            res_elig = client.post(
                "/api/chat",
                json={"message": "Am I qualified for B.Tech admission?"},
            ).get_json()
            assert "qualification" in res_elig["answer"].lower()
            passed += 1

            # 10b. Reproduce all 3 manual queries + paraphrased lab query + library hours
            # using a temporary multi-page PDF fixture
            guide_pdf = _build_minimal_pdf([
                "Student Academic and Campus Guide. Demonstration document.",
                "1. Academic Advising. Important test fact: The sample advising desk is located in Room A-204 of the Academic Services Building. 2. Library Services. The demonstration library is open from 8:30 AM to 6:00 PM, Monday to Saturday. It is closed on Sundays.",
                "3. Computer Laboratory Rules. The sample Computer Laboratory is located in Block C, Room C-105. Technical support: Report a malfunction to the IT Help Desk in Room C-102.",
            ])
            r_guide = client.post(
                "/api/admin/documents",
                data={
                    "title": "Student Academic and Campus Guide",
                    "doc_type": "Hostel and Campus Guidelines",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(guide_pdf), "guide.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            ).get_json()["document"]["document_id"]
            client.post(f"/api/admin/documents/{r_guide}/approve", headers=headers)

            # Manual Query 1 (ambiguous FAQ overridden by approved document)
            q1_res = client.post(
                "/api/chat",
                json={"message": "According to the Student Academic and Campus Guide, where is the Computer Laboratory situated?"},
            ).get_json()
            assert q1_res["answer_source"] == "document"
            assert q1_res["needs_clarification"] is False
            assert q1_res["candidates"] == []
            assert "Block C, Room C-105" in q1_res["answer"]
            assert q1_res["document_sources"][0]["document_title"] == "Student Academic and Campus Guide"
            assert q1_res["document_sources"][0]["page_number"] == 3
            passed += 1

            # Manual Query 2 (workstation malfunction -> IT Help Desk Room C-102)
            q2_res = client.post(
                "/api/chat",
                json={"message": "Where should students report a malfunctioning computer workstation?"},
            ).get_json()
            assert q2_res["answer_source"] == "document"
            assert q2_res["needs_clarification"] is False
            assert "Room C-102" in q2_res["answer"]
            assert q2_res["document_sources"][0]["page_number"] == 3
            passed += 1

            # Manual Query 3 (Academic Advising Desk -> Room A-204, Page 2)
            q3_res = client.post(
                "/api/chat",
                json={"message": "What is the room number of the Academic Advising Desk?"},
            ).get_json()
            assert q3_res["answer_source"] == "document"
            assert q3_res["needs_clarification"] is False
            assert "Room A-204" in q3_res["answer"]
            assert q3_res["document_sources"][0]["page_number"] == 2
            passed += 1

            # Paraphrased query ("lab" synonym -> "Laboratory")
            q_lab = client.post(
                "/api/chat",
                json={"message": "Where is the computer lab situated?"},
            ).get_json()
            assert q_lab["answer_source"] == "document"
            assert "Room C-105" in q_lab["answer"]
            passed += 1

            # Prompt 17.2: Generic FAQ #84 ("extended hours") vs. explicit location in document
            q_where_lab = client.post(
                "/api/chat",
                json={"message": "Where is the Computer Laboratory?"},
            ).get_json()
            assert q_where_lab["answer_source"] == "document"
            assert "Block C, Room C-105" in q_where_lab["answer"]
            assert q_where_lab["document_sources"][0]["page_number"] == 3
            passed += 1

            # Block / room-number variations
            q_block = client.post(
                "/api/chat",
                json={"message": "Which block contains the Computer Laboratory?"},
            ).get_json()
            assert q_block["answer_source"] == "document"
            assert "Block C" in q_block["answer"]
            passed += 1

            # Library hours (generic FAQ #74 vs. explicit hours in document)
            q_lib = client.post(
                "/api/chat",
                json={"message": "When is the sample library open?"},
            ).get_json()
            assert q_lib["answer_source"] == "document"
            assert "8:30 AM to 6:00 PM" in q_lib["answer"]
            passed += 1

            # 10. Index persistence and rebuild after backend restart
            # Re-approve Photonics Lab Policy before simulated restart
            # (unarchive via reprocess or upload new approved doc)
            pdf_restart = _build_minimal_pdf([
                "The Observatory Telescope Facility is open every Friday evening from 6 PM to 9 PM."
            ])
            r_rst = client.post(
                "/api/admin/documents",
                data={
                    "title": "Observatory Schedule",
                    "doc_type": "Hostel and Campus Guidelines",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(pdf_restart), "obs.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            ).get_json()["document"]["document_id"]
            client.post(f"/api/admin/documents/{r_rst}/approve", headers=headers)

            prev_db_env = os.environ.get("INTELLIFAQ_DB_PATH")
            try:
                os.environ["INTELLIFAQ_DB_PATH"] = str(db_file)
                reloaded = importlib.reload(backend_app)
                c_reloaded = reloaded.app.test_client()
                res_after_restart = c_reloaded.post(
                    "/api/chat",
                    json={"message": "When is the Observatory Telescope Facility open?"},
                ).get_json()
                assert res_after_restart["answer_source"] == "document"
                assert "Friday evening" in res_after_restart["answer"]
            finally:
                if prev_db_env is None:
                    os.environ.pop("INTELLIFAQ_DB_PATH", None)
                else:
                    os.environ["INTELLIFAQ_DB_PATH"] = prev_db_env
                importlib.reload(backend_app)
            passed += 1

        finally:
            if prev_upload_env is None:
                os.environ.pop("INTELLIFAQ_UPLOAD_DIR", None)
            else:
                os.environ["INTELLIFAQ_UPLOAD_DIR"] = prev_upload_env
            backend_app.conversation_manager = orig_mgr
            backend_app.kb_repository = orig_kb
            backend_app.admin_auth_repository = orig_auth
            backend_app.unanswered_repository = orig_unans
            backend_app.document_repository = orig_doc_repo
            backend_app.document_retriever = orig_doc_ret

    print("=" * 82)
    print(f"DOCUMENT RETRIEVAL TEST SUITE SUMMARY: {passed} / {total} SCENARIOS PASSED")
    print("=" * 82)


def test_document_retrieval_suite() -> None:
    run_document_retrieval_tests()


if __name__ == "__main__":
    run_document_retrieval_tests()
