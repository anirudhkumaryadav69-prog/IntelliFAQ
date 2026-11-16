# IntelliFAQ 2.0 — Intelligent University FAQ & Document Intelligence System

IntelliFAQ 2.0 is a full-stack conversational university helpdesk and knowledge management platform. It combines an NLTK + Scikit-learn NLP FAQ engine, context-aware multi-intent and clarification workflows, persistent SQLite conversation management, an authenticated multi-admin Console, and an Official University Document Knowledge Base with extractive, citation-backed retrieval.

> **Important Disclaimer:** The initial 100-FAQ dataset in `backend/data/faqs.json` contains **sample demonstration information** and is **not verified official university policy**. Official university policies are only introduced when an authorized administrator uploads, reviews, and explicitly approves official university documents. This project is an active development milestone and is **not claimed to be production-ready**.

---

## Problem Statement

University students frequently face fragmented information across static portals, PDF handbooks, and departmental notices. Keyword-only search fails on conversational queries, follow-up questions, multi-part questions, and personalized eligibility checks, while unverified AI responses risk hallucinating institutional policies. IntelliFAQ 2.0 addresses this by:

- Resolving student queries through deterministic NLP similarity matching, multi-intent splitting, and structured clarification workflows.
- Grounding answers to official policy questions strictly in administrator-approved university documents with page, section, and passage citations.
- Providing administrators a secure web console to curate FAQs, review unanswered queries, and govern document approvals.

---

## Main Features

- **Conversational NLP Engine:** Custom NLTK preprocessing, typo/synonym normalization, TF-IDF + cosine similarity matching, multi-intent question splitting, and context-aware follow-up handling.
- **Clarification & Eligibility Workflows:** Persistent, step-by-step clarification state machine (`clarification_flows.py`) supporting personalized admission eligibility checks and disambiguation.
- **Document Intelligence & Grounded Retrieval:** Admin upload of `.pdf`, `.docx`, and `.txt` documents with magic-byte/MIME validation, SHA-256 deduplication, sentence-aware chunking, versioned archiving, approval gating, conflict disclosure, and direct-evidence arbitration over generic FAQs.
- **Persistent Conversation Management:** SQLite-backed conversation history with auto-titling, search, rename, delete, and full message persistence across reloads.
- **Multi-Admin Console & Security:** Werkzeug password hashing, `HttpOnly` session cookies, CSRF token enforcement (`X-CSRF-Token`), FAQ/category CRUD, live NLP preview, unanswered question triage, and document review/approval.

---

## Technology Stack

| Layer | Technologies |
| --- | --- |
| **Frontend** | React 19, Vite 8, JavaScript (ES Modules), CSS, Lucide React |
| **Backend** | Python 3.12, Flask, Flask-CORS, Werkzeug Security |
| **NLP & Document Processing** | NLTK, Scikit-learn (TF-IDF & cosine similarity), NumPy, `pypdf`, `python-docx` |
| **Database** | SQLite 3 (standard library `sqlite3`, schema v5 with `PRAGMA foreign_keys = ON`) |

---

## System Architecture

```text
+-----------------------+        HTTP / JSON + Cookie + CSRF        +-----------------------------+
|   React 19 + Vite 8   | <---------------------------------------> |     Flask REST API (5000)   |
|  Student Chat & Admin |                                           |  /api/chat, /api/sessions,  |
+-----------------------+                                           |  /api/admin/*               |
                                                                    +--------------+--------------+
                                                                                   |
                      +------------------------------------------------------------+------------------------------------+
                      |                                                            |                                    |
                      v                                                            v                                    v
        +---------------------------+                                +---------------------------+        +---------------------------+
        |     FAQ NLP Engine        |                                |   Document Retriever      |        |   SQLite Repositories     |
        |  preprocessor, TF-IDF,    |                                |  approved chunks TF-IDF,  |        |  conversations, faqs,     |
        |  multi-intent, flows      |                                |  evidence & citations     |        |  documents, admin_users   |
        +---------------------------+                                +---------------------------+        +---------------------------+
```

---

## Project Folder Structure

```text
IntelliFAQ/
├── .env.example
├── .gitignore
├── README.md
├── docs/
│   └── DOCUMENT_KNOWLEDGE_BASE.md
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   ├── data/
│   │   └── faqs.json                  # 100 sample FAQs & 300 phrasings
│   ├── database/
│   │   ├── db.py                      # SQLite schema v5 & connection manager
│   │   ├── conversation_repository.py
│   │   ├── document_repository.py
│   │   └── kb_repository.py
│   ├── nlp/
│   │   ├── chatbot.py
│   │   ├── clarification_flows.py
│   │   ├── document_retriever.py
│   │   └── preprocessor.py
│   ├── services/
│   │   └── document_processor.py
│   └── test_*.py                      # Automated backend test suites
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── components/                # Student chat, history & admin console UI
        └── services/                  # api.js & adminApi.js
```

