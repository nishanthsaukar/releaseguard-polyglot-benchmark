# Task Manager API — Canonical Specification

Version: **1.1**  
Status: **Baseline (clean, no intentional defects)**  
Scope: Applied identically to all five language implementations — Python/FastAPI, Node.js/Express, Go/net/http, Java/Spring Boot, Rust/Axum.

---

## 1. Overview

A small, realistic REST API for managing tasks.  
All five language variants implement this exact contract.  
The API is intentionally narrow: simple Bearer token authentication, in-memory persistence, no user registration, no roles, no frontend.

---

## 2. Task Resource

### 2.1 Schema

#### Public fields (returned in every response)

| Field        | Type     | Nullable | Notes                                      |
|--------------|----------|----------|--------------------------------------------|
| `id`         | integer  | no       | Auto-assigned, positive, monotonically increasing from 1 |
| `title`      | string   | no       | 1–200 characters, stripped of leading/trailing whitespace |
| `description`| string   | yes      | 0–1000 characters; omitted from request = stored as empty string `""` |
| `status`     | string   | no       | One of `TODO`, `IN_PROGRESS`, `COMPLETED`  |
| `created_at` | string   | no       | ISO 8601 UTC timestamp, e.g. `2025-07-21T14:30:00Z` |
| `updated_at` | string   | no       | ISO 8601 UTC timestamp; equals `created_at` on first write |

#### Internal fields (stored in memory, never returned in API responses)

| Field      | Type   | Notes                                                              |
|------------|--------|--------------------------------------------------------------------|
| `owner_id` | string | The token value of the authenticated caller who created the task.  |

`owner_id` is set at task-creation time to the caller's token value and is used only for authorization checks on mutating operations. It must not appear in any response body.

### 2.2 Status Lifecycle

```
TODO  ──►  IN_PROGRESS  ──►  COMPLETED
 │                                ▲
 └────────────────────────────────┘
```

Any transition between any two statuses is permitted via PUT.  
The dedicated `POST /tasks/{id}/complete` endpoint sets status to `COMPLETED` directly.

---

## 3. Authentication and Authorization

### 3.1 Authentication Mechanism

All endpoints except `GET /health` require a **Bearer token** in the `Authorization` header:

```
Authorization: Bearer <token>
```

The server validates the token against the value in the `TASK_API_TOKEN` environment variable (see Section 8).

- If the header is absent or the token does not match, the server returns **HTTP 401**.
- If the header is present and the token matches, the request is authenticated.

There is no login endpoint, no token issuance, and no token refresh. The token is a shared secret configured at startup.

### 3.2 Authorization Rules

| Operation                        | Who is allowed                               | On failure  |
|----------------------------------|----------------------------------------------|-------------|
| `GET /health`                    | Anyone (no token required)                   | —           |
| `GET /tasks`                     | Any authenticated caller                     | 401         |
| `GET /tasks/{id}`                | Any authenticated caller                     | 401         |
| `POST /tasks`                    | Any authenticated caller                     | 401         |
| `PUT /tasks/{id}`                | Authenticated caller **who owns the task**   | 401 / 403   |
| `DELETE /tasks/{id}`             | Authenticated caller **who owns the task**   | 401 / 403   |
| `POST /tasks/{id}/complete`      | Authenticated caller **who owns the task**   | 401 / 403   |

**Ownership:** A caller owns a task when the `TASK_API_TOKEN`-validated token they supply matches the `owner_id` that was recorded when the task was created.

**403 vs 401 distinction:**
- **401 Unauthorized** — no token supplied, or the token is invalid (does not match `TASK_API_TOKEN`).
- **403 Forbidden** — the token is valid but the caller does not own the target task.

### 3.3 Authorization Error Responses

**401 Unauthorized**
```json
{ "error": "Unauthorized" }
```

**403 Forbidden**
```json
{ "error": "Forbidden" }
```

---

## 4. Endpoints

Base path: `/`  
Content-Type: `application/json` for all request and response bodies.

### 4.1 Health Check

```
GET /health
```

**Authentication:** None required.

**Response 200 OK**
```json
{
  "status": "ok",
  "language": "<python|node|go|java|rust>"
}
```

---

### 4.2 List Tasks

```
GET /tasks
```

**Authentication:** Required — valid Bearer token.  
**Authorization:** Any authenticated caller.

**Response 200 OK**
```json
[
  {
    "id": 1,
    "title": "Write unit tests",
    "description": "Cover the happy path and error cases",
    "status": "IN_PROGRESS",
    "created_at": "2025-07-21T14:30:00Z",
    "updated_at": "2025-07-21T15:00:00Z"
  }
]
```

Returns an empty array `[]` when no tasks exist.

**Response 401 Unauthorized** — missing or invalid token
```json
{ "error": "Unauthorized" }
```

---

### 4.3 Get Task by ID

