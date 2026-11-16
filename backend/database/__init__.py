"""
Persistent SQLite storage layer for IntelliFAQ 2.0 conversations.

The FAQ knowledge base itself remains in `data/faqs.json`; only conversation
state and message history are stored here.
"""

from .conversation_repository import (
    DEFAULT_CONVERSATION_TITLE,
    MAX_TITLE_LENGTH,
    ConversationRepository,
    derive_context_update,
    generate_conversation_title,
    normalize_conversation_id,
    redact_sensitive_text,
)
from .db import (
    DB_PATH_ENV_VAR,
    SCHEMA_VERSION,
    Database,
    DatabaseError,
    resolve_database_path,
)
from .document_repository import (
    STANDARD_DOCUMENT_TYPES,
    DocumentRepository,
)
from .kb_repository import (
    VALID_UNANSWERED_STATUSES,
    AdminAuthRepository,
    ConflictError,
    KnowledgeBaseRepository,
    UnansweredRepository,
)

__all__ = [
    "AdminAuthRepository",
    "ConflictError",
    "ConversationRepository",
    "DB_PATH_ENV_VAR",
    "DEFAULT_CONVERSATION_TITLE",
    "Database",
    "DatabaseError",
    "DocumentRepository",
    "KnowledgeBaseRepository",
    "MAX_TITLE_LENGTH",
    "SCHEMA_VERSION",
    "STANDARD_DOCUMENT_TYPES",
    "UnansweredRepository",
    "VALID_UNANSWERED_STATUSES",
    "derive_context_update",
    "generate_conversation_title",
    "normalize_conversation_id",
    "redact_sensitive_text",
    "resolve_database_path",
]
