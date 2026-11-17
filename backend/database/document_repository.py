"""
SQLite Document Knowledge Base Repository for IntelliFAQ 2.0.

Manages official university documents, extracted overlapping chunks,
processing/audit logs, approval lifecycle, versioning, and analytics.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import Database
from .kb_repository import ConflictError

logger = logging.getLogger(__name__)

STANDARD_DOCUMENT_TYPES = [
    "University Prospectus",
    "Admission Guidelines",
    "Academic Regulations",
    "Examination Regulations",
    "Fee Structure",
    "Scholarship Guidelines",
    "Attendance Policy",
    "Hostel and Campus Guidelines",
    "Placement Guidelines",
    "Official Notices",
    "Other",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class DocumentRepository:
    """SQLite-backed repository for official university documents and chunks."""

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _add_log(
        conn: Any,
        document_id: int,
        event_type: str,
        status: str,
        message: str,
        actor: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO document_processing_logs (
                document_id, event_type, status, message, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(document_id), event_type, status, message[:400], actor, _utc_now_iso()),
        )

    def find_by_sha256(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT document_id, title, doc_type, academic_year,
                       processing_status, approval_status, version
                FROM documents
                WHERE sha256_hash = ? AND processing_status != 'archived'
                LIMIT 1
                """,
                (sha256_hash,),
            ).fetchone()
        return dict(row) if row is not None else None

    def create_document_with_extraction(
        self,
        *,
        title: str,
        doc_type: str,
        academic_year: str,
        department: Optional[str],
        description: Optional[str],
        effective_date: Optional[str],
        expiry_date: Optional[str],
        original_filename: str,
        storage_filename: str,
        mime_type: str,
        file_size: int,
        sha256_hash: str,
        uploaded_by: str,
        extraction: Any,
        supersedes_document_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        cleaned_title = title.strip() if isinstance(title, str) else ""
        cleaned_type = doc_type.strip() if isinstance(doc_type, str) else ""
        cleaned_year = academic_year.strip() if isinstance(academic_year, str) else ""
        if not cleaned_title:
            raise ValueError("Document title is required.")
        if not cleaned_type:
            raise ValueError("Document type is required.")
        if not cleaned_year:
            raise ValueError("Academic year is required.")

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            dup = conn.execute(
                """
                SELECT document_id, title FROM documents
                WHERE sha256_hash = ? AND processing_status != 'archived'
                LIMIT 1
                """,
                (sha256_hash,),
            ).fetchone()
            if dup is not None:
                raise ConflictError(
                    f"Duplicate document detected: identical file already uploaded as '{dup['title']}' (#{dup['document_id']})."
                )

            version = 1
            if supersedes_document_id is not None:
                prev_doc = conn.execute(
                    "SELECT document_id, version FROM documents WHERE document_id = ?",
                    (int(supersedes_document_id),),
                ).fetchone()
                if prev_doc is None:
                    raise ValueError("Superseded document does not exist.")
                version = int(prev_doc["version"]) + 1

            doc_id = self.db.insert_returning_id(
                conn,
                """
                INSERT INTO documents (
                    title, doc_type, academic_year, department, description,
                    effective_date, expiry_date, original_filename, storage_filename,
                    mime_type, file_size, sha256_hash, version, superseded_by_id,
                    page_count, chunk_count, extracted_preview,
                    processing_status, approval_status, uploaded_by,
                    error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?)
                """,
                (
                    cleaned_title,
                    cleaned_type,
                    cleaned_year,
                    department.strip() if isinstance(department, str) and department.strip() else None,
                    description.strip() if isinstance(description, str) and description.strip() else None,
                    effective_date.strip() if isinstance(effective_date, str) and effective_date.strip() else None,
                    expiry_date.strip() if isinstance(expiry_date, str) and expiry_date.strip() else None,
                    original_filename,
                    storage_filename,
                    mime_type,
                    int(file_size),
                    sha256_hash,
                    version,
                    extraction.page_count,
                    len(extraction.chunks),
                    extraction.preview_text,
                    extraction.processing_status,
                    uploaded_by,
                    extraction.error_message,
                    now_iso,
                    now_iso,
                ),
                "document_id",
            )

            if supersedes_document_id is not None:
                conn.execute(
                    """
                    UPDATE documents
                    SET processing_status = 'archived',
                        superseded_by_id = ?,
                        updated_at = ?
                    WHERE document_id = ?
                    """,
                    (doc_id, now_iso, int(supersedes_document_id)),
                )
                self._add_log(
                    conn,
                    int(supersedes_document_id),
                    "superseded",
                    "archived",
                    f"Superseded by document #{doc_id} (v{version}).",
                    uploaded_by,
                )

            for ch in extraction.chunks:
                conn.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id, chunk_index, page_number,
                        section_heading, paragraph_ref, chunk_text,
                        char_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        int(ch["chunk_index"]),
                        ch.get("page_number"),
                        ch.get("section_heading"),
                        ch.get("paragraph_ref"),
                        ch["chunk_text"],
                        int(ch["char_count"]),
                        now_iso,
                    ),
                )

            self._add_log(
                conn,
                doc_id,
                "upload_and_extract",
                extraction.processing_status,
                extraction.error_message
                or f"Extracted {len(extraction.chunks)} chunk(s) (v{version}).",
                uploaded_by,
            )

        created = self.get_document(doc_id)
        assert created is not None
        return created

    def list_documents(
        self,
        search: str = "",
        doc_type: str = "",
        academic_year: str = "",
        processing_status: str = "",
        approval_status: str = "",
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        where: List[str] = []
        params: List[Any] = []

        if doc_type.strip():
            where.append("doc_type = ?")
            params.append(doc_type.strip())
        if academic_year.strip():
            where.append("academic_year = ?")
            params.append(academic_year.strip())
        if processing_status.strip():
            where.append("processing_status = ?")
            params.append(processing_status.strip())
        if approval_status.strip():
            where.append("approval_status = ?")
            params.append(approval_status.strip())
        if search.strip():
            esc = (
                search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pat = f"%{esc}%"
            where.append(
                "(LOWER(title) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(COALESCE(department, '')) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(original_filename) LIKE LOWER(?) ESCAPE '\\')"
            )
            params.extend([pat, pat, pat])

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        page_num = max(1, int(page))
        limit = max(1, min(100, int(per_page)))
        offset = (page_num - 1) * limit

        with self.db.connection() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM documents {where_sql}",
                    tuple(params),
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                SELECT document_id, title, doc_type, academic_year, department,
                       description, effective_date, expiry_date, original_filename,
                       mime_type, file_size, sha256_hash, version, superseded_by_id,
                       page_count, chunk_count, processing_status, approval_status,
                       uploaded_by, error_message, created_at, updated_at
                FROM documents
                {where_sql}
                ORDER BY created_at DESC, document_id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (limit, offset),
            ).fetchall()

        return {
            "documents": [dict(r) for r in rows],
            "total_count": total,
            "page": page_num,
            "per_page": limit,
        }

    def get_document(self, document_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT document_id, title, doc_type, academic_year, department,
                       description, effective_date, expiry_date, original_filename,
                       storage_filename, mime_type, file_size, sha256_hash, version,
                       superseded_by_id, page_count, chunk_count, extracted_preview,
                       processing_status, approval_status, uploaded_by,
                       error_message, created_at, updated_at
                FROM documents
                WHERE document_id = ?
                """,
                (int(document_id),),
            ).fetchone()
            if row is None:
                return None
            logs = conn.execute(
                """
                SELECT log_id, event_type, status, message, actor, created_at
                FROM document_processing_logs
                WHERE document_id = ?
                ORDER BY log_id DESC
                LIMIT 20
                """,
                (int(document_id),),
            ).fetchall()

        doc = dict(row)
        doc.pop("storage_filename", None)  # Never expose internal storage path/filename
        doc["logs"] = [dict(l) for l in logs]
        return doc

    def get_storage_filename(self, document_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT document_id, storage_filename, original_filename,
                       processing_status, approval_status
                FROM documents
                WHERE document_id = ?
                """,
                (int(document_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_preview(
        self, document_id: int, limit: int = 25
    ) -> Optional[Dict[str, Any]]:
        doc = self.get_document(document_id)
        if doc is None:
            return None
        with self.db.connection() as conn:
            chunk_rows = conn.execute(
                """
                SELECT chunk_id, chunk_index, page_number, section_heading,
                       paragraph_ref, chunk_text, char_count
                FROM document_chunks
                WHERE document_id = ?
                ORDER BY chunk_index ASC
                LIMIT ?
                """,
                (int(document_id), max(1, min(50, int(limit)))),
            ).fetchall()
        return {
            "document": doc,
            "chunks": [dict(c) for c in chunk_rows],
        }

    def update_metadata(
        self,
        document_id: int,
        updates: Dict[str, Any],
        actor: str,
    ) -> Optional[Dict[str, Any]]:
        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            existing = conn.execute(
                """
                SELECT title, doc_type, academic_year, department, description,
                       effective_date, expiry_date
                FROM documents
                WHERE document_id = ?
                """,
                (int(document_id),),
            ).fetchone()
            if existing is None:
                return None

            title = (
                updates["title"].strip()
                if isinstance(updates.get("title"), str)
                else existing["title"]
            )
            doc_type = (
                updates["doc_type"].strip()
                if isinstance(updates.get("doc_type"), str)
                else existing["doc_type"]
            )
            academic_year = (
                updates["academic_year"].strip()
                if isinstance(updates.get("academic_year"), str)
                else existing["academic_year"]
            )
            if not title or not doc_type or not academic_year:
                raise ValueError("Title, document type, and academic year cannot be empty.")

            department = (
                updates["department"].strip() or None
                if isinstance(updates.get("department"), str)
                else existing["department"]
            )
            description = (
                updates["description"].strip() or None
                if isinstance(updates.get("description"), str)
                else existing["description"]
            )
            effective_date = (
                updates["effective_date"].strip() or None
                if isinstance(updates.get("effective_date"), str)
                else existing["effective_date"]
            )
            expiry_date = (
                updates["expiry_date"].strip() or None
                if isinstance(updates.get("expiry_date"), str)
                else existing["expiry_date"]
            )

            conn.execute(
                """
                UPDATE documents
                SET title = ?, doc_type = ?, academic_year = ?, department = ?,
                    description = ?, effective_date = ?, expiry_date = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    title,
                    doc_type,
                    academic_year,
                    department,
                    description,
                    effective_date,
                    expiry_date,
                    now_iso,
                    int(document_id),
                ),
            )
            self._add_log(
                conn,
                int(document_id),
                "metadata_updated",
                "updated",
                f"Updated metadata for '{title}'.",
                actor,
            )
        return self.get_document(int(document_id))

    def approve_document(self, document_id: int, actor: str) -> Optional[Dict[str, Any]]:
        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT processing_status, title FROM documents WHERE document_id = ?",
                (int(document_id),),
            ).fetchone()
            if row is None:
                return None
            if row["processing_status"] != "processed":
                raise ConflictError(
                    f"Cannot approve document with processing status '{row['processing_status']}'. Only processed documents can be approved."
                )
            conn.execute(
                """
                UPDATE documents
                SET approval_status = 'approved', updated_at = ?
                WHERE document_id = ?
                """,
                (now_iso, int(document_id)),
            )
            self._add_log(
                conn,
                int(document_id),
                "approved",
                "approved",
                f"Document '{row['title']}' approved for student retrieval.",
                actor,
            )
        return self.get_document(int(document_id))

    def reject_document(
        self, document_id: int, actor: str, reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT title FROM documents WHERE document_id = ?",
                (int(document_id),),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE documents
                SET approval_status = 'rejected', updated_at = ?
                WHERE document_id = ?
                """,
                (now_iso, int(document_id)),
            )
            msg = f"Document rejected{': ' + reason.strip() if reason.strip() else '.'}"
            self._add_log(conn, int(document_id), "rejected", "rejected", msg, actor)
        return self.get_document(int(document_id))

    def archive_document(self, document_id: int, actor: str) -> Optional[Dict[str, Any]]:
        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT title FROM documents WHERE document_id = ?",
                (int(document_id),),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE documents
                SET processing_status = 'archived', updated_at = ?
                WHERE document_id = ?
                """,
                (now_iso, int(document_id)),
            )
            self._add_log(
                conn,
                int(document_id),
                "archived",
                "archived",
                f"Document '{row['title']}' archived and excluded from student retrieval.",
                actor,
            )
        return self.get_document(int(document_id))

    def reprocess_document(
        self, document_id: int, extraction: Any, actor: str
    ) -> Optional[Dict[str, Any]]:
        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT title FROM documents WHERE document_id = ?",
                (int(document_id),),
            ).fetchone()
            if row is None:
                return None

            conn.execute(
                "DELETE FROM document_chunks WHERE document_id = ?",
                (int(document_id),),
            )
            for ch in extraction.chunks:
                conn.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id, chunk_index, page_number,
                        section_heading, paragraph_ref, chunk_text,
                        char_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(document_id),
                        int(ch["chunk_index"]),
                        ch.get("page_number"),
                        ch.get("section_heading"),
                        ch.get("paragraph_ref"),
                        ch["chunk_text"],
                        int(ch["char_count"]),
                        now_iso,
                    ),
                )

            conn.execute(
                """
                UPDATE documents
                SET page_count = ?, chunk_count = ?, extracted_preview = ?,
                    processing_status = ?, error_message = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    extraction.page_count,
                    len(extraction.chunks),
                    extraction.preview_text,
                    extraction.processing_status,
                    extraction.error_message,
                    now_iso,
                    int(document_id),
                ),
            )
            self._add_log(
                conn,
                int(document_id),
                "reprocessed",
                extraction.processing_status,
                extraction.error_message
                or f"Reprocessed into {len(extraction.chunks)} chunk(s).",
                actor,
            )
        return self.get_document(int(document_id))

    def delete_document(
        self,
        document_id: int,
        upload_dir: Optional[Path] = None,
        storage: Optional[Any] = None,
    ) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT storage_filename FROM documents WHERE document_id = ?",
                (int(document_id),),
            ).fetchone()
            if row is None:
                return False
            storage_name = row["storage_filename"]
            conn.execute(
                "DELETE FROM documents WHERE document_id = ?",
                (int(document_id),),
            )

        if storage is not None and storage_name:
            try:
                storage.delete(storage_name)
            except Exception as exc:
                logger.warning("Could not delete stored document object: %s", exc)
        elif upload_dir is not None and storage_name:
            candidate = (upload_dir / storage_name).resolve()
            try:
                if upload_dir.resolve() in candidate.parents and candidate.exists():
                    candidate.unlink()
            except OSError as exc:
                logger.warning("Could not delete stored document file: %s", exc)
        return True

    def get_analytics(self) -> Dict[str, Any]:
        with self.db.connection() as conn:
            total_docs = int(
                conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            )
            approved_docs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE approval_status = 'approved' AND processing_status = 'processed'"
                ).fetchone()[0]
            )
            pending_docs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE approval_status = 'pending_review' AND processing_status != 'archived'"
                ).fetchone()[0]
            )
            failed_docs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE processing_status IN ('failed', 'OCR_REQUIRED')"
                ).fetchone()[0]
            )
            indexed_chunks = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM document_chunks AS c
                    JOIN documents AS d ON d.document_id = c.document_id
                    WHERE d.processing_status = 'processed'
                      AND d.approval_status = 'approved'
                    """
                ).fetchone()[0]
            )
            type_rows = conn.execute(
                "SELECT DISTINCT doc_type FROM documents ORDER BY doc_type ASC"
            ).fetchall()

        existing_types = [r["doc_type"] for r in type_rows]
        all_types = list(STANDARD_DOCUMENT_TYPES)
        for t in existing_types:
            if t not in all_types:
                all_types.append(t)

        return {
            "total_documents": total_docs,
            "approved_documents": approved_docs,
            "pending_review": pending_docs,
            "failed_processing": failed_docs,
            "total_indexed_chunks": indexed_chunks,
            "document_types": all_types,
        }

    def export_approved_chunks_for_index(self) -> List[Dict[str, Any]]:
        """
        Export only chunks belonging to processed, approved, non-archived,
        and non-expired documents for student retrieval indexing.
        """
        today = _today_iso()
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.document_id, c.chunk_index, c.page_number,
                       c.section_heading, c.paragraph_ref, c.chunk_text,
                       d.title AS document_title, d.doc_type, d.academic_year,
                       d.department, d.effective_date, d.expiry_date
                FROM document_chunks AS c
                JOIN documents AS d ON d.document_id = c.document_id
                WHERE d.processing_status = 'processed'
                  AND d.approval_status = 'approved'
                  AND (d.expiry_date IS NULL OR d.expiry_date >= ?)
                ORDER BY c.document_id ASC, c.chunk_index ASC
                """,
                (today,),
            ).fetchall()
        return [dict(r) for r in rows]


__all__ = [
    "DocumentRepository",
    "STANDARD_DOCUMENT_TYPES",
]
