"""
Flask REST API Application for IntelliFAQ 2.0.

Provides endpoints for health monitoring, FAQ listing, context-aware multi-turn
chatbot question matching using the pre-initialized FAQChatbot engine, and
isolated conversation reset management.
"""

from functools import wraps
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import Flask, Response, g, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import BadRequest, HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from database import (
    MAX_TITLE_LENGTH,
    AdminAuthRepository,
    ConflictError,
    ConversationRepository,
    Database,
    DatabaseError,
    DocumentRepository,
    KnowledgeBaseRepository,
    UnansweredRepository,
    normalize_conversation_id,
)
from nlp import FAQChatbot
from nlp.chatbot import MATCH_AMBIGUOUS, MATCH_CLEAR, MATCH_NONE
from nlp.clarification_flows import (
    FLOW_REGISTRY,
    detect_clarification_flow_intent,
    process_clarification_turn,
)
from nlp.document_retriever import DocumentRetriever, build_grounded_response
from services import (
    DocumentValidationError,
    StorageError,
    extract_document_content,
    extract_document_content_from_bytes,
    get_document_storage,
    resolve_upload_dir,
    validate_and_save_upload,
    validate_upload_bytes,
)

# Configure application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Allowed frontend origins for CORS
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_extra_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
for _origin in _extra_origins:
    if _origin not in ALLOWED_ORIGINS:
        ALLOWED_ORIGINS.append(_origin)

# Configurable limits for SQLite-backed conversation management
DEFAULT_MAX_CONVERSATIONS = 200
DEFAULT_MAX_EXCHANGES_PER_CONVERSATION = 10
DEFAULT_MAX_STORED_EXCHANGES_PER_CONVERSATION = 50
MAX_CONVERSATION_ID_LENGTH = 128

# Category-specific domain keywords (lemmatized forms) used to detect when a
# user explicitly switches to a new institutional topic vs. asking a follow-up.
CATEGORY_DOMAIN_KEYWORDS: Dict[str, Set[str]] = {
    "Admissions": {
        "admission",
        "admit",
        "applicant",
        "counseling",
        "prospectus",
        "undergraduate",
        "postgraduate",
        "lateral",
        "entrance",
    },
    "Fee Payment": {
        "fee",
        "tuition",
        "installment",
        "upi",
        "challan",
        "netbanking",
    },
    "Attendance": {
        "attendance",
        "absent",
        "absence",
        "condonation",
        "biometric",
        "shortage",
        "detain",
        "detention",
    },
    "Examinations": {
        "exam",
        "examination",
        "midterm",
        "revaluation",
        "backlog",
        "supplementary",
        "arrear",
        "cgpa",
        "sgpa",
        "grading",
        "malpractice",
    },
    "Scholarships": {
        "scholarship",
        "stipend",
        "freeship",
        "fellowship",
        "merit",
    },
    "Campus Facilities": {
        "hostel",
        "library",
        "mess",
        "canteen",
        "cafeteria",
        "wifi",
        "transport",
        "bus",
        "shuttle",
        "gym",
        "sports",
        "clinic",
        "parking",
        "warden",
    },
    "Placements": {
        "placement",
        "internship",
        "recruiter",
        "company",
        "package",
        "salary",
        "ctc",
        "career",
        "interview",
        "ppo",
    },
}

# Surface-level patterns that signal an elliptical or context-dependent follow-up
FOLLOWUP_PHRASE_PATTERNS = re.compile(
    r"^\s*(?:"
    r"what\s+about\b|"
    r"how\s+about\b|"
    r"and\s+(?:what|how|when|where|for|if|is|are|can|do)\b|"
    r"what\s+if\b|"
    r"also\b|"
    r"what\s+documents?\b|"
    r"which\s+documents?\b|"
    r"what\s+(?:is|are)\s+the\s+deadlines?\b|"
    r"when\s+is\s+the\s+(?:deadline|last\s+date)\b|"
    r"is\s+there\s+(?:a|any)\b|"
    r"are\s+there\s+any\b|"
    r"how\s+much\s+(?:is|are|does)\b|"
    r"can\s+i\s+also\b"
    r")",
    re.IGNORECASE,
)

ANAPHORIC_PRONOUNS = {
    "it",
    "its",
    "that",
    "this",
    "they",
    "them",
    "those",
    "these",
    "there",
}


# ============================================================================
# Persistent (SQLite-backed) Conversation Manager
# ============================================================================


class ConversationManager:
    """
    Thread-safe, bounded, SQLite-backed manager for isolated multi-turn
    conversations. Public interface is unchanged from the previous in-memory
    implementation (`create_conversation`, `get_conversation`,
    `record_exchange`, `reset_conversation`), but all state now survives a
    Flask restart.

    Maintains separate context per conversation_id:
    - Every user message (original text, never internally enriched) and every
      assistant response (match metadata, candidates, multi-intent
      sub-responses) is persisted in the `messages` table.
    - `get_conversation` returns a snapshot containing the last resolved FAQ
      context, pending clarification candidates, and the most recent
      `max_exchanges` exchanges (the existing context-window policy).
    - Stored history per conversation is bounded by `max_stored_exchanges`.
    - Total stored conversations are bounded by `max_conversations`, evicting
      reset conversations first and then the least-recently-active ones.

    Note: snapshots are plain dicts; call `get_conversation` again to observe
    updates made by later requests.
    """

    def __init__(
        self,
        database: Optional[Database] = None,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_exchanges: int = DEFAULT_MAX_EXCHANGES_PER_CONVERSATION,
        max_stored_exchanges: int = DEFAULT_MAX_STORED_EXCHANGES_PER_CONVERSATION,
    ) -> None:
        self.database: Database = database if database is not None else Database()
        self.repository = ConversationRepository(self.database)
        self.max_conversations: int = max(1, int(max_conversations))
        self.max_exchanges: int = max(1, int(max_exchanges))
        self.max_stored_exchanges: int = max(
            self.max_exchanges, int(max_stored_exchanges)
        )

    def initialize(self) -> bool:
        """Create the schema if needed. Returns False (and logs) on failure."""
        try:
            self.database.initialize()
            return True
        except DatabaseError:
            logger.error(
                "Conversation storage could not be initialized at startup; "
                "initialization will be retried on the next request."
            )
            return False

    def is_healthy(self) -> bool:
        return self.database.health_check()

    def create_conversation(self) -> Dict[str, Any]:
        """
        Create a new isolated conversation with a unique UUIDv4 identifier.
        Raises DatabaseError if storage is unavailable.
        """
        return self.repository.create_conversation(self.max_conversations)

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Restore an existing conversation's context from SQLite. Returns None if
        the ID is unknown, reset, evicted or malformed. Raises DatabaseError if
        storage is unavailable.
        """
        return self.repository.get_conversation(conversation_id, self.max_exchanges)

    def record_exchange(
        self,
        conversation_id: str,
        original_user_message: str,
        nlp_response: Dict[str, Any],
    ) -> bool:
        """
        Atomically persist a completed user-assistant turn and update the
        contextual state according to the existing match classification rules:
        - clear_match: update last_faq_id, last_question, and last_category.
        - ambiguous_match: preserve prior resolved context; store pending_candidates.
        - no_reliable_match: preserve prior resolved context.
        - multi-intent: adopt the last clear sub-answer; keep pending
          candidates when any sub-question needs clarification.

        Always stores `original_user_message` (never internally enriched text).
        Returns False if the conversation no longer exists.
        """
        recorded = self.repository.record_exchange(
            conversation_id,
            original_user_message,
            nlp_response,
            self.max_stored_exchanges,
        )
        if not recorded:
            logger.warning(
                "Exchange not recorded: conversation '%s' is unknown or was reset.",
                conversation_id,
            )
        return recorded

    def reset_conversation(self, conversation_id: str) -> bool:
        """
        Delete the specified conversation's messages and context without
        affecting any other conversation. Returns True if an active
        conversation was reset, False otherwise.
        """
        return self.repository.reset_conversation(conversation_id)

    def list_conversations(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Return active conversations ordered by most recently updated."""
        return self.repository.list_conversations(limit=limit)

    def search_conversations(
        self, query: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search active conversations by title or message text."""
        return self.repository.search_conversations(query, limit=limit)

    def get_conversation_detail(
        self, conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return complete metadata, restorable context, and messages."""
        return self.repository.get_conversation_detail(conversation_id)

    def rename_conversation(
        self, conversation_id: str, new_title: str
    ) -> Optional[Dict[str, Any]]:
        """Rename an active conversation and mark its title as custom."""
        return self.repository.rename_conversation(conversation_id, new_title)

    def delete_conversation(self, conversation_id: str) -> bool:
        """Permanently delete a conversation and its associated messages."""
        return self.repository.delete_conversation(conversation_id)


# Initialize Flask app
app = Flask(__name__)
# Trust a single reverse proxy hop (Render) for X-Forwarded-For and X-Forwarded-Proto only
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)

