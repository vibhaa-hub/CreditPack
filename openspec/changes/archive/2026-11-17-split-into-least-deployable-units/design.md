# Design

## Context

See proposal.md (Why) for the motivation and the full agent → LDU mapping. The current runtime, documented in `baseline-cpa-app/design.md`, has five features this design must change:

- **One process does everything:** `workbench/runner.py` keeps one `asyncio.Task` per case and runs the whole ADK `Workflow` inside the web process (baseline D9).
- **All agents share one session:** they read and write a single ADK session stored by `DatabaseSessionService` (D8). Parallel agents write `<key>@<agent>` partitions, which merge nodes fold back together (D4).
- **Parallelism is a runtime global:** which agents write to partitions is a module-level `PARALLEL_AGENTS` set, filled in as a side effect of `build()`.
- **Uploads are on local disk:** they are written under `cpa_agents/.adk/uploads/<case>/`.
- **Status is recomputed constantly:** the SSE endpoint works out run status from the full audit trail every 1.5 to 4 seconds.

The design must keep these properties:
- the deterministic graph (D1)
- pure rules (D2)
- least privilege for each agent (D3)
- audit first, then apply (D5)
- the append-only store (D7)

## Goals / Non-Goals

**Goals:**
- Each LDU in the manifest can be deployed and scaled on its own, from one code base and one image.
- An LDU replica can crash without losing the run or corrupting case state.
- Single-process mode stays the default for development and tests, with no changes to existing tests.

**Non-Goals:**
- A separate database for each LDU. All LDUs keep sharing the case store and the session tables, so data ownership per unit is a later change.
- Building the planned LDUs: the DU-10 review scheduler and DU-12 telemetry.
- Real external adapters, SSO, or Kubernetes/Helm manifests. Docker Compose is the reference deployment.
- Changing any agent's instruction, tools, state keys, or any human gate.

## Decisions

### D1. An LDU is defined by its entrypoint, its queue and its manifest entry, not by its repository
All LDUs are built from the one `cpa_app` package and one container image, and are started with `python -m cpa_agents.ldu run <name>`. `cpa_agents/ldu/manifest.yaml` lists each LDU's kind, agents or components, AST unit, status (active or planned), queue name, default concurrency, and optional model.
- **Why:** This gives independent deploy and scale without the cost of 14 repositories or images while the code is still changing quickly. Splitting an LDU into its own image later only changes its build, not the runtime contract.
- **Alternative:** a separate package and image per LDU. Deferred until the boundaries have settled.
- **Enforcement:** an import check (a test) stops an agent LDU's modules from importing another agent LDU's tools. Shared libraries are `rules`, `store`, `mesh.callbacks`, `mesh.instructions`, `tools._common` and `policy`.

### D2. The orchestrator runs the existing graph, and agent nodes become remote steps
The `case-orchestrator` worker keeps the workflow graph from `mesh/orchestrator.py` as the single source of order. Two kinds of node run differently:
- **Function nodes** (`capture_request`, the merges, `await_humans`, `submission_gate`, `report_blocked`) run inside the orchestrator, as they do today.
- **Agent nodes** become *step jobs*. The orchestrator enqueues `{run_id, case_id, agent, step_input}` on the queue of the agent's LDU, then waits for completion.

A join completes when every branch step has completed. In single-process mode the same executor runs with an in-memory queue, and workers run in the same event loop.
- **Why:** The order stays deterministic and auditable (baseline D1), and the expensive part, the LLM agent, is what gets spread out.
- **Alternative: ADK `RemoteA2aAgent` nodes inside the existing `Workflow`.** Rejected for now. A2A agents have their own session state, which would break the shared-state model that tools, the gate and merges depend on. Revisit when each LDU owns its own data.
- **Alternative: a choreography of events with no orchestrator.** Rejected. Sequencing and gate checks would be spread across LDUs and would be harder to evidence.

