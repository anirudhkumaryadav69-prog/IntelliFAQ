"""
Automated Test Suite for Personalized Admission Eligibility Assessment &
Reusable Clarification Architecture (Prompt 14).

Uses temporary SQLite databases only (never modifies the development DB)
and tests all 8 required scenarios plus verified-criteria evaluation:
 1. Initial eligibility request
 2. Sequential information collection
 3. Incomplete information ("I want admission in B.Tech.")
 4. Unsupported programme (does not invent requirements)
 5. Normal FAQ ("What are the admission requirements?")
 6. Topic switching ("Am I eligible for admission?" -> "What is the examination timetable?")
 7. Conversation isolation
 8. Conversation reset
 9. Verified-criteria comparison (when explicitly configured)
"""

from pathlib import Path
import tempfile

import app as backend_app
from database import Database
from nlp.chatbot import MATCH_CLEAR
from nlp.clarification_flows import (
    ADMISSION_ELIGIBILITY_FLOW,
    evaluate_admission_eligibility,
    process_clarification_turn,
)


def run_eligibility_tests() -> None:
    """Execute all admission eligibility & clarification flow tests."""
    passed = 0
    total = 9

    with tempfile.TemporaryDirectory() as tmp_dir:
        original_manager = backend_app.conversation_manager
        try:
            test_db = Path(tmp_dir) / "test_eligibility.db"
            backend_app.conversation_manager = backend_app.ConversationManager(
                database=Database(test_db)
            )
            backend_app.conversation_manager.initialize()
            client = backend_app.app.test_client()

            # -------------------------------------------------------------
            # Scenario 1: Initial eligibility request (all 12 variations)
            # -------------------------------------------------------------
            for prompt in (
                "Am I eligible for admission?",
                "Am I eligible for admissions or not?",
                "Tell me am I eligible for admissions or not.",
                "Tell me whether I am eligible for admission.",
                "Tell me whether I am eligible for admissions or not.",
                "Can you check my admission eligibility?",
                "Can I get admission?",
                "Do I qualify for admission?",
                "Am I qualified for B.Tech admission?",
                "Will I be eligible for B.Tech CSE?",
                "Check whether I qualify for B.Tech.",
                "Can I apply for admission with my percentage?",
                "Is my percentage sufficient for admission?",
                "Am I eligible for B.Tech?",
                "Am I eligible for B.Tech CSE admission?",
                "Can I get admission in B.Tech?",
                "Do I qualify for B.Tech admission?",
                "Will I qualify for admission with my marks?",
                "Can I get admission based on my percentage?",
                "Check my eligibility for B.Tech CSE.",
                "Tell me if I qualify for admission.",
                "Am I eligible to apply for an undergraduate programme?",
            ):
                r1 = client.post("/api/chat", json={"message": prompt})
                d1 = r1.get_json()
                assert r1.status_code == 200
                assert d1["success"] is True
                assert d1["fallback"] is False
                assert d1["match_type"] == MATCH_CLEAR
                assert d1["needs_clarification"] is False
                assert d1["is_multi_intent"] is False
                assert d1["sub_responses"] == []
                assert d1["candidates"] == []
                assert d1["category"] == "Admissions"
                assert "lateral entry" not in d1["answer"].lower()
                snap1 = backend_app.conversation_manager.get_conversation(
                    d1["conversation_id"]
                )
                assert snap1 is not None
                assert snap1["clarification_state"]["flow_name"] == "admission_eligibility"
                # If programme wasn't already specified, bot must ask for programme
                if not snap1["clarification_state"]["slots"].get("programme"):
                    assert "programme" in d1["answer"].lower()
                    assert snap1["clarification_state"]["expected_slot"] == "programme"
                else:
                    assert "qualification" in d1["answer"].lower()
                    assert snap1["clarification_state"]["expected_slot"] == "qualification"
            passed += 1

            # -------------------------------------------------------------
            # Scenario 2: Sequential information collection
            # -------------------------------------------------------------
            t1 = client.post("/api/chat", json={"message": "Am I eligible for admission?"}).get_json()
            cid2 = t1["conversation_id"]
            assert "programme" in t1["answer"].lower()

            t2 = client.post(
                "/api/chat", json={"message": "B.Tech CSE.", "conversation_id": cid2}
            ).get_json()
            assert t2["conversation_id"] == cid2
            assert "qualification" in t2["answer"].lower()

            t3 = client.post(
                "/api/chat", json={"message": "Class 12.", "conversation_id": cid2}
            ).get_json()
            assert "stream" in t3["answer"].lower()

            t4 = client.post(
                "/api/chat", json={"message": "Non-medical.", "conversation_id": cid2}
            ).get_json()
            assert "percentage" in t4["answer"].lower() or "cgpa" in t4["answer"].lower()

            t5 = client.post(
                "/api/chat", json={"message": "72%.", "conversation_id": cid2}
            ).get_json()
            assert t5["fallback"] is False
            assert "B.Tech CSE" in t5["answer"]
            assert "Class 12" in t5["answer"]
            assert "Non-medical" in t5["answer"]
            assert "72%" in t5["answer"]
            assert "admissions office" in t5["answer"].lower() or "admissions portal" in t5["answer"].lower()
            snap_done = backend_app.conversation_manager.get_conversation(cid2)
            assert snap_done is not None
            assert snap_done["clarification_state"] == {}
            passed += 1

            # -------------------------------------------------------------
            # Scenario 3: Incomplete information
            # -------------------------------------------------------------
            r3 = client.post(
                "/api/chat", json={"message": "I want admission in B.Tech."}
            )
            d3 = r3.get_json()
            assert r3.status_code == 200
            assert d3["fallback"] is False
            assert "B.Tech" in d3["answer"]
            assert "qualification" in d3["answer"].lower()
            passed += 1

            # -------------------------------------------------------------
            # Scenario 4: Unsupported programme (no invented criteria)
            # -------------------------------------------------------------
            u1 = client.post(
                "/api/chat",
                json={
                    "message": "I want admission in a programme whose eligibility criteria are not available."
                },
            ).get_json()
            ucid = u1["conversation_id"]
            assert u1["fallback"] is False
            assert "qualification" in u1["answer"].lower()

            client.post("/api/chat", json={"message": "Class 12", "conversation_id": ucid})
            client.post("/api/chat", json={"message": "Science", "conversation_id": ucid})
            u4 = client.post(
                "/api/chat", json={"message": "80%", "conversation_id": ucid}
            ).get_json()
            assert "not available" in u4["answer"].lower()
            assert "cannot make a reliable eligibility determination" in u4["answer"].lower()
            passed += 1

            # -------------------------------------------------------------
            # Scenario 5: Normal FAQs still work (Admissions, Scholarships, Exams)
            # -------------------------------------------------------------
            r5 = client.post(
                "/api/chat", json={"message": "What are the admission requirements?"}
            )
            d5 = r5.get_json()
            assert r5.status_code == 200
            assert d5["match_type"] == MATCH_CLEAR
            assert d5["category"] == "Admissions"
            assert d5["faq_id"] == 1

            r5_tfw = client.post(
                "/api/chat", json={"message": "What is the TFW scholarship scheme?"}
            )
            d5_tfw = r5_tfw.get_json()
            assert r5_tfw.status_code == 200
            assert d5_tfw["match_type"] == MATCH_CLEAR
            assert d5_tfw["category"] == "Scholarships"
            assert d5_tfw["faq_id"] is not None
            passed += 1

            # -------------------------------------------------------------
            # Scenario 6: Topic switching mid-flow
            # -------------------------------------------------------------
            s6_start = client.post(
                "/api/chat", json={"message": "Am I eligible for admission?"}
            ).get_json()
            s6_cid = s6_start["conversation_id"]
            s6_switch = client.post(
                "/api/chat",
                json={
                    "message": "What is the examination timetable?",
                    "conversation_id": s6_cid,
                },
            ).get_json()
            assert s6_switch["category"] == "Examinations"
            assert s6_switch["faq_id"] == 45
            snap_switched = backend_app.conversation_manager.get_conversation(s6_cid)
            assert snap_switched is not None
            assert snap_switched["clarification_state"] == {}
            passed += 1

            # -------------------------------------------------------------
            # Scenario 7: Conversation isolation
            # -------------------------------------------------------------
            iso_a = client.post(
                "/api/chat", json={"message": "I want admission in MBA."}
            ).get_json()
            iso_b = client.post(
                "/api/chat", json={"message": "Am I eligible for admission?"}
            ).get_json()
            snap_a = backend_app.conversation_manager.get_conversation(
                iso_a["conversation_id"]
            )
            snap_b = backend_app.conversation_manager.get_conversation(
                iso_b["conversation_id"]
            )
            assert snap_a["clarification_state"]["slots"].get("programme") == "MBA"
            assert snap_b["clarification_state"]["slots"].get("programme") is None
            passed += 1

            # -------------------------------------------------------------
            # Scenario 8: Conversation reset clears eligibility state
            # -------------------------------------------------------------
            res_reset = client.post(
                "/api/conversations/reset",
                json={"conversation_id": iso_a["conversation_id"]},
            )
            assert res_reset.status_code == 200
            assert (
                backend_app.conversation_manager.get_conversation(
                    iso_a["conversation_id"]
                )
                is None
            )
            assert (
                backend_app.conversation_manager.get_conversation(
                    iso_b["conversation_id"]
                )
                is not None
            )
            passed += 1

            # -------------------------------------------------------------
            # Scenario 9: Verified criteria evaluation (explicitly configured)
            # -------------------------------------------------------------
            sample_verified = {
                "B.Tech CSE": {
                    "qualifications": ["Class 12 (10+2)"],
                    "streams": ["Non-medical (PCM)"],
                    "min_percentage": 60,
                }
            }
            eligible_text = evaluate_admission_eligibility(
                {
                    "programme": "B.Tech CSE",
                    "qualification": "Class 12 (10+2)",
                    "stream": "Non-medical (PCM)",
                    "percentage": "72%",
                },
                backend_app.chatbot,
                verified_criteria=sample_verified,
            )
            assert "meet the listed requirements" in eligible_text.lower()
            ineligible_text = evaluate_admission_eligibility(
                {
                    "programme": "B.Tech CSE",
                    "qualification": "Class 12 (10+2)",
                    "stream": "Non-medical (PCM)",
                    "percentage": "45%",
                },
                backend_app.chatbot,
                verified_criteria=sample_verified,
            )
            assert "not met" in ineligible_text.lower()

            # Also verify reusable state machine turn progression directly
            msg, st = process_clarification_turn(
                ADMISSION_ELIGIBILITY_FLOW,
                "Am I eligible for B.Tech CSE?",
                None,
                backend_app.chatbot,
            )
            assert st["slots"]["programme"] == "B.Tech CSE"
            assert st["expected_slot"] == "qualification"
            passed += 1

        finally:
            backend_app.conversation_manager = original_manager

    print("=" * 82)
    print(f"ELIGIBILITY TEST SUITE SUMMARY: {passed} / {total} SCENARIOS PASSED")
    print("=" * 82)


def test_eligibility_suite() -> None:
    """Entrypoint for pytest/unittest runners."""
    run_eligibility_tests()


if __name__ == "__main__":
    run_eligibility_tests()