# Configure CORS strictly for the React/Vite frontend origins
CORS(
    app,
    supports_credentials=True,
    resources={
        r"/api/*": {
            "origins": ALLOWED_ORIGINS,
            "methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Accept", "X-CSRF-Token"],
        }
    },
)

# Initialize FAQChatbot and persistent SQLite repositories ONCE at startup
chatbot: Optional[FAQChatbot] = None
chatbot_init_error: Optional[str] = None
conversation_manager = ConversationManager()
kb_repository = KnowledgeBaseRepository(conversation_manager.database)
admin_auth_repository = AdminAuthRepository(conversation_manager.database)
unanswered_repository = UnansweredRepository(conversation_manager.database)
document_repository = DocumentRepository(conversation_manager.database)
document_retriever: Optional[DocumentRetriever] = None

_db_ready = conversation_manager.initialize()
if _db_ready:
    try:
        kb_repository.seed_from_json_if_empty()
        admin_auth_repository.ensure_initial_admin()
    except DatabaseError as exc:
        logger.error("Initial knowledge-base/admin bootstrap failed: %s", exc)
        _db_ready = False

try:
    logger.info("Initializing IntelliFAQ NLP engine at startup...")
    chatbot = FAQChatbot()
    document_retriever = DocumentRetriever(preprocessor=chatbot.preprocessor)
    if _db_ready:
        db_records = kb_repository.export_for_chatbot()
        if db_records:
            ok, err = chatbot.reload_from_records(db_records)
            if not ok:
                logger.error("Failed to load FAQs from SQLite: %s", err)
        doc_chunks = document_repository.export_approved_chunks_for_index()
        document_retriever.reload_from_chunks(doc_chunks)
    if chatbot.is_ready:
        logger.info(
            "FAQChatbot initialized successfully with %d FAQs (%d variants).",
            len(chatbot.faqs),
            len(chatbot.variants_index),
        )
    else:
        chatbot_init_error = (
            chatbot.load_error or "Unknown NLP initialization failure."
        )
        logger.error("FAQChatbot failed to become ready: %s", chatbot_init_error)
except Exception as exc:
    chatbot = None
    chatbot_init_error = "Failed to initialize the NLP engine."
    logger.error("Unexpected exception during FAQChatbot startup: %s", exc)


def refresh_chatbot_index() -> Tuple[bool, Optional[str]]:
    """
    Reload the singleton FAQChatbot TF-IDF index from SQLite without restarting
    Flask. Retains the previous working index on failure.
    """
    if chatbot is None:
        return False, "NLP chatbot engine is not initialized."
    records = kb_repository.export_for_chatbot()
    return chatbot.reload_from_records(records)


def refresh_document_index() -> Tuple[bool, Optional[str]]:
    """
    Reload the DocumentRetriever TF-IDF index from approved SQLite chunks.
    Retains the previous working index on failure.
    """
    if document_retriever is None:
        return False, "Document retrieval engine is not initialized."
    chunks = document_repository.export_approved_chunks_for_index()
    return document_retriever.reload_from_chunks(chunks)


# Admin session cookie & brute-force rate-limiting helpers
ADMIN_SESSION_COOKIE = "intellifaq_admin_session"


def _admin_cookie_settings() -> Dict[str, Any]:
    """Return consistent cookie attributes for local HTTP and cross-origin HTTPS."""
    is_secure = request.is_secure or os.environ.get("INTELLIFAQ_COOKIE_SECURE") == "1"
    return {
        "httponly": True,
        "samesite": "None" if is_secure else "Lax",
        "secure": is_secure,
        "path": "/",
    }
_LOGIN_WINDOW_SECONDS = 300.0
_MAX_FAILED_LOGINS = 5
_login_attempts_lock = threading.Lock()
_failed_login_attempts: Dict[str, List[float]] = {}


