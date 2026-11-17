"""
Document Storage Abstraction for IntelliFAQ 2.0.

Supports:
- Local filesystem storage (`LocalDocumentStorage`) for local development and tests.
- Supabase Storage private bucket (`SupabaseDocumentStorage`, default bucket
  `intellifaq-documents`) using server-side credentials only.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .document_processor import resolve_upload_dir

try:
    from supabase import create_client
except ImportError:  # pragma: no cover - optional until supabase is installed
    create_client = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_SUPABASE_BUCKET = "intellifaq-documents"


class StorageError(RuntimeError):
    """Sanitized storage-layer error never carrying credentials or secrets."""


class DocumentStorage:
    """Base interface for storing, reading, and deleting uploaded documents."""

    backend_name: str = "base"

    def save(self, storage_filename: str, data: bytes, mime_type: str) -> None:
        raise NotImplementedError

    def read_bytes(self, storage_filename: str) -> Optional[bytes]:
        raise NotImplementedError

    def delete(self, storage_filename: str) -> bool:
        raise NotImplementedError

    def status(self) -> Dict[str, Any]:
        raise NotImplementedError


class LocalDocumentStorage(DocumentStorage):
    """Stores uploaded documents in a local directory outside web roots."""

    backend_name = "local"

    def __init__(self, upload_dir: Optional[Path] = None) -> None:
        self.upload_dir = (upload_dir or resolve_upload_dir()).resolve()

    def _safe_path(self, storage_filename: str) -> Path:
        candidate = (self.upload_dir / storage_filename).resolve()
        if self.upload_dir not in candidate.parents:
            raise StorageError("Invalid storage filename path.")
        return candidate

    def save(self, storage_filename: str, data: bytes, mime_type: str) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        target = self._safe_path(storage_filename)
        target.write_bytes(data)

    def read_bytes(self, storage_filename: str) -> Optional[bytes]:
        target = self._safe_path(storage_filename)
        if not target.exists():
            return None
        return target.read_bytes()

    def delete(self, storage_filename: str) -> bool:
        target = self._safe_path(storage_filename)
        if not target.exists():
            return False
        target.unlink()
        return True

    def status(self) -> Dict[str, Any]:
        return {
            "backend": self.backend_name,
            "configured": True,
            "bucket": None,
        }


class SupabaseDocumentStorage(DocumentStorage):
    """
    Stores uploaded documents in a private Supabase Storage bucket using
    server-side service-role credentials. Never exposes keys or public URLs.
    """

    backend_name = "supabase"

    def __init__(
        self,
        url: str,
        service_role_key: str,
        bucket: str = DEFAULT_SUPABASE_BUCKET,
        client: Optional[Any] = None,
    ) -> None:
        self.url = url.strip()
        self.service_role_key = service_role_key.strip()
        self.bucket = (bucket or DEFAULT_SUPABASE_BUCKET).strip() or DEFAULT_SUPABASE_BUCKET
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if create_client is None:
            raise StorageError("Supabase client package is not installed.")
        if not self.url or not self.service_role_key:
            raise StorageError("Supabase Storage credentials are not configured.")
        self._client = create_client(self.url, self.service_role_key)
        return self._client

    def _bucket_api(self) -> Any:
        return self._get_client().storage.from_(self.bucket)

    def save(self, storage_filename: str, data: bytes, mime_type: str) -> None:
        try:
            self._bucket_api().upload(
                path=storage_filename,
                file=data,
                file_options={"content-type": mime_type, "upsert": "false"},
            )
        except Exception as exc:
            logger.error("Supabase Storage upload failed (%s).", type(exc).__name__)
            raise StorageError("Failed to upload document to storage.") from exc

    def read_bytes(self, storage_filename: str) -> Optional[bytes]:
        try:
            result = self._bucket_api().download(storage_filename)
        except Exception as exc:
            logger.error("Supabase Storage download failed (%s).", type(exc).__name__)
            return None
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        return None

    def delete(self, storage_filename: str) -> bool:
        try:
            self._bucket_api().remove([storage_filename])
            return True
        except Exception as exc:
            logger.error("Supabase Storage delete failed (%s).", type(exc).__name__)
            return False

    def status(self) -> Dict[str, Any]:
        return {
            "backend": self.backend_name,
            "configured": bool(self.url and self.service_role_key and self.bucket),
            "bucket": self.bucket,
        }


def get_document_storage(upload_dir: Optional[Path] = None) -> DocumentStorage:
    """
    Select Supabase Storage when `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
    are configured (unless an explicit local `upload_dir` is passed).
    """
    if upload_dir is None:
        supa_url = os.environ.get("SUPABASE_URL", "").strip()
        supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if supa_url and supa_key:
            bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", DEFAULT_SUPABASE_BUCKET)
            return SupabaseDocumentStorage(
                url=supa_url,
                service_role_key=supa_key,
                bucket=bucket,
            )
    return LocalDocumentStorage(upload_dir=upload_dir)
