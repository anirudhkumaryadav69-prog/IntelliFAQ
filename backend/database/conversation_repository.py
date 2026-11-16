"""
Conversation persistence repository for IntelliFAQ 2.0.

All SQL is parameterized. Every multi-statement write (create + eviction,
exchange recording + context update + pruning, reset) runs in a single
transaction so a partial failure can never leave a conversation inconsistent.

Structured fields (pending clarification candidates, per-message candidates and
multi-intent sub-responses) are stored as JSON text and whitelisted to known
keys before persistence.
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .db import Database

logger = logging.getLogger(__name__)

MATCH_CLEAR = "clear_match"
MATCH_AMBIGUOUS = "ambiguous_match"
MATCH_NONE = "no_reliable_match"
VALID_MATCH_TYPES = {MATCH_CLEAR, MATCH_AMBIGUOUS, MATCH_NONE}

DEFAULT_CONVERSATION_TITLE = "New Conversation"
MAX_TITLE_LENGTH = 120

_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"tell\s+me\s+(?:whether|if)?\s*|"
    r"can\s+you\s+(?:please\s+)?(?:tell\s+me\s+|check\s+)?|"
    r"could\s+you\s+(?:please\s+)?(?:tell\s+me\s+|check\s+)?|"
    r"please\s+(?:tell\s+me\s+|check\s+)?|"
    r"i\s+(?:want|would\s+like|need)\s+to\s+know\s+|"
    r"what\s+(?:is|are)\s+(?:the\s+)?|"
    r"how\s+(?:can|do)\s+i\s+|"
    r"when\s+(?:is|are|do)\s+(?:the\s+)?|"
    r"where\s+(?:is|are|can)\s+(?:the\s+)?"
    r")+",
    re.IGNORECASE,
)

_ACRONYM_MAP = {
    "b.tech": "B.Tech",
    "btech": "B.Tech",
    "m.tech": "M.Tech",
    "mtech": "M.Tech",
    "cse": "CSE",
    "ece": "ECE",
    "bba": "BBA",
    "mba": "MBA",
    "bca": "BCA",
    "mca": "MCA",
    "b.sc": "B.Sc",
    "m.sc": "M.Sc",
    "b.com": "B.Com",
    "m.com": "M.Com",
    "ph.d": "Ph.D",
    "tfw": "TFW",
    "ews": "EWS",
    "upi": "UPI",
    "cgpa": "CGPA",
    "sgpa": "SGPA",
    "erp": "ERP",
    "faq": "FAQ",
    "wi-fi": "Wi-Fi",
    "wifi": "Wi-Fi",
}

_STOP_WORDS_TITLE = {"a", "an", "the", "of", "for", "in", "on", "to", "and", "or", "is", "are"}


def generate_conversation_title(
    user_message: str, nlp_response: Optional[Dict[str, Any]] = None
) -> str:
    """
    Deterministically generate a concise 3-7 word conversation title from the
    user's initial meaningful message (and optional clarification state).
    """
    if not isinstance(user_message, str) or not user_message.strip():
        return DEFAULT_CONVERSATION_TITLE

    redacted = redact_sensitive_text(user_message).strip()

    # Check if an admission eligibility clarification flow was initiated
    if isinstance(nlp_response, dict):
        next_state = nlp_response.get("_next_clarification_state")
        if (
            isinstance(next_state, dict)
            and next_state.get("flow_name") == "admission_eligibility"
        ):
            prog = (next_state.get("slots") or {}).get("programme")
            if prog:
                return f"{prog} Admission Eligibility"[:MAX_TITLE_LENGTH]
            return "Admission Eligibility Check"

    cleaned = _TITLE_PREFIX_RE.sub("", redacted).strip()
    cleaned = re.sub(r"[?!.,;:\"'()\[\]{}]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        cleaned = re.sub(r"[?!.,;:\"'()\[\]{}]+", " ", redacted).strip()

    words = cleaned.split()
    if not words:
        return DEFAULT_CONVERSATION_TITLE

    # Keep up to 7 words, trimming trailing stop words for cleaner titles
    selected = words[:7]
    while len(selected) > 3 and selected[-1].lower() in _STOP_WORDS_TITLE:
        selected.pop()

    formatted_words: List[str] = []
    for idx, word in enumerate(selected):
        low = word.lower()
        if low in _ACRONYM_MAP:
            formatted_words.append(_ACRONYM_MAP[low])
        elif idx > 0 and low in _STOP_WORDS_TITLE:
            formatted_words.append(low)
        else:
            formatted_words.append(word.capitalize())

    title = " ".join(formatted_words).strip()
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip()
    return title or DEFAULT_CONVERSATION_TITLE

CANDIDATE_KEYS = ("faq_id", "question", "category", "similarity")
SUB_RESPONSE_KEYS = (
    "query",
    "answer",
    "matched_question",
    "category",
    "confidence",
    "faq_id",
    "fallback",
    "match_type",
    "candidates",
    "needs_clarification",
    "clarification_message",
)

REDACTION_PLACEHOLDER = "[REDACTED]"

# Credential assignments such as "password: hunter2" or "my api key is abc123".
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|passcode|api[\s_-]?key|secret[\s_-]?key|client[\s_-]?secret|"
    r"access[\s_-]?token|auth[\s_-]?token|otp)\b(\s*(?:is|:|=)\s*)(\S+)"
)
# Well-known API key / token formats.
_KEY_FORMAT_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*")
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _passes_luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def redact_sensitive_text(text: Any) -> str:
    """
    Remove obvious secrets (credentials, API keys, bearer tokens and
    payment-card numbers) from text before it is persisted. The live NLP
    response is unaffected; this only guards stored conversation records.
    """
    if not isinstance(text, str) or not text:
        return "" if text is None else str(text)

    redacted = _CREDENTIAL_ASSIGNMENT_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTION_PLACEHOLDER}", text
    )
    redacted = _KEY_FORMAT_RE.sub(REDACTION_PLACEHOLDER, redacted)
    redacted = _BEARER_RE.sub(f"Bearer {REDACTION_PLACEHOLDER}", redacted)

    def _card_sub(match: re.Match) -> str:
        digits = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _passes_luhn(digits):
            return REDACTION_PLACEHOLDER
        return match.group(0)

    return _CARD_CANDIDATE_RE.sub(_card_sub, redacted)


def normalize_conversation_id(value: Any) -> Optional[str]:
    """Return the canonical lowercase UUID string, or None if invalid."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if len(candidate) != 36:
        return None
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError):
        return None