def _is_rate_limited(client_ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - _LOGIN_WINDOW_SECONDS
    with _login_attempts_lock:
        recent = [t for t in _failed_login_attempts.get(client_ip, []) if t >= cutoff]
        _failed_login_attempts[client_ip] = recent
        return len(recent) >= _MAX_FAILED_LOGINS


def _record_failed_login(client_ip: str) -> None:
    now = time.monotonic()
    cutoff = now - _LOGIN_WINDOW_SECONDS
    with _login_attempts_lock:
        recent = [t for t in _failed_login_attempts.get(client_ip, []) if t >= cutoff]
        recent.append(now)
        _failed_login_attempts[client_ip] = recent


def _clear_failed_logins(client_ip: str) -> None:
    with _login_attempts_lock:
        _failed_login_attempts.pop(client_ip, None)


def require_admin_auth(fn):
    """Require a valid HttpOnly admin session cookie and CSRF token on mutations."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        session_id = request.cookies.get(ADMIN_SESSION_COOKIE)
        session = admin_auth_repository.get_session(session_id)
        if session is None:
            return (
                jsonify({"success": False, "error": "Administrator authentication required."}),
                401,
            )

        if request.method in {"POST", "PATCH", "DELETE"}:
            csrf_header = request.headers.get("X-CSRF-Token", "")
            if not csrf_header or not secrets.compare_digest(
                csrf_header, session["csrf_token"]
            ):
                return (
                    jsonify({"success": False, "error": "Invalid or missing CSRF token."}),
                    403,
                )

        g.admin_session = session
        return fn(*args, **kwargs)

    return wrapper


def _is_chatbot_ready() -> bool:
    """Return True if the global FAQChatbot instance is loaded and ready."""
    return chatbot is not None and chatbot.is_ready


# ============================================================================
# Context-Aware Follow-Up Interpretation
# ============================================================================


def _detect_explicit_categories(query_tokens: Set[str]) -> Set[str]:
    """
    Identify which FAQ categories are explicitly referenced by domain-specific
    keywords in the user's preprocessed query tokens.
    """
    matched_categories: Set[str] = set()
    for category, keywords in CATEGORY_DOMAIN_KEYWORDS.items():
        if query_tokens & keywords:
            matched_categories.add(category)
    return matched_categories


def _is_followup_or_elliptical(
    raw_message: str, query_tokens: List[str]
) -> bool:
    """
    Return True if the user message has linguistic markers of an incomplete,
    elliptical, or context-dependent follow-up question:
    1. Matches common follow-up phrasing ("What about...", "What documents...",
       "When is the deadline...", "And for...", etc.)
    2. Contains anaphoric pronouns ("it", "that", "they", "them", "this", etc.)
    3. Contains 3 or fewer preprocessed content tokens (short fragment).
    """
    if FOLLOWUP_PHRASE_PATTERNS.search(raw_message):
        return True

    raw_words = set(re.findall(r"\b[a-z]+\b", raw_message.lower()))
    if raw_words & ANAPHORIC_PRONOUNS:
        return True

    if len(query_tokens) <= 3:
        return True

    return False


def _category_has_token_overlap(
    faq_bot: FAQChatbot, category: str, user_tokens: Set[str]
) -> bool:
    """
    Verify that at least one indexed FAQ variant in `category` shares at least
    one meaningful preprocessed content token with the user's current message
    (excluding the category's own name tokens). This prevents context tokens
    alone from fabricating matches on unrelated or unsupported queries.
    """
    if not user_tokens:
        return False

    category_name_tokens = set(faq_bot.preprocessor.tokenize_and_clean(category))
    non_category_user_tokens = user_tokens - category_name_tokens
    tokens_to_check = non_category_user_tokens or user_tokens

    for variant in faq_bot.variants_index:
        if variant.get("category") != category:
            continue
        variant_tokens = set(variant.get("preprocessed", "").split())
        if variant_tokens & tokens_to_check:
            return True

    return False


def _build_clarification_flow_response(
    answer: str,
    category: str,
    next_clarification_state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a standard chat response payload for a progressive clarification
    workflow turn so the frontend renders it as a normal assistant message.
    """
    return {
        "success": True,
        "answer": answer,
        "matched_question": None,
        "category": category,
        "confidence": 100.0,
        "faq_id": None,
        "fallback": False,
        "match_type": MATCH_CLEAR,
        "candidates": [],
        "needs_clarification": False,
        "clarification_message": None,
        "is_multi_intent": False,
        "sub_responses": [],
        "_next_clarification_state": next_clarification_state,
    }


def resolve_query_with_context(
    faq_bot: FAQChatbot,
    user_message: str,
    conversation: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluate a user message using a two-stage context-aware strategy:

    Stage 1 — Standalone Evaluation:
    - Always evaluate `user_message` independently first via `faq_bot.get_response`.
    - If the query explicitly names a single category (e.g., "scholarships") and
      standalone classification was only ambiguous due to a cross-category
      candidate matching generic procedural words, reinforce that explicit
      category.
    - If the conversation has no prior context, or if the user explicitly names
      a different category than the conversation's active category, or if the
      standalone query is already a high-confidence independent clear match,
      return the standalone result without injecting prior context.

    Stage 2 — Contextual Follow-Up Resolution:
    - Triggered only when the conversation has relevant prior context
      (`last_category` / `last_question` or single-category `pending_candidates`),
      the user message does not switch to a different category, and the query
      is either elliptical/follow-up in structure or ambiguous across categories.
    - Verifies that the user's current message shares actual content tokens with
      the active category's FAQs (preventing context injection from matching
      unrelated or unsupported queries).
    - Queries the existing `FAQChatbot` with category-scoped and question-scoped
      context and returns the resulting stored FAQ answer or clarification prompt.
    """
    standalone_result = faq_bot.get_response(
        user_message,
        context_category=conversation.get("last_category"),
    )

    query_token_list = faq_bot.preprocessor.tokenize_and_clean(user_message)
    query_tokens = set(query_token_list)

    explicit_categories = _detect_explicit_categories(query_tokens)

    # Check if an active multi-turn clarification workflow is in progress
    active_clarification = conversation.get("clarification_state")
    if (
        isinstance(active_clarification, dict)
        and active_clarification.get("flow_name") in FLOW_REGISTRY
    ):
        active_flow = FLOW_REGISTRY[active_clarification["flow_name"]]
        is_topic_switch = (
            bool(standalone_result.get("is_multi_intent"))
            or (explicit_categories and active_flow.category not in explicit_categories)
            or (
                standalone_result.get("match_type") == MATCH_CLEAR
                and standalone_result.get("confidence", 0.0) >= 45.0
            )
        )
        if not is_topic_switch:
            answer, next_state = process_clarification_turn(
                active_flow, user_message, active_clarification, faq_bot
            )
            return _build_clarification_flow_response(
                answer, active_flow.category, next_state
            )
    else:
        detected_flow = detect_clarification_flow_intent(user_message, faq_bot)
        if detected_flow is not None:
            answer, next_state = process_clarification_turn(
                detected_flow, user_message, None, faq_bot
            )
            return _build_clarification_flow_response(
                answer, detected_flow.category, next_state
            )

    if standalone_result.get("is_multi_intent"):
        return standalone_result

    # If the user explicitly named a single category in their message, and
    # standalone_result was ambiguous solely because Candidate #2 came from a
    # different category (e.g., matching generic words like "procedure apply"),
    # test reinforcing the user's own explicit category.
    if (
        standalone_result["match_type"] == MATCH_AMBIGUOUS
        and len(explicit_categories) == 1
    ):
        explicit_cat = next(iter(explicit_categories))
        candidates = standalone_result.get("candidates", [])
        if (
            len(candidates) >= 2
            and candidates[0].get("category") == explicit_cat
            and candidates[1].get("category") != explicit_cat
        ):
            reinforced = faq_bot.get_response(
                f"{user_message} for {explicit_cat}"
            )
            if (
                reinforced["match_type"] == MATCH_CLEAR
                and reinforced.get("category") == explicit_cat
            ):
                standalone_result = reinforced

    # Determine active category context from conversation state
    context_category: Optional[str] = conversation.get("last_category")
    context_question: Optional[str] = conversation.get("last_question")
    pending_candidates: List[Dict[str, Any]] = conversation.get(
        "pending_candidates", []
    )

    # If no resolved category exists yet, check if pending clarification
    # candidates all belong to a single category (e.g., after an initial broad
    # question within one category such as "Tell me about semester tuition fees").
    if context_category is None and pending_candidates:
        candidate_categories = {
            c.get("category")
            for c in pending_candidates
            if isinstance(c.get("category"), str)
        }
        if len(candidate_categories) == 1:
            context_category = next(iter(candidate_categories))
        elif len(explicit_categories) == 1:
            # User replied to a multi-category clarification prompt by naming one category
            chosen_cat = next(iter(explicit_categories))
            for cand in pending_candidates:
                if cand.get("category") == chosen_cat:
                    clarified = faq_bot.get_response(
                        f"{cand.get('question', '')} {user_message}"
                    )
                    if clarified["match_type"] == MATCH_CLEAR:
                        return clarified

    # If there is no prior category context, return the standalone evaluation
    if not context_category:
        return standalone_result

    # Rule: If the user explicitly mentions a different category (topic switch),
    # treat the new question independently without injecting prior context.
    if explicit_categories and context_category not in explicit_categories:
        return standalone_result

    # Rule: If the standalone result is ALREADY a clear match in the active
    # conversation category (e.g., "What about late payment?" in Fee Payment),
    # return it directly.
    if (
        standalone_result["match_type"] == MATCH_CLEAR
        and standalone_result.get("category") == context_category
    ):
        return standalone_result

    # Rule: If the user's message already explicitly mentions `context_category`
    # and is ambiguous between two FAQs within `context_category` (intra-category
    # ambiguity), preserve the ambiguous_match rather than duplicating the
    # category keywords.
    standalone_candidates = standalone_result.get("candidates", [])
    if (
        standalone_result["match_type"] == MATCH_AMBIGUOUS
        and context_category in explicit_categories
        and len(standalone_candidates) >= 2
        and standalone_candidates[0].get("category") == context_category
        and standalone_candidates[1].get("category") == context_category
    ):
        return standalone_result

    is_followup = _is_followup_or_elliptical(user_message, query_token_list)

    # Rule: If the standalone result is a clear match in another category with
    # strong confidence and no elliptical follow-up markers, treat it as an
    # independent topic switch.
    if (
        standalone_result["match_type"] == MATCH_CLEAR
        and not is_followup
        and standalone_result.get("confidence", 0.0) >= 45.0
    ):
        return standalone_result

    # Rule: Do not apply context if the user's message has no plausible token
    # overlap with the FAQ corpus or with any FAQ in `context_category`
    # (prevents fabricating matches on unrelated/unsupported follow-ups).
    if not standalone_result.get("candidates"):
        return standalone_result

    if not _category_has_token_overlap(faq_bot, context_category, query_tokens):
        return standalone_result

    # Stage 2A: Evaluate query enriched with the active conversation category
    contextual_result = faq_bot.get_response(
        f"{user_message} for {context_category}"
    )

    if (
        contextual_result["match_type"] == MATCH_CLEAR
        and contextual_result.get("category") == context_category
    ):
        return contextual_result

    # If category enrichment produced an intra-category ambiguity (where the
    # top 2 competing candidates both belong to `context_category`), preserve
    # the ambiguous_match and ask the user for clarification rather than
    # arbitrarily forcing one candidate.
    ctx_candidates = contextual_result.get("candidates", [])
    is_intra_category_ambiguity = (
        contextual_result["match_type"] == MATCH_AMBIGUOUS
        and len(ctx_candidates) >= 2
        and ctx_candidates[0].get("category") == context_category
        and ctx_candidates[1].get("category") == context_category
    )
    if is_intra_category_ambiguity:
        return contextual_result

    # Stage 2B: If category enrichment alone remained ambiguous because a
    # candidate from another category competed with `context_category` (e.g.,
    # "What documents do I need?" in a Scholarships conversation), incorporate
    # the primary action/topic token from `context_question`.
    if context_question:
        question_tokens = faq_bot.preprocessor.tokenize_and_clean(
            context_question
        )
        for token_slice in (question_tokens[:1], question_tokens[:2]):
            context_hint = " ".join(token_slice)
            if not context_hint:
                continue
            deep_contextual_result = faq_bot.get_response(
                f"{user_message} for {context_hint} {context_category}"
            )
            if (
                deep_contextual_result["match_type"] == MATCH_CLEAR
                and deep_contextual_result.get("category") == context_category
                and deep_contextual_result.get("faq_id")
                != conversation.get("last_faq_id")
            ):
                return deep_contextual_result

    # If contextual evaluation produced a valid ambiguous match whose top
    # candidate is in `context_category`, return it so the user receives
    # relevant clarification candidates.
    if (
        contextual_result["match_type"] == MATCH_AMBIGUOUS
        and contextual_result.get("category") == context_category
    ):
        return contextual_result

    return standalone_result


def _build_chat_error_response(
    error_msg: str,
    answer_msg: str,
    status_code: int = 400,
    conversation_id: Optional[str] = None,
) -> Tuple[Response, int]:
    """
    Build a standardized error response for POST /api/chat that preserves all
    expected response fields alongside the `error` description.
    """
    return (
        jsonify(
            {
                "success": False,
                "error": error_msg,
                "answer": answer_msg,
                "matched_question": None,
                "category": None,
                "confidence": 0.0,
                "faq_id": None,
                "fallback": True,
                "match_type": MATCH_NONE,
                "candidates": [],
                "needs_clarification": False,
                "clarification_message": None,
                "is_multi_intent": False,
                "sub_responses": [],
                "conversation_id": conversation_id,
            }
        ),
        status_code,
    )


# ============================================================================
# API Endpoints
# ============================================================================


@app.route("/api/health", methods=["GET"])
def health_check() -> Tuple[Response, int]:
    """
    GET /api/health
    Returns application status, database connection/backend status, loaded FAQ
    count, and read-only document storage configuration status.
    """
    db_connected = conversation_manager.database.health_check()
    db_backend = conversation_manager.database.backend
    storage_status = get_document_storage().status()
    chatbot_ok = _is_chatbot_ready() and chatbot is not None
    faq_count = len(chatbot.faqs) if chatbot is not None else 0

    if chatbot_ok and db_connected:
        return (
            jsonify(
                {
                    "success": True,
                    "status": "ok",
                    "message": "IntelliFAQ backend service is running and healthy.",
                    "chatbot_status": "ready",
                    "faq_count": faq_count,
                    "database": {
                        "connected": True,
                        "backend": db_backend,
                    },
                    "storage": storage_status,
                }
            ),
            200,
        )

    return (
        jsonify(
            {
                "success": False,
                "status": "degraded",
                "message": chatbot_init_error
                or (
                    "Database connection is unavailable."
                    if not db_connected
                    else "NLP chatbot engine is not ready."
                ),
                "chatbot_status": "ready" if chatbot_ok else "unavailable",
                "faq_count": faq_count,
                "database": {
                    "connected": db_connected,
                    "backend": db_backend,
                },
                "storage": storage_status,
            }
        ),
        503,
    )


@app.route("/api/chat", methods=["POST"])
def chat() -> Tuple[Response, int]:
    """
    POST /api/chat
    Accepts JSON payload:
      {
        "message": "<user question>",
        "conversation_id": "<optional existing conversation ID>"
      }
    Validates input and conversation_id, resolves context-dependent follow-ups
    using the singleton FAQChatbot, updates isolated conversation state, and
    returns the standardized response fields including `conversation_id`.
    """
    if not _is_chatbot_ready() or chatbot is None:
        return _build_chat_error_response(
            error_msg="The NLP FAQ engine is currently unavailable.",
            answer_msg="The FAQ knowledge base is temporarily unavailable. Please try again later.",
            status_code=503,
        )

    # Validate JSON payload presence and syntax
    if not request.data or not request.data.strip():
        return _build_chat_error_response(
            error_msg="Request body must be valid JSON containing a 'message' field.",
            answer_msg="Please provide a valid JSON request with a question.",
            status_code=400,
        )

    try:
        payload = request.get_json(force=True)
    except BadRequest:
        return _build_chat_error_response(
            error_msg="Malformed or invalid JSON in request body.",
            answer_msg="The request could not be processed due to invalid JSON format.",
            status_code=400,
        )

    if not isinstance(payload, dict):
        return _build_chat_error_response(
            error_msg="JSON payload must be an object containing a 'message' key.",
            answer_msg="Invalid request structure. Expected a JSON object.",
            status_code=400,
        )

    # Validate required 'message' field
    if "message" not in payload or payload["message"] is None:
        return _build_chat_error_response(
            error_msg="Missing required field: 'message'.",
            answer_msg="Please include a 'message' field in your request.",
            status_code=400,
        )

    user_message = payload["message"]

    if not isinstance(user_message, str):
        return _build_chat_error_response(
            error_msg="Invalid data type: 'message' must be a string.",
            answer_msg="The 'message' field must be a text string.",
            status_code=400,
        )

    if not user_message.strip():
        empty_response = chatbot.get_response(user_message)
        empty_response["error"] = "Message cannot be empty or whitespace only."
        empty_response["conversation_id"] = None
        return jsonify(empty_response), 400

    # Validate or create conversation_id
    conversation: Optional[Dict[str, Any]] = None
    if "conversation_id" in payload and payload["conversation_id"] is not None:
        supplied_id = payload["conversation_id"]
        if not isinstance(supplied_id, str):
            return _build_chat_error_response(
                error_msg="Invalid data type: 'conversation_id' must be a string.",
                answer_msg="The supplied conversation_id must be a valid string.",
                status_code=400,
            )

        cleaned_id = supplied_id.strip()
        if not cleaned_id or len(cleaned_id) > MAX_CONVERSATION_ID_LENGTH:
            return _build_chat_error_response(
                error_msg="Malformed 'conversation_id': must be a non-empty string.",
                answer_msg="Please provide a valid non-empty conversation_id.",
                status_code=400,
            )

        conversation = conversation_manager.get_conversation(cleaned_id)
        if conversation is None:
            return _build_chat_error_response(
                error_msg=f"Unknown or expired conversation_id: '{cleaned_id}'.",
                answer_msg="The specified conversation session was not found or has expired. Please start a new conversation.",
                status_code=400,
            )
    else:
        conversation = conversation_manager.create_conversation()

    conv_id = conversation["conversation_id"]

    # Evaluate user question with conversation context awareness
    nlp_result: Dict[str, Any] = resolve_query_with_context(
        chatbot, user_message, conversation
    )

    # Combine with approved official document retrieval for standard queries
    if (
        document_retriever is not None
        and "_next_clarification_state" not in nlp_result
        and not nlp_result.get("is_multi_intent")
    ):
        doc_chunks = document_retriever.retrieve(user_message)
        nlp_result = build_grounded_response(
            nlp_result,
            doc_chunks,
            query=user_message,
            preprocessor=chatbot.preprocessor,
        )
    else:
        nlp_result.setdefault("answer_source", "faq")
        nlp_result.setdefault("document_sources", [])
        nlp_result.setdefault("supporting_passages", [])
        nlp_result.setdefault(
            "retrieval_confidence", nlp_result.get("confidence", 0.0)
        )
        nlp_result.setdefault("source_conflict", False)
        nlp_result.setdefault(
            "evidence_sufficient", not nlp_result.get("fallback", False)
        )

    # Guarantee needs_clarification is never True when candidates is empty
    if not nlp_result.get("candidates"):
        nlp_result["needs_clarification"] = False
        if nlp_result.get("match_type") == MATCH_AMBIGUOUS:
            nlp_result["match_type"] = MATCH_NONE
            nlp_result["fallback"] = True
            nlp_result["answer_source"] = "insufficient_evidence"
            nlp_result["evidence_sufficient"] = False

    # Record the original user message and response metadata in conversation history
    conversation_manager.record_exchange(conv_id, user_message, nlp_result)
    updated_conv = conversation_manager.get_conversation(conv_id)

    # Track unresolved student questions for admin review (non-blocking)
    if (
        nlp_result.get("match_type") in {MATCH_NONE, MATCH_AMBIGUOUS}
        and "_next_clarification_state" not in nlp_result
    ):
        try:
            unanswered_repository.record_unanswered(
                user_message, conv_id, nlp_result["match_type"]
            )
        except DatabaseError as exc:
            logger.warning("Could not record unanswered question: %s", exc)

    response_payload = dict(nlp_result)
    response_payload.pop("_next_clarification_state", None)
    response_payload["conversation_id"] = conv_id
    if updated_conv is not None:
        response_payload["conversation_title"] = updated_conv.get("title")
    return jsonify(response_payload), 200


@app.route("/api/conversations/reset", methods=["POST"])
def reset_conversation() -> Tuple[Response, int]:
    """
    POST /api/conversations/reset
    Accepts JSON payload {"conversation_id": "<existing-conversation-id>"}
    and clears only that conversation's in-memory state without affecting
    other active conversations.
    """
    if not request.data or not request.data.strip():
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Request body must be valid JSON containing 'conversation_id'.",
                }
            ),
            400,
        )

    try:
        payload = request.get_json(force=True)
    except BadRequest:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Malformed or invalid JSON in request body.",
                }
            ),
            400,
        )

    if not isinstance(payload, dict):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "JSON payload must be an object containing 'conversation_id'.",
                }
            ),
            400,
        )

    if "conversation_id" not in payload or payload["conversation_id"] is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Missing required field: 'conversation_id'.",
                }
            ),
            400,
        )

    supplied_id = payload["conversation_id"]
    if not isinstance(supplied_id, str):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Invalid data type: 'conversation_id' must be a string.",
                }
            ),
            400,
        )

    cleaned_id = supplied_id.strip()
    if not cleaned_id or len(cleaned_id) > MAX_CONVERSATION_ID_LENGTH:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Malformed 'conversation_id': must be a non-empty string.",
                }
            ),
            400,
        )

    was_reset = conversation_manager.reset_conversation(cleaned_id)
    if not was_reset:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Unknown or expired conversation_id: '{cleaned_id}'.",
                    "conversation_id": cleaned_id,
                }
            ),
            404,
        )

    return (
        jsonify(
            {
                "success": True,
                "message": "Conversation reset successfully.",
                "conversation_id": cleaned_id,
            }
        ),
        200,
    )


@app.route("/api/conversations", methods=["GET"])
def list_conversations_endpoint() -> Tuple[Response, int]:
    """
    GET /api/conversations
    List active conversations with IDs, titles, timestamps, and metadata.
    """
    conversations = conversation_manager.list_conversations()
    return (
        jsonify(
            {
                "success": True,
                "conversations": conversations,
                "total_count": len(conversations),
            }
        ),
        200,
    )


@app.route("/api/conversations/search", methods=["GET"])
def search_conversations_endpoint() -> Tuple[Response, int]:
    """
    GET /api/conversations/search?q=<keyword>
    Search active conversations by title or message content.
    """
    query = request.args.get("q", "", type=str)
    conversations = conversation_manager.search_conversations(query)
    return (
        jsonify(
            {
                "success": True,
                "query": query,
                "conversations": conversations,
                "total_count": len(conversations),
            }
        ),
        200,
    )


@app.route("/api/conversations/<conversation_id>", methods=["GET"])
def get_conversation_detail_endpoint(
    conversation_id: str,
) -> Tuple[Response, int]:
    """
    GET /api/conversations/<conversation_id>
    Retrieve complete conversation history and restorable context.
    """
    if normalize_conversation_id(conversation_id) is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Malformed 'conversation_id': must be a valid UUID.",
                }
            ),
            400,
        )

    detail = conversation_manager.get_conversation_detail(conversation_id)
    if detail is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Unknown or deleted conversation_id: '{conversation_id}'.",
                }
            ),
            404,
        )

    return jsonify({"success": True, "conversation": detail}), 200


@app.route("/api/conversations/<conversation_id>", methods=["PATCH"])
def rename_conversation_endpoint(conversation_id: str) -> Tuple[Response, int]:
    """
    PATCH /api/conversations/<conversation_id>
    Rename an active conversation with JSON payload {"title": "<new title>"}.
    """
    if normalize_conversation_id(conversation_id) is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Malformed 'conversation_id': must be a valid UUID.",
                }
            ),
            400,
        )

    if not request.data or not request.data.strip():
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Request body must be valid JSON containing 'title'.",
                }
            ),
            400,
        )

    try:
        payload = request.get_json(force=True)
    except BadRequest:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Malformed or invalid JSON in request body.",
                }
            ),
            400,
        )

    if not isinstance(payload, dict) or "title" not in payload:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Missing required field: 'title'.",
                }
            ),
            400,
        )

    raw_title = payload.get("title")
    if not isinstance(raw_title, str):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Invalid data type: 'title' must be a string.",
                }
            ),
            400,
        )

    cleaned_title = raw_title.strip()
    if not cleaned_title or len(cleaned_title) > MAX_TITLE_LENGTH:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Title must be between 1 and {MAX_TITLE_LENGTH} characters.",
                }
            ),
            400,
        )

    updated = conversation_manager.rename_conversation(
        conversation_id, cleaned_title
    )
    if updated is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Unknown or deleted conversation_id: '{conversation_id}'.",
                }
            ),
            404,
        )

    return jsonify({"success": True, "conversation": updated}), 200


@app.route("/api/conversations/<conversation_id>", methods=["DELETE"])
def delete_conversation_endpoint(conversation_id: str) -> Tuple[Response, int]:
    """
    DELETE /api/conversations/<conversation_id>
    Permanently delete a single conversation and its messages.
    """
    if normalize_conversation_id(conversation_id) is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Malformed 'conversation_id': must be a valid UUID.",
                }
            ),
            400,
        )

    deleted = conversation_manager.delete_conversation(conversation_id)
    if not deleted:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Unknown or already deleted conversation_id: '{conversation_id}'.",
                }
            ),
            404,
        )

    return (
        jsonify(
            {
                "success": True,
                "message": "Conversation deleted successfully.",
                "conversation_id": conversation_id,
            }
        ),
        200,
    )


# ============================================================================
# Admin Authentication & Knowledge Base Management Endpoints
# ============================================================================


@app.route("/api/admin/login", methods=["POST"])
def admin_login() -> Tuple[Response, int]:
    """Authenticate an administrator and set an HttpOnly session cookie."""
    client_ip = request.remote_addr or "unknown"
    if _is_rate_limited(client_ip):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Too many failed login attempts. Please try again later.",
                }
            ),
            429,
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return (
            jsonify({"success": False, "error": "Invalid JSON request body."}),
            400,
        )

    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return (
            jsonify({"success": False, "error": "Username and password are required."}),
            400,
        )

    admin = admin_auth_repository.verify_credentials(username, password)
    if admin is None:
        _record_failed_login(client_ip)
        return (
            jsonify({"success": False, "error": "Invalid username or password."}),
            401,
        )

    _clear_failed_logins(client_ip)
    session = admin_auth_repository.create_session(admin["admin_id"])
    resp = jsonify(
        {
            "success": True,
            "admin": {"admin_id": admin["admin_id"], "username": admin["username"]},
            "csrf_token": session["csrf_token"],
            "expires_at": session["expires_at"],
        }
    )
    cookie_opts = _admin_cookie_settings()
    resp.set_cookie(
        ADMIN_SESSION_COOKIE,
        session["session_id"],
        max_age=12 * 3600,
        **cookie_opts,
    )
    return resp, 200


@app.route("/api/admin/logout", methods=["POST"])
@require_admin_auth
def admin_logout() -> Tuple[Response, int]:
    """Invalidate the current administrator session and clear its cookie."""
    admin_auth_repository.delete_session(g.admin_session["session_id"])
    resp = jsonify({"success": True, "message": "Logged out successfully."})
    cookie_opts = _admin_cookie_settings()
    resp.delete_cookie(
        ADMIN_SESSION_COOKIE,
        path=cookie_opts["path"],
        samesite=cookie_opts["samesite"],
        secure=cookie_opts["secure"],
        httponly=cookie_opts["httponly"],
    )
    return resp, 200


@app.route("/api/admin/me", methods=["GET"])
@require_admin_auth
def admin_me() -> Tuple[Response, int]:
    """Return the authenticated administrator profile and CSRF token."""
    return (
        jsonify(
            {
                "success": True,
                "admin": {
                    "admin_id": g.admin_session["admin_id"],
                    "username": g.admin_session["username"],
                },
                "csrf_token": g.admin_session["csrf_token"],
                "expires_at": g.admin_session["expires_at"],
            }
        ),
        200,
    )


@app.route("/api/admin/dashboard", methods=["GET"])
@require_admin_auth
def admin_dashboard() -> Tuple[Response, int]:
    """Return real SQLite knowledge base, unanswered, and activity statistics."""
    stats = kb_repository.get_dashboard_stats()
    return jsonify({"success": True, "dashboard": stats}), 200


@app.route("/api/admin/faqs", methods=["GET"])
@require_admin_auth
def admin_list_faqs() -> Tuple[Response, int]:
    """List FAQs with optional search query and category_id filter."""
    search = request.args.get("q", "", type=str)
    cat_raw = request.args.get("category_id", None)
    category_id: Optional[int] = None
    if cat_raw is not None and str(cat_raw).strip():
        try:
            category_id = int(cat_raw)
        except ValueError:
            return jsonify({"success": False, "error": "Invalid category_id."}), 400

    faqs = kb_repository.list_faqs(search=search, category_id=category_id)
    return jsonify({"success": True, "faqs": faqs, "total_count": len(faqs)}), 200


@app.route("/api/admin/faqs", methods=["POST"])
@require_admin_auth
def admin_create_faq() -> Tuple[Response, int]:
    """Create a new FAQ with alternative phrasings and refresh the NLP index."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Invalid JSON request body."}), 400

    try:
        cat_id = int(payload.get("category_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Valid category_id is required."}), 400

    try:
        created = kb_repository.create_faq(
            question=payload.get("question", ""),
            answer=payload.get("answer", ""),
            category_id=cat_id,
            alternative_questions=payload.get("alternative_questions", []),
        )
    except ConflictError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    ok, err = refresh_chatbot_index()
    if not ok:
        return (
            jsonify(
                {
                    "success": False,
                    "error": err or "FAQ saved, but NLP index refresh failed.",
                    "faq": created,
                }
            ),
            500,
        )

    return jsonify({"success": True, "faq": created}), 201


