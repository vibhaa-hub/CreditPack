# Tasks

Prerequisite: `baseline-cpa-app` is archived, so that `openspec/specs/agent-orchestration` exists. Run the commands from `cpa_app/` with `../venv/Scripts/python`.

## 1. Spike and manifest

- [x] 1.1 Spike: two OS processes append events to one ADK `DatabaseSessionService` session on Postgres under the per-case advisory lock, with partitioned keys. Write the result in design.md D4 and verify that both writes are present after 100 rounds. If they aren't, switch D4 to the fallback where the orchestrator is the only writer before continuing.
- [x] 1.2 Add `cpa_agents/ldu/manifest.yaml` with the 14 LDUs and the two planned ones from proposal.md, and a loader that validates it. Verify with a test that all 19 agents from `build()` appear exactly once, and that an unassigned agent, a duplicated agent or an unknown agent each stops startup with the agent's name.
- [x] 1.3 Move `parallel` from `specialist()` arguments into the manifest, and make `wkey()` and `PARALLEL_AGENTS` read from it. Verify that `tests/test_mesh.py` and the parallel-write tests pass, and that a process building only `narrative-agent` still partitions `nd_*` writes.
- [x] 1.4 Add an import-boundary test: an agent LDU's tool modules import only shared libraries and their own tools. Verify that it passes on the current code and fails on a deliberately added cross-import.

## 2. Queue, step worker and orchestrator executor (single-process)

- [x] 2.1 Add the queue interface and `InMemoryQueue` (enqueue, claim by LDU, complete, fail, heartbeat). Verify with unit tests for claim-once, rejecting a step for another LDU, and heartbeat expiry.
- [x] 2.2 Add the step worker (design D4): claim a job, check that the agent belongs to this LDU, run one `Runner` turn for that agent in an isolated in-memory step session that has the case's session ID and is seeded with the case state, and complete the job with the resulting state delta. The orchestrator applies the delta as the only writer. Verify with a test using the scripted models from `tests/fakes.py`.
- [x] 2.3 Add the graph executor in `case-orchestrator`, which runs function nodes locally, dispatches agent nodes as steps, and waits at joins. Build it from the edges in `mesh/orchestrator.py`, keeping one definition of the graph. Verify that the existing workflow tests pass unchanged in single-process mode.
- [x] 2.4 Add the `runs` table, with heartbeat and a partial unique index for one active run per case, and replace `workbench/runner.py` with it. Verify the 409, interrupted-after-heartbeat-timeout and run_failed-names-the-step scenarios with tests, and that `tests/test_workbench_app.py` passes.
- [x] 2.5 Switch `/status` and `/stream` to read the `runs` row (polling in single-process mode). Verify that an SSE test receives a change event on a run transition, and that status shows `waiting` with the LDU name when no worker for that LDU is registered.

## 3. Model limits

- [x] 3.1 Wrap `model()` in a per-LDU concurrency limit and retry with backoff on 429, 5xx and timeouts, using the manifest's `concurrency`, `max_attempts` and `model`. Verify with a fake model: at most N calls in flight, success after two 429s with tool writes recorded once, and run_failed after all attempts fail.
- [x] 3.2 Document the per-LDU settings in `cpa_app/README.md`, and verify that the documented environment overrides change the model used by one LDU only.

## 4. Shared files and API LDUs

- [x] 4.1 Add the `FileStore` interface with `LocalFileStore` (today's path) and `S3FileStore`, and add `uri` to document records. Verify that upload then read returns identical bytes and SHA-256 on both, the latter against MinIO in a test marked `distributed`. (Verified against SeaweedFS in the compose stack: MinIO no longer publishes public images.)
- [x] 4.2 Write a one-off migration that copies `.adk/uploads` into the file store and fills in `uri`. Verify on a copy of the sample cases that document IDs and hashes are unchanged.
- [x] 4.3 Move extraction behind `document-extraction` (a direct call in single-process mode, `POST /extract` in distributed mode). Verify that the extraction, unreadable-document and 20,000-character truncation tests pass in both modes.
- [x] 4.4 Move the registry, sanctions, adverse-media and credit-reference lookups behind `external-adapters`, with a per-provider token bucket and STUB labelling kept. Verify the rate-limit scenario with a test, and that `tests/test_tools.py` passes.

## 5. Distributed runtime and packaging

- [x] 5.1 Add `PostgresQueue` (SKIP LOCKED, plus NOTIFY on completion), and switch SSE to `LISTEN` on Postgres. Verify with a test where two worker processes claim 50 jobs, each claimed exactly once.
- [x] 5.2 Add the entrypoint `python -m cpa_agents.ldu run <name>` with a `/health` endpoint for each LDU reporting its name and version, and refuse to start planned LDUs. Verify both scenarios from the deployable-units spec.
- [x] 5.3 Add a `Dockerfile` and a `docker-compose.yml` with Postgres, MinIO and one service per active LDU, configured by `CPA_LDU_MODE=distributed`. Document it in the README, and verify that `docker compose up` brings every service up healthy. (The object store is SeaweedFS, for the same reason.)
- [x] 5.4 Keep `start.ps1` in single-process mode, and verify that it still starts the app and that the full suite passes on SQLite and on Postgres (255 or more passed, 0 failed).

## 6. Integration checks

- [x] 6.1 Run samples `01-acme-motors-increase` and `02-brightway-cars-new-dealer` in single-process and distributed mode, with two replicas each of `due-diligence-agent` and `narrative-agent`, using the same scripted models. Verify that the final state, the gate result and the audit actions match, apart from order within parallel branches, and that the audit hash chain verifies.
- [x] 6.2 Failure drill: stop `narrative-agent` mid-run and verify the status shows "waiting for narrative-agent" and that human actions on other cases still work. Restart it and verify the run finishes. Then kill `case-orchestrator` and verify the run shows "interrupted" after the heartbeat timeout. (narrative-agent is stopped while the run is in flight, before it reaches the narrative steps. A replica dying in the middle of a step is covered by the requeue_expired tests.)
- [x] 6.3 Run `openspec validate split-into-least-deployable-units --strict` and verify there are no errors.

## Workflow follow-up

- Archive `baseline-cpa-app` before archiving this change.
- Raise follow-up changes for the planned LDUs (DU-10 review scheduler, DU-12 telemetry) and for separate data per LDU.