### D3. A durable queue in Postgres, behind a small interface
The `step_jobs` table holds `id, run_id, ldu, agent, payload, state, attempts, claimed_by, claimed_at, heartbeat_at, result`. Workers claim jobs with `SELECT … FOR UPDATE SKIP LOCKED` filtered on `ldu`. Enqueue and release send `NOTIFY cpa_steps 'q:<ldu>'`; complete and fail send `NOTIFY cpa_steps 'd:<id>'`. One `LISTEN` connection per process wakes the waiters, and every wait also polls, so a lost notification only delays a step.

`payload` and `result` are stored as `JSON`, not `JSONB`: JSONB reorders the keys inside objects, and a step's state must come back in the same key order it was written in, because rendered output such as table columns follows that order. Found by running the dispatched-run comparison test on Postgres.

The workbench SSE stream uses the same listener on `cpa_cases` (payload: the session ID), which is sent with every audit event and run change, so a case page updates from any replica's writes.

The interface is `enqueue / claim / complete / fail / heartbeat`. It has two implementations: `PostgresQueue` and `InMemoryQueue` (for single-process mode and SQLite).
- **Why:** No new infrastructure is needed. Job state also commits in the same database as the audit trail, so a step can't be marked complete without its audit events.
- **Alternatives:** Redis/Celery, cloud Pub/Sub or Service Bus. They can be added later behind the same interface, for example if queue volume outgrows Postgres.

### D4. The orchestrator is the only writer to the case session; steps return state deltas
*Revised after the task 1.1 spike.* The first idea was for each worker to append to the shared case session under a per-case lock. That doesn't work with ADK 2.14:
- **How ADK checks writes:** `DatabaseSessionService.append_event` compares the storage revision marker held by the loaded session object with the one in the database. If another writer has appended since the session was loaded, it raises `StaleSessionError`.
- **What the spike showed:** two writers each held a loaded session and appended 100 events. The first stored all 100; the second had 99 rejected. A Runner keeps one session object for a whole agent turn, so a lock can't help.
- **Where the spike ran:** SQLite in one process. The check lives in ADK's own code and is the same on Postgres, where row locking only serialises the check.

So each step runs in an **isolated step session**:
1. The worker creates an `InMemorySessionService` session with the **same session ID as the case**. The audit callbacks and the tools that call `get_store()` then still write to the right case's audit chain.
2. It seeds that session with the case state from the job payload, and runs one `Runner(agent=<that agent>)` turn in it.
3. It returns the **state delta**: the keys whose values changed, with `None` for cleared keys.

The orchestrator then applies each completed step's delta to the real case session as a single event, authored by the agent, so it is the only writer. Partition keys (baseline D4) keep the deltas of parallel steps apart.
- **Why:** There is one writer, so ADK has no stale-session conflicts, and workers are stateless. The behaviour stays the same: tools still read and write `tool_context.state`, and the merges still run in the orchestrator.
- **Trade-off:** each step's model and tool turn-by-turn events now stay in its step session, not in the case's ADK session. Nothing in the app reads ADK session events: replay, the UI and the gate use the store's audit events and snapshots, which are written exactly as before. `agent_complete` snapshots are taken in the step session, so they show the case state plus that step's own writes, not the other parallel branches.

### D5. Partitioning is declared, not discovered
`parallel: true` moves from a `specialist()` argument into the manifest, and `wkey()` reads it from there. A process that builds only its own agents then still knows how every agent partitions its writes, which `merged_view` and the gate depend on.

### D6. Run status has its own table, and changes are pushed
The `runs` table holds `run_id, case_id, workflow, state, waiting_on_ldu, current_step, started_at, finished_at, error, heartbeat_at`. A partial unique index on `case_id` for running or waiting rows enforces one run per case across all web replicas (giving the 409). The orchestrator writes a heartbeat every 10 s, and a run with no heartbeat for 60 s (configurable) reads as `interrupted`.

The SSE endpoint `LISTEN`s on `case_<id>`, which run changes and audit appends `NOTIFY`. On SQLite it falls back to polling the `runs` row, not the audit trail. The audit events `run_started`, `run_finished` and `run_failed` are still written, so audit replay is unchanged.

