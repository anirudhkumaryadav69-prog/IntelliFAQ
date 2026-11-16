"""
Comprehensive Verification & Test Suite for the Upgraded IntelliFAQ NLP Engine.

Tests all required PROMPT 08 capabilities:
1. Exact FAQ question match
2. Alternative phrasing match
3. Differently worded paraphrase (clear match)
4. Ambiguous query (multiple competing plausible FAQ candidates)
5. Clear match verification
6. Unrelated out-of-domain question (fallback handling)
7. Unsupported university question (domain-aware fallback handling)
8. Empty and invalid inputs (whitespace, None, integer, list)
9. Duplicate candidate prevention across alternative phrasings
10. Candidate ranking order (descending cosine similarity, max 3)
11. Configurable threshold boundary cases (clear_match vs ambiguous_match vs no_reliable_match)
"""

import sys
from typing import Any, Dict, List

from nlp import FAQChatbot, preprocess_text
from nlp.chatbot import (
    FALLBACK_UNRELATED_MESSAGE,
    FALLBACK_UNSUPPORTED_UNIVERSITY_MESSAGE,
    MATCH_AMBIGUOUS,
    MATCH_CLEAR,
    MATCH_NONE,
)
from test_evaluation import evaluate_chatbot


def assert_candidate_invariants(response: Dict[str, Any]) -> None:
    """
    Verify candidate list structure, max count (<= 3), absence of duplicate
    faq_ids, and strict descending similarity order.
    """
    candidates: List[Dict[str, Any]] = response.get("candidates", [])
    assert isinstance(candidates, list), "candidates must be a list"
    assert len(candidates) <= 3, f"Expected at most 3 candidates, got {len(candidates)}"

    seen_ids = set()
    prev_sim = 100.01
    for cand in candidates:
        assert set(cand.keys()) == {
            "faq_id",
            "question",
            "category",
            "similarity",
        }, f"Unexpected candidate keys: {cand.keys()}"
        fid = cand["faq_id"]
        assert fid not in seen_ids, f"Duplicate faq_id {fid} found in candidates!"
        seen_ids.add(fid)

        sim = cand["similarity"]
        assert 0.0 <= sim <= 100.0, f"Similarity {sim} out of 0-100 range"
        assert sim <= prev_sim + 1e-6, (
            f"Candidates not sorted descending: {sim} > {prev_sim}"
        )
        prev_sim = sim


def print_test_result(label: str, user_input: object, response: Dict[str, Any]) -> None:
    """Format and print the upgraded NLP engine output for a single test case."""
    print("=" * 82)
    print(f"TEST CASE             : {label}")
    print(f"USER INPUT            : {repr(user_input)}")
    if isinstance(user_input, str):
        print(f"PREPROCESSED TEXT     : {repr(preprocess_text(user_input))}")
    print("-" * 82)
    print(f"Success               : {response.get('success')}")
    print(f"Match Type            : {response.get('match_type')}")
    print(f"Fallback Triggered    : {response.get('fallback')}")
    print(f"Needs Clarification   : {response.get('needs_clarification')}")
    print(f"FAQ ID                : {response.get('faq_id')}")
    print(f"Matched Question      : {response.get('matched_question')}")
    print(f"Category              : {response.get('category')}")
    print(f"Similarity Score      : {response.get('confidence'):.2f}%")
    if response.get("clarification_message"):
        print(f"Clarification Message : {response.get('clarification_message')}")
    print(f"Answer                : {response.get('answer')}")
    print("-" * 82)
    candidates = response.get("candidates", [])
    print(f"Top Distinct Candidates ({len(candidates)}):")
    if not candidates:
        print("  (None)")
    else:
        for idx, cand in enumerate(candidates, start=1):
            print(
                f"  #{idx} [FAQ {cand['faq_id']}] ({cand['category']}) "
                f"{cand['similarity']:.2f}% — {cand['question']}"
            )
    print("=" * 82)
    print()


