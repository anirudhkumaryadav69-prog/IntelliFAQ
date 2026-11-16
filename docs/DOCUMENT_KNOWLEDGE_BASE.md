# IntelliFAQ 2.0 — Official University Document Knowledge Base

> **Important Notice:** The initial 100-FAQ dataset (`backend/data/faqs.json`) contains **sample demonstration information** and is **not** verified official university policy. Official university policies are only introduced when an authorized administrator uploads, reviews, and explicitly approves official university documents.

---

## 1. Supported Document Formats

| Format | Extension | Extraction Engine | Attribution Support |
| --- | --- | --- | --- |
| PDF | `.pdf` | `pypdf` | 1-indexed page numbers + best-effort section headings |
| Microsoft Word | `.docx` | `python-docx` | Section headings (`Heading` styles) + paragraph ranges |
| Plain Text | `.txt` | Python UTF-8 / Latin-1 | Section headings + line ranges |

Scanned / image-only PDFs (containing fewer than 30 extractable characters) are automatically flagged as `OCR_REQUIRED` and cannot be approved until text-based PDFs or future OCR support are provided.

---

## 2. File Storage & Environment Configuration

Uploaded files are stored outside all publicly accessible frontend directories using generated UUID filenames. Original filenames are preserved only as database metadata.

- `INTELLIFAQ_DB_PATH`: Path to the SQLite database (defaults to `backend/instance/intellifaq.db`).
- `INTELLIFAQ_UPLOAD_DIR`: Directory for uploaded documents (defaults to `backend/instance/uploads`).
- `INTELLIFAQ_MAX_UPLOAD_BYTES`: Maximum upload size in bytes (defaults to `10485760` / 10 MB).
- `INTELLIFAQ_ADMIN_USERNAME` / `INTELLIFAQ_ADMIN_PASSWORD`: Administrator credentials for initial bootstrap.

---

## 3. Upload Procedure & Security

1. Sign in to the Admin Console (`/admin`) and navigate to **Document Knowledge Base** (`/admin/documents`).
2. Click **Upload Document** and provide:
   - Title, Document Type (11 standard types or custom), Academic Year, and optional Department, Description, Effective Date, and Expiry/Review Date.
   - A `.pdf`, `.docx`, or `.txt` file.
3. The backend validates file extension, MIME type, magic-byte file signature, size limit, and SHA-256 hash (rejecting duplicates with HTTP `409`).
4. All admin endpoints require an `HttpOnly` session cookie and an `X-CSRF-Token` header on mutations.

---

## 4. Processing Lifecycle & Approval Workflow

- **Processing Statuses:** `uploaded`, `processing`, `processed`, `failed`, `OCR_REQUIRED`, `archived`.
- **Approval Statuses:** `pending_review` (default on upload), `approved`, `rejected`.
- **Chunking Strategy:** Normalized text is split into sentence-aware overlapping chunks (`target_size = 850` characters, `overlap = 125` characters) in `document_chunks`.
- **Versioning:** Uploading a replacement with `supersedes_document_id` increments `version` and automatically archives the previous version without discarding it.
- **Publication Rule:** Only documents with `processing_status = 'processed'`, `approval_status = 'approved'`, and non-expired `expiry_date` are indexed for student retrieval.

---

## 5. Document Retrieval & Citation Behavior

- `DocumentRetriever` (`backend/nlp/document_retriever.py`) indexes approved document chunks using NLTK preprocessing and `TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, norm="l2")` with `threading.RLock()` for thread-safe live index refreshes.
- Strong FAQ matches (`confidence >= 55%`) are preserved (`faq` or `faq_and_document`). When FAQs are weak or unmatched and an approved document chunk meets the retrieval threshold (`>= 18%`), an extractive grounded answer is returned (`answer_source = "document"`) with expandable **Sources used** citations (Title, Page/Section/Paragraph, and supporting passage).
- If multiple distinct approved documents report conflicting numeric/percentage values, `source_conflict = true` is set and both sources are disclosed.

---

## 6. Known Limitations

- OCR for scanned/image-only PDFs is not yet implemented (`OCR_REQUIRED` status).
- Responses are extractive/template-grounded rather than LLM-synthesized (no external paid LLM API is required).
- Retrieval relies on lexical TF-IDF + cosine similarity rather than dense semantic embeddings.
