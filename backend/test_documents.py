"""
Automated Test Suite for Document Upload, Validation, Extraction, Chunking,
and Approval Workflow (Prompt 17 — Part 11).

Uses temporary files and temporary SQLite databases only.
"""

import io
import os
from pathlib import Path
import tempfile

from docx import Document as DocxDocument

import app as backend_app
from database import (
    AdminAuthRepository,
    Database,
    DocumentRepository,
    KnowledgeBaseRepository,
    UnansweredRepository,
)


def _build_minimal_pdf(pages_text):
    """Build a valid multi-page PDF 1.4 byte buffer with extractable text."""
    objects = []
    # 1: Catalog, 2: Pages, 3: Font
    page_ids = []
    next_id = 4
    for _ in pages_text:
        page_ids.append((next_id, next_id + 1))
        next_id += 2

    kids_str = " ".join(f"{pid} 0 R" for pid, _ in page_ids)
    objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append(
        (2, f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>".encode())
    )
    objects.append(
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    )

    for (pid, cid), text in zip(page_ids, pages_text):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_data = (
            f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET" if text else ""
        ).encode("latin-1")
        objects.append(
            (
                pid,
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>".encode(),
            )
        )
        objects.append(
            (
                cid,
                f"<< /Length {len(stream_data)} >>\nstream\n".encode()
                + stream_data
                + b"\nendstream",
            )
        )

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = {}
    for obj_id, body in objects:
        offsets[obj_id] = buf.tell()
        buf.write(f"{obj_id} 0 obj\n".encode())
        buf.write(body)
        buf.write(b"\nendobj\n")

    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode())
    buf.write(b"0000000000 65535 f \n")
    for obj_id in range(1, len(objects) + 1):
        buf.write(f"{offsets[obj_id]:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return buf.getvalue()


def _build_docx_bytes(paragraphs):
    doc = DocxDocument()
    doc.add_heading("Section One: Campus Library", level=1)
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def run_document_tests() -> None:
    """Execute all 13 document upload, extraction, and approval tests."""
    passed = 0
    total = 13

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        upload_dir = tmp_path / "uploads"
        prev_upload_env = os.environ.get("INTELLIFAQ_UPLOAD_DIR")
        prev_max_env = os.environ.get("INTELLIFAQ_MAX_UPLOAD_BYTES")

        orig_mgr = backend_app.conversation_manager
        orig_kb = backend_app.kb_repository
        orig_auth = backend_app.admin_auth_repository
        orig_unans = backend_app.unanswered_repository
        orig_doc_repo = backend_app.document_repository

        try:
            os.environ["INTELLIFAQ_UPLOAD_DIR"] = str(upload_dir)
            db = Database(tmp_path / "test_docs.db")
            db.initialize()

            backend_app.conversation_manager = backend_app.ConversationManager(database=db)
            backend_app.kb_repository = KnowledgeBaseRepository(db)
            backend_app.admin_auth_repository = AdminAuthRepository(db)
            backend_app.unanswered_repository = UnansweredRepository(db)
            backend_app.document_repository = DocumentRepository(db)
            backend_app.kb_repository.seed_from_json_if_empty()
            backend_app.admin_auth_repository.ensure_initial_admin(
                username="admin", password="DocTestPassword!123"
            )
            backend_app.refresh_chatbot_index()
            backend_app.refresh_document_index()

            client = backend_app.app.test_client()

            # 1. Unauthorized upload rejected (401)
            r_unauth = client.post(
                "/api/admin/documents",
                data={"title": "Unauth", "doc_type": "Other", "academic_year": "2026-27"},
            )
            assert r_unauth.status_code == 401
            passed += 1

            # Login as admin
            login_res = client.post(
                "/api/admin/login",
                json={"username": "admin", "password": "DocTestPassword!123"},
            ).get_json()
            headers = {"X-CSRF-Token": login_res["csrf_token"]}

            # 2. CSRF protection on upload (403)
            r_no_csrf = client.post(
                "/api/admin/documents",
                data={"title": "NoCSRF", "doc_type": "Other", "academic_year": "2026-27"},
            )
            assert r_no_csrf.status_code == 403
            passed += 1

            # 3. Valid PDF upload + 4. Page-number preservation
            pdf_bytes = _build_minimal_pdf([
                "Minimum attendance requirement is documented on page one for all undergraduate courses.",
                "Examination hall ticket rules are described on page two for semester exams.",
            ])
            r_pdf = client.post(
                "/api/admin/documents",
                data={
                    "title": "Academic Regulations 2026-27",
                    "doc_type": "Academic Regulations",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(pdf_bytes), "regulations.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            assert r_pdf.status_code == 201
            pdf_doc = r_pdf.get_json()["document"]
            assert pdf_doc["processing_status"] == "processed"
            assert pdf_doc["approval_status"] == "pending_review"
            assert pdf_doc["page_count"] == 2
            assert pdf_doc["chunk_count"] >= 2
            passed += 1  # Valid PDF upload

            preview_pdf = client.get(
                f"/api/admin/documents/{pdf_doc['document_id']}/preview"
            ).get_json()
            pages_found = {c["page_number"] for c in preview_pdf["chunks"]}
            assert pages_found == {1, 2}
            passed += 1  # Page-number preservation & PDF text extraction

            # 5. Valid DOCX upload
            docx_bytes = _build_docx_bytes([
                "The central library operates from 8 AM to 10 PM on all working days.",
                "Students may borrow up to 5 textbooks for 14 days using their ID card.",
            ])
            r_docx = client.post(
                "/api/admin/documents",
                data={
                    "title": "Library Handbook",
                    "doc_type": "Hostel and Campus Guidelines",
                    "academic_year": "2026-27",
                    "file": (
                        io.BytesIO(docx_bytes),
                        "library.docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            assert r_docx.status_code == 201
            docx_doc = r_docx.get_json()["document"]
            assert docx_doc["processing_status"] == "processed"
            assert docx_doc["page_count"] is None  # Never invent PDF page numbers for DOCX
            passed += 1

            # 6. Valid TXT upload + 7. Text chunking and overlap
            long_sentences = " ".join(
                f"Official campus transport bus route number {i} operates from main gate to city center."
                for i in range(1, 25)
            )
            r_txt = client.post(
                "/api/admin/documents",
                data={
                    "title": "Transport Schedule",
                    "doc_type": "Hostel and Campus Guidelines",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(long_sentences.encode("utf-8")), "transport.txt", "text/plain"),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            assert r_txt.status_code == 201
            txt_doc = r_txt.get_json()["document"]
            assert txt_doc["processing_status"] == "processed"
            assert txt_doc["chunk_count"] >= 2
            passed += 1  # Valid TXT upload

            txt_preview = client.get(
                f"/api/admin/documents/{txt_doc['document_id']}/preview"
            ).get_json()
            c0 = txt_preview["chunks"][0]["chunk_text"]
            c1 = txt_preview["chunks"][1]["chunk_text"]
            assert set(c0.split()) & set(c1.split())  # Overlap exists
            passed += 1  # Chunking and overlap

            # 8. Invalid file extension rejection
            r_bad_ext = client.post(
                "/api/admin/documents",
                data={
                    "title": "Bad File",
                    "doc_type": "Other",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(b"MZ..."), "malware.exe", "application/octet-stream"),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            assert r_bad_ext.status_code == 400
            passed += 1

            # 9. Oversized file rejection
            os.environ["INTELLIFAQ_MAX_UPLOAD_BYTES"] = "50"
            r_big = client.post(
                "/api/admin/documents",
                data={
                    "title": "Too Big",
                    "doc_type": "Other",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(b"A" * 200), "big.txt", "text/plain"),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            os.environ.pop("INTELLIFAQ_MAX_UPLOAD_BYTES", None)
            assert r_big.status_code == 400
            passed += 1

            # 10. Duplicate document detection
            r_dup = client.post(
                "/api/admin/documents",
                data={
                    "title": "Duplicate Regulations",
                    "doc_type": "Academic Regulations",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(pdf_bytes), "regulations_copy.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            assert r_dup.status_code == 409
            passed += 1

            # 11. Image-only / scanned PDF detection -> OCR_REQUIRED
            scanned_pdf = _build_minimal_pdf([""])
            r_scan = client.post(
                "/api/admin/documents",
                data={
                    "title": "Scanned Notice",
                    "doc_type": "Official Notices",
                    "academic_year": "2026-27",
                    "file": (io.BytesIO(scanned_pdf), "scanned.pdf", "application/pdf"),
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            assert r_scan.status_code == 201
            scan_doc = r_scan.get_json()["document"]
            assert scan_doc["processing_status"] == "OCR_REQUIRED"
            assert "ocr" in scan_doc["error_message"].lower()
            # Cannot approve an OCR_REQUIRED document
            assert (
                client.post(
                    f"/api/admin/documents/{scan_doc['document_id']}/approve",
                    headers=headers,
                ).status_code
                == 409
            )
            passed += 1

            # 12. Approval and rejection workflow
            r_app = client.post(
                f"/api/admin/documents/{pdf_doc['document_id']}/approve",
                headers=headers,
            )
            assert r_app.status_code == 200
            assert r_app.get_json()["document"]["approval_status"] == "approved"

            r_rej = client.post(
                f"/api/admin/documents/{docx_doc['document_id']}/reject",
                json={"reason": "Needs formatting update"},
                headers=headers,
            )
            assert r_rej.status_code == 200
            assert r_rej.get_json()["document"]["approval_status"] == "rejected"
            passed += 1

            # 13. Database persistence & analytics check
            r_ana = client.get("/api/admin/documents/analytics")
            assert r_ana.status_code == 200
            ana = r_ana.get_json()["analytics"]
            assert ana["total_documents"] == 4
            assert ana["approved_documents"] == 1
            assert ana["failed_processing"] == 1
            passed += 1

        finally:
            if prev_upload_env is None:
                os.environ.pop("INTELLIFAQ_UPLOAD_DIR", None)
            else:
                os.environ["INTELLIFAQ_UPLOAD_DIR"] = prev_upload_env
            if prev_max_env is None:
                os.environ.pop("INTELLIFAQ_MAX_UPLOAD_BYTES", None)
            else:
                os.environ["INTELLIFAQ_MAX_UPLOAD_BYTES"] = prev_max_env
            backend_app.conversation_manager = orig_mgr
            backend_app.kb_repository = orig_kb
            backend_app.admin_auth_repository = orig_auth
            backend_app.unanswered_repository = orig_unans
            backend_app.document_repository = orig_doc_repo

    print("=" * 82)
    print(f"DOCUMENT PROCESSING TEST SUITE SUMMARY: {passed} / {total} SCENARIOS PASSED")
    print("=" * 82)


def test_documents_suite() -> None:
    run_document_tests()


if __name__ == "__main__":
    run_document_tests()
