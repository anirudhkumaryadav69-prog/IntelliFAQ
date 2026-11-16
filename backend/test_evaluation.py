"""
Comprehensive NLP Evaluation Dataset & Metrics Suite for IntelliFAQ 2.0.

Evaluates FAQChatbot across 84 diverse test queries:
- 70 category-specific FAQ queries (10 per category across all 7 categories:
  Admissions, Fee Payment, Attendance, Examinations, Scholarships,
  Campus Facilities, and Placements) spanning canonical, paraphrased,
  conversational, short, synonym-based, and slightly misspelled phrasings.
- 6 genuinely ambiguous queries that must trigger clarification
  (match_type == 'ambiguous_match', needs_clarification == True).
- 8 unsupported university and out-of-domain queries (including grammatically
  correct sentences sharing generic university words) that must safely fall back
  (match_type == 'no_reliable_match', fallback == True, faq_id is None).

Computes and reports:
- Total test queries
- Correct FAQ matches, incorrect FAQ matches
- Correct ambiguity detections, correct fallback responses
- Overall accuracy, macro/weighted precision, recall, and F1-score
- Per-category precision, recall, and F1-score
"""

from typing import Any, Dict, List, Optional, Tuple

from nlp import FAQChatbot
from nlp.chatbot import MATCH_AMBIGUOUS, MATCH_CLEAR, MATCH_NONE