@app.route("/api/admin/faqs/<int:faq_id>", methods=["GET"])
@require_admin_auth
def admin_get_faq(faq_id: int) -> Tuple[Response, int]:
    """Retrieve a single FAQ with all its alternative question phrasings."""
    faq = kb_repository.get_faq(faq_id)
    if faq is None:
        return jsonify({"success": False, "error": "FAQ not found."}), 404
    return jsonify({"success": True, "faq": faq}), 200


@app.route("/api/admin/faqs/<int:faq_id>", methods=["PATCH"])
@require_admin_auth
def admin_update_faq(faq_id: int) -> Tuple[Response, int]:
    """Update an existing FAQ and/or its alternative questions, then refresh NLP."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Invalid JSON request body."}), 400

    cat_id: Optional[int] = None
    if "category_id" in payload and payload["category_id"] is not None:
        try:
            cat_id = int(payload["category_id"])
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid category_id."}), 400

    try:
        updated = kb_repository.update_faq(
            faq_id=faq_id,
            question=payload.get("question") if "question" in payload else None,
            answer=payload.get("answer") if "answer" in payload else None,
            category_id=cat_id,
            alternative_questions=(
                payload.get("alternative_questions")
                if "alternative_questions" in payload
                else None
            ),
        )
    except ConflictError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if updated is None:
        return jsonify({"success": False, "error": "FAQ not found."}), 404

    ok, err = refresh_chatbot_index()
    if not ok:
        return (
            jsonify(
                {
                    "success": False,
                    "error": err or "FAQ updated, but NLP index refresh failed.",
                    "faq": updated,
                }
            ),
            500,
        )

    return jsonify({"success": True, "faq": updated}), 200


@app.route("/api/admin/faqs/<int:faq_id>", methods=["DELETE"])
@require_admin_auth
def admin_delete_faq(faq_id: int) -> Tuple[Response, int]:
    """Delete an FAQ (cascading alternatives) and refresh the NLP index."""
    deleted = kb_repository.delete_faq(faq_id)
    if not deleted:
        return jsonify({"success": False, "error": "FAQ not found."}), 404

    ok, err = refresh_chatbot_index()
    if not ok:
        return (
            jsonify(
                {
                    "success": False,
                    "error": err or "FAQ deleted, but NLP index refresh failed.",
                }
            ),
            500,
        )

    return jsonify({"success": True, "message": "FAQ deleted successfully."}), 200


@app.route("/api/admin/categories", methods=["GET"])
@require_admin_auth
def admin_list_categories() -> Tuple[Response, int]:
    """List all FAQ categories with their FAQ counts."""
    categories = kb_repository.list_categories()
    return jsonify({"success": True, "categories": categories}), 200


@app.route("/api/admin/categories", methods=["POST"])
@require_admin_auth
def admin_create_category() -> Tuple[Response, int]:
    """Create a new FAQ category (case-insensitive duplicate check)."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Invalid JSON request body."}), 400

    try:
        created = kb_repository.create_category(payload.get("name", ""))
    except ConflictError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    return jsonify({"success": True, "category": created}), 201


