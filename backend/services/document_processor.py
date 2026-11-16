"""
Secure Document Upload Validation, Text Extraction, and Chunking Service.

Supports:
- PDF (.pdf) via pypdf (preserves 1-indexed page numbers; detects scanned/image-only
  PDFs and marks them `OCR_REQUIRED`).
- Microsoft Word (.docx) via python-docx (preserves section headings and paragraph
  references; never invents PDF-style page numbers).
- Plain text (.txt) via standard Python UTF-8/Latin-1 decoding (preserves section
  headings and paragraph references).
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from docx import Document as DocxDocument
from pypdf import PdfReader

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
ALLOWED_MIME_TYPES = {
    ".pdf": {"application/pdf", "application/x-pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    ".txt": {"text/plain", "application/octet-stream"},
}

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_UPLOAD_DIR = (
    Path(__file__).resolve().parent.parent / "instance" / "uploads"
)
MIN_PDF_EXTRACTABLE_CHARS = 30


class DocumentValidationError(ValueError):
    """Raised when an uploaded document fails extension, MIME, size, or content checks."""


@dataclass
class ExtractedSegment:
    """A logical unit of extracted text (a PDF page or a DOCX/TXT section)."""

    text: str
    page_number: Optional[int] = None
    section_heading: Optional[str] = None
    paragraph_ref: Optional[str] = None


@dataclass
class ExtractionResult:
    """Result of extracting and chunking a stored document."""

    processing_status: str  # 'processed', 'OCR_REQUIRED', or 'failed'
    page_count: Optional[int]
    preview_text: str
    chunks: List[Dict[str, Any]]
    error_message: Optional[str] = None


def resolve_upload_dir(explicit_dir: Optional[os.PathLike] = None) -> Path:
    if explicit_dir:
        return Path(explicit_dir)
    env_dir = os.environ.get("INTELLIFAQ_UPLOAD_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return DEFAULT_UPLOAD_DIR


def get_max_upload_bytes() -> int:
    raw = os.environ.get("INTELLIFAQ_MAX_UPLOAD_BYTES", "").strip()
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return DEFAULT_MAX_UPLOAD_BYTES


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_text(text: str) -> str:
    """Normalize whitespace and line breaks without altering meaning."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _validate_magic_bytes(ext: str, content: bytes) -> None:
    if ext == ".pdf":
        if not content.lstrip().startswith(b"%PDF-"):
            raise DocumentValidationError("File content is not a valid PDF document.")
    elif ext == ".docx":
        if not content.startswith(b"PK"):
            raise DocumentValidationError("File content is not a valid DOCX archive.")
    elif ext == ".txt":
        if b"\x00" in content[:4096]:
            raise DocumentValidationError("Binary content is not allowed in .txt files.")


