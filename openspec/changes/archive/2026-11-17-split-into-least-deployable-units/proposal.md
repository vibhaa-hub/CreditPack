# Proposal

## Why

Today the whole app (19 agents, rules, the workbench API and the run loop) ships as one process: workflow runs are asyncio tasks inside the FastAPI server. It can't run more than one instance. The narrative drafters, which do the most LLM work, can't be scaled without also scaling intake. One slow PDF parse or a model rate limit slows every case. AST.md describes the process as 12 deployable units, and Arch.md R5 asks for elastic, event-driven execution. The code has neither.

## What Changes

- Introduce the **Least Deployable Unit (LDU)**: the smallest piece that can be deployed, restarted and scaled on its own. An LDU is one of four kinds:
  - **agent:** a worker hosting one or more agents
  - **api:** an HTTP service
  - **worker:** non-LLM code, such as the orchestrator
  - **static:** the UI bundle
- Agents stay exactly as they are (skills, tool allow-lists, state keys). Each agent is assigned to exactly one LDU.
- Pure code that every LDU needs is packaged as **shared libraries** and is not deployed on its own: `rules/` with `policy.yaml`, `store/`, the audit callbacks, `tools/_common.py`, and skills/instructions.
- Declare all LDUs in one manifest (the mapping below). Every LDU starts from one code base with `--ldu <name>`.
- **BREAKING (operations):** workflow runs move out of the web process. The orchestrator worker drives the existing deterministic graph and dispatches each agent step to its LDU through a durable queue held in the database. Run state lives in a `runs` table with a heartbeat, not in process memory.
- Uploaded files move from local disk (`.adk/uploads`) to shared object storage. The local filesystem stays available for development.
- Parallel-agent partitioning is declared in the manifest, not built at runtime in a module-level global (`PARALLEL_AGENTS`).
- Each LDU gets its own limit on concurrent model calls, its own model setting, and retry with backoff on transient model errors.
- Each server-sent event reads one run-status row (database-pushed where available) instead of scanning the whole audit trail every 1.5 s.
- **Single-process mode is kept** (`CPA_LDU_MODE=inprocess`, the default for `start.ps1` and the tests). All LDUs then run in one process through the same interfaces.

### Agent → LDU mapping

| LDU | Kind | Current agents / code | AST unit | Scales with |
|---|---|---|---|---|
| `workbench-ui` | static | `workbench/frontend/dist` | (UI) | users (CDN) |
| `workbench-api` | api | `workbench/app.py`, `permissions.py`, `users.py`, `gates.py` (all human decisions) | human gates of DU-01…DU-09 | concurrent users |
| `case-orchestrator` | worker | `mesh/orchestrator.py` graph and function nodes `capture_request`, `merge_due_diligence`, `merge_evidence`, `merge_drafts`, `await_humans`, `submission_gate`, `report_blocked`; replaces `workbench/runner.py` | Arch "Credit Pack Orchestrator" | active runs |
| `intake-agent` | agent | `intake_classifier` | DU-01 | new cases |
| `entity-agent` | agent | `entity_structure` | DU-03 | parties per case |
| `evidence-agent` | agent | `document_ingestion`, `gap_consolidator` | DU-02 | documents per case |
| `document-extraction` | api | text/table extraction behind `read_document` (PDF, XLSX, DOCX, CSV) | DU-02 | upload volume (CPU) |
| `master-data-agent` | agent | `bureau_external` | DU-11 | cases × lookups |
| `due-diligence-agent` | agent | `dd_sanctions`, `dd_identity`, `dd_adverse_media`, `dd_summary` | DU-04 | parties × checks |
| `external-adapters` | api | `companies_house_lookup`, `sanctions_screen`, `adverse_media_search`, `credit_reference_lookup` (stubs today) | DU-03, DU-04, DU-11 | provider quotas |
| `financial-agent` | agent | `financial_analysis` | DU-05 | statements per case |
| `narrative-agent` | agent | `nd_business_background`, `nd_management_assessment`, `nd_conduct_performance`, `nd_security_esg`, `nd_critic` | DU-06 | LLM tokens (heaviest) |
| `pack-agent` | agent | `pack_request` (DU-07), `pack_validation` (DU-06/08), `pack_transmit` (DU-08) | DU-07, DU-08 | submissions |
| `post-approval-agent` | agent | `post_approval` | DU-09 (and next-review date for DU-10) | approvals |

All 19 agents built in `mesh/agents.py` are covered, each in exactly one LDU. DU-12 (governance, audit, telemetry) is not an LDU. It is the shared audit library inside every LDU, plus the database's append-only enforcement. DU-10's periodic review scheduler and a DU-12 telemetry service don't exist today. They are named in the manifest as **planned**, not built.

## Capabilities

### New Capabilities
- `deployable-units`: how the system is divided into LDUs and run: the manifest, one LDU per agent, independent scaling, per-LDU model limits, shared file storage, failure isolation, and single-process mode.

### Modified Capabilities
- `agent-orchestration`: "One background run per case" becomes a durable run, tracked outside the web process, with interruption detected by heartbeat. "Parallel writes are not lost" must also hold when parallel agents run in separate processes.

(This change depends on `baseline-cpa-app` being archived first, because that change creates `agent-orchestration`.)

## Impact

- **Code:**
  - new: `cpa_agents/ldu/` (manifest, queue, step worker, graph executor, entrypoint)
  - changed: `mesh/orchestrator.py`, `mesh/agents.py`, `tools/_common.py`, `tools/documents.py`, the external-lookup tools, `workbench/runner.py` (replaced), and `workbench/app.py` (status and stream)
- **Data:** new tables `runs`, `step_jobs`, and `uploads` metadata. The audit chain and session tables are unchanged.
- **Infrastructure:**
  - an S3-compatible object store (MinIO locally)
  - a container image with a per-LDU entrypoint
  - `docker-compose.yml` for running distributed locally
  - Postgres becomes required for distributed mode; SQLite stays for single-process mode
- **Behaviour seen by users:** unchanged. The same workflows, gates, audit events and UI. Two exceptions: status can now say "waiting for <LDU>", and a crashed worker shows as interrupted within the heartbeat timeout.
