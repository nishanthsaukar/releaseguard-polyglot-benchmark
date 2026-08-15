import express from "express";

export const app = express();
app.use(express.json());

const tasks = new Map();
let nextId = 1;

app.get("/health", (_req, res) => {
  res.json({ status: "ok", language: "node" });
});

app.get("/tasks", (_req, res) => {
  res.json([...tasks.values()]);
});

app.post("/tasks", (req, res) => {
  const { title } = req.body;
  if (typeof title !== "string" || title.trim() === "") {
    return res.status(400).json({ error: "title is required" });
  }

  const task = { id: nextId++, title, completed: false };
  tasks.set(task.id, task);
  res.status(201).json(task);
});

app.delete("/tasks/:id", (req, res) => {
  const id = Number(req.params.id);
  if (!tasks.has(id)) {
    return res.status(404).json({ error: "Task not found" });
  }
  tasks.delete(id);
  res.status(204).end();
});

if (process.env.NODE_ENV !== "test") {
  app.listen(process.env.PORT || 3000);
}