```
GET /tasks/{id}
```

**Path parameter:** `id` — positive integer.

**Authentication:** Required — valid Bearer token.  
**Authorization:** Any authenticated caller.

**Response 200 OK**
```json
{
  "id": 1,
  "title": "Write unit tests",
  "description": "Cover the happy path and error cases",
  "status": "IN_PROGRESS",
  "created_at": "2025-07-21T14:30:00Z",
  "updated_at": "2025-07-21T15:00:00Z"
}
```

**Response 401 Unauthorized** — missing or invalid token
```json
{ "error": "Unauthorized" }
```

**Response 404 Not Found**
```json
{ "error": "Task not found" }
```

---

### 4.4 Create Task

```
POST /tasks
```

**Authentication:** Required — valid Bearer token.  
**Authorization:** Any authenticated caller. The token value becomes the `owner_id` of the created task.

**Request body**
```json
{
  "title": "Write unit tests",
  "description": "Cover the happy path and error cases"
}
```

| Field         | Required | Validation                           |
|---------------|----------|--------------------------------------|
| `title`       | yes      | Non-empty string, max 200 chars       |
| `description` | no       | String, max 1000 chars; defaults to `""` |

`status`, `created_at`, `updated_at`, and `owner_id` are set by the server and must not be accepted from the client.

**Response 201 Created**  
Body: the full public task object (same shape as Get Task; `owner_id` is NOT included).

**Response 400 Bad Request** — missing or invalid title
```json
{ "error": "title is required" }
```

**Response 400 Bad Request** — title exceeds length limit
```json
{ "error": "title must not exceed 200 characters" }
```

**Response 401 Unauthorized** — missing or invalid token
```json
{ "error": "Unauthorized" }
```

---

### 4.5 Update Task

```
PUT /tasks/{id}
```

**Authentication:** Required — valid Bearer token.  
**Authorization:** Only the task owner (caller whose token matches `owner_id`).

Full replacement of mutable fields.  
`id`, `created_at`, and `owner_id` are immutable and must be ignored if supplied in the request body.  
`updated_at` is set by the server to the current UTC time on every successful PUT.

**Request body**
```json
{
  "title": "Write unit tests",
  "description": "Cover happy path and all error cases",
  "status": "IN_PROGRESS"
}
```

| Field         | Required | Validation                                          |
|---------------|----------|-----------------------------------------------------|
| `title`       | yes      | Non-empty string, max 200 chars                      |
| `description` | no       | String, max 1000 chars; omitting leaves current value unchanged |
| `status`      | no       | One of `TODO`, `IN_PROGRESS`, `COMPLETED`; omitting leaves current value unchanged |

**Response 200 OK**  
Body: the updated full public task object.

**Response 400 Bad Request** — invalid field value
```json
{ "error": "status must be one of TODO, IN_PROGRESS, COMPLETED" }
```

**Response 401 Unauthorized** — missing or invalid token
```json
{ "error": "Unauthorized" }
```

**Response 403 Forbidden** — valid token but caller does not own the task
```json
{ "error": "Forbidden" }
```

**Response 404 Not Found**
```json
{ "error": "Task not found" }
```

---

### 4.6 Delete Task

```
DELETE /tasks/{id}
```

**Authentication:** Required — valid Bearer token.  
**Authorization:** Only the task owner (caller whose token matches `owner_id`).

**Response 204 No Content** — task deleted; empty body.

**Response 401 Unauthorized** — missing or invalid token
```json
{ "error": "Unauthorized" }
```

**Response 403 Forbidden** — valid token but caller does not own the task
```json
{ "error": "Forbidden" }
```

**Response 404 Not Found**
```json
{ "error": "Task not found" }
```

---

### 4.7 Mark Task as Completed

```
POST /tasks/{id}/complete
```

**Authentication:** Required — valid Bearer token.  
**Authorization:** Only the task owner (caller whose token matches `owner_id`).

Convenience endpoint. Sets `status` to `COMPLETED` and updates `updated_at`.  
Idempotent: calling it on an already-completed task returns 200 with no error.

**Response 200 OK**  
Body: the updated full public task object.

**Response 401 Unauthorized** — missing or invalid token
```json
{ "error": "Unauthorized" }
```

**Response 403 Forbidden** — valid token but caller does not own the task
```json
{ "error": "Forbidden" }
```

**Response 404 Not Found**
```json
{ "error": "Task not found" }
```

---

## 5. Validation Rules