def run_tests() -> None:
    """Run all 12 NLP verification scenarios and assert expected properties."""
    print("Initializing Upgraded IntelliFAQ NLP Engine...")
    chatbot = FAQChatbot()

    if not chatbot.is_ready:
        print(f"[ERROR] Chatbot failed to initialize: {chatbot.load_error}")
        sys.exit(1)

    print(
        f"Loaded {len(chatbot.faqs)} FAQ records and indexed "
        f"{len(chatbot.variants_index)} total question variants across "
        f"{len(chatbot.get_categories())} categories: "
        f"{', '.join(chatbot.get_categories())}\n"
    )

    passed = 0
    total_tests = 14

    # -------------------------------------------------------------------------
    # 1. Exact Question Match
    # -------------------------------------------------------------------------
    q1 = "What are the admission requirements for undergraduate programs?"
    r1 = chatbot.get_response(q1)
    print_test_result("1. Exact Question Match", q1, r1)
    assert_candidate_invariants(r1)
    assert r1["success"] is True
    assert r1["match_type"] == MATCH_CLEAR
    assert r1["fallback"] is False
    assert r1["needs_clarification"] is False
    assert r1["clarification_message"] is None
    assert r1["faq_id"] == 1
    assert r1["confidence"] == 100.0
    passed += 1

    # -------------------------------------------------------------------------
    # 2. Alternative Phrasing Match
    # -------------------------------------------------------------------------
    q2 = "Can I pay my semester fees through UPI, net banking, or card?"
    r2 = chatbot.get_response(q2)
    print_test_result("2. Alternative Phrasing Match", q2, r2)
    assert_candidate_invariants(r2)
    assert r2["success"] is True
    assert r2["match_type"] == MATCH_CLEAR
    assert r2["fallback"] is False
    assert r2["needs_clarification"] is False
    assert r2["faq_id"] == 16
    assert r2["confidence"] == 100.0
    passed += 1

    # -------------------------------------------------------------------------
    # 3. Paraphrase Match
    # -------------------------------------------------------------------------
    q3 = "How do I get a medical leave relaxation if I was sick and missed lectures?"
    r3 = chatbot.get_response(q3)
    print_test_result("3. Paraphrase Match", q3, r3)
    assert_candidate_invariants(r3)
    assert r3["success"] is True
    assert r3["match_type"] == MATCH_CLEAR
    assert r3["fallback"] is False
    assert r3["faq_id"] == 33
    assert r3["category"] == "Attendance"
    assert r3["confidence"] >= 34.0
    passed += 1

    # -------------------------------------------------------------------------
    # 4. Ambiguous Query (Multiple competing plausible FAQ matches)
    # -------------------------------------------------------------------------
    q4 = "scholarship"
    r4 = chatbot.get_response(q4)
    print_test_result("4. Ambiguous Query (Competing Candidates)", q4, r4)
    assert_candidate_invariants(r4)
    assert r4["success"] is True
    assert r4["match_type"] == MATCH_AMBIGUOUS
    assert r4["fallback"] is False
    assert r4["needs_clarification"] is True
    assert isinstance(r4["clarification_message"], str) and len(r4["clarification_message"]) > 0
    assert len(r4["candidates"]) == 3
    passed += 1

    # -------------------------------------------------------------------------
    # 5. Clear Match (Distinct High-Confidence Paraphrase)
    # -------------------------------------------------------------------------
    q5 = "How can I connect my laptop to the campus Wi-Fi network?"
    r5 = chatbot.get_response(q5)
    print_test_result("5. Clear Match (Specific Campus Wi-Fi Query)", q5, r5)
    assert_candidate_invariants(r5)
    assert r5["success"] is True
    assert r5["match_type"] == MATCH_CLEAR
    assert r5["fallback"] is False
    assert r5["needs_clarification"] is False
    assert r5["faq_id"] == 76
    assert r5["category"] == "Campus Facilities"
    passed += 1

    # -------------------------------------------------------------------------
    # 6. Unrelated Out-of-Domain Question
    # -------------------------------------------------------------------------
    q6 = "What is the best recipe for baking a chocolate fudge cake at home?"
    r6 = chatbot.get_response(q6)
    print_test_result("6. Unrelated Out-of-Domain Question", q6, r6)
    assert_candidate_invariants(r6)
    assert r6["success"] is True
    assert r6["match_type"] == MATCH_NONE
    assert r6["fallback"] is True
    assert r6["needs_clarification"] is False
    assert r6["faq_id"] is None
    assert r6["answer"] == FALLBACK_UNRELATED_MESSAGE
    passed += 1

    # -------------------------------------------------------------------------
    # 7. Unsupported University Question
    # -------------------------------------------------------------------------
    q7 = "Does the university campus have an Olympic-sized swimming pool and scuba diving club?"
    r7 = chatbot.get_response(q7)
    print_test_result("7. Unsupported University Question", q7, r7)
    assert_candidate_invariants(r7)
    assert r7["success"] is True
    assert r7["match_type"] == MATCH_NONE
    assert r7["fallback"] is True
    assert r7["needs_clarification"] is False
    assert r7["faq_id"] is None
    assert r7["answer"] == FALLBACK_UNSUPPORTED_UNIVERSITY_MESSAGE
    passed += 1

    # -------------------------------------------------------------------------
    # 8. Empty and Invalid Inputs
    # -------------------------------------------------------------------------
    for invalid_label, invalid_val in [
        ("8a. Empty Whitespace Input", "   "),
        ("8b. None Input", None),
        ("8c. Numeric Input", 12345),
    ]:
        r_inv = chatbot.get_response(invalid_val)
        print_test_result(invalid_label, invalid_val, r_inv)
        assert_candidate_invariants(r_inv)
        assert r_inv["success"] is False
        assert r_inv["match_type"] == MATCH_NONE
        assert r_inv["fallback"] is True
        assert r_inv["candidates"] == []
        assert r_inv["needs_clarification"] is False
        assert r_inv["clarification_message"] is None
    passed += 1

    # -------------------------------------------------------------------------
    # 9. Duplicate Candidate Prevention Verification
    # -------------------------------------------------------------------------
    # Query containing words shared across primary + all 3 alternative phrasings of FAQ #16
    q9 = "How can I pay semester tuition fees online through UPI net banking or card?"
    r9 = chatbot.get_response(q9)
    print_test_result(
        "9. Duplicate Candidate Prevention (Multi-Variant Overlap)", q9, r9
    )
    assert_candidate_invariants(r9)
    candidate_ids = [c["faq_id"] for c in r9["candidates"]]
    assert len(candidate_ids) == len(set(candidate_ids)), (
        f"Duplicate FAQ IDs detected: {candidate_ids}"
    )
    assert candidate_ids[0] == 16
    passed += 1

    # -------------------------------------------------------------------------
    # 10. Candidate Ranking Verification
    # -------------------------------------------------------------------------
    q10 = "When will semester examination results and grade cards be declared online?"
    r10 = chatbot.get_response(q10)
    print_test_result("10. Candidate Ranking Verification (Top 3 Order)", q10, r10)
    assert_candidate_invariants(r10)
    sims = [c["similarity"] for c in r10["candidates"]]
    assert len(sims) == 3
    assert sims[0] >= sims[1] >= sims[2], f"Candidates not properly ranked: {sims}"
    passed += 1

    # -------------------------------------------------------------------------
    # 11. Configurable Threshold Boundary Cases
    # -------------------------------------------------------------------------
    print("=" * 82)
    print("TEST CASE             : 11. Threshold Boundary Cases")
    print("-" * 82)
    boundary_query = (
        "How do I get a medical leave relaxation if I was sick and missed lectures?"
    )
    # Note: boundary_query has top similarity = 35.22% (0.3522)

    # Case 11a: confidence_threshold = 0.40 (above 0.3522 -> no_reliable_match)
    strict_bot = FAQChatbot(
        confidence_threshold=0.40,
        clear_match_threshold=0.50,
        ambiguity_margin=0.08,
        preprocessor=chatbot.preprocessor,
    )
    res_11a = strict_bot.get_response(boundary_query)
    print(
        f"  11a [confidence_threshold=0.40] -> match_type={res_11a['match_type']}, "
        f"fallback={res_11a['fallback']}, confidence={res_11a['confidence']}%"
    )
    assert res_11a["match_type"] == MATCH_NONE
    assert res_11a["fallback"] is True

    # Case 11b: confidence_threshold = 0.20, clear_match_threshold = 0.40
    # (0.3522 falls inside [0.20, 0.40) -> ambiguous_match)
    borderline_bot = FAQChatbot(
        confidence_threshold=0.20,
        clear_match_threshold=0.40,
        ambiguity_margin=0.05,
        preprocessor=chatbot.preprocessor,
    )
    res_11b = borderline_bot.get_response(boundary_query)
    print(
        f"  11b [clear_match_threshold=0.40] -> match_type={res_11b['match_type']}, "
        f"needs_clarification={res_11b['needs_clarification']}, confidence={res_11b['confidence']}%"
    )
    assert res_11b["match_type"] == MATCH_AMBIGUOUS
    assert res_11b["needs_clarification"] is True

    # Case 11c: confidence_threshold = 0.20, clear_match_threshold = 0.30
    # (0.3522 >= 0.30 and well ahead of #2 -> clear_match)
    lenient_bot = FAQChatbot(
        confidence_threshold=0.20,
        clear_match_threshold=0.30,
        ambiguity_margin=0.05,
        preprocessor=chatbot.preprocessor,
    )
    res_11c = lenient_bot.get_response(boundary_query)
    print(
        f"  11c [clear_match_threshold=0.30] -> match_type={res_11c['match_type']}, "
        f"needs_clarification={res_11c['needs_clarification']}, confidence={res_11c['confidence']}%"
    )
    assert res_11c["match_type"] == MATCH_CLEAR
    assert res_11c["needs_clarification"] is False
    print("=" * 82)
    print()
    passed += 1

    # -------------------------------------------------------------------------
    # 12. Fee Subtopic Intent Distinction & Disambiguation Regression Suite
    # -------------------------------------------------------------------------
    print("=" * 82)
    print("TEST CASE             : 12. Fee Subtopic Intent Distinction Suite")
    print("-" * 82)
    fee_subtopic_cases = [
        # Fee amount / structure (FAQ #17)
        ("Fee Amount 12a", "What are the semester tuition fees?", 17),
        ("Fee Amount 12b", "How much do I have to pay per semester?", 17),
        ("Fee Amount 12c", "Tell me about the university fee structure.", 17),
        ("Fee Amount 12d", "What is the total tuition fee?", 17),
        # Payment method (FAQ #16)
        ("Payment Method 12e", "How can I pay my semester fees?", 16),
        ("Payment Method 12f", "Can I pay using UPI?", 16),
        ("Payment Method 12g", "Where can I pay my tuition fees?", 16),
        # Payment deadline (FAQ #18)
        ("Payment Deadline 12h", "When is the last date to pay semester fees?", 18),
        ("Payment Deadline 12i", "What is the fee payment deadline?", 18),
        # Late payment & penalties (FAQ #23)
        ("Late Payment 12j", "What happens if I pay my fees late?", 23),
        ("Late Payment 12k", "Is there a late payment penalty?", 23),
        # Refund & admission cancellation refund (FAQ #22)
        ("Fee Refund 12l", "Can I get a refund if I cancel my admission?", 22),
        # Additional fee subtopics (Receipt #19, Failed Transaction #20, Installment #21, Dues #30)
        ("Fee Receipt 12m", "How do I download my fee payment receipt?", 19),
        (
            "Failed Payment 12n",
            "What if my online fee payment failed but money was deducted?",
            20,
        ),
        ("Installment 12o", "Can I pay my semester fees in installments?", 21),
        ("Pending Dues 12p", "How can I check my pending fee dues?", 30),
    ]
    for sublabel, fee_query, expected_faq_id in fee_subtopic_cases:
        fee_res = chatbot.get_response(fee_query)
        assert_candidate_invariants(fee_res)
        print(
            f"  {sublabel:<22} | Q: {fee_query:<52} -> FAQ #{fee_res['faq_id']} "
            f"({fee_res['match_type']}, {fee_res['confidence']:.2f}%)"
        )
        assert fee_res["success"] is True
        assert fee_res["fallback"] is False
        assert fee_res["needs_clarification"] is False
        assert fee_res["match_type"] == MATCH_CLEAR, (
            f"Expected clear_match for '{fee_query}', got {fee_res['match_type']}"
        )
        assert fee_res["category"] == "Fee Payment"
        assert fee_res["faq_id"] == expected_faq_id, (
            f"Expected FAQ #{expected_faq_id} for '{fee_query}', got FAQ #{fee_res['faq_id']}"
        )
    print("=" * 82)
    print()
    passed += 1

    # -------------------------------------------------------------------------
    # 13. Comprehensive 84-Query Multi-Category Evaluation Dataset
    # -------------------------------------------------------------------------
    eval_summary = evaluate_chatbot(chatbot=chatbot, verbose=True)
    assert eval_summary["total_queries"] == 84
    assert eval_summary["correct_faq_matches"] == 70
    assert eval_summary["incorrect_faq_matches"] == 0
    assert eval_summary["correct_ambiguity_detections"] == 6
    assert eval_summary["correct_fallback_responses"] == 8
    assert eval_summary["accuracy"] == 100.0
    passed += 1

    # -------------------------------------------------------------------------
    # 14. Multi-Intent Question Detection, Response Handling & Threshold Consistency (Cases A–J)
    # -------------------------------------------------------------------------
    print("=" * 82)
    print(
        "TEST CASE             : 14. Multi-Intent Question Detection & Response Suite (Cases A–J)"
    )
    print("-" * 82)

    # Case A1 & A2: Hostel facilities + examination timetable (sentence split & conjunction split)
    for case_label, query_a in [
        (
            "Case A1 (Sentence Split)",
            "Tell me about hostel facilities. What is the examination timetable?",
        ),
        (
            "Case A2 (Conjunction Split)",
            "Tell me about hostel facilities and examination timetables.",
        ),
    ]:
        res_a = chatbot.get_response(query_a)
        assert_candidate_invariants(res_a)
        assert res_a["is_multi_intent"] is True, f"{case_label} should be multi-intent"
        assert len(res_a["sub_responses"]) == 2
        assert res_a["sub_responses"][0]["faq_id"] == 75
        assert res_a["sub_responses"][0]["category"] == "Campus Facilities"
        assert res_a["sub_responses"][0]["match_type"] == MATCH_CLEAR
        assert res_a["sub_responses"][0]["confidence"] >= 34.0
        assert res_a["sub_responses"][1]["faq_id"] == 45
        assert res_a["sub_responses"][1]["category"] == "Examinations"
        assert res_a["sub_responses"][1]["match_type"] == MATCH_CLEAR
        assert res_a["sub_responses"][1]["confidence"] >= 34.0
        print(
            f"  {case_label:<28} | Sub-FAQs: #{res_a['sub_responses'][0]['faq_id']} "
            f"({res_a['sub_responses'][0]['confidence']:.2f}%) + #{res_a['sub_responses'][1]['faq_id']} "
            f"({res_a['sub_responses'][1]['confidence']:.2f}%)"
        )

    # Case B1 & B2: Admission eligibility + scholarship application / schemes
    for case_label, query_b, exp_sch_id in [
        (
            "Case B1 (Apply Scholarship)",
            "What is the admission eligibility and how can I apply for scholarships?",
            61,
        ),
        (
            "Case B2 (Scholarship Types)",
            "What are the admission eligibility requirements and what scholarships can I apply for?",
            60,
        ),
    ]:
        res_b = chatbot.get_response(query_b)
        assert_candidate_invariants(res_b)
        assert res_b["is_multi_intent"] is True
        assert len(res_b["sub_responses"]) == 2
        assert res_b["sub_responses"][0]["faq_id"] == 1
        assert res_b["sub_responses"][0]["category"] == "Admissions"
        assert res_b["sub_responses"][0]["match_type"] == MATCH_CLEAR
        assert res_b["sub_responses"][1]["faq_id"] == exp_sch_id
        assert res_b["sub_responses"][1]["category"] == "Scholarships"
        assert res_b["sub_responses"][1]["match_type"] == MATCH_CLEAR
        print(
            f"  {case_label:<28} | Sub-FAQs: #{res_b['sub_responses'][0]['faq_id']} "
            f"({res_b['sub_responses'][0]['confidence']:.2f}%) + #{res_b['sub_responses'][1]['faq_id']} "
            f"({res_b['sub_responses'][1]['confidence']:.2f}%)"
        )

    # Case C1 & C2: Semester fee amount + payment method, and payment method + late fee
    for case_label, query_c, exp_id_1, exp_id_2 in [
        (
            "Case C1 (Amount + Method)",
            "What are the semester tuition fees and how can I pay them?",
            17,
            16,
        ),
        (
            "Case C2 (Method + Late Fee)",
            "How do I pay my semester fees and what happens if I pay late?",
            16,
            23,
        ),
    ]:
        res_c = chatbot.get_response(query_c)
        assert_candidate_invariants(res_c)
        assert res_c["is_multi_intent"] is True
        assert len(res_c["sub_responses"]) == 2
        assert res_c["sub_responses"][0]["faq_id"] == exp_id_1
        assert res_c["sub_responses"][1]["faq_id"] == exp_id_2
        assert res_c["sub_responses"][0]["match_type"] == MATCH_CLEAR
        assert res_c["sub_responses"][1]["match_type"] == MATCH_CLEAR
        print(
            f"  {case_label:<28} | Sub-FAQs: #{res_c['sub_responses'][0]['faq_id']} "
            f"({res_c['sub_responses'][0]['confidence']:.2f}%) + #{res_c['sub_responses'][1]['faq_id']} "
            f"({res_c['sub_responses'][1]['confidence']:.2f}%)"
        )

    # Case D: Placement eligibility + placement registration
    query_d = "What are the placement eligibility criteria and how do I register?"
    res_d = chatbot.get_response(query_d)
    assert_candidate_invariants(res_d)
    assert res_d["is_multi_intent"] is True
    assert len(res_d["sub_responses"]) == 2
    assert res_d["sub_responses"][0]["faq_id"] == 89
    assert res_d["sub_responses"][0]["category"] == "Placements"
    assert res_d["sub_responses"][1]["faq_id"] == 88
    assert res_d["sub_responses"][1]["category"] == "Placements"
    print(
        f"  {'Case D (Placement + Reg)':<28} | Sub-FAQs: #{res_d['sub_responses'][0]['faq_id']} "
        f"({res_d['sub_responses'][0]['confidence']:.2f}%) + #{res_d['sub_responses'][1]['faq_id']} "
        f"({res_d['sub_responses'][1]['confidence']:.2f}%)"
    )

    # Case E: One clear question + one ambiguous question
    query_e = "What is the examination timetable and tell me about scholarships?"
    res_e = chatbot.get_response(query_e)
    assert_candidate_invariants(res_e)
    assert res_e["is_multi_intent"] is True
    assert len(res_e["sub_responses"]) == 2
    assert res_e["sub_responses"][0]["match_type"] == MATCH_CLEAR
    assert res_e["sub_responses"][0]["faq_id"] == 45
    assert res_e["sub_responses"][1]["match_type"] == MATCH_AMBIGUOUS
    assert res_e["sub_responses"][1]["needs_clarification"] is True
    assert res_e["sub_responses"][1]["faq_id"] is None
    assert len(res_e["sub_responses"][1]["candidates"]) >= 2
    assert res_e["needs_clarification"] is True
    print(
        f"  {'Case E (Clear + Ambiguous)':<28} | Sub #1: FAQ #{res_e['sub_responses'][0]['faq_id']} "
        f"(clear_match) + Sub #2: {res_e['sub_responses'][1]['match_type']} "
        f"({len(res_e['sub_responses'][1]['candidates'])} candidates)"
    )

    # Case F: One clear question + one unsupported question
    query_f = "Tell me about hostel facilities and does the university campus have an Olympic swimming pool?"
    res_f = chatbot.get_response(query_f)
    assert_candidate_invariants(res_f)
    assert res_f["is_multi_intent"] is True
    assert len(res_f["sub_responses"]) == 2
    assert res_f["sub_responses"][0]["match_type"] == MATCH_CLEAR
    assert res_f["sub_responses"][0]["faq_id"] == 75
    assert res_f["sub_responses"][1]["match_type"] == MATCH_NONE
    assert res_f["sub_responses"][1]["fallback"] is True
    assert res_f["sub_responses"][1]["faq_id"] is None
    assert res_f["match_type"] == MATCH_CLEAR
    assert res_f["fallback"] is False
    print(
        f"  {'Case F (Clear + Unsupported)':<28} | Sub #1: FAQ #{res_f['sub_responses'][0]['faq_id']} "
        f"(clear_match) + Sub #2: {res_f['sub_responses'][1]['match_type']} (fallback=True)"
    )

    # Case G: Two questions from the same category (Examinations)
    query_g = "Where can I check the examination timetable and how can I download my hall ticket?"
    res_g = chatbot.get_response(query_g)
    assert_candidate_invariants(res_g)
    assert res_g["is_multi_intent"] is True
    assert len(res_g["sub_responses"]) == 2
    assert res_g["sub_responses"][0]["faq_id"] == 45
    assert res_g["sub_responses"][1]["faq_id"] == 46
    assert res_g["sub_responses"][0]["category"] == "Examinations"
    assert res_g["sub_responses"][1]["category"] == "Examinations"
    print(
        f"  {'Case G (Same Category x2)':<28} | Sub-FAQs: #{res_g['sub_responses'][0]['faq_id']} "
        f"+ #{res_g['sub_responses'][1]['faq_id']} (Examinations)"
    )

    # Case H: Duplicate or repeated questions in one message (deduplicated to 1 response)
    query_h = "How can I pay my semester fees and what are the accepted payment modes for semester tuition fees?"
    res_h = chatbot.get_response(query_h)
    assert_candidate_invariants(res_h)
    assert res_h["is_multi_intent"] is False
    assert res_h["sub_responses"] == []
    assert res_h["faq_id"] == 16
    assert res_h["match_type"] == MATCH_CLEAR
    print(
        f"  {'Case H (Duplicate Deduped)':<28} | Deduplicated to single FAQ #{res_h['faq_id']} "
        f"(is_multi_intent={res_h['is_multi_intent']})"
    )

    # Case I: Normal single-question queries with compound phrases (must NOT split)
    for single_q, exp_single_id in [
        ("Can I pay my semester fees through UPI, net banking, or card?", 16),
        ("What are the annual tuition and laboratory fees?", 17),
        (
            "Are hostel, mess, and transportation fees paid separately from tuition fees?",
            25,
        ),
    ]:
        res_i = chatbot.get_response(single_q)
        assert res_i["is_multi_intent"] is False, (
            f"Compound single question should not split: {single_q}"
        )
        assert res_i["sub_responses"] == []
        assert res_i["faq_id"] == exp_single_id
        assert res_i["match_type"] == MATCH_CLEAR
    print(
        f"  {'Case I (Compound Single x3)':<28} | All 3 compound single queries preserved unsplit"
    )

    # Case J: Contextual follow-up & similarity threshold consistency verification
    res_j = chatbot.get_response(
        "What are the eligibility criteria and how do I register?",
        context_category="Placements",
    )
    assert res_j["is_multi_intent"] is True
    assert res_j["sub_responses"][0]["faq_id"] == 89
    assert res_j["sub_responses"][1]["faq_id"] == 88

    # Threshold consistency check: borderline query (< 34% similarity) must never return
    # a confirmed faq_id or matched_question or clear_match classification
    res_borderline = chatbot.get_response("Campus facilities?")
    assert res_borderline["match_type"] == MATCH_AMBIGUOUS
    assert res_borderline["needs_clarification"] is True
    assert res_borderline["faq_id"] is None
    assert res_borderline["matched_question"] is None
    assert not res_borderline["answer"].startswith("[Sample Information]")
    print(
        f"  {'Case J (Context & Threshold)':<28} | Contextual multi-intent & <34% threshold guard verified"
    )
    print("=" * 82)
    print()
    passed += 1

    print("=" * 82)
    print(f"NLP TEST SUITE SUMMARY: {passed} / {total_tests} TEST GROUPS PASSED")
    print("=" * 82)


def test_nlp_suite() -> None:
    """Entrypoint for pytest/unittest runners."""
    run_tests()


if __name__ == "__main__":
    run_tests()