def validate_and_save_upload(
    file_storage: Any,
    upload_dir: Optional[Path] = None,
    max_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Validate extension, MIME type, size, and magic bytes, compute SHA-256,
    and save to a secure UUID-named file outside public frontend directories.
    """
    if file_storage is None or not getattr(file_storage, "filename", ""):
        raise DocumentValidationError("No file was provided.")

    raw_filename = str(file_storage.filename)
    # Strip any directory components to prevent path traversal
    safe_original_name = Path(raw_filename).name.strip()
    if not safe_original_name:
        raise DocumentValidationError("Invalid filename.")

    ext = Path(safe_original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError(
            f"Unsupported file format '{ext}'. Allowed formats: .pdf, .docx, .txt."
        )

    mime_type = (getattr(file_storage, "mimetype", "") or "application/octet-stream").lower()
    base_mime = mime_type.split(";")[0].strip()
    if base_mime not in ALLOWED_MIME_TYPES[ext]:
        raise DocumentValidationError(
            f"Invalid MIME type '{base_mime}' for {ext} file."
        )

    content = file_storage.read()
    if not isinstance(content, (bytes, bytearray)) or len(content) == 0:
        raise DocumentValidationError("Uploaded file is empty.")

    limit = max_bytes if max_bytes is not None else get_max_upload_bytes()
    if len(content) > limit:
        raise DocumentValidationError(
            f"File exceeds maximum allowed size of {limit // (1024 * 1024)} MB."
        )

    _validate_magic_bytes(ext, bytes(content))

    sha256_hash = compute_sha256(bytes(content))
    target_dir = resolve_upload_dir(upload_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    storage_filename = f"{uuid.uuid4().hex}{ext}"
    target_path = (target_dir / storage_filename).resolve()
    # Ensure resolved path stays strictly inside target_dir
    if target_dir.resolve() not in target_path.parents:
        raise DocumentValidationError("Invalid storage path.")

    target_path.write_bytes(content)

    return {
        "original_filename": safe_original_name,
        "storage_filename": storage_filename,
        "storage_path": target_path,
        "extension": ext,
        "mime_type": base_mime,
        "file_size": len(content),
        "sha256_hash": sha256_hash,
    }


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences while keeping punctuation intact."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def chunk_sections(
    segments: List[ExtractedSegment],
    target_size: int = 850,
    overlap: int = 125,
) -> List[Dict[str, Any]]:
    """
    Split extracted segments into overlapping chunks (approx. 700-1,000 chars)
    avoiding mid-sentence splits where possible while preserving page_number,
    section_heading, and paragraph_ref.
    """
    chunks: List[Dict[str, Any]] = []
    chunk_index = 0

    for seg in segments:
        cleaned = _normalize_text(seg.text)
        if not cleaned:
            continue

        sentences = _split_sentences(cleaned)
        if not sentences:
            sentences = [cleaned]

        current_parts: List[str] = []
        current_len = 0

        def _flush_chunk(parts: List[str]) -> None:
            nonlocal chunk_index
            text_val = " ".join(parts).strip()
            if not text_val:
                return
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "page_number": seg.page_number,
                    "section_heading": seg.section_heading,
                    "paragraph_ref": seg.paragraph_ref,
                    "chunk_text": text_val,
                    "char_count": len(text_val),
                }
            )
            chunk_index += 1

        for sent in sentences:
            # Handle a single unusually long sentence safely
            if len(sent) > target_size + 200:
                if current_parts:
                    _flush_chunk(current_parts)
                    current_parts = []
                    current_len = 0
                start = 0
                step = max(100, target_size - overlap)
                while start < len(sent):
                    slice_text = sent[start : start + target_size].strip()
                    if slice_text:
                        _flush_chunk([slice_text])
                    start += step
                continue

            if current_len + len(sent) + 1 > target_size and current_parts:
                _flush_chunk(current_parts)
                # Build sentence-level overlap tail up to `overlap` chars
                overlap_parts: List[str] = []
                overlap_len = 0
                for prev_sent in reversed(current_parts):
                    if overlap_len + len(prev_sent) + 1 <= overlap:
                        overlap_parts.insert(0, prev_sent)
                        overlap_len += len(prev_sent) + 1
                    else:
                        break
                current_parts = overlap_parts
                current_len = overlap_len

            current_parts.append(sent)
            current_len += len(sent) + 1

        if current_parts:
            _flush_chunk(current_parts)

    return chunks


def _detect_heading_from_line(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return None
    md_match = re.match(r"^#{1,4}\s+(.+)$", stripped)
    if md_match:
        return md_match.group(1).strip()
    if stripped.endswith(":"):
        return stripped[:-1].strip()
    if stripped.isupper() and len(stripped.split()) <= 10:
        return stripped.title()
    num_match = re.match(r"^(?:\d+(?:\.\d+)*\.?\s+)([A-Z][A-Za-z0-9\s,&/-]{2,70})$", stripped)
    if num_match and not stripped.endswith("."):
        return num_match.group(1).strip()
    return None


def _extract_pdf(file_path: Path) -> ExtractionResult:
    reader = PdfReader(str(file_path))
    page_count = len(reader.pages)
    segments: List[ExtractedSegment] = []
    total_chars = 0

    for idx, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        normalized = _normalize_text(raw_text)
        total_chars += len(normalized)
        if not normalized:
            continue

        # Best-effort heading detection from the first line of the page
        first_line = normalized.split("\n", 1)[0]
        heading = _detect_heading_from_line(first_line)
        segments.append(
            ExtractedSegment(
                text=normalized,
                page_number=idx,
                section_heading=heading,
                paragraph_ref=None,
            )
        )

    if page_count > 0 and total_chars < MIN_PDF_EXTRACTABLE_CHARS:
        return ExtractionResult(
            processing_status="OCR_REQUIRED",
            page_count=page_count,
            preview_text="",
            chunks=[],
            error_message=(
                "This PDF appears to be scanned or image-only (little or no "
                "extractable text found). OCR processing is not yet supported in this phase."
            ),
        )

    chunks = chunk_sections(segments)
    if not chunks:
        return ExtractionResult(
            processing_status="failed",
            page_count=page_count,
            preview_text="",
            chunks=[],
            error_message="No readable text chunks could be extracted from this PDF.",
        )

    preview = "\n\n".join(s.text for s in segments)[:2000]
    return ExtractionResult(
        processing_status="processed",
        page_count=page_count,
        preview_text=preview,
        chunks=chunks,
    )


def _extract_docx(file_path: Path) -> ExtractionResult:
    doc = DocxDocument(str(file_path))
    segments: List[ExtractedSegment] = []
    current_heading: Optional[str] = None
    buffer: List[str] = []
    para_start = 1
    para_idx = 0

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        para_idx += 1
        style_name = (para.style.name if para.style else "") or ""
        is_heading = style_name.lower().startswith("heading") or bool(
            _detect_heading_from_line(text)
        )
        if is_heading:
            if buffer:
                segments.append(
                    ExtractedSegment(
                        text="\n".join(buffer),
                        page_number=None,
                        section_heading=current_heading,
                        paragraph_ref=f"Paragraphs {para_start}-{para_idx - 1}",
                    )
                )
                buffer = []
            current_heading = _detect_heading_from_line(text) or text[:100]
            para_start = para_idx
        else:
            buffer.append(text)

    if buffer:
        segments.append(
            ExtractedSegment(
                text="\n".join(buffer),
                page_number=None,
                section_heading=current_heading,
                paragraph_ref=f"Paragraphs {para_start}-{para_idx}",
            )
        )

    chunks = chunk_sections(segments)
    if not chunks:
        return ExtractionResult(
            processing_status="failed",
            page_count=None,
            preview_text="",
            chunks=[],
            error_message="No readable text could be extracted from this DOCX file.",
        )

    preview = "\n\n".join(s.text for s in segments)[:2000]
    return ExtractionResult(
        processing_status="processed",
        page_count=None,
        preview_text=preview,
        chunks=chunks,
    )


def _extract_txt(file_path: Path) -> ExtractionResult:
    raw_bytes = file_path.read_bytes()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = raw_bytes.decode("latin-1")

    lines = content.splitlines()
    segments: List[ExtractedSegment] = []
    current_heading: Optional[str] = None
    buffer: List[str] = []
    para_start = 1
    para_idx = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        para_idx += 1
        heading = _detect_heading_from_line(stripped)
        if heading:
            if buffer:
                segments.append(
                    ExtractedSegment(
                        text="\n".join(buffer),
                        page_number=None,
                        section_heading=current_heading,
                        paragraph_ref=f"Lines {para_start}-{para_idx - 1}",
                    )
                )
                buffer = []
            current_heading = heading
            para_start = para_idx
        else:
            buffer.append(stripped)

    if buffer:
        segments.append(
            ExtractedSegment(
                text="\n".join(buffer),
                page_number=None,
                section_heading=current_heading,
                paragraph_ref=f"Lines {para_start}-{para_idx}",
            )
        )

    chunks = chunk_sections(segments)
    if not chunks:
        return ExtractionResult(
            processing_status="failed",
            page_count=None,
            preview_text="",
            chunks=[],
            error_message="The text file contains no readable content.",
        )

    preview = "\n\n".join(s.text for s in segments)[:2000]
    return ExtractionResult(
        processing_status="processed",
        page_count=None,
        preview_text=preview,
        chunks=chunks,
    )


def extract_document_content(file_path: Path, extension: str) -> ExtractionResult:
    """Extract and chunk text from a stored `.pdf`, `.docx`, or `.txt` file."""
    ext = extension.lower()
    try:
        if ext == ".pdf":
            return _extract_pdf(file_path)
        if ext == ".docx":
            return _extract_docx(file_path)
        if ext == ".txt":
            return _extract_txt(file_path)
        return ExtractionResult(
            processing_status="failed",
            page_count=None,
            preview_text="",
            chunks=[],
            error_message=f"Unsupported file extension: {ext}",
        )
    except Exception as exc:
        return ExtractionResult(
            processing_status="failed",
            page_count=None,
            preview_text="",
            chunks=[],
            error_message=f"Extraction failed: {type(exc).__name__}",
        )
