package example.releaseguard;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

@RestController
public class TaskController {
    private final Map<Integer, Task> tasks = new LinkedHashMap<>();
    private final AtomicInteger nextId = new AtomicInteger(1);

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok", "language", "java");
    }

    @GetMapping("/tasks")
    public Collection<Task> list() {
        return tasks.values();
    }

    @PostMapping("/tasks")
    public ResponseEntity<?> create(@RequestBody TaskInput input) {
        if (input.title() == null || input.title().isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "title is required"));
        }

        int id = nextId.getAndIncrement();
        Task task = new Task(id, input.title(), false);
        tasks.put(id, task);
        return ResponseEntity.status(HttpStatus.CREATED).body(task);
    }

    @DeleteMapping("/tasks/{id}")
    public ResponseEntity<?> delete(@PathVariable int id) {
        if (!tasks.containsKey(id)) {
            return ResponseEntity.notFound().build();
        }
        tasks.remove(id);
        return ResponseEntity.noContent().build();
    }

    public record Task(int id, String title, boolean completed) {}
    public record TaskInput(String title) {}
}
