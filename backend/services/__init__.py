"""Document processing and extraction services for IntelliFAQ 2.0."""

from .document_processor import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    DEFAULT_MAX_UPLOAD_BYTES,
    DocumentValidationError,
    ExtractionResult,
    chunk_sections,
    compute_sha256,
    extract_document_content,
    extract_document_content_from_bytes,
    resolve_upload_dir,
    validate_and_save_upload,
    validate_upload_bytes,
)
from .storage import (
    DocumentStorage,
    LocalDocumentStorage,
    StorageError,
    SupabaseDocumentStorage,
    get_document_storage,
)

__all__ = [
    "ALLOWED_EXTENSIONS",
    "ALLOWED_MIME_TYPES",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "DocumentStorage",
    "DocumentValidationError",
    "ExtractionResult",
    "LocalDocumentStorage",
    "StorageError",
    "SupabaseDocumentStorage",
    "chunk_sections",
    "compute_sha256",
    "extract_document_content",
    "extract_document_content_from_bytes",
    "get_document_storage",
    "resolve_upload_dir",
    "validate_and_save_upload",
    "validate_upload_bytes",
]
