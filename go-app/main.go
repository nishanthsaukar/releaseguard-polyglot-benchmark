package main

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"sync"
)

type Task struct {
	ID        int    `json:"id"`
	Title     string `json:"title"`
	Completed bool   `json:"completed"`
}

type Store struct {
	mu     sync.RWMutex
	tasks  map[int]Task
	nextID int
}

func NewStore() *Store {
	return &Store{tasks: make(map[int]Task), nextID: 1}
}

func (s *Store) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "language": "go"})
}

func (s *Store) tasksHandler(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		s.mu.RLock()
		result := make([]Task, 0, len(s.tasks))
		for _, task := range s.tasks {
			result = append(result, task)
		}
		s.mu.RUnlock()
		writeJSON(w, http.StatusOK, result)

	case http.MethodPost:
		var input struct {
			Title string `json:"title"`
		}
		if err := json.NewDecoder(r.Body).Decode(&input); err != nil || strings.TrimSpace(input.Title) == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "title is required"})
			return
		}

		s.mu.Lock()
		task := Task{ID: s.nextID, Title: input.Title}
		s.tasks[task.ID] = task
		s.nextID++
		s.mu.Unlock()

		writeJSON(w, http.StatusCreated, task)

	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Store) taskByID(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(strings.TrimPrefix(r.URL.Path, "/tasks/"))
	if err != nil {
		http.Error(w, "bad task id", http.StatusBadRequest)
		return
	}

	if r.Method != http.MethodDelete {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if _, ok := s.tasks[id]; !ok {
		http.Error(w, "task not found", http.StatusNotFound)
		return
	}

	delete(s.tasks, id)
	w.WriteHeader(http.StatusNoContent)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func main() {
	store := NewStore()

	mux := http.NewServeMux()
	mux.HandleFunc("/health", store.health)
	mux.HandleFunc("/tasks", store.tasksHandler)
	mux.HandleFunc("/tasks/", store.taskByID)

	http.ListenAndServe(":8080", mux)
}
