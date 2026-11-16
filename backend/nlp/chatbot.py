"""
TF-IDF & Cosine Similarity FAQ Matching Engine for IntelliFAQ.

Loads the structured FAQ knowledge base from backend/data/faqs.json,
indexes all primary and alternative question phrasings into a single
TF-IDF vector space at initialization, retrieves and ranks the top 3
distinct FAQ candidates using cosine similarity, classifies matches as
clear_match, ambiguous_match, or no_reliable_match, and generates
clarification prompts when multiple plausible FAQ matches exist.
"""

import difflib
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .preprocessor import TextPreprocessor

logger = logging.getLogger(__name__)

# Reliable default path to backend/data/faqs.json relative to this file
DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "faqs.json"
)

# Default configurable matching and ambiguity thresholds (0.0 to 1.0 scale)
DEFAULT_CONFIDENCE_THRESHOLD = 0.20   # 20.0% minimum similarity for a plausible match
DEFAULT_CLEAR_MATCH_THRESHOLD = 0.34  # 34.0% minimum similarity for a clear match
DEFAULT_AMBIGUITY_MARGIN = 0.08       # 8.0% minimum lead over #2 candidate
DEFAULT_HIGH_CERTAINTY_SCORE = 0.85   # 85.0%+ near-exact match bypasses margin check
DEFAULT_TOP_K = 3                     # Number of distinct FAQ candidates to retrieve

# Ranking penalty multiplier applied to candidates whose fee subtopic intent
# conflicts with the detected fee subtopic intent of the user query
INCOMPATIBLE_FEE_INTENT_PENALTY = 0.55

# Benign query modifiers that should not trigger out-of-vocabulary coverage
# penalties when the query already contains valid in-vocabulary domain terms
BENIGN_QUERY_MODIFIERS: Set[str] = {
    "per",
    "total",
    "cost",
    "price",
    "rate",
    "use",
    "using",
    "via",
    "overall",
    "exact",
    "current",
    "full",
    "complete",
    "accidentally",
    "let",
    "website",
}

# Common student abbreviations, synonyms, and high-frequency domain typos
QUERY_TOKEN_SYNONYMS: Dict[str, str] = {
    "ug": "undergraduate",
    "pg": "postgraduate",
    "btech": "undergraduate",
    "mtech": "postgraduate",
    "datesheet": "timetable",
    "dorm": "hostel",
    "dormitory": "hostel",
    "tution": "tuition",
    "admsision": "admission",
    "attendence": "attendance",
    "examintion": "examination",
    "scholership": "scholarship",
    "hostle": "hostel",
    "placeemnt": "placement",
    "placeemnts": "placement",
    "revalution": "revaluation",
    "eligibilty": "eligibility",
    "timtable": "timetable",
    "certifcate": "certificate",
}

# Specific domain/category anchor tokens; standalone short queries (<= 3 tokens)
# that contain none of these anchors (e.g., "Eligibility?", "application form?")
# are inherently cross-category ambiguous and trigger clarification.
CATEGORY_ANCHOR_TOKENS: Set[str] = {
    "admission",
    "admit",
    "undergraduate",
    "postgraduate",
    "bachelor",
    "lateral",
    "nri",
    "entrance",
    "counseling",
    "fee",
    "tuition",
    "upi",
    "challan",
    "neft",
    "rtgs",
    "installment",
    "refund",
    "caution",
    "receipt",
    "invoice",
    "attendance",
    "absent",
    "condonation",
    "biometric",
    "detain",
    "detention",
    "shortage",
    "exam",
    "examination",
    "midterm",
    "timetable",
    "hall",
    "cgpa",
    "sgpa",
    "revaluation",
    "rechecking",
    "backlog",
    "supplementary",
    "arrear",
    "transcript",
    "malpractice",
    "scribe",
    "scholarship",
    "stipend",
    "fellowship",
    "tfw",
    "ews",
    "nsp",
    "bonafide",
    "library",
    "hostel",
    "wifi",
    "medical",
    "infirmary",
    "ambulance",
    "bus",
    "transport",
    "shuttle",
    "gym",
    "gymnasium",
    "sport",
    "mess",
    "canteen",
    "cafeteria",
    "club",
    "counselor",
    "wellness",
    "ragging",
    "grievance",
    "atm",
    "parking",
    "placement",
    "internship",
    "noc",
    "recruiter",
    "jaf",
    "ppo",
    "interview",
    "resume",
}

# Generic institutional container tokens that should not produce a match on their
# own when the user's query also contains out-of-vocabulary subject nouns
# (e.g., "book international airline tickets through the student ERP portal")
GENERIC_INSTITUTIONAL_CONTAINER_TOKENS: Set[str] = {
    "university",
    "college",
    "campus",
    "student",
    "undergraduate",
    "postgraduate",
    "semester",
    "course",
    "program",
    "department",
    "office",
    "portal",
    "erp",
    "online",
    "website",
    "class",
    "lecture",
    "hall",
    "international",
    "book",
    "ticket",
    "check",
    "apply",
    "get",
    "official",
}

# Match classification constants
MATCH_CLEAR = "clear_match"
MATCH_AMBIGUOUS = "ambiguous_match"
MATCH_NONE = "no_reliable_match"

# Domain terms that indicate an institutional/university question even when
# the specific topic is unsupported by the FAQ dataset
UNIVERSITY_DOMAIN_TERMS = {
    "university",
    "college",
    "campus",
    "student",
    "professor",
    "faculty",
    "dean",
    "chancellor",
    "registrar",
    "department",
    "semester",
    "degree",
    "course",
    "subject",
    "syllabus",
    "curriculum",
    "class",
    "lecture",
    "admission",
    "fee",
    "tuition",
    "exam",
    "examination",
    "attendance",
    "scholarship",
    "hostel",
    "library",
    "placement",
    "internship",
    "convocation",
    "alumni",
    "portal",
    "erp",
}

FALLBACK_UNRELATED_MESSAGE = (
    "I could not find a match for your question in our FAQ knowledge base. "
    "IntelliFAQ is designed to answer institutional questions across "
    "Admissions, Fee Payment, Attendance, Examinations, Scholarships, "
    "Campus Facilities, and Placements. Please ask a question related to "
    "these academic or campus topics."
)

FALLBACK_UNSUPPORTED_UNIVERSITY_MESSAGE = (
    "Your question appears to be related to university or academic matters, "
    "but this specific topic is not covered in our current FAQ demonstration "
    "dataset. Please consult the relevant university administrative office or "
    "official student portal, or try asking about Admissions, Fee Payment, "
    "Attendance, Examinations, Scholarships, Campus Facilities, or Placements."
)

INVALID_INPUT_MESSAGE = (
    "Please enter a valid question so I can search the FAQ knowledge base."
)

UNAVAILABLE_KB_MESSAGE = (
    "The FAQ knowledge base is currently unavailable. Please contact the "
    "system administrator."
)


