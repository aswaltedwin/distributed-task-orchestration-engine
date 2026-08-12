# Interview Defense: Engineering Choices & Trade-offs

Use this guide to defend the technical decisions made in this project during interviews.

---

### Q1: "Why use both Redis and PostgreSQL?"
**The Defense**: "I chose a **Hybrid Persistence Model**. PostgreSQL acts as the **Source of Truth** for state, history, and scheduled tasks because of its ACID guarantees and complex query capabilities (like `FOR UPDATE SKIP LOCKED`). Redis acts as the **Transport Layer**, providing the sub-millisecond, low-overhead queueing necessary for high-throughput task dispatching. This separation allows the system to scale its throughput independently of its storage."

---

### Q2: "How do you handle the Thundering Herd problem?"
**The Defense**: "When tasks fail, I implement **Exponential Backoff with Jitter**. Simply retrying immediately or at fixed intervals causes spikes that can crash downstream services. By adding random jitter (+/- 20%), I ensure that retries are distributed across time, smoothing the load on the database and external APIs."

---

### Q3: "What happens if a worker crashes mid-task?"
**The Defense**: "The engine is designed for **At-Least-Once execution**. I implemented a **Heartbeat-and-Reaper pattern**. Every worker thread periodically updates a heartbeat timestamp in the DB. A separate `Reaper` service monitors these. If a worker dies, its heartbeat stops, the Reaper detects the staleness, and the task is atomically requeued. This ensures that no task is lost due to node failure."

---

### Q4: "How did you ensure task priority is respected?"
**The Defense**: "I avoided naive polling in Python, which is prone to race conditions. Instead, I moved the priority logic into **Redis Lua scripts**. This ensures that the check for High, Normal, and Low priority tasks—and the subsequent pop—happens **atomically** in the Redis kernel. It guarantees that high-priority work always preempts the backlog, even in a highly concurrent environment."

---

### Q5: "How do you handle tasks that hang or loop infinitely?"
**The Defense**: "This was a key architectural challenge because Python threads can't be safely killed. I solved this using **Subprocess Isolation**. Each task runs in a dedicated `multiprocessing` process. The worker thread monitors it with a hard timeout. If the task hangs, the worker can surgically `kill()` the subprocess without affecting the stability of the worker instance itself."