# Each entry: (category_or_group, query_style, query_text, expected_match_type, expected_faq_id)
EVALUATION_DATASET: List[Tuple[str, str, str, str, Optional[int]]] = [
    # =========================================================================
    # 1. Admissions (10 queries)
    # =========================================================================
    (
        "Admissions",
        "synonym",
        "What are the eligibility criteria for joining a bachelor's degree program?",
        MATCH_CLEAR,
        1,
    ),
    (
        "Admissions",
        "conversational",
        "Hey there, could you tell me how I can submit my admission form on the website?",
        MATCH_CLEAR,
        2,
    ),
    (
        "Admissions",
        "short",
        "Admission documents?",
        MATCH_CLEAR,
        3,
    ),
    (
        "Admissions",
        "paraphrase",
        "When does the application window close for new admissions?",
        MATCH_CLEAR,
        4,
    ),
    (
        "Admissions",
        "paraphrase",
        "Do I have to appear for an entrance exam to get admission?",
        MATCH_CLEAR,
        5,
    ),
    (
        "Admissions",
        "misspelled",
        "How can I track my admsision application status online?",
        MATCH_CLEAR,
        6,
    ),
    (
        "Admissions",
        "synonym",
        "Can diploma students get direct second-year lateral entry admission?",
        MATCH_CLEAR,
        7,
    ),
    (
        "Admissions",
        "conversational",
        "I accidentally made a mistake on my submitted admission form, how do I fix it?",
        MATCH_CLEAR,
        8,
    ),
    (
        "Admissions",
        "synonym",
        "How do NRI or foreign students apply for university admission?",
        MATCH_CLEAR,
        9,
    ),
    (
        "Admissions",
        "paraphrase",
        "Can I switch my engineering branch after completing the first semester?",
        MATCH_CLEAR,
        15,
    ),
    # =========================================================================
    # 2. Fee Payment (10 queries)
    # =========================================================================
    (
        "Fee Payment",
        "paraphrase",
        "What are the semester tuition fees?",
        MATCH_CLEAR,
        17,
    ),
    (
        "Fee Payment",
        "conversational",
        "Could you let me know how much I have to pay per semester for tuition?",
        MATCH_CLEAR,
        17,
    ),
    (
        "Fee Payment",
        "misspelled",
        "Can I pay my tution fees using UPI or debit card?",
        MATCH_CLEAR,
        16,
    ),
    (
        "Fee Payment",
        "paraphrase",
        "What is the fee payment deadline?",
        MATCH_CLEAR,
        18,
    ),
    (
        "Fee Payment",
        "synonym",
        "Where do I download my tuition payment invoice and receipt?",
        MATCH_CLEAR,
        19,
    ),
    (
        "Fee Payment",
        "conversational",
        "Money got deducted from my bank account but the online fee payment failed, what should I do?",
        MATCH_CLEAR,
        20,
    ),
    (
        "Fee Payment",
        "paraphrase",
        "Can I pay my semester tuition fee in two installments?",
        MATCH_CLEAR,
        21,
    ),
    (
        "Fee Payment",
        "short",
        "Fee refund?",
        MATCH_CLEAR,
        22,
    ),
    (
        "Fee Payment",
        "paraphrase",
        "What happens if I pay my fees late?",
        MATCH_CLEAR,
        23,
    ),
    (
        "Fee Payment",
        "synonym",
        "How can I claim back my refundable caution money after graduation?",
        MATCH_CLEAR,
        26,
    ),
    # =========================================================================
    # 3. Attendance (10 queries)
    # =========================================================================
    (
        "Attendance",
        "paraphrase",
        "What is the minimum attendance percentage needed to sit for semester exams?",
        MATCH_CLEAR,
        31,
    ),
    (
        "Attendance",
        "misspelled",
        "Where can I check my subject-wise attendence percentage online?",
        MATCH_CLEAR,
        32,
    ),
    (
        "Attendance",
        "conversational",
        "Hi, how do I submit a medical certificate if I missed lectures because I was sick?",
        MATCH_CLEAR,
        33,
    ),
    (
        "Attendance",
        "synonym",
        "Will I get on-duty attendance credit for representing the college at a hackathon?",
        MATCH_CLEAR,
        34,
    ),
    (
        "Attendance",
        "paraphrase",
        "Will my hall ticket be blocked if my attendance falls below the minimum requirement?",
        MATCH_CLEAR,
        35,
    ),
    (
        "Attendance",
        "conversational",
        "My instructor marked me absent by mistake even though I attended class, how do I get it corrected?",
        MATCH_CLEAR,
        36,
    ),
    (
        "Attendance",
        "paraphrase",
        "Is practical lab attendance counted separately from theory lectures?",
        MATCH_CLEAR,
        37,
    ),
    (
        "Attendance",
        "synonym",
        "Can final-year students get an attendance exemption during an approved industry internship?",
        MATCH_CLEAR,
        40,
    ),
    (
        "Attendance",
        "paraphrase",
        "Do we need to swipe our ID card for biometric attendance every day?",
        MATCH_CLEAR,
        41,
    ),
    (
        "Attendance",
        "synonym",
        "Do extra makeup lectures help increase my semester attendance percentage?",
        MATCH_CLEAR,
        43,
    ),
    # =========================================================================
    # 4. Examinations (10 queries)
    # =========================================================================
    (
        "Examinations",
        "short",
        "Exam timetable?",
        MATCH_CLEAR,
        45,
    ),
    (
        "Examinations",
        "synonym",
        "Where can I download my semester exam admit card?",
        MATCH_CLEAR,
        46,
    ),
    (
        "Examinations",
        "paraphrase",
        "How are marks divided between internal quizzes, midterms, and end-semester exams?",
        MATCH_CLEAR,
        47,
    ),
    (
        "Examinations",
        "synonym",
        "How are SGPA and CGPA calculated under the grading system?",
        MATCH_CLEAR,
        48,
    ),
    (
        "Examinations",
        "misspelled",
        "How can I apply for paper revalution or answer script rechecking?",
        MATCH_CLEAR,
        49,
    ),
    (
        "Examinations",
        "synonym",
        "How do I register for arrear or backlog exams if I failed a paper?",
        MATCH_CLEAR,
        50,
    ),
    (
        "Examinations",
        "conversational",
        "What should I do if I missed my mid-term exam because of a medical emergency?",
        MATCH_CLEAR,
        51,
    ),
    (
        "Examinations",
        "misspelled",
        "When will the semester examintion results and grade cards be declared?",
        MATCH_CLEAR,
        52,
    ),
    (
        "Examinations",
        "paraphrase",
        "Are scientific calculators allowed inside the examination hall?",
        MATCH_CLEAR,
        53,
    ),
    (
        "Examinations",
        "synonym",
        "How can I get a duplicate mark sheet or official sealed transcripts?",
        MATCH_CLEAR,
        54,
    ),
    # =========================================================================
    # 5. Scholarships (10 queries)
    # =========================================================================
    (
        "Scholarships",
        "paraphrase",
        "What merit and need-based scholarships are available for students?",
        MATCH_CLEAR,
        60,
    ),
    (
        "Scholarships",
        "misspelled",
        "How do I apply for an institutional scholership on the portal?",
        MATCH_CLEAR,
        61,
    ),
    (
        "Scholarships",
        "short",
        "Scholarship documents?",
        MATCH_CLEAR,
        62,
    ),
    (
        "Scholarships",
        "synonym",
        "Who is the nodal officer to verify my NSP government scholarship form?",
        MATCH_CLEAR,
        63,
    ),
    (
        "Scholarships",
        "paraphrase",
        "Do I need to maintain a minimum CGPA to renew my scholarship next year?",
        MATCH_CLEAR,
        64,
    ),
    (
        "Scholarships",
        "conversational",
        "Can you tell me if I am allowed to hold two scholarships at the same time?",
        MATCH_CLEAR,
        65,
    ),
    (
        "Scholarships",
        "synonym",
        "Are there special scholarships for national sports players or defense wards?",
        MATCH_CLEAR,
        66,
    ),
    (
        "Scholarships",
        "paraphrase",
        "How can I track when my scholarship money will be credited to my bank account?",
        MATCH_CLEAR,
        67,
    ),
    (
        "Scholarships",
        "synonym",
        "Do master's and PhD scholars receive a monthly fellowship stipend?",
        MATCH_CLEAR,
        69,
    ),
    (
        "Scholarships",
        "paraphrase",
        "Is there emergency financial aid if my family faces sudden hardship?",
        MATCH_CLEAR,
        71,
    ),
    # =========================================================================
    # 6. Campus Facilities (10 queries)
    # =========================================================================
    (
        "Campus Facilities",
        "paraphrase",
        "What are the central library timings and how many books can I borrow?",
        MATCH_CLEAR,
        74,
    ),
    (
        "Campus Facilities",
        "misspelled",
        "How can I apply for on-campus hostle room allotment?",
        MATCH_CLEAR,
        75,
    ),
    (
        "Campus Facilities",
        "canonical",
        "How do I connect my laptop or phone to the campus Wi-Fi network?",
        MATCH_CLEAR,
        76,
    ),
    (
        "Campus Facilities",
        "synonym",
        "Is there a doctor, infirmary, or ambulance service on campus for medical emergencies?",
        MATCH_CLEAR,
        77,
    ),
    (
        "Campus Facilities",
        "synonym",
        "Where do I check college bus routes and apply for a daily transport pass?",
        MATCH_CLEAR,
        78,
    ),
    (
        "Campus Facilities",
        "paraphrase",
        "How can students register to use the campus gymnasium and sports grounds?",
        MATCH_CLEAR,
        79,
    ),
    (
        "Campus Facilities",
        "synonym",
        "What hostel mess dining and day-scholar canteen options are on campus?",
        MATCH_CLEAR,
        80,
    ),
    (
        "Campus Facilities",
        "paraphrase",
        "How can I join coding clubs, robotics teams, or cultural societies?",
        MATCH_CLEAR,
        81,
    ),
    (
        "Campus Facilities",
        "conversational",
        "How can I book a confidential session with the mental wellness counselor on campus?",
        MATCH_CLEAR,
        82,
    ),
    (
        "Campus Facilities",
        "paraphrase",
        "I lost my student ID card, how do I apply for a replacement card?",
        MATCH_CLEAR,
        83,
    ),
    # =========================================================================
    # 7. Placements (10 queries)
    # =========================================================================
    (
        "Placements",
        "paraphrase",
        "How do final-year students register on the Training and Placement portal?",
        MATCH_CLEAR,
        88,
    ),
    (
        "Placements",
        "short",
        "Placement eligibility?",
        MATCH_CLEAR,
        89,
    ),
    (
        "Placements",
        "paraphrase",
        "Does the placement cell help students find summer internships?",
        MATCH_CLEAR,
        90,
    ),
    (
        "Placements",
        "synonym",
        "How do I get an NOC signed to join an off-campus company internship?",
        MATCH_CLEAR,
        91,
    ),
    (
        "Placements",
        "misspelled",
        "Does the college organize mock interviews and resume workshops before placeemnts?",
        MATCH_CLEAR,
        92,
    ),
    (
        "Placements",
        "conversational",
        "Can I sit for another company placement drive if I already have one job offer?",
        MATCH_CLEAR,
        93,
    ),
    (
        "Placements",
        "synonym",
        "Where are upcoming company visits and Job Announcement Forms published?",
        MATCH_CLEAR,
        94,
    ),
    (
        "Placements",
        "paraphrase",
        "What are the typical selection rounds from aptitude test to HR interview in placements?",
        MATCH_CLEAR,
        95,
    ),
    (
        "Placements",
        "synonym",
        "What is the dress code for attending pre-placement talks and campus interviews?",
        MATCH_CLEAR,
        96,
    ),
    (
        "Placements",
        "paraphrase",
        "Where can I view the official placement brochure and past recruiters list?",
        MATCH_CLEAR,
        99,
    ),
    # =========================================================================
    # 8. Ambiguous Queries (6 queries -> expected MATCH_AMBIGUOUS)
    # =========================================================================
    (
        "Ambiguous",
        "short",
        "Eligibility?",
        MATCH_AMBIGUOUS,
        None,
    ),
    (
        "Ambiguous",
        "short",
        "Attendance shortage?",
        MATCH_AMBIGUOUS,
        None,
    ),
    (
        "Ambiguous",
        "short",
        "Campus facilities?",
        MATCH_AMBIGUOUS,
        None,
    ),
    (
        "Ambiguous",
        "short",
        "scholarship",
        MATCH_AMBIGUOUS,
        None,
    ),
    (
        "Ambiguous",
        "multi_concept",
        "What about tuition fees structure and payment modes?",
        MATCH_AMBIGUOUS,
        None,
    ),
    (
        "Ambiguous",
        "short",
        "application form?",
        MATCH_AMBIGUOUS,
        None,
    ),
    # =========================================================================
    # 9. Unsupported & Out-of-Domain Queries (8 queries -> expected MATCH_NONE)
    # =========================================================================
    (
        "Unsupported",
        "unsupported_university",
        "Does the university campus have an Olympic-sized swimming pool and scuba diving club?",
        MATCH_NONE,
        None,
    ),
    (
        "Unsupported",
        "unsupported_university",
        "Can I bring my pet dog inside the university lecture halls?",
        MATCH_NONE,
        None,
    ),
    (
        "Unsupported",
        "unsupported_university",
        "Where can I buy official university branded hoodies and souvenirs on campus?",
        MATCH_NONE,
        None,
    ),
    (
        "Unsupported",
        "unsupported_university",
        "Can undergraduate students book international airline tickets through the student ERP portal?",
        MATCH_NONE,
        None,
    ),
    (
        "Unsupported",
        "unsupported_university",
        "Does the college astronomy observatory offer midnight telescope sessions for students?",
        MATCH_NONE,
        None,
    ),
    (
        "Unsupported",
        "out_of_domain",
        "What is the best recipe for baking a chocolate fudge cake at home?",
        MATCH_NONE,
        None,
    ),
    (
        "Unsupported",
        "out_of_domain",
        "Who won the FIFA World Cup final and scored a hat-trick?",
        MATCH_NONE,
        None,
    ),
    (
        "Unsupported",
        "out_of_domain",
        "What will the weather forecast and temperature be in Tokyo tomorrow?",
        MATCH_NONE,
        None,
    ),
]


