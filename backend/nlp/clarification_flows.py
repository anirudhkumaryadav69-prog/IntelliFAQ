"""
Reusable Multi-Turn Clarification & Assessment Architecture for IntelliFAQ 2.0.

Provides a generic, extensible workflow engine (`ClarificationFlow`, `WorkflowSlot`,
`FLOW_REGISTRY`) for multi-turn conversational clarification and personalized
assessment, while keeping all conversation state serializable for SQLite storage.

Currently implements:
- `admission_eligibility`: Progressive slot collection (programme, qualification,
  stream/discipline, percentage/CGPA) and verified-criteria evaluation without
  fabricating unverified institutional admission cutoffs or rules.

Future workflows (e.g., scholarship_eligibility, placement_eligibility,
examination_query, attendance_query) can register additional `ClarificationFlow`
definitions using the same state machine.
"""

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class WorkflowSlot:
    """Definition of a single progressive clarification slot in a workflow."""

    name: str
    label: str
    prompt_builder: Callable[[Dict[str, Any]], str]
    extractor: Callable[[str, bool], Optional[str]]
    is_applicable: Callable[[Dict[str, Any]], bool] = lambda _slots: True


@dataclass(frozen=True)
class ClarificationFlow:
    """Definition of a reusable multi-turn clarification workflow."""

    flow_name: str
    category: str
    slots: Tuple[WorkflowSlot, ...]
    evaluator: Callable[[Dict[str, Any], Any, Optional[Dict[str, Any]]], str]


# ============================================================================
# Admission Eligibility Detection & Slot Extractors
# ============================================================================

_ADMISSION_PERSONAL_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:am\s+i|can\s+i|do\s+i|could\s+i|would\s+i|will\s+i(?:\s+be)?)\b.*\b(?:eligib\w*|qualif(?:y|ied)|get\s+admission|admit(?:ted)?|apply\s+for\s+(?:admissions?|b\.?\s*tech|m\.?\s*tech|bba|mba|bca|mca|b\.?\s*sc|m\.?\s*sc|b\.?\s*com|m\.?\s*com|diploma))\b|"
    r"\b(?:whether|if)\s+i\s+(?:am\s+|can\s+|will\s+be\s+)?(?:eligib\w*|qualif(?:y|ied)|meet)\b.*\b(?:eligib\w*|qualif(?:y|ied)|admissions?|b\.?\s*tech|m\.?\s*tech|bba|mba|bca|mca|b\.?\s*sc|m\.?\s*sc|b\.?\s*com|m\.?\s*com|diploma)\b|"
    r"\bcheck\s+(?:whether|if)\s+i\s+(?:am\s+)?(?:eligib\w*|qualif(?:y|ied))\b|"
    r"\b(?:my\s+(?:percentage|marks|score|cgpa|gpa|chances)|chances\s+of\s+(?:getting\s+)?admissions?)\b|"
    r"\b(?:is\s+my\s+(?:percentage|marks|score|cgpa)\s+(?:enough|sufficient|valid|eligible))\b|"
    r"\bi\s+(?:want|would\s+like|need|wish)\s+(?:to\s+(?:take|get|apply\s+for)\s+)?admissions?\b|"
    r"\bcheck\s+(?:my\s+)?(?:admissions?\s+)?eligib\w*\b|"
    r"\bget\s+admissions?\s+(?:after|with|in|into|for)\b"
    r")",
    re.IGNORECASE,
)

_NON_ADMISSION_ELIGIBILITY_TOPICS = re.compile(
    r"\b(?:scholarship|stipend|placement|internship|recruiter|exam(?:ination)?|attendance|hostel|library|fee|tuition|refund|cancel|challan|receipt|installment|dues|payment)\b",
    re.IGNORECASE,
)