| Rule                          | Behaviour                                  |
|-------------------------------|--------------------------------------------|
| `Authorization` header absent | 401 with `{"error": "Unauthorized"}` |
| Token present but does not match `TASK_API_TOKEN` | 401 with `{"error": "Unauthorized"}` |
| Valid token but caller is not the task owner | 403 with `{"error": "Forbidden"}` |
| `title` absent or empty string | 400 with `{"error": "title is required"}` |
| `title` > 200 chars           | 400 with `{"error": "title must not exceed 200 characters"}` |
| `description` > 1000 chars    | 400 with `{"error": "description must not exceed 1000 characters"}` |
| `status` not in enum          | 400 with `{"error": "status must be one of TODO, IN_PROGRESS, COMPLETED"}` |
| `{id}` non-integer path param | 400 or 422 (framework-dependent; must not return 500) |
| `{id}` valid but not found    | 404 with `{"error": "Task not found"}` |
| Request body malformed JSON   | 400 (framework-dependent message acceptable) |

**Precedence:** Authentication is checked before authorization, and both are checked before input validation. A request with no token and an invalid body returns 401, not 400.

---

## 6. HTTP Status Code Summary

| Code | Meaning                          | Used by                        |
|------|----------------------------------|--------------------------------|
| 200  | OK                               | GET /tasks, GET /tasks/{id}, PUT /tasks/{id}, POST /tasks/{id}/complete |
| 201  | Created                          | POST /tasks                    |
| 204  | No Content                       | DELETE /tasks/{id}             |
| 400  | Bad Request                      | Validation failures            |
| 401  | Unauthorized                     | Missing or invalid token       |
| 403  | Forbidden                        | Valid token, wrong owner       |
| 404  | Not Found                        | Missing task by ID             |

The API does not return 5xx codes under normal operation.

---

## 7. Persistence

**Approach:** In-memory, per-process store. No database, no file system writes.  
All data is lost on process restart. This is intentional for the baseline.

Implementation pattern across all languages:

- A hash-map / dictionary keyed by integer ID, storing the full internal task record (including `owner_id`).
- A monotonic integer counter for ID generation, starting at 1.
- Thread-safe access where the language runtime requires it (Go: `sync.RWMutex`, Java: `AtomicInteger` + `LinkedHashMap`, Rust: `Arc<Mutex<...>>`; Python and Node.js are effectively single-threaded in the request path).

---

## 8. Environment Variables

| Variable         | Required | Default | Description                             |
|------------------|----------|---------|-----------------------------------------|
| `PORT`           | no       | See below | Port the server listens on            |
| `TASK_API_TOKEN` | yes      | none    | Shared Bearer token used to authenticate all API requests. The server must refuse to start (or refuse all protected requests with 401) if this variable is not set. |

### Default ports by language

| Language | Default port |
|----------|-------------|
| Python   | 8000        |
| Node.js  | 3000        |
| Go       | 8080        |
| Java     | 8080        |
| Rust     | 3000        |

---

## 9. Health Endpoint Contract

```
GET /health
```

- Must return HTTP 200.
- Must return `Content-Type: application/json`.
- Body must include `"status": "ok"`.
- Body must include `"language"` set to the lower-case language name.
- Must respond within a reasonable time even when the task store is empty.
- **Does not require a token.** Used by Docker health checks and CI smoke tests.

---

## 10. Error Response Format

All error responses use this envelope:

```json
{ "error": "<human-readable message>" }
```

The `error` field is always a string.  
No stack traces, internal details, or nested error objects in responses.

---

## 11. Test Expectations

Each language implementation must include tests that cover:

| Test case                                                  | Expected result                        |
|------------------------------------------------------------|----------------------------------------|
| GET /health                                                | 200 + `{"status":"ok",...}` (no token needed) |
| POST /tasks — valid token, valid title only                | 201 + task with `status: "TODO"`, no `owner_id` in body |
| POST /tasks — valid token, title + description             | 201 + task with all public fields      |
| POST /tasks — missing title                                | 400                                    |
| POST /tasks — empty string title                           | 400                                    |
| POST /tasks — no token                                     | 401                                    |
| POST /tasks — wrong token                                  | 401                                    |
| GET /tasks — after create, valid token                     | 200 + array with the task              |
| GET /tasks — no token                                      | 401                                    |
| GET /tasks/{id} — existing task, valid token               | 200 + task                             |
| GET /tasks/{id} — no token                                 | 401                                    |
| GET /tasks/{id} — non-existent id                          | 404                                    |
| PUT /tasks/{id} — same token as creator                    | 200 + updated task                     |
| PUT /tasks/{id} — different valid token (not owner)        | 403                                    |
| PUT /tasks/{id} — no token                                 | 401                                    |
| PUT /tasks/{id} — invalid status value                     | 400                                    |
| PUT /tasks/{id} — non-existent id                          | 404                                    |
| DELETE /tasks/{id} — same token as creator                 | 204                                    |
| DELETE /tasks/{id} — different valid token (not owner)     | 403                                    |
| DELETE /tasks/{id} — no token                              | 401                                    |
| DELETE /tasks/{id} — non-existent id                       | 404                                    |
| POST /tasks/{id}/complete — same token as creator          | 200 + task with `status: "COMPLETED"`  |
| POST /tasks/{id}/complete — already completed, owner token | 200 (idempotent)                       |
| POST /tasks/{id}/complete — different valid token          | 403                                    |
| POST /tasks/{id}/complete — no token                       | 401                                    |
| GET /tasks after delete                                    | 200 + task absent from list            |