@app.route("/api/admin/categories/<int:category_id>", methods=["PATCH"])
@require_admin_auth
def admin_rename_category(category_id: int) -> Tuple[Response, int]:
    """Rename an FAQ category and refresh the NLP index."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Invalid JSON request body."}), 400

    try:
        updated = kb_repository.rename_category(category_id, payload.get("name", ""))
    except ConflictError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if updated is None:
        return jsonify({"success": False, "error": "Category not found."}), 404

    refresh_chatbot_index()
    return jsonify({"success": True, "category": updated}), 200


@app.route("/api/admin/categories/<int:category_id>", methods=["DELETE"])
@require_admin_auth
def admin_delete_category(category_id: int) -> Tuple[Response, int]:
    """
    Delete a category. If it contains FAQs, requires `reassign_to_category_id`
    in the JSON body or returns 409 Conflict without orphaning FAQs.
    """
    payload = request.get_json(silent=True) or {}
    reassign_id: Optional[int] = None
    if isinstance(payload, dict) and payload.get("reassign_to_category_id") is not None:
        try:
            reassign_id = int(payload["reassign_to_category_id"])
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": "Invalid reassign_to_category_id."}),
                400,
            )

    try:
        deleted = kb_repository.delete_category(
            category_id, reassign_to_category_id=reassign_id
        )
    except ConflictError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if not deleted:
        return jsonify({"success": False, "error": "Category not found."}), 404

    if reassign_id is not None:
        refresh_chatbot_index()
    return jsonify({"success": True, "message": "Category deleted successfully."}), 200


@app.route("/api/admin/test-chatbot", methods=["POST"])
@require_admin_auth
def admin_test_chatbot() -> Tuple[Response, int]:
    """
    Preview and test a question against the live NLP index without modifying
    student conversation history, clarification state, or unanswered tracking.
    """
    if not _is_chatbot_ready() or chatbot is None:
        return (
            jsonify({"success": False, "error": "NLP chatbot engine is unavailable."}),
            503,
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("question"), str):
        return (
            jsonify({"success": False, "error": "A 'question' string is required."}),
            400,
        )

    question = payload["question"].strip()
    if not question:
        return (
            jsonify({"success": False, "error": "Question cannot be empty."}),
            400,
        )

    raw_cleaned = chatbot.preprocessor.preprocess(question)
    normalized_query, _ = chatbot._normalize_and_correct_query(raw_cleaned)
    result = chatbot.get_response(question)

    return (
        jsonify(
            {
                "success": True,
                "preview": {
                    "original_question": question,
                    "normalized_query": normalized_query,
                    "matched_question": result.get("matched_question"),
                    "category": result.get("category"),
                    "similarity_score": result.get("confidence", 0.0),
                    "match_type": result.get("match_type"),
                    "answer": result.get("answer"),
                    "faq_id": result.get("faq_id"),
                    "candidates": result.get("candidates", []),
                    "is_multi_intent": result.get("is_multi_intent", False),
                    "sub_responses": result.get("sub_responses", []),
                },
            }
        ),
        200,
    )


@app.route("/api/admin/unanswered", methods=["GET"])
@require_admin_auth
def admin_list_unanswered() -> Tuple[Response, int]:
    """List tracked unresolved student queries with optional search and status filter."""
    search = request.args.get("q", "", type=str)
    status = request.args.get("status", "", type=str)
    try:
        items = unanswered_repository.list_unanswered(search=search, status=status)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "items": items, "total_count": len(items)}), 200


@app.route("/api/admin/unanswered/<int:item_id>", methods=["PATCH"])
@require_admin_auth
def admin_update_unanswered(item_id: int) -> Tuple[Response, int]:
    """Update review status and optional notes for an unanswered question."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Invalid JSON request body."}), 400

    try:
        updated = unanswered_repository.update_unanswered(
            item_id=item_id,
            status=payload.get("status"),
            review_notes=payload.get("review_notes"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if updated is None:
        return jsonify({"success": False, "error": "Unanswered item not found."}), 404

    return jsonify({"success": True, "item": updated}), 200


# ============================================================================
# Admin Document Knowledge Base Endpoints
# ============================================================================


@app.route("/api/admin/documents/analytics", methods=["GET"])
@require_admin_auth
def admin_document_analytics() -> Tuple[Response, int]:
    """Return document knowledge base analytics for the Admin Dashboard."""
    analytics = document_repository.get_analytics()
    return jsonify({"success": True, "analytics": analytics}), 200


@app.route("/api/admin/documents", methods=["GET"])
@require_admin_auth
def admin_list_documents() -> Tuple[Response, int]:
    """List uploaded documents with search, filtering, and pagination."""
    search = request.args.get("q", "", type=str)
    doc_type = request.args.get("doc_type", "", type=str)
    academic_year = request.args.get("academic_year", "", type=str)
    processing_status = request.args.get("processing_status", "", type=str)
    approval_status = request.args.get("approval_status", "", type=str)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    result = document_repository.list_documents(
        search=search,
        doc_type=doc_type,
        academic_year=academic_year,
        processing_status=processing_status,
        approval_status=approval_status,
        page=page,
        per_page=per_page,
    )
    return jsonify({"success": True, **result}), 200


@app.route("/api/admin/documents", methods=["POST"])
@require_admin_auth
def admin_upload_document() -> Tuple[Response, int]:
    """
    Upload an official university document (.pdf, .docx, .txt), validate it,
    extract & chunk text, and persist it with `approval_status='pending_review'`.
    """
    uploaded_file = request.files.get("file")
    title = request.form.get("title", "")
    doc_type = request.form.get("doc_type", "")
    academic_year = request.form.get("academic_year", "")
    department = request.form.get("department", "")
    description = request.form.get("description", "")
    effective_date = request.form.get("effective_date", "")
    expiry_date = request.form.get("expiry_date", "")
    supersedes_raw = request.form.get("supersedes_document_id", "")

    supersedes_id: Optional[int] = None
    if supersedes_raw and str(supersedes_raw).strip():
        try:
            supersedes_id = int(supersedes_raw)
        except ValueError:
            return (
                jsonify({"success": False, "error": "Invalid supersedes_document_id."}),
                400,
            )

    if not title.strip() or not doc_type.strip() or not academic_year.strip():
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Title, document type, and academic year are required.",
                }
            ),
            400,
        )

    storage = get_document_storage()
    validated: Optional[Dict[str, Any]] = None
    stored_filename: Optional[str] = None
    saved_to_storage = False
    try:
        validated = validate_upload_bytes(uploaded_file)
        existing_dup = document_repository.find_by_sha256(validated["sha256_hash"])
        if existing_dup is not None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Duplicate document detected: already uploaded as '{existing_dup['title']}'.",
                    }
                ),
                409,
            )

        extraction = extract_document_content_from_bytes(
            validated["content"], validated["extension"]
        )
        stored_filename = validated["storage_filename"]
        storage.save(
            stored_filename,
            validated["content"],
            validated["mime_type"],
        )
        saved_to_storage = True
        created = document_repository.create_document_with_extraction(
            title=title,
            doc_type=doc_type,
            academic_year=academic_year,
            department=department,
            description=description,
            effective_date=effective_date,
            expiry_date=expiry_date,
            original_filename=validated["original_filename"],
            storage_filename=stored_filename,
            mime_type=validated["mime_type"],
            file_size=validated["file_size"],
            sha256_hash=validated["sha256_hash"],
            uploaded_by=g.admin_session["username"],
            extraction=extraction,
            supersedes_document_id=supersedes_id,
        )
    except DocumentValidationError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except StorageError as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    except ConflictError as exc:
        if saved_to_storage and stored_filename:
            storage.delete(stored_filename)
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        if saved_to_storage and stored_filename:
            storage.delete(stored_filename)
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        if saved_to_storage and stored_filename:
            storage.delete(stored_filename)
        logger.error("Unexpected error persisting uploaded document: %s", type(exc).__name__)
        return jsonify({"success": False, "error": "Failed to persist uploaded document."}), 500

    # If replacing an approved document, refresh index so superseded doc is excluded
    if supersedes_id is not None:
        refresh_document_index()

    return jsonify({"success": True, "document": created}), 201