_PROGRAMME_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bb\.?\s*tech\s+(?:in\s+)?(?:cse|computer\s+science(?:\s+and\s+engineering)?)\b", re.I), "B.Tech CSE"),
    (re.compile(r"\bb\.?\s*tech\s+(?:in\s+)?(?:ece|electronics(?:\s+and\s+communication)?)\b", re.I), "B.Tech ECE"),
    (re.compile(r"\bb\.?\s*tech\s+(?:in\s+)?(?:me|mechanical)\b", re.I), "B.Tech Mechanical"),
    (re.compile(r"\bb\.?\s*tech\s+(?:in\s+)?(?:ce|civil)\b", re.I), "B.Tech Civil"),
    (re.compile(r"\bb\.?\s*tech\s+(?:in\s+)?(?:it|information\s+technology)\b", re.I), "B.Tech IT"),
    (re.compile(r"\bb\.?\s*tech\b|\bbachelor\s+of\s+technology\b", re.I), "B.Tech"),
    (re.compile(r"\bm\.?\s*tech\b|\bmaster\s+of\s+technology\b", re.I), "M.Tech"),
    (re.compile(r"\bbba\b|\bbachelor\s+of\s+business\s+administration\b", re.I), "BBA"),
    (re.compile(r"\bmba\b|\bmaster\s+of\s+business\s+administration\b", re.I), "MBA"),
    (re.compile(r"\bbca\b|\bbachelor\s+of\s+computer\s+applications\b", re.I), "BCA"),
    (re.compile(r"\bmca\b|\bmaster\s+of\s+computer\s+applications\b", re.I), "MCA"),
    (re.compile(r"\bb\.?\s*sc\b", re.I), "B.Sc"),
    (re.compile(r"\bm\.?\s*sc\b", re.I), "M.Sc"),
    (re.compile(r"\bb\.?\s*com\b", re.I), "B.Com"),
    (re.compile(r"\bm\.?\s*com\b", re.I), "M.Com"),
    (re.compile(r"\bb\.?\s*pharm\b", re.I), "B.Pharm"),
    (re.compile(r"\bd\.?\s*pharm\b", re.I), "D.Pharm"),
    (re.compile(r"\bph\.?\s*d\b", re.I), "Ph.D"),
    (re.compile(r"\bllb\b", re.I), "LLB"),
)

_QUALIFICATION_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(?:class\s*12|12th|10\s*\+\s*2|higher\s+secondary|senior\s+secondary|hsc|intermediate)\b", re.I), "Class 12 (10+2)"),
    (re.compile(r"\b(?:diploma|polytechnic)\b", re.I), "Diploma"),
    (re.compile(r"\b(?:graduation|graduate|bachelor'?s?|undergraduate\s+degree)\b", re.I), "Graduation (Bachelor's Degree)"),
    (re.compile(r"\b(?:post\s*graduation|postgraduate|master'?s?)\b", re.I), "Postgraduation (Master's Degree)"),
    (re.compile(r"\b(?:class\s*10|10th|matric(?:ulation)?|ssc)\b", re.I), "Class 10"),
)

_STREAM_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(?:non[\s-]*medical|pcm|physics\s*,?\s*chemistry\s*(?:and|,)?\s*math(?:ematic)?s?)\b", re.I), "Non-medical (PCM)"),
    (re.compile(r"\b(?:medical|pcb|physics\s*,?\s*chemistry\s*(?:and|,)?\s*biology)\b", re.I), "Medical (PCB)"),
    (re.compile(r"\b(?:commerce|accounts?|accountancy)\b", re.I), "Commerce"),
    (re.compile(r"\b(?:arts|humanities)\b", re.I), "Arts / Humanities"),
    (re.compile(r"\b(?:computer\s+science|cse|it|information\s+technology)\b", re.I), "Computer Science / IT"),
    (re.compile(r"\b(?:mechanical|civil|electrical|electronics)\b", re.I), "Engineering"),
    (re.compile(r"\bscience\b", re.I), "Science"),
    (re.compile(r"\bmanagement\b", re.I), "Management"),
)

_PERCENTAGE_RE = re.compile(
    r"(?<!\d)(100(?:\.0+)?|\d{1,2}(?:\.\d+)?)\s*(?:%|percent(?:age)?\b)",
    re.IGNORECASE,
)
_CGPA_RE = re.compile(
    r"(?<!\d)(10(?:\.0+)?|[0-9](?:\.\d+)?)\s*(?:cgpa|gpa)\b",
    re.IGNORECASE,
)
_BARE_NUMBER_RE = re.compile(r"^\s*(100(?:\.0+)?|\d{1,2}(?:\.\d+)?)\s*\.?\s*$")

_GENERIC_NON_ANSWERS = {
    "yes",
    "no",
    "yeah",
    "nope",
    "maybe",
    "ok",
    "okay",
    "sure",
    "not sure",
    "dont know",
    "don't know",
    "idk",
    "none",
    "nothing",
}


