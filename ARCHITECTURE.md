# Architecture Deep Dive

This document details the engineering principles and design patterns implemented in the Distributed Task Engine.

---

## 1. The Distributed State Machine
Tasks move through a strict lifecycle to ensure consistency and visibility.

| State | Responsibility | Trigger |
| :--- | :--- | :--- |
| `QUEUED` | Available for execution | API Submission or Scheduler Promotion |
| `RUNNING` | Owned by a specific worker | Atomic Claim by Worker |
| `SUCCESS` | Successfully completed | Task Handler Return |
| `FAILED` | Exception occurred | Task Handler Raise (triggers backoff) |
| `SCHEDULED` | Waiting for future run_at | Backoff Logic or API Deferred |
| `CANCELLED` | User-requested stop | API Cancellation |
| `DEAD_LETTER` | Max retries exhausted | Error Recovery Logic |

---

## 2. Atomic Claiming (The "Double Guard")
To prevent multiple workers from executing the same task (Double Spend Problem), the engine uses two layers of protection:

1.  **Transport (Redis)**: Workers use an atomic **Lua Script** to `RPOPLPUSH` from the priority queues. This ensures only one worker gets the Task ID.
2.  **Persistence (PostgreSQL)**: Once a worker has the ID, it must perform an atomic update:
    ```sql
    UPDATE tasks 
    SET status = 'RUNNING', claimed_by = :worker_id, worker_host = :host
    WHERE id = :id AND status = 'QUEUED'
    RETURNING *;
    ```
    If `rowcount == 0`, the worker knows it lost a race or the task was cancelled, and it gracefully aborts.

---

## 3. Resilience Mechanisms

### Failure Detection (The Reaper)
Since workers can crash (SIGKILL, hardware failure), the system implements a **Heartbeat** pattern.
*   Running tasks update a `heartbeat_at` timestamp every 5 seconds.
*   The **Reaper** service scans for tasks where `heartbeat_at < (now - threshold)`.
*   Stale tasks are automatically requeued (until max retries).

### Poison Pill Protection (Hard Timeouts)
A common failure mode in task engines is a task that hangs forever (e.g., infinite loop). Because Python cannot safely kill threads, this engine uses **Process Isolation**:
*   Every task is spawned in a separate `multiprocessing.Process`.
*   The parent worker thread enforces a `join(timeout=task.timeout)`.
*   If the limit is reached, the parent executes `process.kill()`, freeing up system resources.

---

## 4. Priority Queue Architecture
The engine implements three priority tiers (`HIGH`, `NORMAL`, `LOW`) using segregated Redis lists.

**The Lua Dispatcher**:
To avoid "Busy Waiting" or "Race Windows," a custom Lua script is executed in Redis during `reserve()`:
1.  Check `tasks:high`. If task found, pop and return.
2.  Check `tasks:normal`. If task found, pop and return.
3.  Check `tasks:low`. If task found, pop and return.
This ensures **Absolute Priority**—a high-priority task will always be serviced before any normal task, even if the normal queue has 1,000,000 entries.