def evaluate_chatbot(chatbot: Optional[FAQChatbot] = None, verbose: bool = True) -> Dict[str, Any]:
    """
    Run the 84-query evaluation dataset against FAQChatbot and compute:
    - Total queries
    - Correct FAQ matches (clear_match with exact expected faq_id)
    - Incorrect FAQ matches
    - Correct ambiguity detections (ambiguous_match with needs_clarification=True)
    - Correct fallback responses (no_reliable_match with fallback=True and faq_id is None)
    - Overall Accuracy, Macro Precision, Macro Recall, Macro F1-Score
    - Per-category Precision, Recall, and F1-Score across the 7 FAQ categories
      plus Ambiguous and Unsupported outcome classes.
    """
    bot = chatbot or FAQChatbot()

    total_queries = len(EVALUATION_DATASET)
    correct_faq_matches = 0
    incorrect_faq_matches = 0
    correct_ambiguity_detections = 0
    incorrect_ambiguity_cases = 0
    correct_fallback_responses = 0
    incorrect_fallback_cases = 0

    failures: List[Dict[str, Any]] = []

    # Track per-category / per-class TP, FP, FN
    classes = [
        "Admissions",
        "Fee Payment",
        "Attendance",
        "Examinations",
        "Scholarships",
        "Campus Facilities",
        "Placements",
        "Ambiguous",
        "Unsupported",
    ]
    tp: Dict[str, int] = {c: 0 for c in classes}
    fp: Dict[str, int] = {c: 0 for c in classes}
    fn: Dict[str, int] = {c: 0 for c in classes}
    support: Dict[str, int] = {c: 0 for c in classes}

    for group, style, query, expected_mt, expected_faq_id in EVALUATION_DATASET:
        support[group] += 1
        res = bot.get_response(query)
        actual_mt = res.get("match_type")
        actual_faq_id = res.get("faq_id")
        actual_cat = res.get("category")

        if expected_mt == MATCH_CLEAR:
            is_correct = (
                actual_mt == MATCH_CLEAR
                and actual_faq_id == expected_faq_id
                and res.get("fallback") is False
            )
            if is_correct:
                correct_faq_matches += 1
                tp[group] += 1
            else:
                incorrect_faq_matches += 1
                fn[group] += 1
                if actual_mt == MATCH_AMBIGUOUS:
                    fp["Ambiguous"] += 1
                elif actual_mt == MATCH_NONE:
                    fp["Unsupported"] += 1
                elif actual_cat in fp:
                    fp[actual_cat] += 1
        elif expected_mt == MATCH_AMBIGUOUS:
            is_correct = (
                actual_mt == MATCH_AMBIGUOUS
                and res.get("needs_clarification") is True
                and res.get("fallback") is False
            )
            if is_correct:
                correct_ambiguity_detections += 1
                tp["Ambiguous"] += 1
            else:
                incorrect_ambiguity_cases += 1
                fn["Ambiguous"] += 1
                if actual_mt == MATCH_NONE:
                    fp["Unsupported"] += 1
                elif actual_cat in fp:
                    fp[actual_cat] += 1
        else:  # MATCH_NONE (Unsupported / Out-of-domain)
            is_correct = (
                actual_mt == MATCH_NONE
                and res.get("fallback") is True
                and actual_faq_id is None
            )
            if is_correct:
                correct_fallback_responses += 1
                tp["Unsupported"] += 1
            else:
                incorrect_fallback_cases += 1
                fn["Unsupported"] += 1
                if actual_mt == MATCH_AMBIGUOUS:
                    fp["Ambiguous"] += 1
                elif actual_cat in fp:
                    fp[actual_cat] += 1

        if not is_correct:
            failures.append(
                {
                    "group": group,
                    "style": style,
                    "query": query,
                    "expected_match_type": expected_mt,
                    "expected_faq_id": expected_faq_id,
                    "actual_match_type": actual_mt,
                    "actual_faq_id": actual_faq_id,
                    "confidence": res.get("confidence"),
                    "candidates": [
                        (c["faq_id"], c["category"], c["similarity"])
                        for c in res.get("candidates", [])
                    ],
                }
            )

    total_correct = (
        correct_faq_matches
        + correct_ambiguity_detections
        + correct_fallback_responses
    )
    overall_accuracy = (total_correct / total_queries) * 100.0 if total_queries else 0.0

    per_class_metrics: Dict[str, Dict[str, float]] = {}
    precisions: List[float] = []
    recalls: List[float] = []
    f1s: List[float] = []

    for c in classes:
        c_tp = tp[c]
        c_fp = fp[c]
        c_fn = fn[c]
        prec = (c_tp / (c_tp + c_fp)) * 100.0 if (c_tp + c_fp) > 0 else 0.0
        rec = (c_tp / (c_tp + c_fn)) * 100.0 if (c_tp + c_fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_class_metrics[c] = {
            "support": support[c],
            "tp": c_tp,
            "fp": c_fp,
            "fn": c_fn,
            "precision": round(prec, 2),
            "recall": round(rec, 2),
            "f1": round(f1, 2),
        }
        precisions.append(prec)
        recalls.append(rec)
        f1s.append(f1)

    macro_precision = sum(precisions) / len(precisions)
    macro_recall = sum(recalls) / len(recalls)
    macro_f1 = sum(f1s) / len(f1s)

    summary = {
        "total_queries": total_queries,
        "total_correct": total_correct,
        "correct_faq_matches": correct_faq_matches,
        "incorrect_faq_matches": incorrect_faq_matches,
        "correct_ambiguity_detections": correct_ambiguity_detections,
        "incorrect_ambiguity_cases": incorrect_ambiguity_cases,
        "correct_fallback_responses": correct_fallback_responses,
        "incorrect_fallback_cases": incorrect_fallback_cases,
        "accuracy": round(overall_accuracy, 2),
        "macro_precision": round(macro_precision, 2),
        "macro_recall": round(macro_recall, 2),
        "macro_f1": round(macro_f1, 2),
        "per_class_metrics": per_class_metrics,
        "failures": failures,
    }

    if verbose:
        print("=" * 86)
        print("INTELLIFAQ 2.0 — COMPREHENSIVE NLP EVALUATION REPORT (CONSTRUCTED TEST SUITE)")
        print("=" * 86)
        print(f"Total Evaluation Queries      : {total_queries}")
        print(f"Correct FAQ Matches (of 70)   : {correct_faq_matches}")
        print(f"Incorrect FAQ Matches         : {incorrect_faq_matches}")
        print(f"Correct Ambiguity Detections  : {correct_ambiguity_detections} / {support['Ambiguous']}")
        print(f"Correct Fallback Responses    : {correct_fallback_responses} / {support['Unsupported']}")
        print(f"Overall Accuracy              : {summary['accuracy']:.2f}% ({total_correct}/{total_queries})")
        print(f"Macro Precision               : {summary['macro_precision']:.2f}%")
        print(f"Macro Recall                  : {summary['macro_recall']:.2f}%")
        print(f"Macro F1-Score                : {summary['macro_f1']:.2f}%")
        print("-" * 86)
        print(f"{'Category / Class':<22} | {'Support':>7} | {'Precision':>10} | {'Recall':>10} | {'F1-Score':>10}")
        print("-" * 86)
        for c in classes:
            m = per_class_metrics[c]
            print(
                f"{c:<22} | {m['support']:>7} | {m['precision']:>9.2f}% | {m['recall']:>9.2f}% | {m['f1']:>9.2f}%"
            )
        print("=" * 86)
        if failures:
            print(f"\nFAILURES ({len(failures)}):")
            for f in failures:
                print(
                    f"  [{f['group']} / {f['style']}] {f['query']}\n"
                    f"    Expected: {f['expected_match_type']} (FAQ #{f['expected_faq_id']}) | "
                    f"Got: {f['actual_match_type']} (FAQ #{f['actual_faq_id']}, {f['confidence']}%) | "
                    f"Cands: {f['candidates']}"
                )
        print()

    return summary


if __name__ == "__main__":
    evaluate_chatbot(verbose=True)
