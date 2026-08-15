from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ReleaseGuard Python Demo", version="1.0.0")

tasks = {}
next_id = 1

class TaskCreate(BaseModel):
    title: str

@app.get("/health")
def health():
    return {"status": "ok", "language": "python"}

@app.get("/tasks")
def list_tasks():
    return list(tasks.values())

@app.post("/tasks", status_code=201)
def create_task(payload: TaskCreate):
    global next_id
    task = {"id": next_id, "title": payload.title, "completed": False}
    tasks[next_id] = task
    next_id += 1
    return task

@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    del tasks[task_id]
