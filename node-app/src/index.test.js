import test from "node:test";
import assert from "node:assert/strict";
import { app } from "./index.js";

async function request(path, options = {}) {
  const server = app.listen(0);
  const { port } = server.address();
  try {
    return await fetch(`http://127.0.0.1:${port}${path}`, options);
  } finally {
    server.close();
  }
}

test("health endpoint", async () => {
  const response = await request("/health");
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.status, "ok");
});

test("create and list task", async () => {
  const created = await request("/tasks", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ title: "Build ReleaseGuard" })
  });
  assert.equal(created.status, 201);

  const task = await created.json();
  const listed = await request("/tasks");
  assert.equal(listed.status, 200);

  const tasks = await listed.json();
  assert.ok(tasks.some(item => item.id === task.id));
});
