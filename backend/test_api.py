"""
Comprehensive Flask REST API Test Suite for IntelliFAQ 2.0 (backend/test_api.py).

Uses the Flask test client to verify all 14 required API and context-aware
conversation scenarios:
 1. New conversation creation
 2. Conversation ID returned in responses (alongside all NLP fields)
 3. Reusing an existing conversation ID
 4. Context-dependent follow-up questions (Admissions & Fee Payment)
 5. Clearly independent new question (Topic switch to Scholarships)
 6. Conversation isolation across concurrent sessions
 7. Conversation reset (POST /api/conversations/reset)
 8. Unknown conversation ID handling (/api/chat and /api/conversations/reset)
 9. Ambiguous follow-up handling (preserves prior resolved context)
10. No reliable contextual match handling (preserves prior resolved context)
11. Missing or malformed conversation ID validation
12. Existing health endpoint (GET /api/health)
13. Existing FAQ listing endpoint (GET /api/faqs)
14. Existing chat validation scenarios (empty message, missing message, invalid JSON, wrong type)

Also verifies bounded history/conversation limits and single FAQChatbot initialization.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict

import app as backend_app
from database import Database
from nlp.chatbot import MATCH_AMBIGUOUS, MATCH_CLEAR, MATCH_NONE

EXPECTED_CHAT_RESPONSE_KEYS = {
    "success",
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
    "is_multi_intent",
    "sub_responses",
    "conversation_id",
}


def print_scenario_result(
    title: str,
    status_code: int,
    response_data: Dict[str, Any],
    truncate_faqs: bool = False,
) -> None:
    """Format and print the HTTP status code and JSON payload for a test case."""
    print("=" * 82)
    print(f"SCENARIO    : {title}")
    print(f"STATUS CODE : {status_code}")
    print("-" * 82)

    display_data = dict(response_data)
    if (
        truncate_faqs
        and "faqs" in display_data
        and isinstance(display_data["faqs"], list)
    ):
        total_items = len(display_data["faqs"])
        display_data[f"faqs_preview (first 3 of {total_items})"] = (
            display_data.pop("faqs")[:3]
        )

    print(json.dumps(display_data, indent=2, ensure_ascii=False))
    print("=" * 82)
    print()


def assert_chat_response_schema(data: Dict[str, Any]) -> None:
    """Verify that a valid POST /api/chat response contains all required fields."""
    missing = EXPECTED_CHAT_RESPONSE_KEYS - set(data.keys())
    assert not missing, f"Missing required response fields: {missing}"
    assert isinstance(data["candidates"], list), "candidates must be a list"
    assert isinstance(data["conversation_id"], str) and len(data["conversation_id"]) > 0


def run_api_tests() -> None:
    """Execute all 17 API verification scenarios and assert expected outcomes."""
    temp_dir = tempfile.TemporaryDirectory()
    original_manager = backend_app.conversation_manager
    try:
        test_db_path = Path(temp_dir.name) / "test_api_conversations.db"
        backend_app.conversation_manager = backend_app.ConversationManager(
            database=Database(test_db_path)
        )
        backend_app.conversation_manager.initialize()
        _run_api_scenarios(temp_dir.name)
    finally:
        backend_app.conversation_manager = original_manager
        temp_dir.cleanup()


def _run_api_scenarios(temp_dir_path: str) -> None:
    client = backend_app.app.test_client()

    # Record initial object references to verify single initialization
    initial_chatbot_id = id(backend_app.chatbot)
    initial_vectorizer_id = (
        id(backend_app.chatbot.vectorizer) if backend_app.chatbot else None
    )

    passed_count = 0
    total_scenarios = 17

    # -------------------------------------------------------------------------
    # Scenario 1: New Conversation Creation (No conversation_id supplied)
    # -------------------------------------------------------------------------
    res1 = client.post(
        "/api/chat",
        json={
            "message": "What are the admission requirements for undergraduate programs?"
        },
    )
    data1 = res1.get_json()
    print_scenario_result(
        "1. New Conversation Creation (POST /api/chat without conversation_id)",
        res1.status_code,
        data1,
    )
    assert res1.status_code == 200
    assert data1["success"] is True
    assert data1["match_type"] == MATCH_CLEAR
    assert data1["category"] == "Admissions"
    assert data1["faq_id"] == 1
    conv_a_id = data1["conversation_id"]
    assert isinstance(conv_a_id, str) and len(conv_a_id) >= 16
    conv_a_state = backend_app.conversation_manager.get_conversation(conv_a_id)
    assert conv_a_state is not None
    assert conv_a_state["last_faq_id"] == 1
    assert conv_a_state["last_category"] == "Admissions"
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 2: Conversation ID Returned Alongside All Existing Response Fields
    # -------------------------------------------------------------------------
    print_scenario_result(
        "2. Conversation ID & Complete Response Contract Verification",
        res1.status_code,
        {
            "conversation_id": conv_a_id,
            "verified_fields": sorted(list(EXPECTED_CHAT_RESPONSE_KEYS)),
            "all_fields_present": EXPECTED_CHAT_RESPONSE_KEYS.issubset(
                set(data1.keys())
            ),
        },
    )
    assert_chat_response_schema(data1)
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 3: Reusing an Existing Conversation ID
    # -------------------------------------------------------------------------
    res3 = client.post(
        "/api/chat",
        json={
            "message": "How can I apply for admission online?",
            "conversation_id": conv_a_id,
        },
    )
    data3 = res3.get_json()
    print_scenario_result(
        "3. Reusing an Existing Conversation ID",
        res3.status_code,
        data3,
    )
    assert res3.status_code == 200
    assert_chat_response_schema(data3)
    assert data3["conversation_id"] == conv_a_id
    assert data3["match_type"] == MATCH_CLEAR
    assert data3["category"] == "Admissions"
    assert data3["faq_id"] == 2
    conv_a_state = backend_app.conversation_manager.get_conversation(conv_a_id)
    assert conv_a_state is not None
    assert len(conv_a_state["history"]) == 2
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 4: Context-Dependent Follow-Up Questions
    #   4a: In Admissions conversation -> "What documents do I need?"
    #   4b: In Fee Payment conversation -> "What about late payment?"
    # -------------------------------------------------------------------------
    res4a = client.post(
        "/api/chat",
        json={
            "message": "What documents do I need?",
            "conversation_id": conv_a_id,
        },
    )
    data4a = res4a.get_json()
    print_scenario_result(
        "4a. Context-Dependent Follow-Up (Admissions -> 'What documents do I need?')",
        res4a.status_code,
        data4a,
    )
    assert res4a.status_code == 200
    assert_chat_response_schema(data4a)
    assert data4a["conversation_id"] == conv_a_id
    assert data4a["match_type"] == MATCH_CLEAR
    assert data4a["category"] == "Admissions"
    assert data4a["faq_id"] == 3
    assert data4a["fallback"] is False
    # Verify original user message is preserved in conversation history (not enriched query)
    conv_a_state = backend_app.conversation_manager.get_conversation(conv_a_id)
    assert conv_a_state is not None
    assert conv_a_state["history"][-1]["user_message"] == "What documents do I need?"

    # 4b: Start Conversation B on Fee Payment ("Tell me about semester tuition fees.")
    res4b_init = client.post(
        "/api/chat",
        json={"message": "Tell me about semester tuition fees."},
    )
    data4b_init = res4b_init.get_json()
    conv_b_id = data4b_init["conversation_id"]
    assert res4b_init.status_code == 200
    assert conv_b_id != conv_a_id

    res4b_followup = client.post(
        "/api/chat",
        json={
            "message": "What about late payment?",
            "conversation_id": conv_b_id,
        },
    )
    data4b_followup = res4b_followup.get_json()
    print_scenario_result(
        "4b. Context-Dependent Follow-Up (Fee Payment -> 'What about late payment?')",
        res4b_followup.status_code,
        data4b_followup,
    )
    assert res4b_followup.status_code == 200
    assert_chat_response_schema(data4b_followup)
    assert data4b_followup["conversation_id"] == conv_b_id
    assert data4b_followup["match_type"] == MATCH_CLEAR
    assert data4b_followup["category"] == "Fee Payment"
    assert data4b_followup["faq_id"] == 23
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 5: Clearly Independent New Question (Topic Switch in Conversation A)
    #   Conversation A was in Admissions; user now asks about Scholarships.
    # -------------------------------------------------------------------------
    res5 = client.post(
        "/api/chat",
        json={
            "message": "What is the procedure for applying for scholarships?",
            "conversation_id": conv_a_id,
        },
    )
    data5 = res5.get_json()
    print_scenario_result(
        "5. Clearly Independent New Question (Admissions -> Scholarships Switch)",
        res5.status_code,
        data5,
    )
    assert res5.status_code == 200
    assert_chat_response_schema(data5)
    assert data5["conversation_id"] == conv_a_id
    assert data5["match_type"] == MATCH_CLEAR
    assert data5["category"] == "Scholarships"
    assert data5["fallback"] is False
    conv_a_state = backend_app.conversation_manager.get_conversation(conv_a_id)
    assert conv_a_state is not None
    assert conv_a_state["last_category"] == "Scholarships"
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 6: Conversation Isolation Across Concurrent Conversations
    #   - conv_adm (Admissions) vs conv_fee (Fee Payment) asking the exact
    #     same follow-up: "What about the deadlines?"
    #   - conv_sch (Scholarships) asking "What documents do I need?"
    # -------------------------------------------------------------------------
    res_adm_init = client.post(
        "/api/chat",
        json={
            "message": "What are the admission requirements for undergraduate programs?"
        },
    )
    conv_adm_id = res_adm_init.get_json()["conversation_id"]

    res_fee_init = client.post(
        "/api/chat",
        json={"message": "How can I pay my semester tuition fees?"},
    )
    conv_fee_id = res_fee_init.get_json()["conversation_id"]

    res_sch_init = client.post(
        "/api/chat",
        json={
            "message": "How do I apply for an institutional merit or need-based scholarship?"
        },
    )
    conv_sch_id = res_sch_init.get_json()["conversation_id"]

    # Ask identical follow-up "What about the deadlines?" in both conv_adm and conv_fee
    res_adm_deadline = client.post(
        "/api/chat",
        json={
            "message": "What about the deadlines?",
            "conversation_id": conv_adm_id,
        },
    )
    data_adm_deadline = res_adm_deadline.get_json()

    res_fee_deadline = client.post(
        "/api/chat",
        json={
            "message": "What about the deadlines?",
            "conversation_id": conv_fee_id,
        },
    )
    data_fee_deadline = res_fee_deadline.get_json()

    # Ask "What documents do I need?" in conv_sch (Scholarships)
    res_sch_docs = client.post(
        "/api/chat",
        json={
            "message": "What documents do I need?",
            "conversation_id": conv_sch_id,
        },
    )
    data_sch_docs = res_sch_docs.get_json()

    print_scenario_result(
        "6. Conversation Isolation (Same Follow-Up in Different Conversations)",
        200,
        {
            "admissions_conversation_deadline": {
                "conversation_id": conv_adm_id,
                "category": data_adm_deadline["category"],
                "faq_id": data_adm_deadline["faq_id"],
                "matched_question": data_adm_deadline["matched_question"],
                "match_type": data_adm_deadline["match_type"],
            },
            "fee_payment_conversation_deadline": {
                "conversation_id": conv_fee_id,
                "category": data_fee_deadline["category"],
                "faq_id": data_fee_deadline["faq_id"],
                "matched_question": data_fee_deadline["matched_question"],
                "match_type": data_fee_deadline["match_type"],
            },
            "scholarships_conversation_documents": {
                "conversation_id": conv_sch_id,
                "category": data_sch_docs["category"],
                "faq_id": data_sch_docs["faq_id"],
                "matched_question": data_sch_docs["matched_question"],
                "match_type": data_sch_docs["match_type"],
            },
        },
    )
    assert data_adm_deadline["match_type"] == MATCH_CLEAR
    assert data_adm_deadline["category"] == "Admissions"
    assert data_adm_deadline["faq_id"] == 4

    assert data_fee_deadline["match_type"] == MATCH_CLEAR
    assert data_fee_deadline["category"] == "Fee Payment"
    assert data_fee_deadline["faq_id"] in (18, 23)

    assert data_sch_docs["match_type"] == MATCH_CLEAR
    assert data_sch_docs["category"] == "Scholarships"
    assert data_sch_docs["faq_id"] == 62
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 7: Conversation Reset (POST /api/conversations/reset)
    # -------------------------------------------------------------------------
    res7 = client.post(
        "/api/conversations/reset",
        json={"conversation_id": conv_adm_id},
    )
    data7 = res7.get_json()
    print_scenario_result(
        "7. Conversation Reset (POST /api/conversations/reset)",
        res7.status_code,
        data7,
    )
    assert res7.status_code == 200
    assert data7["success"] is True
    assert data7["conversation_id"] == conv_adm_id
    # Verify conv_adm_id was removed while conv_fee_id and conv_sch_id remain intact
    assert (
        backend_app.conversation_manager.get_conversation(conv_adm_id) is None
    )
    assert (
        backend_app.conversation_manager.get_conversation(conv_fee_id)
        is not None
    )
    assert (
        backend_app.conversation_manager.get_conversation(conv_sch_id)
        is not None
    )
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 8: Unknown Conversation ID Handling
    # -------------------------------------------------------------------------
    res8_chat = client.post(
        "/api/chat",
        json={
            "message": "What about the deadlines?",
            "conversation_id": conv_adm_id,  # Already reset/deleted in Scenario 7
        },
    )
    data8_chat = res8_chat.get_json()
    print_scenario_result(
        "8a. Unknown/Reset Conversation ID in POST /api/chat",
        res8_chat.status_code,
        data8_chat,
    )
    assert res8_chat.status_code == 400
    assert data8_chat["success"] is False
    assert "Unknown or expired conversation_id" in data8_chat["error"]

    res8_reset = client.post(
        "/api/conversations/reset",
        json={"conversation_id": "unknown-conv-id-00000000"},
    )
    data8_reset = res8_reset.get_json()
    print_scenario_result(
        "8b. Unknown Conversation ID in POST /api/conversations/reset",
        res8_reset.status_code,
        data8_reset,
    )
    assert res8_reset.status_code == 404
    assert data8_reset["success"] is False
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 9: Ambiguous Follow-Up (Preserves Prior Resolved Context)
    # -------------------------------------------------------------------------
    # In conv_fee_id, last_category is "Fee Payment" and last_faq_id is 23 (from Scenario 6).
    prior_fee_faq_id = backend_app.conversation_manager.get_conversation(
        conv_fee_id
    )["last_faq_id"]
    res9 = client.post(
        "/api/chat",
        json={
            "message": "What about tuition fees structure and payment modes?",
            "conversation_id": conv_fee_id,
        },
    )
    data9 = res9.get_json()
    print_scenario_result(
        "9. Ambiguous Follow-Up (Preserves Clarification & Prior Context)",
        res9.status_code,
        data9,
    )
    assert res9.status_code == 200
    assert_chat_response_schema(data9)
    assert data9["match_type"] == MATCH_AMBIGUOUS
    assert data9["needs_clarification"] is True
    assert (
        isinstance(data9["clarification_message"], str)
        and len(data9["clarification_message"]) > 0
    )
    assert len(data9["candidates"]) >= 2
    # Verify resolved FAQ context was NOT overwritten by the ambiguous turn
    conv_fee_after_ambig = backend_app.conversation_manager.get_conversation(
        conv_fee_id
    )
    assert conv_fee_after_ambig["last_faq_id"] == prior_fee_faq_id
    assert conv_fee_after_ambig["last_category"] == "Fee Payment"
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 10: No Reliable Contextual Match (Preserves Prior Context)
    # -------------------------------------------------------------------------
    res10 = client.post(
        "/api/chat",
        json={
            "message": "Does the university campus have an Olympic-sized swimming pool and scuba diving club?",
            "conversation_id": conv_fee_id,
        },
    )
    data10 = res10.get_json()
    print_scenario_result(
        "10. No Reliable Contextual Match in Active Conversation",
        res10.status_code,
        data10,
    )
    assert res10.status_code == 200
    assert_chat_response_schema(data10)
    assert data10["match_type"] == MATCH_NONE
    assert data10["fallback"] is True
    assert data10["faq_id"] is None
    assert data10["needs_clarification"] is False
    # Verify useful conversation context in conv_fee_id was NOT overwritten
    conv_fee_after_none = backend_app.conversation_manager.get_conversation(
        conv_fee_id
    )
    assert conv_fee_after_none["last_faq_id"] == prior_fee_faq_id
    assert conv_fee_after_none["last_category"] == "Fee Payment"
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 11: Missing or Malformed Conversation ID Validation
    # -------------------------------------------------------------------------
    res11_empty_chat = client.post(
        "/api/chat",
        json={"message": "How do I pay fees?", "conversation_id": "   "},
    )
    data11_empty_chat = res11_empty_chat.get_json()

    res11_type_chat = client.post(
        "/api/chat",
        json={"message": "How do I pay fees?", "conversation_id": 12345},
    )
    data11_type_chat = res11_type_chat.get_json()

    res11_missing_reset = client.post("/api/conversations/reset", json={})
    data11_missing_reset = res11_missing_reset.get_json()

    res11_empty_reset = client.post(
        "/api/conversations/reset", json={"conversation_id": ""}
    )
    data11_empty_reset = res11_empty_reset.get_json()

    res11_type_reset = client.post(
        "/api/conversations/reset", json={"conversation_id": ["not-a-string"]}
    )
    data11_type_reset = res11_type_reset.get_json()

    print_scenario_result(
        "11. Missing or Malformed conversation_id Validation",
        400,
        {
            "chat_whitespace_id": {
                "status": res11_empty_chat.status_code,
                "error": data11_empty_chat["error"],
            },
            "chat_numeric_id": {
                "status": res11_type_chat.status_code,
                "error": data11_type_chat["error"],
            },
            "reset_missing_id": {
                "status": res11_missing_reset.status_code,
                "error": data11_missing_reset["error"],
            },
            "reset_empty_id": {
                "status": res11_empty_reset.status_code,
                "error": data11_empty_reset["error"],
            },
            "reset_list_id": {
                "status": res11_type_reset.status_code,
                "error": data11_type_reset["error"],
            },
        },
    )
    assert res11_empty_chat.status_code == 400
    assert data11_empty_chat["success"] is False
    assert res11_type_chat.status_code == 400
    assert data11_type_chat["success"] is False
    assert res11_missing_reset.status_code == 400
    assert data11_missing_reset["success"] is False
    assert res11_empty_reset.status_code == 400
    assert data11_empty_reset["success"] is False
    assert res11_type_reset.status_code == 400
    assert data11_type_reset["success"] is False
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 12: Existing Health Endpoint (GET /api/health)
    # -------------------------------------------------------------------------
    res12 = client.get("/api/health")
    data12 = res12.get_json()
    print_scenario_result("12. GET /api/health", res12.status_code, data12)
    assert res12.status_code == 200
    assert data12["success"] is True
    assert data12["chatbot_status"] == "ready"
    assert data12["faq_count"] == 100
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 13: Existing FAQ Listing Endpoint (GET /api/faqs)
    # -------------------------------------------------------------------------
    res13 = client.get("/api/faqs")
    data13 = res13.get_json()
    print_scenario_result(
        "13. GET /api/faqs — FAQ Listing & Categories",
        res13.status_code,
        data13,
        truncate_faqs=True,
    )
    assert res13.status_code == 200
    assert data13["success"] is True
    assert data13["total_count"] == 100
    assert len(data13["categories"]) == 7
    assert len(data13["faqs"]) == 100
    assert set(data13["faqs"][0].keys()) == {"id", "question", "category"}
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 14: Existing Chat Validation Scenarios & Bounded Memory Limits
    # -------------------------------------------------------------------------
    res14_empty = client.post("/api/chat", json={"message": "    "})
    data14_empty = res14_empty.get_json()

    res14_missing = client.post("/api/chat", json={"query": "hello"})
    data14_missing = res14_missing.get_json()

    res14_malformed = client.post(
        "/api/chat",
        data="{invalid_json_syntax:",
        content_type="application/json",
    )
    data14_malformed = res14_malformed.get_json()

    res14_wrong_type = client.post("/api/chat", json={"message": 98765})
    data14_wrong_type = res14_wrong_type.get_json()

    # Also test bounded ConversationManager eviction and exchange history truncation
    bounded_db_path = Path(temp_dir_path) / "test_bounded_conversations.db"
    bounded_mgr = backend_app.ConversationManager(
        database=Database(bounded_db_path),
        max_conversations=3,
        max_exchanges=2,
    )
    bounded_mgr.initialize()
    c1 = bounded_mgr.create_conversation()["conversation_id"]
    c2 = bounded_mgr.create_conversation()["conversation_id"]
    c3 = bounded_mgr.create_conversation()["conversation_id"]
    # Record 3 exchanges in c1 (max_exchanges=2 -> should retain latest 2)
    for i in range(3):
        bounded_mgr.record_exchange(
            c1,
            f"Question {i}",
            {"match_type": MATCH_CLEAR, "faq_id": 1, "category": "Admissions"},
        )
    assert len(bounded_mgr.get_conversation(c1)["history"]) == 2
    assert (
        bounded_mgr.get_conversation(c1)["history"][0]["user_message"]
        == "Question 1"
    )
    # Creating c4 should evict oldest LRU conversation (c2, since c1 was just accessed)
    c4 = bounded_mgr.create_conversation()["conversation_id"]
    assert bounded_mgr.get_conversation(c2) is None
    assert bounded_mgr.get_conversation(c1) is not None
    assert bounded_mgr.get_conversation(c4) is not None

    print_scenario_result(
        "14. Existing Chat Validation Scenarios & Bounded Storage Verification",
        400,
        {
            "empty_message_status": res14_empty.status_code,
            "missing_message_status": res14_missing.status_code,
            "malformed_json_status": res14_malformed.status_code,
            "wrong_type_status": res14_wrong_type.status_code,
            "bounded_history_verified": True,
            "lru_conversation_eviction_verified": True,
        },
    )
    assert res14_empty.status_code == 400 and data14_empty["success"] is False
    assert (
        res14_missing.status_code == 400 and data14_missing["success"] is False
    )
    assert (
        res14_malformed.status_code == 400
        and data14_malformed["success"] is False
    )
    assert (
        res14_wrong_type.status_code == 400
        and data14_wrong_type["success"] is False
    )
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 15: Fee Subtopic Intent Distinction & Multi-Turn Fee Regression
    # -------------------------------------------------------------------------
    fee_api_cases = [
        # Fee amount / structure (FAQ #17)
        ("What are the semester tuition fees?", 17),
        ("How much do I have to pay per semester?", 17),
        ("Tell me about the university fee structure.", 17),
        ("What is the total tuition fee?", 17),
        # Payment method (FAQ #16)
        ("How can I pay my semester fees?", 16),
        ("Can I pay using UPI?", 16),
        ("Where can I pay my tuition fees?", 16),
        # Payment deadline (FAQ #18)
        ("When is the last date to pay semester fees?", 18),
        ("What is the fee payment deadline?", 18),
        # Late payment (FAQ #23)
        ("What happens if I pay my fees late?", 23),
        ("Is there a late payment penalty?", 23),
        # Refund (FAQ #22)
        ("Can I get a refund if I cancel my admission?", 22),
    ]
    for query_text, expected_faq_id in fee_api_cases:
        res_fee_case = client.post("/api/chat", json={"message": query_text})
        data_fee_case = res_fee_case.get_json()
        assert res_fee_case.status_code == 200
        assert_chat_response_schema(data_fee_case)
        assert data_fee_case["match_type"] == MATCH_CLEAR, (
            f"Expected clear_match for '{query_text}', got {data_fee_case['match_type']}"
        )
        assert data_fee_case["category"] == "Fee Payment"
        assert data_fee_case["faq_id"] == expected_faq_id, (
            f"Expected FAQ #{expected_faq_id} for '{query_text}', got FAQ #{data_fee_case['faq_id']}"
        )

    # Multi-turn 15a: Fee amount question (FAQ #17) -> Payment method question (FAQ #16)
    res_mt1_turn1 = client.post(
        "/api/chat",
        json={"message": "What are the semester tuition fees?"},
    )
    data_mt1_turn1 = res_mt1_turn1.get_json()
    mt1_conv_id = data_mt1_turn1["conversation_id"]
    assert data_mt1_turn1["faq_id"] == 17
    assert data_mt1_turn1["match_type"] == MATCH_CLEAR

    res_mt1_turn2 = client.post(
        "/api/chat",
        json={
            "message": "How can I pay my semester fees?",
            "conversation_id": mt1_conv_id,
        },
    )
    data_mt1_turn2 = res_mt1_turn2.get_json()
    assert data_mt1_turn2["conversation_id"] == mt1_conv_id
    assert data_mt1_turn2["faq_id"] == 16
    assert data_mt1_turn2["match_type"] == MATCH_CLEAR

    # Multi-turn 15b: Payment method question (FAQ #16) -> Fee amount question (FAQ #17)
    res_mt2_turn1 = client.post(
        "/api/chat",
        json={"message": "Where can I pay my tuition fees?"},
    )
    data_mt2_turn1 = res_mt2_turn1.get_json()
    mt2_conv_id = data_mt2_turn1["conversation_id"]
    assert data_mt2_turn1["faq_id"] == 16
    assert data_mt2_turn1["match_type"] == MATCH_CLEAR

    res_mt2_turn2 = client.post(
        "/api/chat",
        json={
            "message": "What is the total tuition fee?",
            "conversation_id": mt2_conv_id,
        },
    )
    data_mt2_turn2 = res_mt2_turn2.get_json()
    assert data_mt2_turn2["conversation_id"] == mt2_conv_id
    assert data_mt2_turn2["faq_id"] == 17
    assert data_mt2_turn2["match_type"] == MATCH_CLEAR

    # Multi-turn 15c: Switch from fee-related questions to an unrelated university topic (Attendance)
    res_mt2_turn3 = client.post(
        "/api/chat",
        json={
            "message": "What is the minimum attendance policy required to appear for semester examinations?",
            "conversation_id": mt2_conv_id,
        },
    )
    data_mt2_turn3 = res_mt2_turn3.get_json()
    assert data_mt2_turn3["conversation_id"] == mt2_conv_id
    assert data_mt2_turn3["category"] == "Attendance"
    assert data_mt2_turn3["faq_id"] == 31
    assert data_mt2_turn3["match_type"] == MATCH_CLEAR

    print_scenario_result(
        "15. Fee Subtopic Intent Distinction & Multi-Turn Fee Regression Suite",
        200,
        {
            "single_turn_fee_queries_verified": len(fee_api_cases),
            "amount_to_payment_method_transition": {
                "turn1_faq_id": data_mt1_turn1["faq_id"],
                "turn2_faq_id": data_mt1_turn2["faq_id"],
            },
            "payment_method_to_amount_transition": {
                "turn1_faq_id": data_mt2_turn1["faq_id"],
                "turn2_faq_id": data_mt2_turn2["faq_id"],
            },
            "fee_to_attendance_topic_switch": {
                "category": data_mt2_turn3["category"],
                "faq_id": data_mt2_turn3["faq_id"],
            },
        },
    )
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 16: Short-Query Context Handling, Examination Follow-Ups,
    #              Campus Facilities & Placement Regression Verification
    # -------------------------------------------------------------------------
    # 16a: Standalone short queries ("Eligibility?", "Attendance shortage?", "Campus facilities?")
    #      must ask for clarification when context is insufficient
    for ambig_short in ("Eligibility?", "Attendance shortage?", "Campus facilities?"):
        res_short_ambig = client.post("/api/chat", json={"message": ambig_short})
        data_short_ambig = res_short_ambig.get_json()
        assert res_short_ambig.status_code == 200
        assert data_short_ambig["match_type"] == MATCH_AMBIGUOUS, (
            f"Expected ambiguous_match for standalone '{ambig_short}', got {data_short_ambig['match_type']}"
        )
        assert data_short_ambig["needs_clarification"] is True

    # 16b: Standalone specific short queries ("Scholarship documents?", "Placement eligibility?",
    #      "Exam timetable?", "Hostel facilities?", "Fee refund?") resolve clearly
    for short_q, exp_cat, exp_id in [
        ("Scholarship documents?", "Scholarships", 62),
        ("Placement eligibility?", "Placements", 89),
        ("Exam timetable?", "Examinations", 45),
        ("Hostel facilities?", "Campus Facilities", 75),
        ("Fee refund?", "Fee Payment", 22),
    ]:
        res_short_clear = client.post("/api/chat", json={"message": short_q})
        data_short_clear = res_short_clear.get_json()
        assert res_short_clear.status_code == 200
        assert data_short_clear["match_type"] == MATCH_CLEAR
        assert data_short_clear["category"] == exp_cat
        assert data_short_clear["faq_id"] == exp_id

    # 16c: Context-aware short follow-up ("Eligibility?" in Placements conversation -> FAQ #89)
    #      and verify unrelated short question ("Exam timetable?") is NOT forced into Placements
    res_pl_start = client.post(
        "/api/chat",
        json={
            "message": "How do I register with the Training and Placement Cell for campus recruitment?"
        },
    )
    data_pl_start = res_pl_start.get_json()
    pl_conv_id = data_pl_start["conversation_id"]
    assert data_pl_start["faq_id"] == 88

    res_pl_elig = client.post(
        "/api/chat",
        json={"message": "Eligibility?", "conversation_id": pl_conv_id},
    )
    data_pl_elig = res_pl_elig.get_json()
    assert data_pl_elig["match_type"] == MATCH_CLEAR
    assert data_pl_elig["category"] == "Placements"
    assert data_pl_elig["faq_id"] == 89

    # Unrelated short question ("Exam timetable?") switches to Examinations (#45), not forced into Placements
    res_pl_exam = client.post(
        "/api/chat",
        json={"message": "Exam timetable?", "conversation_id": pl_conv_id},
    )
    data_pl_exam = res_pl_exam.get_json()
    assert data_pl_exam["match_type"] == MATCH_CLEAR
    assert data_pl_exam["category"] == "Examinations"
    assert data_pl_exam["faq_id"] == 45

    # 16d: Examination follow-up inside active Examinations conversation ("What about admit card?" -> FAQ #46)
    res_exam_followup = client.post(
        "/api/chat",
        json={"message": "What about admit card?", "conversation_id": pl_conv_id},
    )
    data_exam_followup = res_exam_followup.get_json()
    assert data_exam_followup["match_type"] == MATCH_CLEAR
    assert data_exam_followup["category"] == "Examinations"
    assert data_exam_followup["faq_id"] == 46

    # 16e: Campus Facilities query ("How can I apply for on-campus hostel accommodation?" -> FAQ #75)
    res_cf = client.post(
        "/api/chat",
        json={"message": "How can I apply for on-campus hostle room allotment?"},
    )
    data_cf = res_cf.get_json()
    assert data_cf["match_type"] == MATCH_CLEAR
    assert data_cf["category"] == "Campus Facilities"
    assert data_cf["faq_id"] == 75

    print_scenario_result(
        "16. Short-Query Context Handling, Examination Follow-Ups & Cross-Category Regression",
        200,
        {
            "standalone_ambiguous_short_queries_verified": 3,
            "standalone_clear_short_queries_verified": 5,
            "contextual_eligibility_in_placements_faq_id": data_pl_elig["faq_id"],
            "unforced_short_topic_switch_to_examinations_faq_id": data_pl_exam["faq_id"],
            "examination_admit_card_followup_faq_id": data_exam_followup["faq_id"],
            "campus_facilities_hostel_typo_faq_id": data_cf["faq_id"],
        },
    )
    passed_count += 1

    # -------------------------------------------------------------------------
    # Scenario 17: Multi-Intent Question Detection, Response Handling &
    #              Threshold Consistency Suite (Cases A–J via POST /api/chat)
    # -------------------------------------------------------------------------
    # Case A: Hostel facilities + examination timetable (sentence & conjunction forms)
    for query_a in (
        "Tell me about hostel facilities. What is the examination timetable?",
        "Tell me about hostel facilities and examination timetables.",
    ):
        res_mi_a = client.post("/api/chat", json={"message": query_a})
        data_mi_a = res_mi_a.get_json()
        assert res_mi_a.status_code == 200
        assert_chat_response_schema(data_mi_a)
        assert data_mi_a["is_multi_intent"] is True
        assert len(data_mi_a["sub_responses"]) == 2
        assert data_mi_a["sub_responses"][0]["faq_id"] == 75
        assert data_mi_a["sub_responses"][1]["faq_id"] == 45

    # Case B: Admission eligibility + scholarship application / schemes
    res_mi_b = client.post(
        "/api/chat",
        json={
            "message": "What are the admission eligibility requirements and what scholarships can I apply for?"
        },
    )
    data_mi_b = res_mi_b.get_json()
    assert res_mi_b.status_code == 200
    assert_chat_response_schema(data_mi_b)
    assert data_mi_b["is_multi_intent"] is True
    assert len(data_mi_b["sub_responses"]) == 2
    assert data_mi_b["sub_responses"][0]["faq_id"] == 1
    assert data_mi_b["sub_responses"][1]["faq_id"] == 60

    # Case C: Semester fee amount + payment method, and payment method + late fee
    res_mi_c1 = client.post(
        "/api/chat",
        json={"message": "What are the semester tuition fees and how can I pay them?"},
    )
    data_mi_c1 = res_mi_c1.get_json()
    assert data_mi_c1["is_multi_intent"] is True
    assert data_mi_c1["sub_responses"][0]["faq_id"] == 17
    assert data_mi_c1["sub_responses"][1]["faq_id"] == 16

    res_mi_c2 = client.post(
        "/api/chat",
        json={"message": "How do I pay my semester fees and what happens if I pay late?"},
    )
    data_mi_c2 = res_mi_c2.get_json()
    assert data_mi_c2["is_multi_intent"] is True
    assert data_mi_c2["sub_responses"][0]["faq_id"] == 16
    assert data_mi_c2["sub_responses"][1]["faq_id"] == 23

    # Case D: Placement eligibility + placement registration (followed by Case J contextual follow-up)
    res_mi_d = client.post(
        "/api/chat",
        json={
            "message": "What are the placement eligibility criteria and how do I register?"
        },
    )
    data_mi_d = res_mi_d.get_json()
    assert data_mi_d["is_multi_intent"] is True
    assert data_mi_d["sub_responses"][0]["faq_id"] == 89
    assert data_mi_d["sub_responses"][1]["faq_id"] == 88
    mi_d_conv_id = data_mi_d["conversation_id"]

    # Case J: Short contextual follow-up after multi-intent Placements turn ("What is the dress code?")
    res_mi_j = client.post(
        "/api/chat",
        json={
            "message": "What is the dress code?",
            "conversation_id": mi_d_conv_id,
        },
    )
    data_mi_j = res_mi_j.get_json()
    assert data_mi_j["is_multi_intent"] is False
    assert data_mi_j["match_type"] == MATCH_CLEAR
    assert data_mi_j["category"] == "Placements"
    assert data_mi_j["faq_id"] == 96

    # Case E: One clear question + one ambiguous question
    res_mi_e = client.post(
        "/api/chat",
        json={
            "message": "What is the examination timetable and tell me about scholarships?"
        },
    )
    data_mi_e = res_mi_e.get_json()
    assert data_mi_e["is_multi_intent"] is True
    assert data_mi_e["sub_responses"][0]["match_type"] == MATCH_CLEAR
    assert data_mi_e["sub_responses"][0]["faq_id"] == 45
    assert data_mi_e["sub_responses"][1]["match_type"] == MATCH_AMBIGUOUS
    assert data_mi_e["sub_responses"][1]["needs_clarification"] is True
    assert data_mi_e["needs_clarification"] is True

    # Case F: One clear question + one unsupported question
    res_mi_f = client.post(
        "/api/chat",
        json={
            "message": "Tell me about hostel facilities and does the university campus have an Olympic swimming pool?"
        },
    )
    data_mi_f = res_mi_f.get_json()
    assert data_mi_f["is_multi_intent"] is True
    assert data_mi_f["sub_responses"][0]["match_type"] == MATCH_CLEAR
    assert data_mi_f["sub_responses"][0]["faq_id"] == 75
    assert data_mi_f["sub_responses"][1]["match_type"] == MATCH_NONE
    assert data_mi_f["sub_responses"][1]["fallback"] is True
    assert data_mi_f["fallback"] is False

    # Case G: Two questions from the same category (Examinations)
    res_mi_g = client.post(
        "/api/chat",
        json={
            "message": "Where can I check the examination timetable and how can I download my hall ticket?"
        },
    )
    data_mi_g = res_mi_g.get_json()
    assert data_mi_g["is_multi_intent"] is True
    assert data_mi_g["sub_responses"][0]["faq_id"] == 45
    assert data_mi_g["sub_responses"][1]["faq_id"] == 46

    # Case H: Duplicate or repeated questions in one message -> deduplicated to 1 response
    res_mi_h = client.post(
        "/api/chat",
        json={
            "message": "How can I pay my semester fees and what are the accepted payment modes for semester tuition fees?"
        },
    )
    data_mi_h = res_mi_h.get_json()
    assert data_mi_h["is_multi_intent"] is False
    assert data_mi_h["sub_responses"] == []
    assert data_mi_h["faq_id"] == 16

    # Case I: Single-question compound phrase -> stays single-intent
    res_mi_i = client.post(
        "/api/chat",
        json={"message": "What are the annual tuition and laboratory fees?"},
    )
    data_mi_i = res_mi_i.get_json()
    assert data_mi_i["is_multi_intent"] is False
    assert data_mi_i["faq_id"] == 17

    print_scenario_result(
        "17. Multi-Intent Question Detection, Response Handling & Threshold Suite (Cases A–J)",
        200,
        {
            "case_a_hostel_and_exam_faq_ids": [
                s["faq_id"] for s in data_mi_a["sub_responses"]
            ],
            "case_b_admission_and_scholarship_faq_ids": [
                s["faq_id"] for s in data_mi_b["sub_responses"]
            ],
            "case_c1_fee_amount_and_method_faq_ids": [
                s["faq_id"] for s in data_mi_c1["sub_responses"]
            ],
            "case_c2_fee_method_and_late_faq_ids": [
                s["faq_id"] for s in data_mi_c2["sub_responses"]
            ],
            "case_d_placement_eligibility_and_reg_faq_ids": [
                s["faq_id"] for s in data_mi_d["sub_responses"]
            ],
            "case_e_clear_plus_ambiguous_match_types": [
                s["match_type"] for s in data_mi_e["sub_responses"]
            ],
            "case_f_clear_plus_unsupported_match_types": [
                s["match_type"] for s in data_mi_f["sub_responses"]
            ],
            "case_g_same_category_exam_faq_ids": [
                s["faq_id"] for s in data_mi_g["sub_responses"]
            ],
            "case_h_duplicate_deduplicated_faq_id": data_mi_h["faq_id"],
            "case_i_compound_single_faq_id": data_mi_i["faq_id"],
            "case_j_contextual_followup_faq_id": data_mi_j["faq_id"],
        },
    )
    passed_count += 1

    # -------------------------------------------------------------------------
    # Verify Single Initialization Across All Requests
    # -------------------------------------------------------------------------
    final_chatbot_id = id(backend_app.chatbot)
    final_vectorizer_id = (
        id(backend_app.chatbot.vectorizer) if backend_app.chatbot else None
    )
    same_instance = (
        initial_chatbot_id == final_chatbot_id
        and initial_vectorizer_id == final_vectorizer_id
        and initial_vectorizer_id is not None
    )

    print("=" * 82)
    print("FINAL VERIFICATION SUMMARY")
    print("-" * 82)
    print(f"Scenarios Passed             : {passed_count} / {total_scenarios}")
    print(f"Single Chatbot Instance Used : {same_instance}")
    print(f"Health Reported FAQ Count    : {data12['faq_count']}")
    print("=" * 82)

    if not same_instance or passed_count != total_scenarios:
        sys.exit(1)


def test_api_suite() -> None:
    """Entrypoint for pytest/unittest runners."""
    run_api_tests()


if __name__ == "__main__":
    run_api_tests()
