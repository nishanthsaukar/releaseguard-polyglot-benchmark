# Task Manager Python API — Implementation Plan

## Top-Level Overview

Implement the complete Task Manager API in Python using FastAPI, Pydantic, pytest, and httpx.
The existing `python-app/` scaffold has only a skeleton (`/health`, `GET /tasks`, `POST /tasks`, `DELETE /tasks/{id}`)
with no validation, no authentication, no authorization, and only two minimal tests.

This plan closes the gap between the skeleton and the canonical specification in `docs/api-spec.md`.
Persistence is in-memory only. No database, no external services.

---

## Sub-Task 1 — Rewrite `app/main.py` with full implementation

**Intent**
Replace the skeleton `main.py` with a complete, spec-compliant FastAPI application covering all
endpoints, validation, authentication, authorization, and ownership rules.

**Expected Outcomes**
- All 7 endpoints respond with correct status codes and response shapes.
- Token validation rejects any token that doesn't match `user_[a-zA-Z0-9_-]+`, returning 401.
- Public mode (no token) sees all tasks; authenticated mode sees only own tasks.
- Accessing another user's task returns 404 (not 403).
- POST /tasks returns 201; DELETE /tasks/{id} returns 204 with no body.
- No stack traces in error responses.
- Validation: `title` required, non-empty, max 255 chars → 422.
- Invalid integer ID → 404 (FastAPI path coercion handles non-integer → 422 naturally, spec says 400; handle via exception handler or validator).

**Todo List**
1. Define internal `Task` dataclass/model with `id`, `title`, `completed`, `user_id`.
2. Define `TaskCreate` Pydantic model with `title`: non-empty, max_length=255, required.
3. Define `TaskUpdate` Pydantic model with optional `title`: if present, non-empty, max_length=255.
4. Define `TaskResponse` Pydantic model with only `id`, `title`, `completed` (no `user_id`).
5. Implement `parse_token(authorization_header)` helper:
   - No header → return `(None, None)` (public mode).
   - Header present but doesn't match `Bearer user_[a-zA-Z0-9_-]+` → return `(None, "invalid")`.
   - Valid → return `(user_id, None)`.
6. Implement `resolve_user` dependency using `Header(None)` for `authorization`:
   - Calls `parse_token`; if invalid, raises `HTTPException(401, "Invalid authorization token")`.
   - Returns `user_id` (str or None).
7. Implement `GET /health` → `{"status": "ok", "language": "python"}`.
8. Implement `GET /tasks` — list all or filter by `user_id`.
9. Implement `POST /tasks` — create with 201, assign `user_id`.
10. Implement `GET /tasks/{task_id: int}` — get by id with auth check.
11. Implement `PUT /tasks/{task_id: int}` — full update (title required in body).
12. Implement `DELETE /tasks/{task_id: int}` — 204 no content.
13. Implement `PATCH /tasks/{task_id: int}/complete` — set `completed=True`, return 200.
14. Add custom exception handler for `RequestValidationError` to ensure no stack traces leak.
15. Read `TASK_API_TOKEN` env var (not used for validation itself — the spec uses the `Authorization: Bearer` header, but note the env var name for reference in README).

**Relevant Context**
- Spec: `docs/api-spec.md` §3, §4, §5, §6
- Current skeleton: `python-app/app/main.py`
- Token format regex: `^user_[a-zA-Z0-9_-]+$`
- Public fields only in responses: `id`, `title`, `completed`
- `user_id` field is internal, never returned

**Status:** [ ] pending

---

## Sub-Task 2 — Rewrite `tests/test_app.py` with complete test suite

**Intent**
Replace the two-test skeleton with a full test suite covering all spec requirements listed
in §11 and the user's requirements (items 9–13).

**Expected Outcomes**
- Tests cover all 7 endpoints for success paths.
- Tests cover 401 (invalid token), 404 (not found, wrong user), 422 (validation), 204 (delete).
- Tests verify authenticated users only see their own tasks.
- Tests verify state transitions (created → completed → uncompleted).
- Tests verify ownership: user A cannot get/update/delete user B's task.
- No tests rely on shared mutable state — each test or test group resets state via app restart or fixture.

**Todo List**
1. Use `TestClient(app)` from `fastapi.testclient` (ships with httpx).
2. Add pytest fixture `client` that resets in-memory storage before each test (clear `tasks` dict and reset `next_id`).
3. Write `test_health` — checks `{"status": "ok", "language": "python"}`.
4. Write `test_create_task` — POST returns 201, correct shape.
5. Write `test_create_task_missing_title` — POST with `{}` returns 422.
6. Write `test_create_task_empty_title` — POST with `{"title": ""}` returns 422.
7. Write `test_create_task_title_too_long` — POST with 256-char title returns 422.
8. Write `test_list_tasks_public` — no token sees all tasks.
9. Write `test_list_tasks_authenticated` — token user only sees own tasks.
10. Write `test_get_task` — GET /tasks/{id} returns 200 with correct shape.
11. Write `test_get_task_not_found` — non-existent ID returns 404.
12. Write `test_get_task_wrong_user` — authenticated user gets 404 for another user's task.
13. Write `test_update_task` — PUT updates title, returns 200.
14. Write `test_update_task_not_found` — 404 for missing task.
15. Write `test_update_task_wrong_user` — 404 when wrong owner.
16. Write `test_delete_task` — 204, task gone from list.
17. Write `test_delete_task_not_found` — 404.
18. Write `test_delete_task_wrong_user` — 404.
19. Write `test_complete_task` — PATCH /tasks/{id}/complete → `completed: true`, 200.
20. Write `test_complete_task_idempotent` — completing an already-completed task returns 200.
21. Write `test_invalid_token` — any request with malformed token returns 401.
22. Write `test_auth_token_no_user_prefix` — token without `user_` prefix → 401.

**Relevant Context**
- `fastapi.testclient.TestClient` wraps httpx.
- In-memory state must be reset between tests; expose `tasks` dict and `next_id` via module-level names so the fixture can clear them.
- Spec: `docs/api-spec.md` §11

**Status:** [ ] pending

---

## Sub-Task 3 — Update `README.md`

**Intent**
Update the Python app README to document all endpoints, auth/token usage, environment variables,
and test commands.

**Expected Outcomes**
- README describes all 7 endpoints with method and path.
- README explains the `Authorization: Bearer user_<id>` token format.
- README mentions `TASK_API_TOKEN` environment variable.
- README includes setup, run, and test commands.

**Todo List**
1. Add endpoint table (method, path, description).
2. Add authentication section explaining token format.
3. Add environment variables section (`SERVER_PORT`, `TASK_API_TOKEN`).
4. Confirm existing setup/run/test commands are correct.

**Relevant Context**
- `python-app/README.md` (current minimal version)
- Spec: `docs/api-spec.md` §8, §12

**Status:** [ ] pending

---

## Sub-Task 4 — Run the test suite and verify

**Intent**
Execute `pytest` inside `python-app/` to confirm all tests pass before reporting completion.

**Expected Outcomes**
- All tests pass with zero failures and zero errors.
- Output shows test count and results.

**Todo List**
1. Switch to agent mode.
2. Run `pytest -v` from `python-app/` directory.
3. If any tests fail, fix the root cause (implementation or test bug).
4. Report final test results.

**Relevant Context**
- Run command: `cd python-app && pytest -v`
- Python virtual environment must be activated or `pytest` must be run via the venv.

**Status:** [ ] pending