@app.route("/api/admin/documents/<int:document_id>", methods=["GET"])
@require_admin_auth
def admin_get_document(document_id: int) -> Tuple[Response, int]:
    """Retrieve document metadata, status, and processing logs."""
    doc = document_repository.get_document(document_id)
    if doc is None:
        return jsonify({"success": False, "error": "Document not found."}), 404
    return jsonify({"success": True, "document": doc}), 200


@app.route("/api/admin/documents/<int:document_id>/preview", methods=["GET"])
@require_admin_auth
def admin_preview_document(document_id: int) -> Tuple[Response, int]:
    """Retrieve extracted text preview and sample chunks for review."""
    limit = request.args.get("limit", 25, type=int)
    preview = document_repository.get_preview(document_id, limit=limit)
    if preview is None:
        return jsonify({"success": False, "error": "Document not found."}), 404
    return jsonify({"success": True, **preview}), 200


@app.route("/api/admin/documents/<int:document_id>", methods=["PATCH"])
@require_admin_auth
def admin_update_document(document_id: int) -> Tuple[Response, int]:
    """Update document metadata and refresh the index if the document is approved."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Invalid JSON request body."}), 400

    try:
        updated = document_repository.update_metadata(
            document_id, payload, actor=g.admin_session["username"]
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if updated is None:
        return jsonify({"success": False, "error": "Document not found."}), 404

    if updated.get("approval_status") == "approved":
        refresh_document_index()

    return jsonify({"success": True, "document": updated}), 200


@app.route("/api/admin/documents/<int:document_id>", methods=["DELETE"])
@require_admin_auth
def admin_delete_document(document_id: int) -> Tuple[Response, int]:
    """Delete a document, its chunks/logs, and stored file, then refresh index."""
    deleted = document_repository.delete_document(
        document_id, storage=get_document_storage()
    )
    if not deleted:
        return jsonify({"success": False, "error": "Document not found."}), 404

    refresh_document_index()
    return jsonify({"success": True, "message": "Document deleted successfully."}), 200


@app.route("/api/admin/documents/<int:document_id>/approve", methods=["POST"])
@require_admin_auth
def admin_approve_document(document_id: int) -> Tuple[Response, int]:
    """Approve a processed document and refresh the student retrieval index."""
    try:
        doc = document_repository.approve_document(
            document_id, actor=g.admin_session["username"]
        )
    except ConflictError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409

    if doc is None:
        return jsonify({"success": False, "error": "Document not found."}), 404

    ok, err = refresh_document_index()
    if not ok:
        return (
            jsonify(
                {
                    "success": False,
                    "error": err or "Approved document, but index refresh failed.",
                    "document": doc,
                }
            ),
            500,
        )
    return jsonify({"success": True, "document": doc}), 200


@app.route("/api/admin/documents/<int:document_id>/reject", methods=["POST"])
@require_admin_auth
def admin_reject_document(document_id: int) -> Tuple[Response, int]:
    """Reject a document so it cannot be retrieved by students."""
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason", "") if isinstance(payload, dict) else ""
    doc = document_repository.reject_document(
        document_id, actor=g.admin_session["username"], reason=str(reason)
    )
    if doc is None:
        return jsonify({"success": False, "error": "Document not found."}), 404

    refresh_document_index()
    return jsonify({"success": True, "document": doc}), 200


@app.route("/api/admin/documents/<int:document_id>/archive", methods=["POST"])
@require_admin_auth
def admin_archive_document(document_id: int) -> Tuple[Response, int]:
    """Archive a document and exclude it from the student retrieval index."""
    doc = document_repository.archive_document(
        document_id, actor=g.admin_session["username"]
    )
    if doc is None:
        return jsonify({"success": False, "error": "Document not found."}), 404

    refresh_document_index()
    return jsonify({"success": True, "document": doc}), 200


@app.route("/api/admin/documents/<int:document_id>/reprocess", methods=["POST"])
@require_admin_auth
def admin_reprocess_document(document_id: int) -> Tuple[Response, int]:
    """Re-run text extraction and chunking on a stored document."""
    info = document_repository.get_storage_filename(document_id)
    if info is None:
        return jsonify({"success": False, "error": "Document not found."}), 404

    storage = get_document_storage()
    raw_bytes = storage.read_bytes(info["storage_filename"])
    if raw_bytes is None:
        return (
            jsonify({"success": False, "error": "Stored document file is missing."}),
            404,
        )

    ext = Path(info["original_filename"]).suffix.lower()
    extraction = extract_document_content_from_bytes(raw_bytes, ext)
    doc = document_repository.reprocess_document(
        document_id, extraction, actor=g.admin_session["username"]
    )
    if doc and doc.get("approval_status") == "approved":
        refresh_document_index()
    return jsonify({"success": True, "document": doc}), 200


@app.route("/api/faqs", methods=["GET"])
def list_faqs() -> Tuple[Response, int]:
    """
    GET /api/faqs
    Returns total FAQ count, available categories, and public FAQ directory
    (id, canonical question, and category) without exposing internal vectors
    or alternative phrasing arrays.
    """
    if not _is_chatbot_ready() or chatbot is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "The FAQ knowledge base is currently unavailable.",
                    "total_count": 0,
                    "categories": [],
                    "faqs": [],
                }
            ),
            503,
        )

    sanitized_faqs = [
        {
            "id": faq.get("id"),
            "question": faq.get("question"),
            "category": faq.get("category"),
        }
        for faq in chatbot.faqs
    ]

    return (
        jsonify(
            {
                "success": True,
                "total_count": len(sanitized_faqs),
                "categories": chatbot.get_categories(),
                "faqs": sanitized_faqs,
            }
        ),
        200,
    )


# ============================================================================
# Global Error Handlers (Never expose stack traces)
# ============================================================================


@app.errorhandler(400)
def handle_bad_request(error: HTTPException) -> Tuple[Response, int]:
    """Return clean JSON for 400 Bad Request errors."""
    return (
        jsonify(
            {
                "success": False,
                "error": "Bad request. Please verify your request payload.",
            }
        ),
        400,
    )


@app.errorhandler(404)
def handle_not_found(error: HTTPException) -> Tuple[Response, int]:
    """Return clean JSON for 404 Not Found errors."""
    return (
        jsonify(
            {
                "success": False,
                "error": "The requested API endpoint does not exist.",
            }
        ),
        404,
    )


@app.errorhandler(405)
def handle_method_not_allowed(error: HTTPException) -> Tuple[Response, int]:
    """Return clean JSON for 405 Method Not Allowed errors."""
    return (
        jsonify(
            {
                "success": False,
                "error": "HTTP method not allowed for this endpoint.",
            }
        ),
        405,
    )


@app.errorhandler(Exception)
def handle_unexpected_exception(error: Exception) -> Tuple[Response, int]:
    """Catch-all handler for unhandled internal server errors without stack traces."""
    if isinstance(error, HTTPException) and error.code is not None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": error.description or "HTTP error occurred.",
                }
            ),
            error.code,
        )

    logger.error("Unhandled internal server error: %s", error)
    return (
        jsonify(
            {
                "success": False,
                "error": "An internal server error occurred. Please try again later.",
            }
        ),
        500,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
