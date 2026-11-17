# IntelliFAQ 2.0 — Intelligent University FAQ & Document Intelligence System

IntelliFAQ 2.0 is a full-stack conversational university helpdesk and knowledge management platform. It combines an NLTK + Scikit-learn NLP FAQ engine, context-aware multi-intent and clarification workflows, dual-backend persistence (SQLite for local development, PostgreSQL for production), Supabase private Storage for uploaded documents, an authenticated multi-admin Console, and an Official University Document Knowledge Base with extractive, citation-backed retrieval.

> **Important Disclaimer:** The initial 100-FAQ dataset in `backend/data/faqs.json` contains **sample demonstration information** and is **not verified official university policy**. Official university policies are only introduced when an authorized administrator uploads, reviews, and explicitly approves official university documents.

---

## Problem Statement

University students frequently face fragmented information across static portals, PDF handbooks, and departmental notices. Keyword-only search fails on conversational queries, follow-up questions, multi-part questions, and personalized eligibility checks, while unverified AI responses risk hallucinating institutional policies. IntelliFAQ 2.0 addresses this by:

- Resolving student queries through deterministic NLP similarity matching, multi-intent splitting, and structured clarification workflows.
- Grounding answers to official policy questions strictly in administrator-approved university documents with page, section, and passage citations.
- Providing administrators a secure web console to curate FAQs, review unanswered queries, and govern document approvals.

---

## Main Features

- **Conversational NLP Engine:** Custom NLTK preprocessing, contraction/typo/synonym normalization, TF-IDF + cosine similarity matching, multi-intent question splitting, and context-aware follow-up handling.
- **Clarification & Eligibility Workflows:** Persistent, step-by-step clarification state machine (`clarification_flows.py`) supporting personalized admission eligibility checks and disambiguation.
- **Document Intelligence & Grounded Retrieval:** Admin upload of `.pdf`, `.docx`, and `.txt` documents with magic-byte/MIME validation, SHA-256 deduplication, sentence-aware chunking, versioned archiving, approval gating, conflict disclosure, and direct-evidence arbitration over generic FAQs.
- **Dual Database Architecture:** Uses SQLite (`backend/instance/intellifaq.db`) by default for local development and switches to PostgreSQL (Supabase) when `DATABASE_URL` is configured, sharing a unified repository and schema v5 contract.
- **Supabase Private Storage Integration:** Stores uploaded documents in a private Supabase Storage bucket (`intellifaq-documents`) using server-side service-role credentials, falling back to local filesystem storage (`backend/instance/uploads/`) when Supabase Storage environment variables are unset.
- **Multi-Admin Console & Security:** Werkzeug password hashing, database-backed `HttpOnly` session cookies (`SameSite=None; Secure` over HTTPS), `X-CSRF-Token` enforcement on mutations, Werkzeug `ProxyFix` for single-hop reverse proxies, FAQ/category CRUD, live NLP preview, unanswered question triage, and document review/approval.

---

## Technology Stack

| Layer | Technologies |
| --- | --- |
| **Frontend** | React 19, Vite 8, JavaScript (ES Modules), CSS, Lucide React |
| **Backend** | Python 3.12, Flask, Flask-CORS, Gunicorn, Werkzeug (`ProxyFix`, password hashing) |
| **NLP & Document Processing** | NLTK, Scikit-learn (TF-IDF & cosine similarity), NumPy, `pypdf`, `python-docx` |
| **Database** | SQLite 3 (local default, schema v5) / PostgreSQL via `psycopg[binary]` (Supabase production) |
| **File Storage** | Local filesystem (local dev) / Supabase private Storage (`supabase` SDK) |

---

## System Architecture

