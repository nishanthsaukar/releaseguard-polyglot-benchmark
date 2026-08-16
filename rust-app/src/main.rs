use axum::{
    extract::{Path, State},
    http::StatusCode,
    routing::{delete, get},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

#[derive(Clone)]
struct AppState {
    tasks: Arc<Mutex<HashMap<u64, Task>>>,
}

#[derive(Clone, Serialize)]
struct Task {
    id: u64,
    title: String,
    completed: bool,
}

#[derive(Deserialize)]
struct TaskInput {
    title: String,
}

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status": "ok", "language": "rust"}))
}

async fn list_tasks(State(state): State<AppState>) -> Json<Vec<Task>> {
    let tasks = state.tasks.lock().unwrap();
    Json(tasks.values().cloned().collect())
}

async fn create_task(
    State(state): State<AppState>,
    Json(input): Json<TaskInput>,
) -> (StatusCode, Json<Task>) {
    let mut tasks = state.tasks.lock().unwrap();
    let id = tasks.len() as u64 + 1;
    let task = Task {
        id,
        title: input.title,
        completed: false,
    };
    tasks.insert(id, task.clone());
    (StatusCode::CREATED, Json(task))
}

async fn delete_task(
    State(state): State<AppState>,
    Path(id): Path<u64>,
) -> StatusCode {
    let mut tasks = state.tasks.lock().unwrap();

    if tasks.remove(&id).is_some() {
        StatusCode::NO_CONTENT
    } else {
        StatusCode::NOT_FOUND
    }
}

#[tokio::main]
async fn main() {
    let state = AppState {
        tasks: Arc::new(Mutex::new(HashMap::new())),
    };

    let app = Router::new()
        .route("/health", get(health))
        .route("/tasks", get(list_tasks).post(create_task))
        .route("/tasks/{id}", delete(delete_task))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .unwrap();

    axum::serve(listener, app).await.unwrap();
}

#[cfg(test)]
mod main_test;
