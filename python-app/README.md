# Python Task Manager API

A clean-baseline implementation of the Task Manager API using Python, FastAPI, and Pydantic.

---

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVER_PORT` | `8000` | Port the server listens on |
| `TASK_API_TOKEN` | _(none)_ | Reserved for tooling / CI; runtime auth uses `Authorization: Bearer` headers |

---

## Run the API

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive docs: <http://127.0.0.1:8000/docs>

---

## Run Tests

```bash
pytest -v
```

---

## Authentication

Requests are authenticated via a Bearer token in the `Authorization` header:

```
Authorization: Bearer user_<id>
```

**Token format:** `user_[a-zA-Z0-9_-]+`  
Examples: `user_alice`, `user_bob`, `user_123`

| Scenario | Behaviour |
|---|---|
| No `Authorization` header | Public mode — all tasks visible |
| Valid `Bearer user_<id>` | Authenticated mode — user sees only their own tasks |
| Invalid / malformed token | `401 Unauthorized` |

---

## Endpoints

| Method | Path | Auth required | Status | Description |
|---|---|---|---|---|
| `GET` | `/health` | No | 200 | Health check |
| `GET` | `/tasks` | Optional | 200 | List tasks (filtered by owner if authenticated) |
| `POST` | `/tasks` | Optional | 201 | Create a task |
| `GET` | `/tasks/{id}` | Optional | 200 | Get a task by ID |
| `PUT` | `/tasks/{id}` | Optional | 200 | Update a task's title |
| `DELETE` | `/tasks/{id}` | Optional | 204 | Delete a task |
| `PATCH` | `/tasks/{id}/complete` | Optional | 200 | Mark a task as completed |

### `GET /health`

```json
{"status": "ok", "language": "python"}
```

### `GET /tasks`

Returns an array of task objects. Authenticated users see only their own tasks.

```json
[{"id": 1, "title": "Buy groceries", "completed": false}]
```

### `POST /tasks`

**Request body:**
```json
{"title": "Buy groceries"}
```
**Response (201):**
```json
{"id": 1, "title": "Buy groceries", "completed": false}
```

### `GET /tasks/{id}`

**Response (200):**
```json
{"id": 1, "title": "Buy groceries", "completed": false}
```

### `PUT /tasks/{id}`

**Request body:**
```json
{"title": "Updated title"}
```
**Response (200):**
```json
{"id": 1, "title": "Updated title", "completed": false}
```

### `DELETE /tasks/{id}`

Returns `204 No Content` with an empty body.

### `PATCH /tasks/{id}/complete`

No request body needed.  
**Response (200):**
```json
{"id": 1, "title": "Buy groceries", "completed": true}
```

---

## Error Responses

All errors return JSON with a `detail` field:

```json
{"detail": "Task not found"}
```

| Status | Meaning |
|---|---|
| `400` | Bad request |
| `401` | Invalid or malformed authorization token |
| `404` | Task not found (or belongs to another user) |
| `422` | Validation error (missing/empty title, title > 255 chars) |

---

## Authorization Rules

- **Public mode** (no token): all tasks are accessible; new tasks are assigned to an anonymous owner.
- **Authenticated mode** (valid token): user can only read/update/delete tasks they created.
- Accessing another user's task returns **404** (not 403) to avoid information leakage.
- An invalid token always returns **401**, regardless of the requested resource.

---

## Persistence

In-memory only. All tasks are lost on restart. No database required.