```text
+-----------------------+        HTTPS / JSON + Cookie + CSRF       +-----------------------------+
|   React 19 + Vite 8   | <---------------------------------------> |   Flask + Gunicorn (API)    |
|  Vercel (SPA /admin)  |                                           |  Render Web Service         |
+-----------------------+                                           +--------------+--------------+
                                                                                   |
                      +------------------------------------------------------------+------------------------------------+
                      |                                                            |                                    |
                      v                                                            v                                    v
        +---------------------------+                                +---------------------------+        +---------------------------+
        |   FAQ NLP & Doc Retriever |                                |  PostgreSQL / SQLite DB   |        |  Supabase Private Bucket  |
        |  NLTK, TF-IDF, citations, |                                |  conversations, faqs,     |        |  intellifaq-documents     |
        |  clarification flows      |                                |  documents, admin_users   |        |  (server-side access)     |
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
│   │   └── faqs.json                              # 100 sample FAQs & 300 phrasings
│   ├── database/
│   │   ├── db.py                                  # SQLite & PostgreSQL schema v5 manager
│   │   ├── conversation_repository.py
│   │   ├── document_repository.py
│   │   ├── kb_repository.py
│   │   └── migrations/
│   │       └── 001_initial_postgresql_schema.sql  # Supabase PostgreSQL schema + RLS
│   ├── nlp/
│   │   ├── chatbot.py
│   │   ├── clarification_flows.py
│   │   ├── document_retriever.py
│   │   └── preprocessor.py                        # Loads bundled or user NLTK datasets
│   ├── services/
│   │   ├── document_processor.py
│   │   └── storage.py                             # LocalDocumentStorage & SupabaseDocumentStorage
│   └── test_*.py                                  # 9 automated backend test suites
└── frontend/
    ├── index.html
    ├── package.json
    ├── vercel.json                                # SPA rewrite for /admin & client routes
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── components/                            # Student chat, history & admin console UI
        └── services/                              # api.js & adminApi.js
```

---

## Prerequisites

- **Python** 3.12+
- **Node.js** 20+ and **npm**
- **Git**

---

## Local Development Setup

### Backend Setup

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

### Frontend Setup

1. Install Node dependencies inside `frontend/`:
   ```powershell
   cd frontend
   npm install
   ```

---

## Environment Variable Configuration

Copy `.env.example` or configure variables in your environment (Render for backend, Vercel for frontend). Leave `DATABASE_URL` and `SUPABASE_*` unset locally to use SQLite and local file storage.

| Variable | Purpose | Where Configured | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection URI (`postgresql://...`) | Render (prod) | Must use Supabase's **IPv4-compatible Session Pooler** (`port 5432`, `?sslmode=require`) for Render Free. Omit locally for SQLite. |
| `SUPABASE_URL` | Supabase project URL | Render (prod) | Server-side only. |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service-role key (`sb_secret_...`) | Render (prod) | Server-side only; never expose to frontend or Git. |
| `SUPABASE_STORAGE_BUCKET` | Private Storage bucket name | Render (prod) | Defaults to `intellifaq-documents`. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Initial admin bootstrap credentials | Render / Local | Required on first PostgreSQL startup (`INTELLIFAQ_ADMIN_*` also supported). |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins | Render (prod) | Set to your deployed Vercel origin (e.g. `https://<app>.vercel.app`). |
| `INTELLIFAQ_COOKIE_SECURE` | Forces `Secure` + `SameSite=None` on admin cookies | Render (prod) | Set to `1` in production HTTPS; `0` or unset locally. |
| `INTELLIFAQ_DB_PATH` | Local SQLite path override | Local only | Defaults to `backend/instance/intellifaq.db`. |
| `INTELLIFAQ_UPLOAD_DIR` | Local upload directory override | Local only | Defaults to `backend/instance/uploads`. |
| `INTELLIFAQ_MAX_UPLOAD_BYTES` | Max document upload size in bytes | Render / Local | Defaults to `10485760` (10 MB). |
| `VITE_API_BASE_URL` | Backend origin for frontend `fetch` calls | Vercel (prod) | Must be the Render backend origin **without `/api`** (defaults locally to `http://<current-host>:5000`). |

