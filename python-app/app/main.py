import os
import re
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Task Manager API", version="1.0.0")

# ---------------------------------------------------------------------------
# In-memory storage
# ---------------------------------------------------------------------------

tasks: dict[int, dict] = {}
next_id: int = 1

# ---------------------------------------------------------------------------
# Token / auth helpers
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"^user_[a-zA-Z0-9_-]+$")


def _parse_token(authorization: Optional[str]) -> tuple[Optional[str], bool]:
    """Return (user_id, is_invalid).

    - No header            → (None, False)   – public mode
    - Valid Bearer token   → (user_id, False) – authenticated mode
    - Anything else        → (None, True)     – reject with 401
    """
    if authorization is None:
        return None, False

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None, True

    token = parts[1]
    if not _TOKEN_RE.match(token):
        return None, True

    # token is "user_<id>", so user_id is everything after "user_"
    user_id = token[len("user_"):]
    return user_id, False


def resolve_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """FastAPI dependency that validates the Authorization header.

    Returns the user_id string (authenticated), or None (public mode).
    Raises HTTP 401 if the token is present but invalid.
    """
    user_id, is_invalid = _parse_token(authorization)
    if is_invalid:
        raise HTTPException(status_code=401, detail="Invalid authorization token")
    return user_id


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class TaskUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class TaskResponse(BaseModel):
    id: int
    title: str
    completed: bool


# ---------------------------------------------------------------------------
# Exception handlers — ensure no stack traces leak
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_task_for_user(task_id: int, user_id: Optional[str]) -> dict:
    """Fetch a task from storage applying ownership rules.

    - Public mode (user_id is None): any task is accessible.
    - Authenticated mode: only tasks whose user_id matches are accessible.
    In both cases a missing or unauthorised task returns 404.
    """
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _task_response(task: dict) -> dict:
    """Return only the public fields of a task."""
    return {"id": task["id"], "title": task["title"], "completed": task["completed"]}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "language": "python"}


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks(user_id: Optional[str] = Depends(resolve_user)):
    if user_id is None:
        return [_task_response(t) for t in tasks.values()]
    return [_task_response(t) for t in tasks.values() if t["user_id"] == user_id]


@app.post("/tasks", status_code=201, response_model=TaskResponse)
def create_task(
    payload: TaskCreate,
    user_id: Optional[str] = Depends(resolve_user),
):
    global next_id
    task = {
        "id": next_id,
        "title": payload.title,
        "completed": False,
        "user_id": user_id,
    }
    tasks[next_id] = task
    next_id += 1
    return _task_response(task)


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, user_id: Optional[str] = Depends(resolve_user)):
    task = _get_task_for_user(task_id, user_id)
    return _task_response(task)


@app.put("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    user_id: Optional[str] = Depends(resolve_user),
):
    task = _get_task_for_user(task_id, user_id)
    task["title"] = payload.title
    return _task_response(task)


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, user_id: Optional[str] = Depends(resolve_user)):
    _get_task_for_user(task_id, user_id)
    del tasks[task_id]


@app.patch("/tasks/{task_id}/complete", response_model=TaskResponse)
def complete_task(task_id: int, user_id: Optional[str] = Depends(resolve_user)):
    task = _get_task_for_user(task_id, user_id)
    task["completed"] = True
    return _task_response(task)