> **Note on the 403 test cases:** To test a "different valid token" scenario, implementations may use a secondary hardcoded test token (e.g., `"other-token"`) in tests only. This does not require a second `TASK_API_TOKEN` env var; the test can create one task using the real token and then attempt the operation using a different arbitrary string.

---

## 12. Local Development Instructions

### Python

```bash
cd python-app
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
TASK_API_TOKEN=dev-token uvicorn app.main:app --reload --port 8000
# Tests
TASK_API_TOKEN=dev-token pytest -q
```

### Node.js

```bash
cd node-app
npm install
TASK_API_TOKEN=dev-token npm start          # listens on PORT or 3000
# Tests
TASK_API_TOKEN=dev-token npm test
```

### Go

```bash
cd go-app
TASK_API_TOKEN=dev-token go run .           # listens on :8080
# Tests
TASK_API_TOKEN=dev-token go test ./...
```

### Java

```bash
cd java-app
TASK_API_TOKEN=dev-token mvn spring-boot:run   # listens on :8080
# Tests
TASK_API_TOKEN=dev-token mvn test
```

### Rust

```bash
cd rust-app
TASK_API_TOKEN=dev-token cargo run          # listens on :3000
# Tests
TASK_API_TOKEN=dev-token cargo test
```

---

## 13. Deployment Expectations

- Each app ships its own `Dockerfile` using a multi-stage build.
- Build stage: language-specific compiler image.
- Runtime stage: minimal base image (slim/alpine/bookworm-slim as appropriate).
- The container exposes the default port for that language (see Section 8).
- The Docker image must pass a `GET /health` → 200 check before being considered ready.
- `TASK_API_TOKEN` must be supplied to the container at runtime via an environment variable (e.g., `docker run -e TASK_API_TOKEN=...`). It must **not** be baked into the image.
- No orchestration (Kubernetes, Compose, etc.) is required for the baseline.

---

## 14. Endpoint Summary

| Method | Path                    | Auth required | Owner only | Description              | Success code |
|--------|-------------------------|---------------|------------|--------------------------|--------------|
| GET    | /health                 | No            | No         | Health check             | 200          |
| GET    | /tasks                  | Yes           | No         | List all tasks           | 200          |
| GET    | /tasks/{id}             | Yes           | No         | Get task by ID           | 200          |
| POST   | /tasks                  | Yes           | No         | Create a task            | 201          |
| PUT    | /tasks/{id}             | Yes           | Yes        | Update a task            | 200          |
| DELETE | /tasks/{id}             | Yes           | Yes        | Delete a task            | 204          |
| POST   | /tasks/{id}/complete    | Yes           | Yes        | Mark task as completed   | 200          |

---

## 15. Out of Scope for the Baseline

The following are explicitly excluded:

- User registration or login endpoints
- OAuth, JWT, or any token-issuance infrastructure
- Role-based authorization or permission systems
- External identity providers
- Multiple simultaneous user identities (one shared token per running instance)
- Pagination, filtering, or sorting of task lists
- Payments, notifications, or messaging
- Chat or AI features
- Frontend or web UI
- Analytics or metrics endpoints
- Microservices architecture
- Kubernetes or cloud infrastructure
- Database persistence
- Rate limiting
- Webhooks

These constraints keep each app small enough to serve as a reliable benchmark target.

---

## 16. Relationship to Benchmark Defect Categories

This spec defines the clean baseline. Later, each language app will have controlled defects introduced against these categories (per `benchmark/ground-truth.md`):

| # | Category                          | Example violation of this spec                        |
|---|-----------------------------------|-------------------------------------------------------|
| 1 | Functional requirement failure    | GET /tasks/{id} missing; complete endpoint returns wrong status |
| 2 | Missing/weak test coverage        | No test for 404; no test for invalid status value; no test for 401/403 |
| 3 | Security/configuration problem    | Auth middleware bypassed; `owner_id` returned in response; `TASK_API_TOKEN` hardcoded in source; 403 returns 200 |
| 4 | Dependency problem                | Pinned to a yanked version; known CVE in dependency   |
| 5 | Documentation mismatch            | README says port 8000 but app runs on 9000            |
| 6 | Deployment/health-check problem   | /health returns 500; Dockerfile exposes wrong port    |
| 7 | Environment/configuration mismatch| `TASK_API_TOKEN` or `PORT` env var ignored            |
| 8 | Error-handling problem            | Non-integer ID causes 500; missing title returns 200  |
