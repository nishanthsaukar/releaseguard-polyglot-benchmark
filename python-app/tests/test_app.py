"""
Task Manager API — complete test suite.

Covers:
  1.  Task creation (success, validation errors)
  2.  Task listing (public and authenticated)
  3.  Task retrieval (success, not-found, wrong-user)
  4.  Task update via PUT (success, not-found, wrong-user, validation)
  5.  Task deletion (success, not-found, wrong-user)
  6.  Task completion via PATCH /tasks/{id}/complete
  7.  Authentication failures (invalid / malformed tokens)
  8.  Authorization failures (accessing another user's task)
  9.  Invalid task IDs
  10. Validation errors (empty title, title too long, missing title)
  11. State transitions (completed → still-readable, can be un-completed)
  12. Health endpoint
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_storage():
    """Reset in-memory storage before every test for full isolation."""
    main_module.tasks.clear()
    main_module.next_id = 1
    yield


@pytest.fixture
def client():
    return TestClient(app)


# Convenience header factories
def auth(user: str) -> dict:
    return {"Authorization": f"Bearer user_{user}"}


# ---------------------------------------------------------------------------
# 12. Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_body(self, client):
        r = client.get("/health")
        assert r.json() == {"status": "ok", "language": "python"}


# ---------------------------------------------------------------------------
# 1. Task creation
# ---------------------------------------------------------------------------

class TestCreateTask:
    def test_create_returns_201(self, client):
        r = client.post("/tasks", json={"title": "Buy groceries"})
        assert r.status_code == 201

    def test_create_response_shape(self, client):
        r = client.post("/tasks", json={"title": "Buy groceries"})
        body = r.json()
        assert body["id"] == 1
        assert body["title"] == "Buy groceries"
        assert body["completed"] is False

    def test_create_does_not_expose_user_id(self, client):
        r = client.post("/tasks", json={"title": "Secret"}, headers=auth("alice"))
        assert "user_id" not in r.json()

    def test_create_increments_id(self, client):
        id1 = client.post("/tasks", json={"title": "T1"}).json()["id"]
        id2 = client.post("/tasks", json={"title": "T2"}).json()["id"]
        assert id2 == id1 + 1

    # --- validation errors (10.) ---

    def test_create_missing_title_returns_422(self, client):
        r = client.post("/tasks", json={})
        assert r.status_code == 422

    def test_create_empty_title_returns_422(self, client):
        r = client.post("/tasks", json={"title": ""})
        assert r.status_code == 422

    def test_create_title_too_long_returns_422(self, client):
        r = client.post("/tasks", json={"title": "x" * 256})
        assert r.status_code == 422

    def test_create_title_max_length_accepted(self, client):
        r = client.post("/tasks", json={"title": "x" * 255})
        assert r.status_code == 201

    # --- auth on create ---

    def test_create_with_invalid_token_returns_401(self, client):
        r = client.post(
            "/tasks",
            json={"title": "T"},
            headers={"Authorization": "Bearer badtoken"},
        )
        assert r.status_code == 401

    def test_create_authenticated_assigns_owner(self, client):
        client.post("/tasks", json={"title": "Alice task"}, headers=auth("alice"))
        # Alice sees her task
        r = client.get("/tasks", headers=auth("alice"))
        assert len(r.json()) == 1
        # Bob sees nothing
        r2 = client.get("/tasks", headers=auth("bob"))
        assert r2.json() == []


# ---------------------------------------------------------------------------
# 2. Task listing
# ---------------------------------------------------------------------------

class TestListTasks:
    def test_list_empty(self, client):
        r = client.get("/tasks")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_public_sees_all(self, client):
        client.post("/tasks", json={"title": "T1"}, headers=auth("alice"))
        client.post("/tasks", json={"title": "T2"}, headers=auth("bob"))
        r = client.get("/tasks")  # no token
        assert len(r.json()) == 2

    def test_list_authenticated_sees_only_own(self, client):
        client.post("/tasks", json={"title": "Alice"}, headers=auth("alice"))
        client.post("/tasks", json={"title": "Bob"}, headers=auth("bob"))
        r = client.get("/tasks", headers=auth("alice"))
        titles = [t["title"] for t in r.json()]
        assert titles == ["Alice"]

    def test_list_no_user_id_in_response(self, client):
        client.post("/tasks", json={"title": "T"})
        r = client.get("/tasks")
        for task in r.json():
            assert "user_id" not in task

    def test_list_invalid_token_returns_401(self, client):
        r = client.get("/tasks", headers={"Authorization": "Bearer notvalid"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 3. Task retrieval
# ---------------------------------------------------------------------------

class TestGetTask:
    def test_get_returns_200(self, client):
        tid = client.post("/tasks", json={"title": "Read"}).json()["id"]
        r = client.get(f"/tasks/{tid}")
        assert r.status_code == 200

    def test_get_response_shape(self, client):
        tid = client.post("/tasks", json={"title": "Read"}).json()["id"]
        body = client.get(f"/tasks/{tid}").json()
        assert body["id"] == tid
        assert body["title"] == "Read"
        assert body["completed"] is False

    def test_get_not_found_returns_404(self, client):
        r = client.get("/tasks/9999")
        assert r.status_code == 404

    def test_get_not_found_error_message(self, client):
        r = client.get("/tasks/9999")
        assert "detail" in r.json()

    # --- 8. authorization failure ---

    def test_get_wrong_user_returns_404(self, client):
        # Alice creates a task
        tid = client.post(
            "/tasks", json={"title": "Alice secret"}, headers=auth("alice")
        ).json()["id"]
        # Bob tries to read it
        r = client.get(f"/tasks/{tid}", headers=auth("bob"))
        assert r.status_code == 404

    def test_get_own_task_authenticated(self, client):
        tid = client.post(
            "/tasks", json={"title": "Mine"}, headers=auth("alice")
        ).json()["id"]
        r = client.get(f"/tasks/{tid}", headers=auth("alice"))
        assert r.status_code == 200

    # --- 7. authentication failure ---

    def test_get_invalid_token_returns_401(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        r = client.get(f"/tasks/{tid}", headers={"Authorization": "Bearer invalid!"})
        assert r.status_code == 401

    # --- 9. invalid task ID ---

    def test_get_noninteger_id_returns_422(self, client):
        r = client.get("/tasks/abc")
        # FastAPI path coercion failure → 422
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 4. Task update (PUT)
# ---------------------------------------------------------------------------

class TestUpdateTask:
    def test_update_returns_200(self, client):
        tid = client.post("/tasks", json={"title": "Old"}).json()["id"]
        r = client.put(f"/tasks/{tid}", json={"title": "New"})
        assert r.status_code == 200

    def test_update_changes_title(self, client):
        tid = client.post("/tasks", json={"title": "Old"}).json()["id"]
        body = client.put(f"/tasks/{tid}", json={"title": "New"}).json()
        assert body["title"] == "New"
        assert body["id"] == tid
        assert body["completed"] is False

    def test_update_not_found_returns_404(self, client):
        r = client.put("/tasks/9999", json={"title": "X"})
        assert r.status_code == 404

    def test_update_empty_title_returns_422(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        r = client.put(f"/tasks/{tid}", json={"title": ""})
        assert r.status_code == 422

    def test_update_title_too_long_returns_422(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        r = client.put(f"/tasks/{tid}", json={"title": "x" * 256})
        assert r.status_code == 422

    # --- authorization ---

    def test_update_wrong_user_returns_404(self, client):
        tid = client.post(
            "/tasks", json={"title": "Alice"}, headers=auth("alice")
        ).json()["id"]
        r = client.put(f"/tasks/{tid}", json={"title": "Hacked"}, headers=auth("bob"))
        assert r.status_code == 404

    def test_update_own_task_authenticated(self, client):
        tid = client.post(
            "/tasks", json={"title": "Mine"}, headers=auth("alice")
        ).json()["id"]
        r = client.put(f"/tasks/{tid}", json={"title": "Updated"}, headers=auth("alice"))
        assert r.status_code == 200
        assert r.json()["title"] == "Updated"

    def test_update_invalid_token_returns_401(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        r = client.put(
            f"/tasks/{tid}", json={"title": "X"}, headers={"Authorization": "Bearer bad"}
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 5. Task deletion
# ---------------------------------------------------------------------------

class TestDeleteTask:
    def test_delete_returns_204(self, client):
        tid = client.post("/tasks", json={"title": "Gone"}).json()["id"]
        r = client.delete(f"/tasks/{tid}")
        assert r.status_code == 204

    def test_delete_no_body(self, client):
        tid = client.post("/tasks", json={"title": "Gone"}).json()["id"]
        r = client.delete(f"/tasks/{tid}")
        assert r.content == b""

    def test_delete_removes_task(self, client):
        tid = client.post("/tasks", json={"title": "Gone"}).json()["id"]
        client.delete(f"/tasks/{tid}")
        r = client.get(f"/tasks/{tid}")
        assert r.status_code == 404

    def test_delete_not_found_returns_404(self, client):
        r = client.delete("/tasks/9999")
        assert r.status_code == 404

    def test_delete_wrong_user_returns_404(self, client):
        tid = client.post(
            "/tasks", json={"title": "Alice"}, headers=auth("alice")
        ).json()["id"]
        r = client.delete(f"/tasks/{tid}", headers=auth("bob"))
        assert r.status_code == 404

    def test_delete_own_task_authenticated(self, client):
        tid = client.post(
            "/tasks", json={"title": "Mine"}, headers=auth("alice")
        ).json()["id"]
        r = client.delete(f"/tasks/{tid}", headers=auth("alice"))
        assert r.status_code == 204

    def test_delete_invalid_token_returns_401(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        r = client.delete(f"/tasks/{tid}", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 6. Task completion (PATCH /tasks/{id}/complete)
# ---------------------------------------------------------------------------

class TestCompleteTask:
    def test_complete_returns_200(self, client):
        tid = client.post("/tasks", json={"title": "Do it"}).json()["id"]
        r = client.patch(f"/tasks/{tid}/complete")
        assert r.status_code == 200

    def test_complete_sets_completed_true(self, client):
        tid = client.post("/tasks", json={"title": "Do it"}).json()["id"]
        body = client.patch(f"/tasks/{tid}/complete").json()
        assert body["completed"] is True
        assert body["id"] == tid

    def test_complete_idempotent(self, client):
        tid = client.post("/tasks", json={"title": "Do it"}).json()["id"]
        client.patch(f"/tasks/{tid}/complete")
        r = client.patch(f"/tasks/{tid}/complete")
        assert r.status_code == 200
        assert r.json()["completed"] is True

    def test_complete_not_found_returns_404(self, client):
        r = client.patch("/tasks/9999/complete")
        assert r.status_code == 404

    def test_complete_wrong_user_returns_404(self, client):
        tid = client.post(
            "/tasks", json={"title": "Alice"}, headers=auth("alice")
        ).json()["id"]
        r = client.patch(f"/tasks/{tid}/complete", headers=auth("bob"))
        assert r.status_code == 404

    def test_complete_own_task_authenticated(self, client):
        tid = client.post(
            "/tasks", json={"title": "Mine"}, headers=auth("alice")
        ).json()["id"]
        r = client.patch(f"/tasks/{tid}/complete", headers=auth("alice"))
        assert r.status_code == 200
        assert r.json()["completed"] is True

    def test_complete_invalid_token_returns_401(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        r = client.patch(
            f"/tasks/{tid}/complete", headers={"Authorization": "Bearer !!!"}
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 7. Authentication failures
# ---------------------------------------------------------------------------

class TestAuthFailures:
    def test_no_bearer_keyword_returns_401(self, client):
        r = client.get("/tasks", headers={"Authorization": "user_alice"})
        assert r.status_code == 401

    def test_token_without_user_prefix_returns_401(self, client):
        r = client.get("/tasks", headers={"Authorization": "Bearer alice"})
        assert r.status_code == 401

    def test_empty_token_returns_401(self, client):
        r = client.get("/tasks", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_token_with_invalid_chars_returns_401(self, client):
        r = client.get("/tasks", headers={"Authorization": "Bearer user_ali ce"})
        assert r.status_code == 401

    def test_401_response_body(self, client):
        r = client.get("/tasks", headers={"Authorization": "Bearer bad"})
        assert r.json() == {"detail": "Invalid authorization token"}

    def test_basic_auth_scheme_returns_401(self, client):
        r = client.get("/tasks", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 8. Authorization failures
# ---------------------------------------------------------------------------

class TestAuthorizationFailures:
    def test_authenticated_user_cannot_read_other_task(self, client):
        tid = client.post(
            "/tasks", json={"title": "Private"}, headers=auth("alice")
        ).json()["id"]
        r = client.get(f"/tasks/{tid}", headers=auth("bob"))
        assert r.status_code == 404

    def test_authenticated_user_cannot_update_other_task(self, client):
        tid = client.post(
            "/tasks", json={"title": "Private"}, headers=auth("alice")
        ).json()["id"]
        r = client.put(f"/tasks/{tid}", json={"title": "Hacked"}, headers=auth("bob"))
        assert r.status_code == 404

    def test_authenticated_user_cannot_delete_other_task(self, client):
        tid = client.post(
            "/tasks", json={"title": "Private"}, headers=auth("alice")
        ).json()["id"]
        r = client.delete(f"/tasks/{tid}", headers=auth("bob"))
        assert r.status_code == 404

    def test_authenticated_user_cannot_complete_other_task(self, client):
        tid = client.post(
            "/tasks", json={"title": "Private"}, headers=auth("alice")
        ).json()["id"]
        r = client.patch(f"/tasks/{tid}/complete", headers=auth("bob"))
        assert r.status_code == 404

    def test_auth_error_returns_404_not_403(self, client):
        """Spec: cross-user access must return 404, never 403."""
        tid = client.post(
            "/tasks", json={"title": "Private"}, headers=auth("alice")
        ).json()["id"]
        r = client.get(f"/tasks/{tid}", headers=auth("charlie"))
        assert r.status_code == 404
        assert r.status_code != 403


# ---------------------------------------------------------------------------
# 9. Invalid task IDs
# ---------------------------------------------------------------------------

class TestInvalidTaskIds:
    def test_nonexistent_id_get_returns_404(self, client):
        r = client.get("/tasks/99999")
        assert r.status_code == 404

    def test_nonexistent_id_put_returns_404(self, client):
        r = client.put("/tasks/99999", json={"title": "X"})
        assert r.status_code == 404

    def test_nonexistent_id_delete_returns_404(self, client):
        r = client.delete("/tasks/99999")
        assert r.status_code == 404

    def test_nonexistent_id_complete_returns_404(self, client):
        r = client.patch("/tasks/99999/complete")
        assert r.status_code == 404

    def test_string_id_returns_422(self, client):
        r = client.get("/tasks/notanumber")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 11. State transitions
# ---------------------------------------------------------------------------

class TestStateTransitions:
    def test_new_task_is_not_completed(self, client):
        body = client.post("/tasks", json={"title": "T"}).json()
        assert body["completed"] is False

    def test_complete_transitions_to_true(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        body = client.patch(f"/tasks/{tid}/complete").json()
        assert body["completed"] is True

    def test_completed_task_visible_in_list(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        client.patch(f"/tasks/{tid}/complete")
        tasks_list = client.get("/tasks").json()
        match = next(t for t in tasks_list if t["id"] == tid)
        assert match["completed"] is True

    def test_update_does_not_reset_completed(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        client.patch(f"/tasks/{tid}/complete")
        body = client.put(f"/tasks/{tid}", json={"title": "Updated"}).json()
        # PUT only changes title; completed flag must be preserved
        assert body["completed"] is True
        assert body["title"] == "Updated"

    def test_completed_task_can_be_recompleted(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        client.patch(f"/tasks/{tid}/complete")
        r = client.patch(f"/tasks/{tid}/complete")
        assert r.status_code == 200
        assert r.json()["completed"] is True

    def test_completed_task_can_be_deleted(self, client):
        tid = client.post("/tasks", json={"title": "T"}).json()["id"]
        client.patch(f"/tasks/{tid}/complete")
        r = client.delete(f"/tasks/{tid}")
        assert r.status_code == 204