def _as_int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sanitize_candidates(candidates: Any) -> List[Dict[str, Any]]:
    if not isinstance(candidates, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        cleaned.append(
            {
                "faq_id": _as_int_or_none(cand.get("faq_id")),
                "question": str(cand.get("question") or ""),
                "category": cand.get("category") if isinstance(cand.get("category"), str) else None,
                "similarity": _as_float(cand.get("similarity")),
            }
        )
    return cleaned


def _sanitize_sub_responses(sub_responses: Any) -> List[Dict[str, Any]]:
    if not isinstance(sub_responses, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for sub in sub_responses:
        if not isinstance(sub, dict):
            continue
        match_type = sub.get("match_type")
        cleaned.append(
            {
                "query": redact_sensitive_text(sub.get("query") or ""),
                "answer": str(sub.get("answer") or ""),
                "matched_question": sub.get("matched_question"),
                "category": sub.get("category"),
                "confidence": _as_float(sub.get("confidence")),
                "faq_id": _as_int_or_none(sub.get("faq_id")),
                "fallback": bool(sub.get("fallback", False)),
                "match_type": match_type if match_type in VALID_MATCH_TYPES else MATCH_NONE,
                "candidates": _sanitize_candidates(sub.get("candidates")),
                "needs_clarification": bool(sub.get("needs_clarification", False)),
                "clarification_message": sub.get("clarification_message"),
            }
        )
    return cleaned


def _loads_json_list(raw: Any) -> List[Any]:
    if not isinstance(raw, str) or not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Discarding malformed JSON column value in conversation storage.")
        return []
    return parsed if isinstance(parsed, list) else []


def _loads_json_dict(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Discarding malformed JSON dict column value in conversation storage.")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def derive_context_update(
    current: Dict[str, Any], nlp_response: Dict[str, Any]
) -> Tuple[Optional[int], Optional[str], Optional[str], List[Dict[str, Any]]]:
    """
    Apply the existing IntelliFAQ context rules (unchanged from the in-memory
    ConversationManager) and return the new
    (last_faq_id, last_question, last_category, pending_candidates):

    - Multi-intent: adopt the LAST clear_match sub-response as resolved context;
      store pending candidates if any sub-question needs clarification.
    - clear_match: update resolved context and clear pending candidates.
    - ambiguous_match: preserve resolved context; store pending candidates.
    - no_reliable_match: preserve everything.
    """
    last_faq_id = current.get("last_faq_id")
    last_question = current.get("last_question")
    last_category = current.get("last_category")
    pending = list(current.get("pending_candidates") or [])

    match_type = nlp_response.get("match_type", MATCH_NONE)

    if nlp_response.get("is_multi_intent"):
        clear_subs = [
            s
            for s in nlp_response.get("sub_responses", []) or []
            if isinstance(s, dict) and s.get("match_type") == MATCH_CLEAR
        ]
        if clear_subs:
            last_clear = clear_subs[-1]
            last_faq_id = _as_int_or_none(last_clear.get("faq_id"))
            last_question = last_clear.get("matched_question")
            last_category = last_clear.get("category")
        if nlp_response.get("needs_clarification"):
            pending = _sanitize_candidates(nlp_response.get("candidates", []))
        elif clear_subs:
            pending = []
    elif match_type == MATCH_CLEAR:
        last_faq_id = _as_int_or_none(nlp_response.get("faq_id"))
        last_question = nlp_response.get("matched_question")
        last_category = nlp_response.get("category")
        pending = []
    elif match_type == MATCH_AMBIGUOUS:
        pending = _sanitize_candidates(nlp_response.get("candidates", []))

    return last_faq_id, last_question, last_category, pending


class ConversationRepository:
    """SQLite-backed storage for conversations and their messages."""

    def __init__(self, database: Database) -> None:
        self.db = database

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    def create_conversation(self, max_conversations: int) -> Dict[str, Any]:
        """
        Insert a new conversation with a UUIDv4 identifier. If the stored
        conversation count has reached `max_conversations`, evict reset
        (inactive) conversations first, then the least-recently-active ones.
        Eviction and insertion share one transaction.
        """
        conv_id = str(uuid.uuid4())
        now_iso = _utc_now_iso()
        evicted: List[str] = []

        with self.db.transaction() as conn:
            total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            overflow = total - max_conversations + 1
            if overflow > 0:
                rows = conn.execute(
                    """
                    SELECT conversation_id FROM conversations
                    ORDER BY is_active ASC, last_activity_seq ASC, rowid ASC
                    LIMIT ?
                    """,
                    (overflow,),
                ).fetchall()
                evicted = [row["conversation_id"] for row in rows]
                conn.executemany(
                    "DELETE FROM conversations WHERE conversation_id = ?",
                    [(cid,) for cid in evicted],
                )

            next_seq = conn.execute(
                "SELECT COALESCE(MAX(last_activity_seq), 0) + 1 FROM conversations"
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, created_at, updated_at,
                    last_resolved_faq_id, last_resolved_question, last_resolved_category,
                    pending_candidates, clarification_state, title, is_title_custom,
                    is_active, last_activity_seq
                ) VALUES (?, ?, ?, NULL, NULL, NULL, '[]', '{}', ?, 0, 1, ?)
                """,
                (conv_id, now_iso, now_iso, DEFAULT_CONVERSATION_TITLE, next_seq),
            )

        for cid in evicted:
            logger.info(
                "Evicted conversation '%s' to enforce max_conversations=%d.",
                cid,
                max_conversations,
            )

        return {
            "conversation_id": conv_id,
            "title": DEFAULT_CONVERSATION_TITLE,
            "is_title_custom": False,
            "created_at": now_iso,
            "updated_at": now_iso,
            "last_faq_id": None,
            "last_question": None,
            "last_category": None,
            "pending_candidates": [],
            "clarification_state": {},
            "history": [],
            "is_active": True,
        }

    def get_conversation(
        self, conversation_id: Any, history_limit: int
    ) -> Optional[Dict[str, Any]]:
        """
        Load an ACTIVE conversation's context and its most recent
        `history_limit` exchanges. Returns None for unknown, reset or
        malformed IDs.
        """
        conv_id = normalize_conversation_id(conversation_id)
        if conv_id is None:
            return None

        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT conversation_id, title, is_title_custom, created_at, updated_at,
                       last_resolved_faq_id, last_resolved_question,
                       last_resolved_category, pending_candidates,
                       clarification_state, is_active
                FROM conversations
                WHERE conversation_id = ? AND is_active = 1
                """,
                (conv_id,),
            ).fetchone()
            if row is None:
                return None

            exchange_rows = conn.execute(
                """
                SELECT a.message_id, a.created_at, a.match_type, a.faq_id,
                       a.matched_question, a.category, a.confidence, a.fallback,
                       a.needs_clarification, a.is_multi_intent, a.sub_responses,
                       u.message_text AS user_message, u.created_at AS user_created_at
                FROM messages AS a
                LEFT JOIN messages AS u ON u.message_id = a.reply_to_message_id
                WHERE a.conversation_id = ? AND a.role = 'assistant'
                ORDER BY a.message_id DESC
                LIMIT ?
                """,
                (conv_id, max(1, int(history_limit))),
            ).fetchall()

        history = [
            {
                "timestamp": r["user_created_at"] or r["created_at"],
                "user_message": r["user_message"] or "",
                "match_type": r["match_type"],
                "faq_id": r["faq_id"],
                "matched_question": r["matched_question"],
                "category": r["category"],
                "confidence": r["confidence"] if r["confidence"] is not None else 0.0,
                "fallback": bool(r["fallback"]),
                "needs_clarification": bool(r["needs_clarification"]),
                "is_multi_intent": bool(r["is_multi_intent"]),
                "sub_responses": _loads_json_list(r["sub_responses"]),
            }
            for r in reversed(exchange_rows)
        ]

        return {
            "conversation_id": row["conversation_id"],
            "title": row["title"] or DEFAULT_CONVERSATION_TITLE,
            "is_title_custom": bool(row["is_title_custom"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_faq_id": row["last_resolved_faq_id"],
            "last_question": row["last_resolved_question"],
            "last_category": row["last_resolved_category"],
            "pending_candidates": _loads_json_list(row["pending_candidates"]),
            "clarification_state": _loads_json_dict(row["clarification_state"]),
            "history": history,
            "is_active": bool(row["is_active"]),
        }

    def record_exchange(
        self,
        conversation_id: Any,
        original_user_message: str,
        nlp_response: Dict[str, Any],
        max_stored_exchanges: int,
    ) -> bool:
        """
        Atomically persist the user message, the assistant response (with
        candidates and multi-intent sub-responses), update the resolved /
        pending context, bump activity ordering and prune old exchanges.
        Returns False if the conversation is unknown or has been reset.
        """
        conv_id = normalize_conversation_id(conversation_id)
        if conv_id is None:
            return False

        now_iso = _utc_now_iso()
        match_type = nlp_response.get("match_type")
        if match_type not in VALID_MATCH_TYPES:
            match_type = MATCH_NONE

        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT last_resolved_faq_id, last_resolved_question,
                       last_resolved_category, pending_candidates,
                       title, is_title_custom
                FROM conversations
                WHERE conversation_id = ? AND is_active = 1
                """,
                (conv_id,),
            ).fetchone()
            if row is None:
                return False

            user_cursor = conn.execute(
                """
                INSERT INTO messages (conversation_id, role, message_text, created_at)
                VALUES (?, 'user', ?, ?)
                """,
                (conv_id, redact_sensitive_text(original_user_message), now_iso),
            )
            user_message_id = user_cursor.lastrowid

            conn.execute(
                """
                INSERT INTO messages (
                    conversation_id, role, message_text, created_at, match_type,
                    category, faq_id, confidence, is_multi_intent, matched_question,
                    fallback, needs_clarification, clarification_message,
                    candidates, sub_responses, reply_to_message_id
                ) VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conv_id,
                    str(nlp_response.get("answer") or ""),
                    now_iso,
                    match_type,
                    nlp_response.get("category"),
                    _as_int_or_none(nlp_response.get("faq_id")),
                    _as_float(nlp_response.get("confidence")),
                    1 if nlp_response.get("is_multi_intent") else 0,
                    nlp_response.get("matched_question"),
                    1 if nlp_response.get("fallback") else 0,
                    1 if nlp_response.get("needs_clarification") else 0,
                    nlp_response.get("clarification_message"),
                    json.dumps(_sanitize_candidates(nlp_response.get("candidates"))),
                    json.dumps(_sanitize_sub_responses(nlp_response.get("sub_responses"))),
                    user_message_id,
                ),
            )

            current_state = {
                "last_faq_id": row["last_resolved_faq_id"],
                "last_question": row["last_resolved_question"],
                "last_category": row["last_resolved_category"],
                "pending_candidates": _loads_json_list(row["pending_candidates"]),
            }
            last_faq_id, last_question, last_category, pending = derive_context_update(
                current_state, nlp_response
            )

            next_seq = conn.execute(
                "SELECT COALESCE(MAX(last_activity_seq), 0) + 1 FROM conversations"
            ).fetchone()[0]
            next_clarification_state = nlp_response.get("_next_clarification_state")
            if not isinstance(next_clarification_state, dict):
                next_clarification_state = {}

            current_title = row["title"] or DEFAULT_CONVERSATION_TITLE
            is_title_custom = bool(row["is_title_custom"])
            if not is_title_custom and current_title == DEFAULT_CONVERSATION_TITLE:
                updated_title = generate_conversation_title(
                    original_user_message, nlp_response
                )
            else:
                updated_title = current_title

            conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?,
                    last_resolved_faq_id = ?,
                    last_resolved_question = ?,
                    last_resolved_category = ?,
                    pending_candidates = ?,
                    clarification_state = ?,
                    title = ?,
                    last_activity_seq = ?
                WHERE conversation_id = ?
                """,
                (
                    now_iso,
                    last_faq_id,
                    last_question,
                    last_category,
                    json.dumps(pending),
                    json.dumps(next_clarification_state),
                    updated_title,
                    next_seq,
                    conv_id,
                ),
            )

            # Retention: keep only the newest `max_stored_exchanges` user turns.
            # Deleting a user message cascades to its assistant reply.
            conn.execute(
                """
                DELETE FROM messages
                WHERE conversation_id = ? AND role = 'user'
                  AND message_id NOT IN (
                      SELECT message_id FROM messages
                      WHERE conversation_id = ? AND role = 'user'
                      ORDER BY message_id DESC
                      LIMIT ?
                  )
                """,
                (conv_id, conv_id, max(1, int(max_stored_exchanges))),
            )
        return True

    def reset_conversation(self, conversation_id: Any) -> bool:
        """
        Delete ALL messages of one conversation and clear its context in a
        single transaction, marking it inactive so the ID can no longer be
        used. Other conversations are untouched. Returns False for unknown,
        malformed or already-reset IDs (idempotent and safe to repeat).
        """
        conv_id = normalize_conversation_id(conversation_id)
        if conv_id is None:
            return False

        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ? AND is_active = 1",
                (conv_id,),
            ).fetchone()
            if row is None:
                return False

            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            conn.execute(
                """
                UPDATE conversations
                SET is_active = 0,
                    updated_at = ?,
                    last_resolved_faq_id = NULL,
                    last_resolved_question = NULL,
                    last_resolved_category = NULL,
                    pending_candidates = '[]',
                    clarification_state = '{}'
                WHERE conversation_id = ?
                """,
                (_utc_now_iso(), conv_id),
            )
        return True

    # ------------------------------------------------------------------
    # Dashboard & Session Management (list, search, detail, rename, delete)
    # ------------------------------------------------------------------
    def _row_to_summary(self, row: Any) -> Dict[str, Any]:
        clar_state = _loads_json_dict(row["clarification_state"])
        return {
            "conversation_id": row["conversation_id"],
            "title": row["title"] or DEFAULT_CONVERSATION_TITLE,
            "is_title_custom": bool(row["is_title_custom"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_faq_id": row["last_resolved_faq_id"],
            "last_question": row["last_resolved_question"],
            "last_category": row["last_resolved_category"],
            "message_count": int(row["message_count"] or 0),
            "has_active_clarification": bool(
                isinstance(clar_state, dict) and clar_state.get("flow_name")
            ),
        }

    def list_conversations(self, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Return active conversations ordered by most recently updated, along
        with message counts and metadata (no fake/demo records).
        """
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.conversation_id, c.title, c.is_title_custom,
                       c.created_at, c.updated_at,
                       c.last_resolved_faq_id, c.last_resolved_question,
                       c.last_resolved_category, c.clarification_state,
                       COUNT(m.message_id) AS message_count
                FROM conversations AS c
                LEFT JOIN messages AS m
                    ON m.conversation_id = c.conversation_id
                WHERE c.is_active = 1
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC, c.last_activity_seq DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_to_summary(r) for r in rows]

    def search_conversations(
        self, query: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search active conversations by title or message content using SQLite
        case-insensitive partial matching (read-only; never modifies data).
        """
        cleaned = query.strip() if isinstance(query, str) else ""
        if not cleaned:
            return self.list_conversations(limit=limit)

        escaped = (
            cleaned.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"

        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.conversation_id, c.title, c.is_title_custom,
                       c.created_at, c.updated_at,
                       c.last_resolved_faq_id, c.last_resolved_question,
                       c.last_resolved_category, c.clarification_state,
                       COUNT(m_all.message_id) AS message_count
                FROM conversations AS c
                LEFT JOIN messages AS m_all
                    ON m_all.conversation_id = c.conversation_id
                WHERE c.is_active = 1
                  AND (
                      LOWER(c.title) LIKE LOWER(?) ESCAPE '\\'
                      OR EXISTS (
                          SELECT 1 FROM messages AS m_hit
                          WHERE m_hit.conversation_id = c.conversation_id
                            AND LOWER(m_hit.message_text) LIKE LOWER(?) ESCAPE '\\'
                      )
                  )
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC, c.last_activity_seq DESC
                LIMIT ?
                """,
                (pattern, pattern, max(1, int(limit))),
            ).fetchall()
        return [self._row_to_summary(r) for r in rows]

    def get_conversation_detail(
        self, conversation_id: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve an active conversation's full metadata, restorable context,
        and complete chronological message history.
        """
        conv_id = normalize_conversation_id(conversation_id)
        if conv_id is None:
            return None

        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT conversation_id, title, is_title_custom,
                       created_at, updated_at,
                       last_resolved_faq_id, last_resolved_question,
                       last_resolved_category, pending_candidates,
                       clarification_state, is_active
                FROM conversations
                WHERE conversation_id = ? AND is_active = 1
                """,
                (conv_id,),
            ).fetchone()
            if row is None:
                return None

        messages = self.get_messages(conv_id)
        return {
            "conversation_id": row["conversation_id"],
            "title": row["title"] or DEFAULT_CONVERSATION_TITLE,
            "is_title_custom": bool(row["is_title_custom"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_faq_id": row["last_resolved_faq_id"],
            "last_question": row["last_resolved_question"],
            "last_category": row["last_resolved_category"],
            "pending_candidates": _loads_json_list(row["pending_candidates"]),
            "clarification_state": _loads_json_dict(row["clarification_state"]),
            "is_active": bool(row["is_active"]),
            "messages": messages,
        }

    def rename_conversation(
        self, conversation_id: Any, new_title: str
    ) -> Optional[Dict[str, Any]]:
        """
        Update a conversation's title and mark `is_title_custom = 1` so future
        turns do not overwrite it. Returns the updated summary, or None if
        the conversation does not exist or is inactive.
        """
        conv_id = normalize_conversation_id(conversation_id)
        if conv_id is None:
            return None

        cleaned = new_title.strip() if isinstance(new_title, str) else ""
        if not cleaned or len(cleaned) > MAX_TITLE_LENGTH:
            raise ValueError(
                f"Title must be between 1 and {MAX_TITLE_LENGTH} characters."
            )

        now_iso = _utc_now_iso()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE conversations
                SET title = ?,
                    is_title_custom = 1,
                    updated_at = ?
                WHERE conversation_id = ? AND is_active = 1
                """,
                (cleaned, now_iso, conv_id),
            )
            if cursor.rowcount == 0:
                return None

            row = conn.execute(
                """
                SELECT c.conversation_id, c.title, c.is_title_custom,
                       c.created_at, c.updated_at,
                       c.last_resolved_faq_id, c.last_resolved_question,
                       c.last_resolved_category, c.clarification_state,
                       COUNT(m.message_id) AS message_count
                FROM conversations AS c
                LEFT JOIN messages AS m
                    ON m.conversation_id = c.conversation_id
                WHERE c.conversation_id = ?
                GROUP BY c.conversation_id
                """,
                (conv_id,),
            ).fetchone()
        return self._row_to_summary(row) if row is not None else None

    def delete_conversation(self, conversation_id: Any) -> bool:
        """
        Permanently delete a single conversation and its messages (via ON DELETE
        CASCADE) in one transaction without affecting other conversations.
        Returns True if deleted, False if nonexistent or malformed.
        """
        conv_id = normalize_conversation_id(conversation_id)
        if conv_id is None:
            return False

        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ? AND is_active = 1",
                (conv_id,),
            ).fetchone()
            if row is None:
                return False

            conn.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conv_id,),
            )
        return True

    # ------------------------------------------------------------------
    # Inspection helpers (diagnostics / tests)
    # ------------------------------------------------------------------
    def count_conversations(self, active_only: bool = True) -> int:
        query = "SELECT COUNT(*) FROM conversations"
        if active_only:
            query += " WHERE is_active = 1"
        with self.db.connection() as conn:
            return int(conn.execute(query).fetchone()[0])

    def get_messages(self, conversation_id: Any) -> List[Dict[str, Any]]:
        """Return every stored message for a conversation in chronological order."""
        conv_id = normalize_conversation_id(conversation_id)
        if conv_id is None:
            return []
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT message_id, conversation_id, role, message_text, created_at,
                       match_type, category, faq_id, confidence, is_multi_intent,
                       matched_question, fallback, needs_clarification,
                       clarification_message, candidates, sub_responses,
                       reply_to_message_id
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, message_id ASC
                """,
                (conv_id,),
            ).fetchall()

        messages: List[Dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            item["is_multi_intent"] = bool(item["is_multi_intent"])
            item["fallback"] = bool(item["fallback"])
            item["needs_clarification"] = bool(item["needs_clarification"])
            item["candidates"] = _loads_json_list(item["candidates"])
            item["sub_responses"] = _loads_json_list(item["sub_responses"])
            messages.append(item)
        return messages


__all__ = [
    "ConversationRepository",
    "DEFAULT_CONVERSATION_TITLE",
    "MAX_TITLE_LENGTH",
    "derive_context_update",
    "generate_conversation_title",
    "normalize_conversation_id",
    "redact_sensitive_text",
]
