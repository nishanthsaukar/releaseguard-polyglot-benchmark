from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_create_list_delete():
    created = client.post("/tasks", json={"title": "Build ReleaseGuard"})
    assert created.status_code == 201

    task_id = created.json()["id"]

    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert any(task["id"] == task_id for task in listed.json())

    deleted = client.delete(f"/tasks/{task_id}")
    assert deleted.status_code == 204