def extract_programme(text: str, is_expected_slot: bool = False) -> Optional[str]:
    """Extract programme/course of interest from user text."""
    if not isinstance(text, str) or not text.strip():
        return None
    for pattern, canonical in _PROGRAMME_PATTERNS:
        if pattern.search(text):
            return canonical

    # Handle explicit "admission in <programme>" or direct answer when programme is expected
    match = re.search(
        r"\badmission\s+(?:in|to|for|into)\s+([A-Za-z0-9.\s&/-]{2,60}?)(?:\s*[.?]|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        candidate = match.group(1).strip(" .?!,")
        lowered = candidate.lower()
        if lowered not in {"this university", "the university", "university", "college"}:
            return candidate

    if is_expected_slot:
        cleaned = text.strip(" .?!,")
        if cleaned.lower() not in _GENERIC_NON_ANSWERS and len(cleaned) >= 2:
            # Avoid capturing a percentage or qualification as a programme name
            if not _BARE_NUMBER_RE.match(cleaned) and not extract_qualification(cleaned, False):
                return cleaned
    return None


def extract_qualification(text: str, is_expected_slot: bool = False) -> Optional[str]:
    """Extract previous educational qualification from user text."""
    if not isinstance(text, str) or not text.strip():
        return None
    for pattern, canonical in _QUALIFICATION_PATTERNS:
        if pattern.search(text):
            return canonical

    if is_expected_slot:
        cleaned = text.strip(" .?!,")
        if cleaned.lower() not in _GENERIC_NON_ANSWERS and len(cleaned) >= 2:
            if not _BARE_NUMBER_RE.match(cleaned):
                return cleaned
    return None


def extract_stream(text: str, is_expected_slot: bool = False) -> Optional[str]:
    """Extract academic stream or relevant subjects from user text."""
    if not isinstance(text, str) or not text.strip():
        return None
    for pattern, canonical in _STREAM_PATTERNS:
        if pattern.search(text):
            return canonical

    if is_expected_slot:
        cleaned = text.strip(" .?!,")
        if cleaned.lower() not in _GENERIC_NON_ANSWERS and len(cleaned) >= 2:
            if not _BARE_NUMBER_RE.match(cleaned):
                return cleaned
    return None


def extract_percentage(text: str, is_expected_slot: bool = False) -> Optional[str]:
    """Extract percentage or CGPA score from user text."""
    if not isinstance(text, str) or not text.strip():
        return None
    pct_match = _PERCENTAGE_RE.search(text)
    if pct_match:
        val = float(pct_match.group(1))
        if 0.0 <= val <= 100.0:
            return f"{pct_match.group(1)}%"

    cgpa_match = _CGPA_RE.search(text)
    if cgpa_match:
        val = float(cgpa_match.group(1))
        if 0.0 <= val <= 10.0:
            return f"{cgpa_match.group(1)} CGPA"

    if is_expected_slot:
        bare_match = _BARE_NUMBER_RE.match(text)
        if bare_match:
            val = float(bare_match.group(1))
            if 0.0 <= val <= 100.0:
                return f"{bare_match.group(1)}%"
    return None


def _prompt_programme(_slots: Dict[str, Any]) -> str:
    return (
        "Sure! I can help you check your admission eligibility. "
        "First, which programme are you interested in applying for "
        "(for example, B.Tech, B.Tech CSE, BBA, MBA, or another programme)?"
    )


def _prompt_qualification(slots: Dict[str, Any]) -> str:
    prog = slots.get("programme", "this programme")
    return (
        f"Got it — you're interested in {prog}. "
        "What is your previous or highest completed educational qualification "
        "(for example, Class 12, Diploma, or Graduation)?"
    )


def _prompt_stream(slots: Dict[str, Any]) -> str:
    qual = slots.get("qualification", "your qualification")
    return (
        f"Thanks! Which academic stream or relevant subjects did you study in {qual} "
        "(for example, Non-medical / PCM, Medical / PCB, Commerce, Arts, or Computer Science)?"
    )


def _prompt_percentage(_slots: Dict[str, Any]) -> str:
    return (
        "What percentage or CGPA did you obtain in your qualifying examination "
        "(for example, 72% or 8.0 CGPA)?"
    )


def _parse_numeric_score(score_str: Optional[str]) -> Optional[Tuple[str, float]]:
    if not score_str:
        return None
    pct_match = _PERCENTAGE_RE.search(score_str)
    if pct_match:
        return ("percentage", float(pct_match.group(1)))
    cgpa_match = _CGPA_RE.search(score_str)
    if cgpa_match:
        return ("cgpa", float(cgpa_match.group(1)))
    return None


def evaluate_admission_eligibility(
    slots: Dict[str, Any],
    faq_bot: Any,
    verified_criteria: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """
    Evaluate collected admission details against verified criteria when
    explicitly configured. When verified programme-specific criteria are
    unavailable (as in the sample FAQ dataset), report the collected details
    honestly without fabricating cutoffs or claiming eligibility, and guide
    the user to the official Admissions Office or Portal.
    """
    programme = slots.get("programme", "the requested programme")
    qualification = slots.get("qualification", "Not provided")
    stream = slots.get("stream", "Not provided")
    percentage = slots.get("percentage", "Not provided")

    summary = (
        f"Thank you for sharing your details:\n"
        f"• Programme: {programme}\n"
        f"• Qualification: {qualification}\n"
        f"• Stream / Subjects: {stream}\n"
        f"• Score Obtained: {percentage}"
    )

    # Check if an explicitly verified criteria source has rules for this programme
    if verified_criteria and programme in verified_criteria:
        rules = verified_criteria[programme]
        checks: List[str] = []
        all_met = True

        req_quals = rules.get("qualifications")
        if req_quals:
            if qualification in req_quals:
                checks.append(f"• Qualification ({qualification}): Satisfied.")
            else:
                checks.append(
                    f"• Qualification ({qualification}): Not satisfied (requires {', '.join(req_quals)})."
                )
                all_met = False

        req_streams = rules.get("streams")
        if req_streams:
            if stream in req_streams:
                checks.append(f"• Stream / Subjects ({stream}): Satisfied.")
            else:
                checks.append(
                    f"• Stream / Subjects ({stream}): Not satisfied (requires {', '.join(req_streams)})."
                )
                all_met = False

        min_pct = rules.get("min_percentage")
        parsed = _parse_numeric_score(percentage)
        if min_pct is not None and parsed and parsed[0] == "percentage":
            if parsed[1] >= float(min_pct):
                checks.append(
                    f"• Minimum Percentage ({min_pct}%): Satisfied ({percentage})."
                )
            else:
                checks.append(
                    f"• Minimum Percentage ({min_pct}%): Not satisfied ({percentage} is below {min_pct}%)."
                )
                all_met = False

        verdict = (
            f"Based on the verified criteria for {programme}, you meet the listed requirements."
            if all_met
            else f"Based on the verified criteria for {programme}, one or more listed requirements are not met."
        )
        return f"{summary}\n\n{verdict}\n" + "\n".join(checks)

    # Retrieve general admission guidance from the existing FAQ knowledge base
    faq_guidance = ""
    if faq_bot is not None and getattr(faq_bot, "is_ready", False):
        query_hint = (
            "lateral entry admission requirements"
            if qualification == "Diploma"
            else "undergraduate admission requirements"
        )
        faq_res = faq_bot.get_response(query_hint)
        if faq_res.get("match_type") == "clear_match" and faq_res.get("answer"):
            faq_guidance = f"\n\nGeneral FAQ Guidance:\n{faq_res['answer']}"

    return (
        f"{summary}\n\n"
        f"I have collected your details for {programme}, but verified programme-specific "
        "eligibility criteria (such as exact minimum percentages, required subject combinations, "
        "and entrance examination rules) are not available in our current FAQ demonstration dataset, "
        "so I cannot make a reliable eligibility determination on my own.\n\n"
        "Please contact the University Admissions Office or check the official Admissions Portal "
        f"to confirm your eligibility for {programme}."
        f"{faq_guidance}"
    )


# ============================================================================
# Reusable Flow Registry & State Machine Helpers
# ============================================================================

ADMISSION_ELIGIBILITY_FLOW = ClarificationFlow(
    flow_name="admission_eligibility",
    category="Admissions",
    slots=(
        WorkflowSlot(
            name="programme",
            label="Programme of interest",
            prompt_builder=_prompt_programme,
            extractor=extract_programme,
        ),
        WorkflowSlot(
            name="qualification",
            label="Previous qualification",
            prompt_builder=_prompt_qualification,
            extractor=extract_qualification,
        ),
        WorkflowSlot(
            name="stream",
            label="Academic stream / subjects",
            prompt_builder=_prompt_stream,
            extractor=extract_stream,
        ),
        WorkflowSlot(
            name="percentage",
            label="Percentage / CGPA",
            prompt_builder=_prompt_percentage,
            extractor=extract_percentage,
        ),
    ),
    evaluator=evaluate_admission_eligibility,
)

FLOW_REGISTRY: Dict[str, ClarificationFlow] = {
    ADMISSION_ELIGIBILITY_FLOW.flow_name: ADMISSION_ELIGIBILITY_FLOW,
}


def detect_clarification_flow_intent(
    user_message: str, faq_bot: Any
) -> Optional[ClarificationFlow]:
    """
    Detect whether a standalone user message initiates a personalized
    clarification workflow (e.g., admission eligibility assessment).

    Exact/near-exact matches to existing informational FAQs (confidence >= 85%)
    are left to the standard FAQ engine so normal FAQ queries are never hijacked.
    """
    if not isinstance(user_message, str) or not user_message.strip():
        return None

    # Do not hijack queries about other university categories
    if _NON_ADMISSION_ELIGIBILITY_TOPICS.search(user_message):
        return None

    # Preserve exact / near-exact existing FAQ matches (e.g., FAQ #1, #7, #11)
    if faq_bot is not None and getattr(faq_bot, "is_ready", False):
        standalone = faq_bot.get_response(user_message)
        if (
            standalone.get("match_type") == "clear_match"
            and standalone.get("confidence", 0.0) >= 85.0
        ):
            return None

    if _ADMISSION_PERSONAL_PATTERNS.search(user_message):
        return FLOW_REGISTRY["admission_eligibility"]

    return None


def _extract_all_slots(
    flow: ClarificationFlow,
    message: str,
    existing_slots: Dict[str, Any],
    expected_slot_name: Optional[str],
) -> Dict[str, Any]:
    """Extract any applicable slot values from `message` into a new slots dict."""
    updated = dict(existing_slots)

    # First try extracting the currently expected slot specifically
    if expected_slot_name:
        for slot in flow.slots:
            if slot.name == expected_slot_name and not updated.get(slot.name):
                val = slot.extractor(message, True)
                if val:
                    updated[slot.name] = val
                break

    # Also opportunistic extraction for any other missing slots mentioned in the same message
    # (skip extracting stream when the message only named the target programme, e.g. "B.Tech CSE")
    for slot in flow.slots:
        if slot.name == expected_slot_name or updated.get(slot.name):
            continue
        if expected_slot_name == "programme" and slot.name == "stream":
            continue
        if slot.is_applicable(updated):
            val = slot.extractor(message, False)
            if val:
                updated[slot.name] = val

    return updated


def _next_missing_slot(
    flow: ClarificationFlow, slots: Dict[str, Any]
) -> Optional[WorkflowSlot]:
    for slot in flow.slots:
        if slot.is_applicable(slots) and not slots.get(slot.name):
            return slot
    return None


def process_clarification_turn(
    flow: ClarificationFlow,
    user_message: str,
    current_state: Optional[Dict[str, Any]],
    faq_bot: Any,
    verified_criteria: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Advance a clarification workflow by one user turn.

    Returns `(assistant_answer, next_clarification_state)`.
    When all required slots are collected, `next_clarification_state` is `{}`
    (workflow completed) and `assistant_answer` is the eligibility assessment.
    """
    existing_slots = (
        dict(current_state.get("slots", {}))
        if isinstance(current_state, dict)
        else {}
    )
    expected_slot = (
        current_state.get("expected_slot")
        if isinstance(current_state, dict)
        else None
    )

    updated_slots = _extract_all_slots(
        flow, user_message, existing_slots, expected_slot
    )
    missing_slot = _next_missing_slot(flow, updated_slots)

    if missing_slot is None:
        answer = flow.evaluator(updated_slots, faq_bot, verified_criteria)
        return answer, {}

    prompt = missing_slot.prompt_builder(updated_slots)
    next_state = {
        "flow_name": flow.flow_name,
        "category": flow.category,
        "slots": updated_slots,
        "expected_slot": missing_slot.name,
    }
    return prompt, next_state


__all__ = [
    "ADMISSION_ELIGIBILITY_FLOW",
    "ClarificationFlow",
    "FLOW_REGISTRY",
    "WorkflowSlot",
    "detect_clarification_flow_intent",
    "evaluate_admission_eligibility",
    "extract_percentage",
    "extract_programme",
    "extract_qualification",
    "extract_stream",
    "process_clarification_turn",
]