---

## Database Initialization & Admin Account Setup

- **Local SQLite:** On startup, `backend/database/db.py` creates `backend/instance/intellifaq.db` (if missing), initializes schema v5, seeds 100 sample FAQs from `backend/data/faqs.json`, and bootstraps an initial admin account if `admin_users` is empty.
- **Production PostgreSQL:** Apply `backend/database/migrations/001_initial_postgresql_schema.sql` to Supabase PostgreSQL, configure `DATABASE_URL` + `ADMIN_USERNAME` + `ADMIN_PASSWORD`, and start the backend. Passwords are stored exclusively as Werkzeug hashes in `admin_users`.

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

## Production Deployment Architecture & Configuration

The codebase is prepared for split free-tier deployment (actual Render/Vercel service creation and live deployment are completed separately from this repository):

### Backend — Render Free Web Service

- **Root Directory:** `backend`
- **Build Command:**
  ```bash
  pip install -r requirements.txt && python -m nltk.downloader -d nltk_data punkt punkt_tab stopwords wordnet omw-1.4
  ```
  *(Downloads the 5 required NLTK datasets into `backend/nltk_data`, which `backend/nlp/preprocessor.py` registers on `nltk.data.path` at runtime.)*
- **Start Command:**
  ```bash
  gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
  ```
- **Required Render Environment Variables:** `DATABASE_URL` (Supabase IPv4 Session Pooler URI), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET=intellifaq-documents`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CORS_ORIGINS`, `INTELLIFAQ_COOKIE_SECURE=1`.

### Frontend — Vercel Hobby

- **Root Directory:** `frontend`
- **Framework Preset:** `Vite`
- **Build Command:** `npm run build`
- **Output Directory:** `dist`
- **SPA Routing:** Configured via `frontend/vercel.json` to rewrite client-side routes (such as `/admin`) to `/index.html`.
- **Required Vercel Environment Variable:** `VITE_API_BASE_URL` set to the Render backend origin **without `/api`**.

---

## Automated Testing

Run all 9 backend test suites from `backend/` (with `venv` activated; all tests use isolated temporary databases/directories):

```powershell
python test_database.py
python test_postgresql_and_storage.py
python test_documents.py
python test_document_retrieval.py
python test_admin.py
python test_session_management.py
python test_eligibility.py
python test_nlp.py
python test_api.py
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
3. The backend validates extension, MIME type, magic bytes, file size, and SHA-256 uniqueness, stores the file in Supabase private Storage (or local uploads in dev), extracts text, and stores overlapping sentence-aware chunks (`pending_review`).
4. Only documents with `processing_status = 'processed'`, `approval_status = 'approved'`, and non-expired `expiry_date` are indexed for student retrieval.

---

## Current & Free-Tier Limitations

- **No OCR:** Scanned/image-only PDFs (< 30 extractable characters) are flagged as `OCR_REQUIRED` and cannot be approved until text-based files or OCR support are provided.
- **Extractive Responses & Lexical Retrieval:** Grounded document responses are extractive/template-based using TF-IDF + cosine similarity + direct-evidence scoring rather than LLM synthesis or dense embeddings.
- **Render Free Cold Starts & Ephemeral Filesystem:** Free Render services sleep after inactivity (causing ~30–60s cold starts) and reset local disk on restart (mitigated by Supabase PostgreSQL and Supabase Storage). Keeping Gunicorn to `--workers 1` fits within the 512 MB RAM tier.
- **Cross-Region Latency:** Hosting Supabase in Tokyo and Render/Vercel in another region adds network round-trip latency on database and storage operations.
- **Cross-Site Cookie Restrictions:** Strict browser privacy modes (e.g., Safari ITP / Incognito) may block cross-origin `SameSite=None` admin session cookies between separate `.vercel.app` and `.onrender.com` domains.