### D7. Uploads go to an object store behind a `FileStore` interface
The interface is `put(case, name, bytes) -> uri`, `get(uri) -> bytes` and `stat(uri)`. `LocalFileStore` keeps today's path for single-process mode. `S3FileStore` works with any S3-compatible store (MinIO locally, or the target cloud's store). Document records keep their ID and SHA-256, and gain a `uri`. Provenance refers to the document ID, so it doesn't change.

### D8. Document extraction and external lookups are API LDUs
- **`document-extraction`:** `read_document` keeps its signature but calls `document-extraction` (`POST /extract {uri}`), which runs the PdfReader, openpyxl and python-docx code that runs inside the tool today. Truncation and unreadable-file handling stay the same.
- **`external-adapters`:** the external-lookup tools call `external-adapters` (`POST /lookup/<provider>`). It serves the existing `stubs/*.json`, labels results STUB, and applies a per-provider token bucket.
- **In single-process mode** both are called directly as functions, not over HTTP.
- **Why:** CPU-heavy parsing and provider quotas scale differently from LLM steps. Putting all external calls behind one place is also where real adapters, credentials and rate limits will go (Arch 3.5, "rate and quota limits on bureau calls").

### D9. Model concurrency and retry are wrapped around the model per LDU
`mesh/agents.py` `model()` is wrapped by an `LduModel` that holds an `asyncio.Semaphore(concurrency)`. It retries `429`, `5xx` and timeouts with exponential backoff and jitter, up to `max_attempts` (default 4). Only model calls are retried, never whole steps, because tool calls aren't idempotent (for example, `record_check_result`). The per-LDU `model` from the manifest overrides `CPA_MODEL`.

## Risks / Trade-offs

- **[Concurrent session appends across processes misbehave in ADK]** → Confirmed by the task 1.1 spike. Resolved by D4: the orchestrator is the only writer.
- **[The orchestrator crashes after a step completed but before applying its delta]** → The delta is stored in `step_jobs.result`, so a re-run can see it. The run shows as interrupted, as for any orchestrator crash.
- **[Every LDU still shares one database, so it can become a bottleneck or a shared failure point]** → Use connection pooling per LDU and keep job claims short. Separate data per LDU is a stated non-goal and a follow-up change.
- **[More moving parts for operators]** → Single-process mode stays the default. The Compose file plus a health endpoint for each LDU make local distributed runs reproducible.
- **[A step crashes after its tools wrote state but before it completed]** → The job's heartbeat expires. The orchestrator marks the run `interrupted` instead of retrying, as happens today after a restart, and a human re-runs it. Automatic step retry is out of scope because tools aren't idempotent.
- **[Where events from parallel steps fall in the audit trail now depends on timing]** → This is already true within one process. The hash chain stays per case and serialised, and the specs only promise the same order outside parallel branches.
- **[An extra network hop for each agent step]** → Small next to LLM latency, which takes seconds per step.

## Migration Plan

1. Land the interfaces (queue, file store, manifest, run table), with in-memory and local implementations only. Behaviour and tests stay unchanged.
2. Switch the workbench to the `runs` table and the orchestrator executor in single-process mode, and remove `workbench/runner.py`.
3. Add the Postgres queue, the S3 file store and HTTP clients for the API LDUs, plus `docker-compose.yml`. Distributed mode is opt-in with `CPA_LDU_MODE=distributed`.
4. Migrate existing uploads: a one-off script copies `.adk/uploads` into the file store and fills in `uri` on the document records. Document IDs and hashes don't change.
5. **Rollback:** set `CPA_LDU_MODE=inprocess`. The new tables are additive and are ignored in that mode.

## Open Questions

- Which object store and container platform to target in production (Azure Blob/AKS, GCS/Cloud Run, or S3/ECS). This doesn't affect the interfaces in D3 and D7.
- The starting replica counts and concurrency limits for each LDU. Set them after the first distributed load test against the model provider's quotas.
