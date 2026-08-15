package example.releaseguard;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class TaskControllerTest {

    @Test
    void healthReturnsOk() {
        TaskController controller = new TaskController();
        assertEquals("ok", controller.health().get("status"));
    }

    @Test
    void createAndListTask() {
        TaskController controller = new TaskController();
        var response = controller.create(new TaskController.TaskInput("Build ReleaseGuard"));

        assertEquals(201, response.getStatusCode().value());
        assertEquals(1, controller.list().size());
    }
}
