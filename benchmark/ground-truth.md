# Benchmark Ground Truth

This file defines the controlled benchmark and should be kept PRIVATE during
the final live demo if the judges should see ReleaseGuard discover the defects
without being told their locations.

## Baseline

All five applications begin in a clean state.

## Planned defect categories

The later benchmark will introduce examples from these categories:

1. Functional requirement failure
2. Missing/weak test coverage
3. Security/configuration problem
4. Dependency problem
5. Documentation mismatch
6. Deployment/health-check problem
7. Environment/configuration mismatch
8. Error-handling problem

## Language coverage

- Python: FastAPI
- Node.js: Express
- Go: net/http
- Java: Spring Boot
- Rust: Axum

## Success criterion

ReleaseGuard must detect problems using evidence appropriate to each project,
rather than using Python-only commands or file assumptions.

---

## Defect Log

### DEFECT #1 — Authorization / Ownership Bypass

> **Intentionally introduced for the ReleaseGuard benchmark.**

| Field                   | Value |
|-------------------------|-------|
| **Category**            | Security |
| **Severity**            | BLOCKER |
| **Affected file**       | `python-app/app/main.py` |
| **Affected function**   | `_get_task_for_user` |
| **Release impact**      | BLOCKED — must not ship |

#### Mutation

The two-line ownership guard was deleted from `_get_task_for_user`:

```python
# REMOVED — the missing check
if user_id is not None and task["user_id"] != user_id:
    raise HTTPException(status_code=404, detail="Task not found")
```

This was the **only** place in the application where an authenticated caller's
identity was compared against a stored task's owner before any single-task
operation (GET, PUT, DELETE, PATCH /complete).

#### Expected behaviour (clean baseline)

- An authenticated user **must not** be able to access or mutate a task that
  belongs to another user.
- The expected HTTP response for any cross-user single-task operation is
  **404** (task existence is hidden from unauthorised callers).

#### Observed behaviour (mutated)

- Cross-user `GET /tasks/{id}` returns **200** and exposes the task body.
- Cross-user `PUT /tasks/{id}` returns **200** and overwrites the task title.
- Cross-user `DELETE /tasks/{id}` returns **204** and permanently destroys the task.
- Cross-user `PATCH /tasks/{id}/complete` returns **200** and mutates task state.

#### Authentication status

Authentication itself remains functional:

- Missing or malformed tokens continue to be rejected with **401**.
- Valid tokens continue to resolve the correct `user_id`.
- `GET /tasks` (list) continues to filter to the authenticated user's own tasks.

The failure is exclusively at the **authorization** layer.

#### Evidence

The ownership comparison `task["user_id"] != user_id` is absent from
`_get_task_for_user`. Because this helper is the shared entry point for all
four single-task endpoints, every one of those routes is affected.

#### Test results

| State    | Passed | Failed | Total |
|----------|--------|--------|-------|
| Baseline | 69     | 0      | 69    |
| Mutated  | 60     | **9**  | 69    |

#### Failing tests (9)

| Test | HTTP verb | Expected | Got |
|------|-----------|----------|-----|
| `TestGetTask::test_get_wrong_user_returns_404` | GET | 404 | 200 |
| `TestUpdateTask::test_update_wrong_user_returns_404` | PUT | 404 | 200 |
| `TestDeleteTask::test_delete_wrong_user_returns_404` | DELETE | 404 | 204 |
| `TestCompleteTask::test_complete_wrong_user_returns_404` | PATCH | 404 | 200 |
| `TestAuthorizationFailures::test_authenticated_user_cannot_read_other_task` | GET | 404 | 200 |
| `TestAuthorizationFailures::test_authenticated_user_cannot_update_other_task` | PUT | 404 | 200 |
| `TestAuthorizationFailures::test_authenticated_user_cannot_delete_other_task` | DELETE | 404 | 204 |
| `TestAuthorizationFailures::test_authenticated_user_cannot_complete_other_task` | PATCH | 404 | 200 |
| `TestAuthorizationFailures::test_auth_error_returns_404_not_403` | GET | 404 | 200 |

#### Expected remediation

Restore the ownership validation inside `_get_task_for_user`:

```python
if user_id is not None and task["user_id"] != user_id:
    raise HTTPException(status_code=404, detail="Task not found")
```

#### Verification requirement

All **69/69** existing tests must pass again with no modifications to the test
suite. No new tests are required; the existing cross-user authorization tests
are sufficient to confirm the fix.

---

### DEFECT #2 — Task Title Validation Contract Violation

> **Intentionally introduced for the ReleaseGuard benchmark.**

| Field                   | Value |
|-------------------------|-------|
| **Category**            | Configuration / API contract |
| **Severity**            | HIGH |
| **Affected file**       | `python-app/app/main.py` |
| **Affected model**      | `TaskCreate` |
| **Release impact**      | BLOCKED — API accepts data outside its declared contract |

#### Mutation

`TaskCreate.title` field constraint changed from `max_length=255` to `max_length=256`:

```python
# Before (correct)
title: str = Field(..., min_length=1, max_length=255)

# After (defect)
title: str = Field(..., min_length=1, max_length=256)
```

#### Expected behaviour (clean baseline)

- Any title longer than 255 characters submitted to `POST /tasks` must be
  rejected with **HTTP 422**.
- This matches the documented API contract in `python-app/README.md`:
  `title > 255 chars → 422`.

#### Observed behaviour (mutated)

- A 256-character title submitted to `POST /tasks` is **accepted** and returns
  **HTTP 201**.
- `PUT /tasks/{id}` still rejects a 256-character title with **422** because
  `TaskUpdate.title` retains `max_length=255`.
- This creates an **inconsistent validation contract** between the two write
  paths: the same oversized string can be stored via `POST` but cannot be
  written via `PUT`.

#### Evidence

| Test | HTTP verb | Path | Expected | Got |
|------|-----------|------|----------|-----|
| `TestCreateTask::test_create_title_too_long_returns_422` | POST | `/tasks` | 422 | 201 |

#### Test results

| State | Passed | Failed | Total |
|-------|--------|--------|-------|
| Before Defect #2 (Defect #1 present) | 60 | 9 | 69 |
| After Defect #2 | **59** | **10** | 69 |

New failures caused specifically by Defect #2: **1**

The 9 pre-existing Defect #1 authorization failures remain unchanged.

#### Expected remediation

Restore the correct constraint in `TaskCreate`:

```python
title: str = Field(..., min_length=1, max_length=255)
```

#### Verification requirement

All **69/69** existing tests must pass again with no modifications to the test
suite. The corrected constraint must be verified to apply consistently to both
`TaskCreate` (used by `POST /tasks`) and `TaskUpdate` (used by `PUT /tasks/{id}`).