---

## Prerequisites

- **Python** 3.12+
- **Node.js** 20+ and **npm**
- **Git**

---

## Backend Setup

1. Create and activate a Python virtual environment inside `backend/`:
   ```powershell
   cd backend
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
   *(On macOS/Linux: `source venv/bin/activate`)*

2. Install Python dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Frontend Setup

1. Install Node dependencies inside `frontend/`:
   ```powershell
   cd frontend
   npm install
   ```

---

## Environment Variable Configuration

Copy `.env.example` or set the variables in your shell before starting the backend:

- `INTELLIFAQ_DB_PATH`: Path to the SQLite database (defaults to `backend/instance/intellifaq.db`).
- `INTELLIFAQ_UPLOAD_DIR`: Directory for uploaded documents (defaults to `backend/instance/uploads`).
- `INTELLIFAQ_MAX_UPLOAD_BYTES`: Maximum upload size in bytes (defaults to `10485760` / 10 MB).
- `INTELLIFAQ_ADMIN_USERNAME` / `INTELLIFAQ_ADMIN_PASSWORD`: Initial administrator bootstrap credentials.
- `INTELLIFAQ_COOKIE_SECURE`: Set to `1` over HTTPS so admin session cookies set `Secure`.
- `VITE_API_BASE_URL`: Optional frontend override for the backend API URL (defaults to `http://<current-host>:5000`).

---

## Database Initialization & Admin Account Setup

- **Automatic Initialization:** On backend startup, `database/db.py` creates `backend/instance/intellifaq.db` (if missing), initializes schema version `5`, and seeds initial FAQs from `backend/data/faqs.json`.
- **Admin Bootstrap (Without Hardcoding Secrets):**
  Set `INTELLIFAQ_ADMIN_USERNAME` and `INTELLIFAQ_ADMIN_PASSWORD` in your environment before launching `python app.py` for the first time:
  ```powershell
  $env:INTELLIFAQ_ADMIN_USERNAME="admin"
  $env:INTELLIFAQ_ADMIN_PASSWORD="your-strong-password"
  ```
  Passwords are stored exclusively as Werkzeug password hashes in `admin_users`. If `INTELLIFAQ_ADMIN_PASSWORD` is omitted during initial bootstrap, the backend generates a one-time random password and logs it once at startup.

---

## Running the Application Locally

Start the backend server (from `backend/` with `venv` activated):

```powershell
python app.py
```

The Flask API runs at `http://localhost:5000`.

Start the frontend development server (from `frontend/`):

```powershell
npm run dev
```

The Vite frontend runs at `http://localhost:5173`. Access the Admin Console at `http://localhost:5173/admin`.

---

## Automated Testing

Run the backend test suites from `backend/` (with `venv` activated; all tests use isolated temporary databases/directories):

```powershell
python test_nlp.py
python test_api.py
python test_database.py
python test_eligibility.py
python test_session_management.py
python test_admin.py
python test_documents.py
python test_document_retrieval.py
```

Run frontend linting and production build verification from `frontend/`:

```powershell
npm run lint
npm run build
```

---

## Document Upload and Approval Workflow

See [docs/DOCUMENT_KNOWLEDGE_BASE.md](docs/DOCUMENT_KNOWLEDGE_BASE.md) for full details:

1. Sign in to the Admin Console (`/admin`) and open **Document Knowledge Base** (`/admin/documents`).
2. Upload a `.pdf`, `.docx`, or `.txt` file with title, document type, and academic year metadata.
3. The backend validates extension, MIME type, magic bytes, file size, and SHA-256 uniqueness, extracts text, and stores overlapping sentence-aware chunks (`pending_review`).
4. Only documents with `processing_status = 'processed'`, `approval_status = 'approved'`, and non-expired `expiry_date` are indexed for student retrieval.

---

## Current Limitations

- **No OCR:** Scanned/image-only PDFs (< 30 extractable characters) are flagged as `OCR_REQUIRED` and cannot be approved until text-based files or OCR support are provided.
- **Extractive Responses:** Grounded document responses are extractive/template-based rather than LLM-synthesized.
- **Lexical Retrieval:** Retrieval relies on TF-IDF + cosine similarity + direct-evidence scoring rather than dense semantic embeddings.
- **Development Milestone:** Built for local/academic demonstration; not hardened for production deployment without HTTPS, reverse-proxy rate limiting, and verified institutional data.

---

## Future Development Roadmap

- OCR pipeline integration for scanned university circulars and handbooks.
- Optional hybrid dense/semantic retrieval alongside TF-IDF.
- Automated scheduled expiry notifications and richer admin audit logging.
- Production deployment configuration (WSGI server, TLS termination, external secrets management).