class FAQChatbot:
    """
    NLP-powered FAQ retrieval engine using NLTK preprocessing, Scikit-learn
    TF-IDF vectorization, top-K distinct candidate ranking, and threshold-based
    match classification (clear_match, ambiguous_match, no_reliable_match).
    """

    def __init__(
        self,
        dataset_path: Optional[Union[str, Path]] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        clear_match_threshold: float = DEFAULT_CLEAR_MATCH_THRESHOLD,
        ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
        top_k: int = DEFAULT_TOP_K,
        preprocessor: Optional[TextPreprocessor] = None,
    ) -> None:
        """
        Initialize the FAQChatbot and fit the TF-IDF vectorizer once.

        Args:
            dataset_path: Optional custom path to faqs.json. Defaults to
                backend/data/faqs.json.
            confidence_threshold: Minimum cosine similarity (on 0.0–1.0 scale)
                required to consider any FAQ candidate plausible.
            clear_match_threshold: Minimum cosine similarity (on 0.0–1.0 scale)
                required to classify a top match as a clear_match.
            ambiguity_margin: Minimum similarity lead (on 0.0–1.0 scale) the #1
                candidate must have over the #2 plausible candidate to avoid
                being classified as an ambiguous_match.
            top_k: Maximum number of distinct FAQ candidates to return (default 3).
            preprocessor: Optional TextPreprocessor instance.
        """
        self.dataset_path: Path = (
            Path(dataset_path) if dataset_path is not None else DEFAULT_DATASET_PATH
        )
        self.confidence_threshold: float = float(
            np.clip(confidence_threshold, 0.0, 1.0)
        )
        self.clear_match_threshold: float = float(
            np.clip(
                max(clear_match_threshold, self.confidence_threshold),
                0.0,
                1.0,
            )
        )
        self.ambiguity_margin: float = float(
            np.clip(ambiguity_margin, 0.0, 1.0)
        )
        self.top_k: int = max(1, int(top_k))
        self.preprocessor: TextPreprocessor = preprocessor or TextPreprocessor()

        self.faqs: List[Dict[str, Any]] = []
        self.variants_index: List[Dict[str, Any]] = []
        self.faq_intents: Dict[Any, Set[str]] = {}
        self.domain_words: Set[str] = set()
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix: Any = None
        self.is_ready: bool = False
        self.load_error: Optional[str] = None
        self._index_lock = threading.RLock()

        self._initialize_knowledge_base()

    def _normalize_and_correct_query(
        self, cleaned_query: str
    ) -> tuple[str, bool]:
        """
        Apply lightweight domain synonym normalization and fuzzy spelling
        correction (edit-distance >= 0.84 with matching initial character)
        for out-of-vocabulary tokens against the indexed FAQ vocabulary.

        Returns:
            Tuple of (normalized_query_string, has_uncorrected_oov_token).
        """
        if not cleaned_query or self.vectorizer is None:
            return cleaned_query, False

        # Preserve exact matches to any indexed variant untouched
        for entry in self.variants_index:
            if entry["preprocessed"] == cleaned_query:
                return cleaned_query, False

        vocab = self.vectorizer.vocabulary_
        tokens = cleaned_query.split()
        corrected_tokens: List[str] = []
        has_uncorrected_oov = False

        for tok in tokens:
            if tok in QUERY_TOKEN_SYNONYMS:
                corrected_tokens.append(QUERY_TOKEN_SYNONYMS[tok])
                continue

            if tok in vocab or tok in BENIGN_QUERY_MODIFIERS:
                corrected_tokens.append(tok)
                continue

            if len(tok) >= 5 and tok.isalpha() and self.domain_words:
                same_initial = [
                    w
                    for w in self.domain_words
                    if w[0] == tok[0] and abs(len(w) - len(tok)) <= 2
                ]
                close = difflib.get_close_matches(
                    tok, same_initial, n=1, cutoff=0.84
                )
                if close:
                    corrected_tokens.append(close[0])
                    continue

            corrected_tokens.append(tok)
            has_uncorrected_oov = True

        return " ".join(corrected_tokens), has_uncorrected_oov

    @staticmethod
    def _detect_fee_intents(raw_text: str, cleaned_text: str) -> Set[str]:
        """
        Detect fine-grained fee subtopic intents from raw and preprocessed text
        so the ranking engine can distinguish between:
        - fee_amount (fee structure, tuition fee amount, how much to pay per semester, total fee)
        - payment_method (how/where to pay fees, online modes, UPI, card, net banking, DD, NEFT)
        - payment_deadline (deadline, last date, due date for fee payment)
        - late_payment (late fee, penalty, fine, paying fees late, missing fee deadline)
        - fee_refund (fee refund policy, admission cancellation refund, caution deposit refund)
        - fee_receipt (download fee receipt, invoice, payment confirmation)
        - transaction_issue (failed fee payment, amount debited/deducted, unpaid status)
        - fee_installment (installments, part payment, split tuition fee)
        - pending_dues (pending fee dues, outstanding balance, no-dues clearance)
        - education_loan (demand letter, fee estimation certificate for bank loan)
        - auxiliary_fees (hostel, mess, bus/transport fees paid separately)
        - scholarship_adjustment (fee waiver/scholarship adjustment)
        - exam_fee (examination / backlog / supplementary registration fees)
        - admission_withdrawal (admission withdrawal/cancellation without refund context)
        """
        if not isinstance(raw_text, str) or not raw_text.strip():
            return set()

        lowered = raw_text.lower().strip()
        tokens = set(cleaned_text.split())

        fee_domain_signals = {
            "fee",
            "fees",
            "tuition",
            "pay",
            "paying",
            "paid",
            "payment",
            "payments",
            "upi",
            "challan",
            "neft",
            "rtgs",
            "installment",
            "installments",
            "refund",
            "refunded",
            "refundable",
            "receipt",
            "invoice",
            "debit",
            "debited",
            "deduct",
            "deducted",
            "due",
            "dues",
            "fine",
            "penalty",
            "cost",
            "charge",
            "charges",
            "caution",
        }
        raw_words = set(re.findall(r"\b[a-z0-9]+\b", lowered))
        has_fee_signal = bool((tokens | raw_words) & fee_domain_signals) or bool(
            re.search(
                r"\bhow\s+much\b.*\b(semester|course|program|tuition|college|university)\b",
                lowered,
            )
        )

        # Admission withdrawal/cancellation without any fee/refund context (e.g., FAQ #13)
        if (
            (tokens & {"withdraw", "withdrawal", "cancel", "cancellation"})
            and "admission" in tokens
            and not (
                (tokens | raw_words)
                & {"refund", "refunded", "refundable", "fee", "fees", "tuition", "caution", "deposit"}
            )
        ):
            return {"admission_withdrawal"}

        if not has_fee_signal:
            return set()

        intents: Set[str] = set()

        # 1. Refund & cancellation refund
        if (tokens | raw_words) & {
            "refund",
            "refunded",
            "refundable",
            "reimburse",
            "reimbursement",
        } or re.search(
            r"\b(caution\s+money|caution\s+deposit|security\s+deposit|money\s+back)\b",
            lowered,
        ):
            intents.add("fee_refund")

        # 2. Fee receipt & payment confirmation
        if (tokens | raw_words) & {"receipt", "receipts", "invoice"} or re.search(
            r"\b(payment\s+confirmation|duplicate\s+fee\s+receipt)\b", lowered
        ):
            intents.add("fee_receipt")

        # 3. Failed payment / transaction issues (exclude "debit card" which is a payment instrument)
        has_debit_card = bool(re.search(r"\bdebit\s+cards?\b", lowered))
        if (tokens | raw_words) & {
            "debited",
            "deduct",
            "deducted",
            "unpaid",
            "reconciliation",
        } or ("debit" in (tokens | raw_words) and not has_debit_card) or (
            (tokens | raw_words) & {"fail", "failed", "failure"}
            and (tokens | raw_words) & {"pay", "payment", "fee", "fees", "transaction", "online"}
        ):
            intents.add("transaction_issue")

        # 4. Installments / part payment
        if (tokens | raw_words) & {
            "installment",
            "installments",
            "instalment",
            "instalments",
        } or re.search(
            r"\b(part\s+payment|split\s+(?:my\s+)?(?:tuition\s+|semester\s+)?fee)\b",
            lowered,
        ):
            intents.add("fee_installment")

        # 5. Pending dues / outstanding balance (exclude caution deposit refund no-dues)
        if "fee_refund" not in intents and (
            re.search(
                r"\b(pending\s+(?:fee\s+)?dues|outstanding\s+(?:fee\s+)?balance|fee\s+dues|no\s*[-]?\s*dues)\b",
                lowered,
            )
        ):
            intents.add("pending_dues")

        # 6. Education loan demand letter / bonafide fee structure
        if re.search(
            r"\b(education\s+loan|bank\s+loan|demand\s+letter|estimation\s+certificate)\b",
            lowered,
        ):
            intents.add("education_loan")

        # 7. Auxiliary fees (hostel, mess, transport)
        if (tokens | raw_words) & {
            "hostel",
            "mess",
            "bus",
            "transport",
            "transportation",
            "residential",
        } and (tokens | raw_words) & {"fee", "fees", "tuition", "charge", "charges", "pay"}:
            intents.add("auxiliary_fees")

        # 8. Scholarship / fee waiver adjustment
        if (tokens | raw_words) & {"scholarship", "scholarships", "waiver", "waivers", "tfw"} and (
            tokens | raw_words
        ) & {"adjust", "adjusted", "upfront", "reimbursement", "fee", "fees", "tuition"}:
            intents.add("scholarship_adjustment")

        # 9. Examination / backlog / supplementary registration fees
        if (
            (tokens | raw_words)
            & {"exam", "examination", "backlog", "supplementary", "revaluation"}
            and (tokens | raw_words) & {"fee", "fees", "pay", "payment"}
            and "pending_dues" not in intents
        ):
            intents.add("exam_fee")

        # 10. Late payment & penalties (exclude "without a late fine" which is a deadline phrasing)
        has_without_late = bool(
            re.search(r"\bwithout\s+(?:a\s+|any\s+)?late\b", lowered)
        )
        if not has_without_late:
            if (
                re.search(
                    r"\b(late\s+fee|late\s+fees|late\s+fine|late\s+payment|late\s+charge|late\s+charges|delayed\s+fee|overdue)\b",
                    lowered,
                )
                or (
                    (tokens | raw_words) & {"penalty", "penalties", "fine"}
                    and (tokens | raw_words) & {"fee", "fees", "tuition", "pay", "payment", "late"}
                )
                or re.search(
                    r"\b(pay|paying|paid)\b.*\b(late|after\s+the\s+deadline)\b",
                    lowered,
                )
                or (
                    re.search(r"\bmiss(?:ed|ing)?\b.*\b(deadline|due\s+date)\b", lowered)
                    and (tokens | raw_words) & {"fee", "fees", "tuition", "pay", "payment"}
                )
            ):
                intents.add("late_payment")

        # 11. Fee payment deadline / last date / due date
        if "late_payment" not in intents and "fee_installment" not in intents:
            if (
                (
                    re.search(
                        r"\b(deadline|deadlines|last\s+date|due\s+date|due\s+dates|until\s+when)\b",
                        lowered,
                    )
                    and (tokens | raw_words)
                    & {"fee", "fees", "tuition", "pay", "paying", "payment", "semester"}
                )
                or re.search(
                    r"\bwhen\b.*\b(pay|paying|payment)\b.*\b(fee|fees|tuition|semester)\b",
                    lowered,
                )
            ):
                intents.add("payment_deadline")

        # 12. Payment methods / modes / channels (UPI, net banking, card, DD, NEFT, how/where to pay)
        is_how_much_query = bool(re.search(r"\bhow\s+much\b", lowered))
        if not is_how_much_query and not (
            intents
            & {
                "auxiliary_fees",
                "exam_fee",
                "fee_installment",
                "payment_deadline",
                "late_payment",
                "fee_receipt",
                "transaction_issue",
                "education_loan",
            }
        ):
            has_payment_instrument = bool(
                re.search(
                    r"\b(upi|net\s*banking|netbanking|debit\s+card|credit\s+card|\bcard\b|challan|demand\s+draft|\bdd\b|neft|rtgs|payment\s+modes?|modes?\s+of\s+(?:fee\s+)?payment|payment\s+gateways?|offline\s+fee\s+payment)\b",
                    lowered,
                )
            )
            has_how_or_where_to_pay = bool(
                re.search(
                    r"\b(how|where)\s+(?:can|do|to|should|may)\s+(?:i\s+|we\s+|students?\s+)?pay\b",
                    lowered,
                )
                and (tokens | raw_words) & {"fee", "fees", "tuition", "semester", "college", "online"}
            )
            has_can_pay_instrument = bool(
                re.search(
                    r"\bcan\s+i\s+pay\b.*\b(online|through|using|via|by|upi|card|bank|net\s*banking)\b",
                    lowered,
                )
            )
            if has_payment_instrument or has_how_or_where_to_pay or has_can_pay_instrument:
                intents.add("payment_method")

        # 13. Fee amount / fee structure / total or semester tuition fee enquiry
        if "education_loan" not in intents:
            has_explicit_structure = bool(
                re.search(
                    r"\b(fee\s+structures?|fees\s+structures?|fee\s+breakdown|fee\s+schedule)\b",
                    lowered,
                )
            )
            has_amount_quantifier = bool(
                re.search(
                    r"\b(how\s+much|total|annual|per\s+semester|cost|price|breakdown)\b",
                    lowered,
                )
                and (tokens | raw_words)
                & {"fee", "fees", "tuition", "pay", "semester", "course", "program"}
                and not (
                    intents
                    & {
                        "fee_refund",
                        "late_payment",
                        "payment_deadline",
                        "fee_installment",
                        "auxiliary_fees",
                        "exam_fee",
                    }
                )
            )
            has_direct_tuition_amount_enquiry = bool(
                not intents
                and re.search(
                    r"\b(what\s+is|what\s+are|tell\s+me\s+about|details\s+of|find|where\s+is)\b",
                    lowered,
                )
                and (tokens | raw_words) & {"fee", "fees", "tuition"}
                and (tokens | raw_words)
                & {"semester", "tuition", "course", "program", "annual", "university", "college"}
            )
            if (
                has_explicit_structure
                or has_amount_quantifier
                or has_direct_tuition_amount_enquiry
            ):
                intents.add("fee_amount")

        return intents

    def _prepare_query_for_matching(
        self, raw_query: str, cleaned_query: str, query_intents: Set[str]
    ) -> str:
        """
        Normalize a preprocessed user query across fee and general institutional
        subtopics so morphological variations (e.g., 'payment' vs 'pay',
        'cancel' vs 'cancellation'), stopword-stripped quantifiers ('how much ... pay'),
        and cross-category synonyms ('website' -> 'online') align with the indexed
        FAQ phrasing without altering exact variant matches.
        """
        if not cleaned_query:
            return cleaned_query

        # Preserve exact matches to any indexed variant untouched (100% similarity)
        for entry in self.variants_index:
            if entry["preprocessed"] == cleaned_query:
                return cleaned_query

        lowered = raw_query.lower().strip()
        tokens = cleaned_query.split()
        token_set = set(tokens)

        # Single-intent fee subtopic normalization
        if len(query_intents) == 1:
            intent = next(iter(query_intents))

            if intent == "fee_amount":
                # In "How much do I have to pay per semester?", "how much" was removed
                # by stopwords, leaving "pay" which misleads TF-IDF toward payment methods.
                if re.search(r"\bhow\s+much\b", lowered) and "pay" in token_set:
                    tokens = [t for t in tokens if t != "pay"]
                    token_set = set(tokens)
                    for term in ("tuition", "fee", "structure"):
                        if term not in token_set:
                            tokens.append(term)
                elif (token_set & {"total", "cost", "price"}) and "structure" not in token_set:
                    tokens = [t for t in tokens if t not in {"total", "cost", "price"}]
                    for term in ("semester", "tuition", "fee", "structure"):
                        if term not in tokens:
                            tokens.append(term)
                return " ".join(tokens)

            if intent == "payment_method":
                # Strip functional prepositions ("using" -> "use", "via") and "debit"/"credit"
                # modifiers on "card" (since "debit" only appears in FAQ #20's "debited")
                drop_tokens = {"use", "via"}
                if "card" in token_set:
                    drop_tokens |= {"debit", "credit"}
                filtered = [t for t in tokens if t not in drop_tokens]
                if filtered:
                    tokens = filtered
                    token_set = set(tokens)
                if "upi" in token_set and "fee" not in token_set:
                    tokens.extend(["semester", "fee"])
                return " ".join(tokens)

            if intent == "payment_deadline":
                # Bridge morphological gap between noun "payment" and verb lemma "pay"
                if "payment" in token_set and "pay" not in token_set:
                    tokens.extend(["pay", "semester"])
                return " ".join(tokens)

            if intent == "late_payment":
                # Bridge "pay fees late" / "late payment penalty" across FAQ #23 variants
                for term in ("penalty", "fine", "fee", "pay", "payment"):
                    if term not in token_set:
                        tokens.append(term)
                return " ".join(tokens)

            if intent == "fee_refund":
                # Bridge verb "cancel" with nominal/synonym forms in FAQ #22 ("cancellation", "withdraw")
                if "cancel" in token_set or "withdraw" in token_set:
                    tokens = [t for t in tokens if t not in {"get", "cancel"}]
                    token_set = set(tokens)
                    for term in ("fee", "cancellation", "withdraw"):
                        if term not in token_set:
                            tokens.append(term)
                return " ".join(tokens)

        # General cross-category normalization for non-fee queries
        if "website" in token_set or "webpage" in token_set:
            tokens = [
                "online" if t in {"website", "webpage"} else t for t in tokens
            ]
            token_set = set(tokens)

        # NRI / foreign / international admission queries (FAQ #9)
        if (token_set & {"nri", "foreign", "international"}) and (
            token_set & {"admission", "apply"}
        ):
            for term in ("international", "nri", "foreign", "national"):
                if term not in token_set:
                    tokens.append(term)
            return " ".join(tokens)

        # Hostel facility / facilities enquiry -> align with FAQ #75 ("on-campus hostel accommodation" / "room")
        if "hostel" in token_set and "facility" in token_set and not (
            token_set & {"medical", "sport", "gym", "mess", "food", "visitor", "curfew", "fee"}
        ):
            tokens = [t for t in tokens if t != "facility"]
            for term in ("accommodation", "room"):
                if term not in tokens:
                    tokens.append(term)
            return " ".join(tokens)

        # "How can I apply for scholarships?" / "What is the procedure for applying for scholarships?"
        if (
            "scholarship" in token_set
            and "apply" in token_set
            and (
                re.search(r"\bhow\b", lowered)
                or "procedure" in token_set
                or "process" in token_set
            )
            and not (
                token_set
                & {"document", "certificate", "type", "scheme", "portal", "nsp", "online"}
            )
        ):
            tokens = [t for t in tokens if t != "procedure"]
            for term in ("institutional", "merit"):
                if term not in tokens:
                    tokens.append(term)
            return " ".join(tokens)

        # Placement registration enquiry -> align "register" + "placement" with FAQ #88 ("campus recruitment")
        if (
            "placement" in token_set
            and ("register" in token_set or "registration" in token_set)
            and not (
                token_set
                & {"dress", "wear", "attire", "conduct", "code", "absent", "miss", "attend", "rule"}
            )
        ):
            for term in ("campus", "recruitment"):
                if term not in token_set:
                    tokens.append(term)
            return " ".join(tokens)

        return " ".join(tokens)

    def _initialize_knowledge_base(self) -> None:
        """
        Load faqs.json, expand all primary and alternative questions,
        preprocess them, and fit the TF-IDF matrix once.
        """
        self.faqs = []
        self.variants_index = []
        self.faq_intents = {}
        self.domain_words = set()
        self.vectorizer = None
        self.tfidf_matrix = None
        self.is_ready = False
        self.load_error = None

        if not self.dataset_path.exists() or not self.dataset_path.is_file():
            self.load_error = f"Dataset file not found at: {self.dataset_path}"
            logger.error(self.load_error)
            return

        try:
            raw_content = self.dataset_path.read_text(encoding="utf-8").strip()
            if not raw_content:
                self.load_error = f"Dataset file is empty: {self.dataset_path}"
                logger.error(self.load_error)
                return

            parsed_data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            self.load_error = f"Malformed JSON in dataset ({self.dataset_path}): {exc}"
            logger.error(self.load_error)
            return
        except OSError as exc:
            self.load_error = f"Error reading dataset ({self.dataset_path}): {exc}"
            logger.error(self.load_error)
            return

        if not isinstance(parsed_data, list) or len(parsed_data) == 0:
            self.load_error = "Dataset must be a non-empty JSON array of FAQ records."
            logger.error(self.load_error)
            return

        ok, err = self.reload_from_records(parsed_data)
        if not ok:
            self.load_error = err

    def _build_index_from_records(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[
        List[Dict[str, Any]],
        List[Dict[str, Any]],
        Dict[Any, Set[str]],
        TfidfVectorizer,
        Any,
        Set[str],
    ]:
        """Build a complete, isolated TF-IDF index from FAQ record dicts."""
        if not isinstance(records, list) or len(records) == 0:
            raise ValueError("FAQ dataset must be a non-empty list of records.")

        faqs: List[Dict[str, Any]] = []
        variants_index: List[Dict[str, Any]] = []
        faq_intents: Dict[Any, Set[str]] = {}
        corpus: List[str] = []

        for record in records:
            if not isinstance(record, dict):
                continue

            faq_id = record.get("id")
            category = record.get("category")
            primary_question = record.get("question")
            answer = record.get("answer")
            alt_questions = record.get("alternative_questions", [])

            if (
                faq_id is None
                or not isinstance(category, str)
                or not isinstance(primary_question, str)
                or not isinstance(answer, str)
                or not category.strip()
                or not primary_question.strip()
                or not answer.strip()
            ):
                continue

            faqs.append(record)

            candidate_phrasings: List[str] = [primary_question.strip()]
            if isinstance(alt_questions, list):
                for alt in alt_questions:
                    if isinstance(alt, str) and alt.strip():
                        candidate_phrasings.append(alt.strip())

            seen_phrasings = set()
            record_cleaned_phrasings: List[str] = []
            for phrasing in candidate_phrasings:
                lowered_phrasing = phrasing.lower()
                if lowered_phrasing in seen_phrasings:
                    continue
                seen_phrasings.add(lowered_phrasing)

                cleaned_text = self.preprocessor.preprocess(phrasing)
                if not cleaned_text:
                    continue

                record_cleaned_phrasings.append(cleaned_text)
                variants_index.append(
                    {
                        "faq_id": faq_id,
                        "category": category.strip(),
                        "canonical_question": primary_question.strip(),
                        "variant_question": phrasing,
                        "answer": answer.strip(),
                        "preprocessed": cleaned_text,
                    }
                )
                corpus.append(cleaned_text)

            normalized_category = category.strip()
            if normalized_category in {"Fee Payment", "Admissions"} and record_cleaned_phrasings:
                primary_cleaned = record_cleaned_phrasings[0]
                detected_intents = self._detect_fee_intents(
                    primary_question.strip(), primary_cleaned
                )
                if normalized_category == "Admissions":
                    detected_intents &= {"admission_withdrawal"}
                elif not detected_intents:
                    for phrasing, cleaned_phrasing in zip(
                        candidate_phrasings, record_cleaned_phrasings
                    ):
                        detected_intents |= self._detect_fee_intents(
                            phrasing, cleaned_phrasing
                        )
                if detected_intents:
                    faq_intents[faq_id] = detected_intents

        if not corpus:
            raise ValueError("No valid FAQ questions found after preprocessing.")

        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            norm="l2",
            lowercase=True,
        )
        tfidf_matrix = vectorizer.fit_transform(corpus)
        domain_words = {
            tok
            for tok in vectorizer.vocabulary_.keys()
            if " " not in tok and len(tok) >= 4 and tok.isalpha()
        }
        return faqs, variants_index, faq_intents, vectorizer, tfidf_matrix, domain_words

    def reload_from_records(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[bool, Optional[str]]:
        """
        Thread-safely rebuild the TF-IDF index from `records`.
        If building fails, the previous working index is retained unchanged.
        """
        try:
            (
                new_faqs,
                new_variants,
                new_intents,
                new_vectorizer,
                new_matrix,
                new_domain_words,
            ) = self._build_index_from_records(records)
        except Exception as exc:
            err_msg = f"Failed to rebuild NLP index: {exc}"
            logger.error(err_msg)
            return False, err_msg

        with self._index_lock:
            self.faqs = new_faqs
            self.variants_index = new_variants
            self.faq_intents = new_intents
            self.vectorizer = new_vectorizer
            self.tfidf_matrix = new_matrix
            self.domain_words = new_domain_words
            self.is_ready = True
            self.load_error = None
        return True, None

    def _rank_distinct_candidates(
        self,
        similarities: np.ndarray,
        query_intents: Optional[Set[str]] = None,
        raw_query: str = "",
        cleaned_query: str = "",
        has_uncorrected_oov: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate variant similarity scores by unique faq_id (selecting the
        highest-scoring variant per FAQ to prevent duplicates), penalize
        candidates from incompatible subtopic intents, guard against OOV
        queries that only match on generic container words, and return all
        distinct FAQs with positive similarity ranked in descending order.
        """
        best_per_faq: Dict[Any, Dict[str, Any]] = {}
        faq_matched_tokens: Dict[Any, Set[str]] = {}
        query_token_set = set(cleaned_query.split())
        lowered_query = raw_query.lower().strip()

        for idx, raw_score in enumerate(similarities):
            score = float(raw_score)
            if score <= 0.0:
                continue

            variant_entry = self.variants_index[idx]
            faq_id = variant_entry["faq_id"]

            existing = best_per_faq.get(faq_id)
            if existing is None or score > existing["raw_score"]:
                best_per_faq[faq_id] = {
                    "faq_id": faq_id,
                    "question": variant_entry["canonical_question"],
                    "category": variant_entry["category"],
                    "answer": variant_entry["answer"],
                    "raw_score": score,
                    "similarity": round(score * 100.0, 2),
                }
                faq_matched_tokens[faq_id] = (
                    set(variant_entry["preprocessed"].split()) & query_token_set
                )

        if query_intents:
            for faq_id, entry in best_per_faq.items():
                candidate_intents = self.faq_intents.get(faq_id, set())
                if candidate_intents and not (candidate_intents & query_intents):
                    penalized_score = (
                        entry["raw_score"] * INCOMPATIBLE_FEE_INTENT_PENALTY
                    )
                    entry["raw_score"] = penalized_score
                    entry["similarity"] = round(penalized_score * 100.0, 2)

        # General cross-category and subtopic disambiguation penalties (no score inflation)
        has_deadline_signal = bool(
            re.search(
                r"\b(deadline|deadlines|last\s+date|due\s+date|close|closing|until\s+when|when)\b",
                lowered_query,
            )
        )
        has_withdraw_signal = bool(
            query_token_set & {"withdraw", "withdrawal", "cancel", "cancellation", "return"}
        )
        has_gap_age_signal = bool(query_token_set & {"gap", "age"})

        # Detect if the query explicitly names a single institutional category
        category_signals: Dict[str, Set[str]] = {
            "Admissions": {"admission", "admit", "undergraduate", "postgraduate", "bachelor", "lateral", "nri", "counseling"},
            "Fee Payment": {"fee", "tuition", "upi", "challan", "neft", "rtgs", "installment", "refund", "caution", "receipt", "invoice"},
            "Attendance": {"attendance", "absent", "condonation", "biometric", "detain", "detention", "shortage"},
            "Examinations": {"exam", "examination", "midterm", "timetable", "hall", "cgpa", "sgpa", "revaluation", "rechecking", "backlog", "supplementary", "arrear", "transcript", "malpractice", "scribe"},
            "Scholarships": {"scholarship", "stipend", "fellowship", "tfw", "ews", "nsp"},
            "Campus Facilities": {"library", "hostel", "wifi", "infirmary", "ambulance", "bus", "transport", "shuttle", "gym", "gymnasium", "sport", "mess", "canteen", "cafeteria", "club", "counselor", "wellness", "ragging", "grievance", "atm", "parking"},
            "Placements": {"placement", "internship", "noc", "recruiter", "jaf", "ppo"},
        }
        explicit_categories = {
            cat_name
            for cat_name, signals in category_signals.items()
            if query_token_set & signals
        }
        single_explicit_category = (
            next(iter(explicit_categories))
            if len(explicit_categories) == 1
            else None
        )

        for faq_id, entry in best_per_faq.items():
            penalty = 1.0
            cat = entry["category"]

            # 0. Single explicit category focus: if the query explicitly names one
            #    category and no other, lightly penalize cross-category candidates
            #    that only matched on generic procedural words ("document", "status", "portal").
            if single_explicit_category and cat != single_explicit_category:
                penalty *= 0.72

            # 1. OOV guard: if query has an uncorrected OOV subject noun and only
            #    matches this candidate on generic container words, penalize.
            if has_uncorrected_oov:
                shared = faq_matched_tokens.get(faq_id, set())
                specific_shared = shared - GENERIC_INSTITUTIONAL_CONTAINER_TOKENS
                if not specific_shared:
                    penalty *= 0.40

            # 2. Admissions subtopic disambiguation
            if faq_id == 4 and not has_deadline_signal and (
                query_token_set & {"how", "submit", "apply", "online", "website", "portal"}
            ):
                penalty *= 0.65
            elif faq_id == 13 and not has_withdraw_signal:
                penalty *= 0.65
            elif faq_id == 14 and not has_gap_age_signal:
                penalty *= 0.65
            elif (
                (query_token_set & {"nri", "foreign", "international"})
                and (query_token_set & {"admission", "apply"})
                and faq_id != 9
                and cat == "Admissions"
            ):
                penalty *= 0.55

            # 3. Scholarships subtopic disambiguation (FAQ #60 available types vs FAQ #61 how to apply
            #    vs FAQ #62 document checklist, and FAQ #67 disbursement/credit tracking vs FAQ #72 bank account)
            if "scholarship" in query_token_set:
                if (
                    faq_id == 60
                    and ("apply" in query_token_set or "application" in query_token_set)
                    and re.search(r"\b(how|where)\b", lowered_query)
                    and not (
                        query_token_set & {"type", "scheme", "available", "offer"}
                    )
                ):
                    penalty *= 0.65
                elif (
                    faq_id == 61
                    and ("available" in query_token_set or "type" in query_token_set or "offer" in query_token_set)
                    and not (query_token_set & {"apply", "application", "form", "process"})
                ):
                    penalty *= 0.65
                elif (
                    faq_id == 62
                    and ("apply" in query_token_set or "application" in query_token_set)
                    and not (
                        query_token_set
                        & {
                            "document",
                            "certificate",
                            "paperwork",
                            "paper",
                            "checklist",
                            "income",
                            "caste",
                            "domicile",
                            "bonafide",
                            "passbook",
                            "require",
                            "need",
                        }
                    )
                ):
                    penalty *= 0.65
                elif (
                    faq_id == 72
                    and (
                        query_token_set & {"track", "status", "disbursement", "approve", "approval"}
                        or re.search(r"\bwhen\b.*\b(credit|credited|receive)\b", lowered_query)
                    )
                    and not (query_token_set & {"parent", "aadhaar", "detail", "update", "need"})
                ):
                    penalty *= 0.60

            # 4. Placements subtopic disambiguation (FAQ #88 registration vs FAQ #96 dress code / absence rules)
            if (
                faq_id == 96
                and "register" in query_token_set
                and not (
                    query_token_set
                    & {"dress", "wear", "attire", "conduct", "code", "absent", "miss", "attend", "rule"}
                )
            ):
                penalty *= 0.65

            # 5. Attendance vs Examinations / Placements cross-category disambiguation
            if "attendance" in query_token_set and cat != "Attendance" and not (
                query_token_set & {"scholarship", "renew"}
            ):
                penalty *= 0.65
            elif "placement" in query_token_set and "attendance" not in query_token_set and cat == "Attendance":
                penalty *= 0.60

            if penalty < 1.0:
                new_score = entry["raw_score"] * penalty
                entry["raw_score"] = new_score
                entry["similarity"] = round(new_score * 100.0, 2)

        ranked = sorted(
            best_per_faq.values(),
            key=lambda item: (-item["raw_score"], item["faq_id"]),
        )
        return ranked

    @staticmethod
    def _serialize_candidates(
        ranked_entries: List[Dict[str, Any]], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Format the top-K distinct candidates for public response output
        without exposing internal answers or raw score fields.
        """
        return [
            {
                "faq_id": entry["faq_id"],
                "question": entry["question"],
                "category": entry["category"],
                "similarity": entry["similarity"],
            }
            for entry in ranked_entries[:limit]
        ]

    def _build_clarification_message(
        self, top_candidates: List[Dict[str, Any]]
    ) -> str:
        """
        Generate a helpful clarification prompt when multiple plausible FAQ
        matches exist or when a match falls in the ambiguous similarity band.
        """
        plausible = [
            c
            for c in top_candidates
            if c["raw_score"] >= self.confidence_threshold
        ]
        if not plausible and top_candidates:
            plausible = top_candidates[:2]

        if len(plausible) >= 2:
            options_text = " ".join(
                f'({i + 1}) "{c["question"]}" [{c["category"]}]'
                for i, c in enumerate(plausible[:3])
            )
            return (
                "Multiple FAQ topics closely match your question. Could you "
                f"please clarify which of these you mean: {options_text}?"
            )

        if len(plausible) == 1:
            single = plausible[0]
            return (
                "I found a potentially related FAQ, but your question is broad. "
                f'Did you mean "{single["question"]}" ({single["category"]})?'
            )

        return (
            "Could you please provide a few more details so I can match the "
            "most relevant institutional FAQ?"
        )

    def _select_fallback_message(
        self, cleaned_query: str, top_raw_score: float
    ) -> str:
        """
        Choose an appropriate fallback message distinguishing between
        unsupported university questions and unrelated out-of-domain queries.
        """
        query_tokens = set(cleaned_query.split())
        has_university_context = bool(
            query_tokens & UNIVERSITY_DOMAIN_TERMS
        ) or (0.0 < top_raw_score < self.confidence_threshold)

        if has_university_context:
            return FALLBACK_UNSUPPORTED_UNIVERSITY_MESSAGE
        return FALLBACK_UNRELATED_MESSAGE

    @staticmethod
    def _build_response(
        *,
        success: bool,
        answer: str,
        matched_question: Optional[str] = None,
        category: Optional[str] = None,
        confidence: float = 0.0,
        faq_id: Optional[int] = None,
        fallback: bool = False,
        match_type: str = MATCH_NONE,
        candidates: Optional[List[Dict[str, Any]]] = None,
        needs_clarification: bool = False,
        clarification_message: Optional[str] = None,
        is_multi_intent: bool = False,
        sub_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Construct the standardized response dictionary preserving all existing
        fields and including the upgraded candidate ranking, classification,
        and multi-intent response fields.
        Note: `confidence` and candidate `similarity` are 0–100 TF-IDF cosine
        similarity percentages, not calibrated probabilities.
        """
        return {
            "success": bool(success),
            "answer": str(answer),
            "matched_question": matched_question,
            "category": category,
            "confidence": round(float(confidence), 2),
            "faq_id": faq_id,
            "fallback": bool(fallback),
            "match_type": str(match_type),
            "candidates": list(candidates) if candidates is not None else [],
            "needs_clarification": bool(needs_clarification),
            "clarification_message": clarification_message,
            "is_multi_intent": bool(is_multi_intent),
            "sub_responses": (
                list(sub_responses) if sub_responses is not None else []
            ),
        }

    def _detect_explicit_categories(self, query_text: str) -> Set[str]:
        """
        Identify which institutional FAQ categories are explicitly anchored by
        domain tokens in `query_text`.
        """
        raw_cleaned = self.preprocessor.preprocess(query_text)
        if not raw_cleaned:
            return set()
        cleaned, _ = self._normalize_and_correct_query(raw_cleaned)
        token_set = set(cleaned.split())
        category_signals: Dict[str, Set[str]] = {
            "Admissions": {
                "admission",
                "admit",
                "undergraduate",
                "postgraduate",
                "bachelor",
                "lateral",
                "nri",
                "counseling",
            },
            "Fee Payment": {
                "fee",
                "tuition",
                "upi",
                "challan",
                "neft",
                "rtgs",
                "installment",
                "refund",
                "caution",
                "receipt",
                "invoice",
            },
            "Attendance": {
                "attendance",
                "absent",
                "condonation",
                "biometric",
                "detain",
                "detention",
                "shortage",
            },
            "Examinations": {
                "exam",
                "examination",
                "midterm",
                "timetable",
                "hall",
                "cgpa",
                "sgpa",
                "revaluation",
                "rechecking",
                "backlog",
                "supplementary",
                "arrear",
                "transcript",
                "malpractice",
                "scribe",
            },
            "Scholarships": {
                "scholarship",
                "stipend",
                "fellowship",
                "tfw",
                "ews",
                "nsp",
            },
            "Campus Facilities": {
                "library",
                "hostel",
                "wifi",
                "infirmary",
                "ambulance",
                "bus",
                "transport",
                "shuttle",
                "gym",
                "gymnasium",
                "sport",
                "mess",
                "canteen",
                "cafeteria",
                "club",
                "counselor",
                "wellness",
                "ragging",
                "grievance",
                "atm",
                "parking",
            },
            "Placements": {
                "placement",
                "internship",
                "noc",
                "recruiter",
                "jaf",
                "ppo",
            },
        }
        return {
            cat_name
            for cat_name, signals in category_signals.items()
            if token_set & signals
        }

    def _get_single_response(self, user_question: object) -> Dict[str, Any]:
        """
        Evaluate a single question segment against the fitted TF-IDF FAQ index,
        retrieve the top-3 distinct FAQ candidates, and classify the match as
        clear_match, ambiguous_match, or no_reliable_match.
        """
        # 1. Validate input type and non-emptiness
        if not isinstance(user_question, str) or not user_question.strip():
            return self._build_response(
                success=False,
                answer=INVALID_INPUT_MESSAGE,
                fallback=True,
                match_type=MATCH_NONE,
                candidates=[],
                needs_clarification=False,
                clarification_message=None,
            )

        # 2. Verify knowledge base readiness
        if not self.is_ready or self.vectorizer is None or self.tfidf_matrix is None:
            return self._build_response(
                success=False,
                answer=UNAVAILABLE_KB_MESSAGE,
                fallback=True,
                match_type=MATCH_NONE,
                candidates=[],
                needs_clarification=False,
                clarification_message=None,
            )

        # 3. Preprocess the user question, normalize synonyms/typos, and detect intents
        raw_cleaned_query = self.preprocessor.preprocess(user_question)
        if not raw_cleaned_query:
            return self._build_response(
                success=True,
                answer=FALLBACK_UNRELATED_MESSAGE,
                confidence=0.0,
                fallback=True,
                match_type=MATCH_NONE,
                candidates=[],
                needs_clarification=False,
                clarification_message=None,
            )

        cleaned_query, has_uncorrected_oov = self._normalize_and_correct_query(
            raw_cleaned_query
        )
        query_intents = self._detect_fee_intents(user_question, cleaned_query)
        matching_query = self._prepare_query_for_matching(
            user_question, cleaned_query, query_intents
        )

        # 4. Transform query using the already-fitted TF-IDF vectorizer
        query_vector = self.vectorizer.transform([matching_query])

        if query_vector.nnz == 0:
            fallback_msg = self._select_fallback_message(cleaned_query, 0.0)
            return self._build_response(
                success=True,
                answer=fallback_msg,
                confidence=0.0,
                fallback=True,
                match_type=MATCH_NONE,
                candidates=[],
                needs_clarification=False,
                clarification_message=None,
            )

        # 5. Compute cosine similarity and adjust for out-of-vocabulary query terms
        query_tokens = matching_query.split()
        vocab = self.vectorizer.vocabulary_
        known_token_count = sum(1 for tok in query_tokens if tok in vocab)
        effective_tokens = [
            tok
            for tok in query_tokens
            if tok in vocab or tok not in BENIGN_QUERY_MODIFIERS
        ]
        coverage_ratio = (
            known_token_count / len(effective_tokens)
            if effective_tokens and known_token_count > 0
            else 0.0
        )

        similarities: np.ndarray = (
            cosine_similarity(query_vector, self.tfidf_matrix).flatten()
            * coverage_ratio
        )

        ranked_distinct = self._rank_distinct_candidates(
            similarities,
            query_intents=query_intents,
            raw_query=user_question,
            cleaned_query=cleaned_query,
            has_uncorrected_oov=has_uncorrected_oov,
        )
        top_candidates_public = self._serialize_candidates(
            ranked_distinct, self.top_k
        )

        if not ranked_distinct:
            fallback_msg = self._select_fallback_message(cleaned_query, 0.0)
            return self._build_response(
                success=True,
                answer=fallback_msg,
                confidence=0.0,
                fallback=True,
                match_type=MATCH_NONE,
                candidates=[],
                needs_clarification=False,
                clarification_message=None,
            )

        best_entry = ranked_distinct[0]
        top_score = best_entry["raw_score"]
        top_similarity_pct = best_entry["similarity"]

        second_score = (
            ranked_distinct[1]["raw_score"] if len(ranked_distinct) > 1 else 0.0
        )

        # 6. Classify: no_reliable_match if below confidence_threshold
        if (
            top_score < self.confidence_threshold
            or (top_similarity_pct / 100.0) < self.confidence_threshold
        ):
            fallback_msg = self._select_fallback_message(
                cleaned_query, top_score
            )
            return self._build_response(
                success=True,
                answer=fallback_msg,
                matched_question=None,
                category=None,
                confidence=top_similarity_pct,
                faq_id=None,
                fallback=True,
                match_type=MATCH_NONE,
                candidates=top_candidates_public,
                needs_clarification=False,
                clarification_message=None,
            )

        # 7. Check for ambiguity:
        #    (a) Top score is in the moderate/borderline band [confidence_threshold, clear_match_threshold), OR
        #    (b) Second distinct candidate is also >= confidence_threshold and within ambiguity_margin
        #        (unless top_score is a near-exact match >= DEFAULT_HIGH_CERTAINTY_SCORE), OR
        #    (c) The query explicitly asks about multiple distinct fee subtopic intents at once
        #        and a second plausible candidate exists, OR
        #    (d) A short query (<= 3 tokens) contains no category-identifying anchor token
        #        (e.g., "Eligibility?", "application form?").
        raw_word_count = len(re.findall(r"\b[a-z0-9]+\b", user_question.lower()))
        matching_token_set = set(matching_query.split())
        is_category_free_short_query = (
            raw_word_count <= 3
            and not query_intents
            and not (matching_token_set & CATEGORY_ANCHOR_TOKENS)
            and second_score >= self.confidence_threshold
        )
        has_competing_second = (
            second_score >= self.confidence_threshold
            and (top_score - second_score) < self.ambiguity_margin
            and top_score < DEFAULT_HIGH_CERTAINTY_SCORE
        )
        is_borderline_score = (
            top_score < self.clear_match_threshold
            or (top_similarity_pct / 100.0) < self.clear_match_threshold
        )
        has_multi_fee_intent_ambiguity = (
            len(query_intents) >= 2
            and second_score >= self.confidence_threshold
        )

        if (
            has_competing_second
            or is_borderline_score
            or has_multi_fee_intent_ambiguity
            or is_category_free_short_query
        ):
            clarification_msg = self._build_clarification_message(
                ranked_distinct[: self.top_k]
            )
            return self._build_response(
                success=True,
                answer=clarification_msg,
                matched_question=None,
                category=best_entry["category"],
                confidence=top_similarity_pct,
                faq_id=None,
                fallback=False,
                match_type=MATCH_AMBIGUOUS,
                candidates=top_candidates_public,
                needs_clarification=True,
                clarification_message=clarification_msg,
            )

        # 8. Clear match
        return self._build_response(
            success=True,
            answer=best_entry["answer"],
            matched_question=best_entry["question"],
            category=best_entry["category"],
            confidence=top_similarity_pct,
            faq_id=best_entry["faq_id"],
            fallback=False,
            match_type=MATCH_CLEAR,
            candidates=top_candidates_public,
            needs_clarification=False,
            clarification_message=None,
        )

    def split_multi_intent_query(self, user_question: str) -> List[str]:
        """
        Segment a user message into independent question clauses when the user
        combines multiple questions in a single message, while preserving single
        questions that contain compound noun phrases or lists of options (e.g.,
        "Can I pay my semester fees through UPI, net banking, or card?",
        "What are the annual tuition and laboratory fees?",
        "Are hostel, mess, and transportation fees paid separately from tuition fees?").
        """
        if not isinstance(user_question, str) or not user_question.strip():
            return []

        stripped = user_question.strip()

        # Guard: If the full query is an exact preprocessed match to any indexed
        # FAQ variant, treat it strictly as a single question.
        full_cleaned = self.preprocessor.preprocess(stripped)
        if full_cleaned and self.is_ready:
            for entry in self.variants_index:
                if entry["preprocessed"] == full_cleaned:
                    return [stripped]

        # Stage 1: Protect common academic/title abbreviations before splitting
        # on sentence-ending punctuation (?, ., !, ;, \n).
        abbrev_map: Dict[str, str] = {}

        def _mask_abbrev(match: re.Match) -> str:
            key = f"__ABBREV_{len(abbrev_map)}__"
            abbrev_map[key] = match.group(0)
            return key

        masked = re.sub(
            r"\b(?:b\.tech|m\.tech|b\.sc|m\.sc|b\.com|m\.com|b\.a|m\.a|m\.b\.a|ph\.d|b\.e|m\.e|dr|mr|ms|mrs|prof|e\.g|i\.e|etc)\.",
            _mask_abbrev,
            stripped,
            flags=re.IGNORECASE,
        )

        raw_sentences = re.split(r"(?:[?!;\n]+|\.(?=\s+[A-Za-z]))\s*", masked)
        sentence_segments: List[str] = []
        for seg in raw_sentences:
            restored = seg.strip()
            for k, v in abbrev_map.items():
                restored = restored.replace(k, v)
            restored = restored.strip(" .,;:\t\r\n")
            if not restored or not self.preprocessor.preprocess(restored):
                continue
            # If a trailing fragment is a prepositional modifier (e.g., "for Admissions"
            # appended after a question mark during contextual resolution), keep it
            # attached to the preceding question segment.
            if sentence_segments and re.match(
                r"^for\s+", restored, flags=re.IGNORECASE
            ):
                sentence_segments[-1] = f"{sentence_segments[-1]} {restored}"
            else:
                sentence_segments.append(restored)

        if not sentence_segments:
            return [stripped]

        # Stage 2: Within each sentence segment, split on coordinating conjunctions
        # ("and", "also", "plus", "as well as") when followed by an interrogative,
        # auxiliary question starter, or imperative verb.
        conjunction_question_re = re.compile(
            r"(?:,\s*|\s+)\b(?:and\s+also|and\s+then|and|also|plus|as\s+well\s+as)\s+"
            r"(?=(?:what|how|when|where|which|who|whom|whose|why|"
            r"can\s+(?:i|we|you|a\s+student|students)|"
            r"could\s+(?:i|we|you)|"
            r"do\s+(?:i|we|you|students|they)|"
            r"does\s+(?:the|a|an|it|this|hostel|university|college|campus)|"
            r"is\s+(?:there|the|it|a|an|hostel|wifi|wi-fi|attendance|fee|tuition|scholarship|placement)|"
            r"are\s+(?:there|the|they|students|hostel)|"
            r"will\s+(?:i|we|the|my|there)|"
            r"should\s+(?:i|we)|"
            r"tell\s+me|explain|show\s+me|give\s+me)\b)",
            re.IGNORECASE,
        )

        clause_segments: List[str] = []
        for sent in sentence_segments:
            sub_clauses = conjunction_question_re.split(sent)
            valid_sub_clauses = [
                c.strip(" ,;:")
                for c in sub_clauses
                if c.strip(" ,;:") and self.preprocessor.preprocess(c)
            ]
            if len(valid_sub_clauses) >= 2:
                clause_segments.extend(valid_sub_clauses)
            else:
                clause_segments.append(sent)

        # Stage 3: Check for shared-prefix multi-topic conjunctions where a single
        # introductory verb/interrogative governs two distinct institutional topics
        # joined by "and" (e.g., "Tell me about hostel facilities and examination timetables.").
        shared_prefix_re = re.compile(
            r"^(?P<prefix>(?:please\s+)?(?:tell\s+me\s+about|give\s+me\s+(?:details|information)\s+(?:on|about)|"
            r"explain|what\s+is\s+the|what\s+are\s+the|i\s+want\s+to\s+know\s+about))\s+"
            r"(?P<left>[^,]+?)\s+(?:and|as\s+well\s+as)\s+(?P<right>[^,]+?)[?.!]*$",
            re.IGNORECASE,
        )

        final_segments: List[str] = []
        for clause in clause_segments:
            prefix_match = shared_prefix_re.match(clause.strip())
            if prefix_match and self.is_ready:
                prefix_str = prefix_match.group("prefix").strip()
                left_np = prefix_match.group("left").strip()
                right_np = prefix_match.group("right").strip()

                left_clean = self.preprocessor.preprocess(left_np)
                right_clean = self.preprocessor.preprocess(right_np)

                if left_clean and right_clean:
                    unsplit_res = self._get_single_response(clause)
                    left_query = f"{prefix_str} {left_np}"
                    right_query = f"{prefix_str} {right_np}"
                    left_res = self._get_single_response(left_query)
                    right_res = self._get_single_response(right_query)

                    left_cats = self._detect_explicit_categories(left_np)
                    right_cats = self._detect_explicit_categories(right_np)
                    left_intents = self._detect_fee_intents(left_np, left_clean)
                    right_intents = self._detect_fee_intents(
                        right_np, right_clean
                    )

                    has_distinct_categories = bool(
                        left_cats and right_cats and left_cats != right_cats
                    )
                    has_disjoint_fee_intents = bool(
                        len(left_intents) == 1
                        and len(right_intents) == 1
                        and left_intents != right_intents
                    )

                    if (
                        unsplit_res["confidence"] < 75.0
                        and (has_distinct_categories or has_disjoint_fee_intents)
                        and left_res.get("faq_id") != right_res.get("faq_id")
                        and (
                            left_res["match_type"] == MATCH_CLEAR
                            or right_res["match_type"] == MATCH_CLEAR
                        )
                    ):
                        final_segments.append(left_query)
                        final_segments.append(right_query)
                        continue

            final_segments.append(clause)

        return final_segments if final_segments else [stripped]

    def get_response(
        self,
        user_question: object,
        context_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Match a user question (single-intent or multi-intent) against the fitted
        TF-IDF FAQ index, retrieve distinct FAQ candidates, classify each sub-query
        as clear_match, ambiguous_match, or no_reliable_match, and return the
        standardized response dictionary.
        """
        with self._index_lock:
            return self._get_response_unlocked(
                user_question, context_category=context_category
            )

    def _get_response_unlocked(
        self,
        user_question: object,
        context_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(user_question, str) or not user_question.strip():
            return self._get_single_response(user_question)

        if not self.is_ready or self.vectorizer is None or self.tfidf_matrix is None:
            return self._get_single_response(user_question)

        segments = self.split_multi_intent_query(user_question)
        if len(segments) <= 1:
            return self._get_single_response(user_question)

        # Evaluate each detected question segment sequentially, propagating
        # intra-message category context to elliptical or pronoun-bearing follow-up
        # clauses (e.g., "and how do I register?", "and how can I pay them?").
        active_cat: Optional[str] = context_category
        raw_sub_responses: List[Dict[str, Any]] = []

        anaphoric_pronoun_re = re.compile(
            r"\b(?:it|them|they|this|that|those|these)\b", re.IGNORECASE
        )

        for seg in segments:
            sub_res = self._get_single_response(seg)
            seg_raw_clean = self.preprocessor.preprocess(seg)
            _, seg_has_oov = self._normalize_and_correct_query(seg_raw_clean)
            seg_explicit_cats = self._detect_explicit_categories(seg)
            has_anaphora = bool(anaphoric_pronoun_re.search(seg))

            if (
                active_cat
                and not seg_has_oov
                and (not seg_explicit_cats or active_cat in seg_explicit_cats)
                and (
                    sub_res["match_type"] != MATCH_CLEAR
                    or (has_anaphora and sub_res.get("category") != active_cat)
                )
            ):
                enriched_res = self._get_single_response(
                    f"{seg} for {active_cat}"
                )
                if (
                    enriched_res["match_type"] == MATCH_CLEAR
                    and enriched_res.get("category") == active_cat
                ):
                    sub_res = enriched_res

            if sub_res["match_type"] == MATCH_CLEAR and sub_res.get("category"):
                active_cat = sub_res["category"]

            raw_sub_responses.append(
                {
                    "query": seg,
                    "answer": sub_res["answer"],
                    "matched_question": sub_res["matched_question"],
                    "category": sub_res["category"],
                    "confidence": sub_res["confidence"],
                    "faq_id": sub_res["faq_id"],
                    "fallback": sub_res["fallback"],
                    "match_type": sub_res["match_type"],
                    "candidates": sub_res["candidates"],
                    "needs_clarification": sub_res["needs_clarification"],
                    "clarification_message": sub_res["clarification_message"],
                }
            )

        # Deduplicate sub-responses that map to the same FAQ ID or identical query
        deduped_sub_responses: List[Dict[str, Any]] = []
        seen_faq_ids: Dict[int, int] = {}
        seen_non_clear_queries: Set[str] = set()

        for item in raw_sub_responses:
            fid = item.get("faq_id")
            if item["match_type"] == MATCH_CLEAR and fid is not None:
                if fid in seen_faq_ids:
                    existing_idx = seen_faq_ids[fid]
                    if (
                        item["confidence"]
                        > deduped_sub_responses[existing_idx]["confidence"]
                    ):
                        deduped_sub_responses[existing_idx]["confidence"] = item[
                            "confidence"
                        ]
                    continue
                seen_faq_ids[fid] = len(deduped_sub_responses)
                deduped_sub_responses.append(item)
            else:
                norm_q = self.preprocessor.preprocess(item["query"])
                if norm_q in seen_non_clear_queries:
                    continue
                seen_non_clear_queries.add(norm_q)
                deduped_sub_responses.append(item)

        # If deduplication reduced all segments to a single FAQ response (e.g.,
        # repeated or paraphrased duplicate questions in one message), return a
        # single-intent response so the answer is never duplicated.
        if len(deduped_sub_responses) == 1:
            only = deduped_sub_responses[0]
            return self._build_response(
                success=True,
                answer=only["answer"],
                matched_question=only["matched_question"],
                category=only["category"],
                confidence=only["confidence"],
                faq_id=only["faq_id"],
                fallback=only["fallback"],
                match_type=only["match_type"],
                candidates=only["candidates"],
                needs_clarification=only["needs_clarification"],
                clarification_message=only["clarification_message"],
                is_multi_intent=False,
                sub_responses=[],
            )

        # Format clearly separated multi-part answer text and aggregate top-level metadata
        formatted_sections: List[str] = []
        for idx, sub in enumerate(deduped_sub_responses, start=1):
            if sub["match_type"] == MATCH_CLEAR:
                header = f"[{idx}] {sub['category']} — {sub['matched_question']}"
                formatted_sections.append(f"{header}\n{sub['answer']}")
            elif sub["match_type"] == MATCH_AMBIGUOUS:
                header = f"[{idx}] Clarification Needed — \"{sub['query']}\""
                formatted_sections.append(
                    f"{header}\n{sub['clarification_message'] or sub['answer']}"
                )
            else:
                header = f"[{idx}] Unmatched Topic — \"{sub['query']}\""
                formatted_sections.append(f"{header}\n{sub['answer']}")

        combined_answer = "\n\n".join(formatted_sections)

        clear_subs = [
            s for s in deduped_sub_responses if s["match_type"] == MATCH_CLEAR
        ]
        ambig_subs = [
            s
            for s in deduped_sub_responses
            if s["match_type"] == MATCH_AMBIGUOUS
        ]

        if clear_subs:
            top_match_type = MATCH_CLEAR
            top_fallback = False
            primary_faq_id = clear_subs[0]["faq_id"]
            primary_matched_question = clear_subs[0]["matched_question"]
            # Use the last resolved category so follow-up turns naturally track the latest topic
            primary_category = clear_subs[-1]["category"]
            avg_confidence = sum(s["confidence"] for s in clear_subs) / len(
                clear_subs
            )
        elif ambig_subs:
            top_match_type = MATCH_AMBIGUOUS
            top_fallback = False
            primary_faq_id = None
            primary_matched_question = None
            primary_category = ambig_subs[-1]["category"]
            avg_confidence = sum(s["confidence"] for s in ambig_subs) / len(
                ambig_subs
            )
        else:
            top_match_type = MATCH_NONE
            top_fallback = True
            primary_faq_id = None
            primary_matched_question = None
            primary_category = None
            avg_confidence = max(
                (s["confidence"] for s in deduped_sub_responses), default=0.0
            )

        top_needs_clarification = bool(ambig_subs)
        top_clarification_msg = (
            ambig_subs[0]["clarification_message"] if ambig_subs else None
        )

        # Build deduplicated, descending-sorted top-3 candidates list
        if ambig_subs:
            combined_candidates = list(ambig_subs[0]["candidates"])[: self.top_k]
        else:
            candidate_pool: Dict[Any, Dict[str, Any]] = {}
            for s in deduped_sub_responses:
                for cand in s.get("candidates", []):
                    cid = cand["faq_id"]
                    if (
                        cid not in candidate_pool
                        or cand["similarity"] > candidate_pool[cid]["similarity"]
                    ):
                        candidate_pool[cid] = dict(cand)
            combined_candidates = sorted(
                candidate_pool.values(),
                key=lambda item: (-item["similarity"], item["faq_id"]),
            )[: self.top_k]

        return self._build_response(
            success=True,
            answer=combined_answer,
            matched_question=primary_matched_question,
            category=primary_category,
            confidence=avg_confidence,
            faq_id=primary_faq_id,
            fallback=top_fallback,
            match_type=top_match_type,
            candidates=combined_candidates,
            needs_clarification=top_needs_clarification,
            clarification_message=top_clarification_msg,
            is_multi_intent=True,
            sub_responses=deduped_sub_responses,
        )

    def get_categories(self) -> List[str]:
        """Return sorted list of unique FAQ categories in the loaded dataset."""
        categories = {
            faq.get("category", "").strip()
            for faq in self.faqs
            if isinstance(faq.get("category"), str) and faq.get("category").strip()
        }
        return sorted(categories)


# Singleton instance helper
_default_chatbot: Optional[FAQChatbot] = None


def get_chatbot() -> FAQChatbot:
    """Return a shared, initialized FAQChatbot instance."""
    global _default_chatbot
    if _default_chatbot is None:
        _default_chatbot = FAQChatbot()
    return _default_chatbot
