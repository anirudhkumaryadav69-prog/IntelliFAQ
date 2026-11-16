"""
Automated Test Suite for Prompt 15: Conversation History Dashboard & Session Management.

Uses temporary SQLite databases only (never modifies the development DB)
to verify all 15 required scenarios:
 1. Listing conversations
 2. Retrieving a complete conversation
 3. Searching by title
 4. Searching by message content
 5. Case-insensitive and partial search
 6. Renaming a conversation (and preserving custom title on subsequent turns)
 7. Rejecting empty or invalid titles
 8. Deleting a conversation
 9. Ensuring deletion does not affect other conversations
10. Restoring conversation context after reopening
11. Restoring unfinished admission eligibility workflows
12. Creating a new conversation without overwriting an old one
13. Preserving history after backend restart
14. Handling nonexistent & malformed conversation IDs
15. Handling empty conversation history
"""

import importlib
import os
from pathlib import Path
import tempfile
import uuid

import app as backend_app
from database import Database


def run_session_management_tests() -> None:
    """Execute all 15 Prompt 15 session-management & dashboard API scenarios."""
    passed = 0
    total = 15

    with tempfile.TemporaryDirectory() as tmp_dir:
        original_manager = backend_app.conversation_manager
        try:
            test_db = Path(tmp_dir) / "test_sessions.db"
            backend_app.conversation_manager = backend_app.ConversationManager(
                database=Database(test_db)
            )
            backend_app.conversation_manager.initialize()
            client = backend_app.app.test_client()

            # -------------------------------------------------------------
            # 15. Handling empty conversation history
            # -------------------------------------------------------------
            r_empty = client.get("/api/conversations")
            d_empty = r_empty.get_json()
            assert r_empty.status_code == 200
            assert d_empty["success"] is True
            assert d_empty["conversations"] == []
            assert d_empty["total_count"] == 0
            passed += 1  # Scenario 15

            # -------------------------------------------------------------
            # 1 & 12. Create two conversations without overwriting & list them
            # -------------------------------------------------------------
            c1_res = client.post(
                "/api/chat",
                json={"message": "What is the scholarship application process?"},
            ).get_json()
            c1_id = c1_res["conversation_id"]
            assert c1_res["conversation_title"] is not None
            assert "scholarship" in c1_res["conversation_title"].lower()

            c2_res = client.post(
                "/api/chat",
                json={"message": "Am I qualified for B.Tech admission?"},
            ).get_json()
            c2_id = c2_res["conversation_id"]
            assert c2_id != c1_id
            assert c2_res["conversation_title"] == "B.Tech Admission Eligibility"
            passed += 1  # Scenario 12

            r_list = client.get("/api/conversations")
            d_list = r_list.get_json()
            assert r_list.status_code == 200
            assert d_list["total_count"] == 2
            listed_ids = {c["conversation_id"] for c in d_list["conversations"]}
            assert listed_ids == {c1_id, c2_id}
            passed += 1  # Scenario 1

            # -------------------------------------------------------------
            # 2. Retrieving a complete conversation
            # -------------------------------------------------------------
            r_detail = client.get(f"/api/conversations/{c1_id}")
            d_detail = r_detail.get_json()
            assert r_detail.status_code == 200
            assert d_detail["success"] is True
            conv_obj = d_detail["conversation"]
            assert conv_obj["conversation_id"] == c1_id
            assert len(conv_obj["messages"]) == 2
            assert conv_obj["messages"][0]["role"] == "user"
            assert conv_obj["messages"][1]["role"] == "assistant"
            passed += 1  # Scenario 2

            # -------------------------------------------------------------
            # 3, 4 & 5. Search by title, message content, case-insensitive/partial
            # -------------------------------------------------------------
            r_s_title = client.get("/api/conversations/search?q=Eligibility")
            d_s_title = r_s_title.get_json()
            assert r_s_title.status_code == 200
            assert [c["conversation_id"] for c in d_s_title["conversations"]] == [c2_id]
            passed += 1  # Scenario 3

            r_s_msg = client.get("/api/conversations/search?q=application")
            d_s_msg = r_s_msg.get_json()
            assert r_s_msg.status_code == 200
            assert [c["conversation_id"] for c in d_s_msg["conversations"]] == [c1_id]
            passed += 1  # Scenario 4

            r_s_ci = client.get("/api/conversations/search?q=SCHOLAR")
            d_s_ci = r_s_ci.get_json()
            assert [c["conversation_id"] for c in d_s_ci["conversations"]] == [c1_id]
            r_s_empty = client.get("/api/conversations/search?q=")
            assert r_s_empty.get_json()["total_count"] == 2
            passed += 1  # Scenario 5

            # -------------------------------------------------------------
            # 6. Renaming a conversation & preserving custom title
            # -------------------------------------------------------------
            r_ren = client.patch(
                f"/api/conversations/{c1_id}",
                json={"title": "My Custom Scholarship Notes"},
            )
            d_ren = r_ren.get_json()
            assert r_ren.status_code == 200
            assert d_ren["conversation"]["title"] == "My Custom Scholarship Notes"
            assert d_ren["conversation"]["is_title_custom"] is True

            # Follow-up message must NOT overwrite the custom title
            client.post(
                "/api/chat",
                json={"message": "What documents do I need?", "conversation_id": c1_id},
            )
            c1_after = client.get(f"/api/conversations/{c1_id}").get_json()["conversation"]
            assert c1_after["title"] == "My Custom Scholarship Notes"
            passed += 1  # Scenario 6

            # -------------------------------------------------------------
            # 7. Rejecting empty or invalid titles
            # -------------------------------------------------------------
            assert client.patch(f"/api/conversations/{c1_id}", json={"title": "   "}).status_code == 400
            assert client.patch(f"/api/conversations/{c1_id}", json={}).status_code == 400
            assert client.patch(f"/api/conversations/{c1_id}", json={"title": 123}).status_code == 400
            assert client.patch(f"/api/conversations/{c1_id}", json={"title": "x" * 121}).status_code == 400
            passed += 1  # Scenario 7

            # -------------------------------------------------------------
            # 10 & 11. Reopening conversation & restoring unfinished eligibility
            # -------------------------------------------------------------
            reopened_c1 = client.get(f"/api/conversations/{c1_id}").get_json()["conversation"]
            assert reopened_c1["last_category"] == "Scholarships"
            assert len(reopened_c1["messages"]) == 4
            passed += 1  # Scenario 10

            reopened_c2 = client.get(f"/api/conversations/{c2_id}").get_json()["conversation"]
            assert reopened_c2["clarification_state"]["flow_name"] == "admission_eligibility"
            assert reopened_c2["clarification_state"]["slots"]["programme"] == "B.Tech"
            # Continue c2 with Class 12 -> must ask for stream (not restart)
            c2_next = client.post(
                "/api/chat",
                json={"message": "Class 12", "conversation_id": c2_id},
            ).get_json()
            assert c2_next["conversation_id"] == c2_id
            assert "stream" in c2_next["answer"].lower()
            passed += 1  # Scenario 11

            # -------------------------------------------------------------
            # 13. Preserving history after backend restart
            # -------------------------------------------------------------
            restart_db = Path(tmp_dir) / "restart_sessions.db"
            prev_env = os.environ.get("INTELLIFAQ_DB_PATH")
            try:
                os.environ["INTELLIFAQ_DB_PATH"] = str(restart_db)
                app1 = importlib.reload(backend_app)
                cl1 = app1.app.test_client()
                r_init = cl1.post(
                    "/api/chat",
                    json={"message": "Am I qualified for B.Tech admission?"},
                ).get_json()
                rcid = r_init["conversation_id"]
                cl1.patch(
                    f"/api/conversations/{rcid}",
                    json={"title": "Persisted B.Tech Check"},
                )

                app2 = importlib.reload(app1)
                cl2 = app2.app.test_client()
                r_list_after = cl2.get("/api/conversations").get_json()
                assert r_list_after["total_count"] == 1
                assert r_list_after["conversations"][0]["title"] == "Persisted B.Tech Check"
                r_cont = cl2.post(
                    "/api/chat",
                    json={"message": "Class 12", "conversation_id": rcid},
                ).get_json()
                assert "stream" in r_cont["answer"].lower()
            finally:
                if prev_env is None:
                    os.environ.pop("INTELLIFAQ_DB_PATH", None)
                else:
                    os.environ["INTELLIFAQ_DB_PATH"] = prev_env
                importlib.reload(backend_app)
                backend_app.conversation_manager = backend_app.ConversationManager(
                    database=Database(test_db)
                )
                backend_app.conversation_manager.initialize()
                client = backend_app.app.test_client()
            passed += 1  # Scenario 13

            # -------------------------------------------------------------
            # 8 & 9. Deleting one conversation without affecting another
            # -------------------------------------------------------------
            r_del = client.delete(f"/api/conversations/{c1_id}")
            assert r_del.status_code == 200
            assert client.get(f"/api/conversations/{c1_id}").status_code == 404
            # Search must not return deleted conversation
            assert client.get("/api/conversations/search?q=Scholarship").get_json()["total_count"] == 0
            passed += 1  # Scenario 8

            # c2 remains intact
            assert client.get(f"/api/conversations/{c2_id}").status_code == 200
            assert client.get("/api/conversations").get_json()["total_count"] == 1
            passed += 1  # Scenario 9

            # -------------------------------------------------------------
            # 14. Handling nonexistent & malformed conversation IDs
            # -------------------------------------------------------------
            missing_uuid = str(uuid.uuid4())
            assert client.get(f"/api/conversations/{missing_uuid}").status_code == 404
            assert client.patch(f"/api/conversations/{missing_uuid}", json={"title": "X"}).status_code == 404
            assert client.delete(f"/api/conversations/{missing_uuid}").status_code == 404
            assert client.get("/api/conversations/not-a-uuid").status_code == 400
            assert client.patch("/api/conversations/not-a-uuid", json={"title": "X"}).status_code == 400
            assert client.delete("/api/conversations/not-a-uuid").status_code == 400
            passed += 1  # Scenario 14

        finally:
            backend_app.conversation_manager = original_manager

    print("=" * 82)
    print(f"SESSION MANAGEMENT TEST SUITE SUMMARY: {passed} / {total} SCENARIOS PASSED")
    print("=" * 82)


def test_session_management_suite() -> None:
    """Entrypoint for pytest/unittest runners."""
    run_session_management_tests()


if __name__ == "__main__":
    run_session_management_tests()
