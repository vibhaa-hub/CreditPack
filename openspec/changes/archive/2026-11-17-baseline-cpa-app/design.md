# Design

## Context

This change documents an app that already exists (see proposal.md, Why). The design below describes the architecture as built, in `cpa_app/`, so that future changes can reason about it. Requirements are in `specs/`. This document explains *how* and *why*.

```
+---------------------------------------------------------------+
| Browser: React 18 + TS + MUI 6 (workbench/frontend)           |
|   React Query cache, SSE subscription, ActionDialog approvals |
+------------------------------+--------------------------------+
                               | /api (JSON, signed cookie)
+------------------------------v--------------------------------+
| FastAPI workbench (workbench/)                                |
|   app.py routes | permissions.py roles | gates.py decisions   |
|   runner.py background runs (asyncio task per case)           |
+-------------+-----------------------------------+-------------+
              | start workflow                    | human decision
+-------------v-------------------+   +-----------v-------------+
| ADK agent mesh (cpa_agents/mesh)|   | store/runtime.py         |
|  orchestrator.py: 3 Workflows   |   |  audit FIRST, then apply |
|  agents.py: ~20 LlmAgents       |   +-----------+-------------+
|  instructions.py: SKILL.md text |               |
+-------------+-------------------+               |
              | tool calls (allow-listed)         |
+-------------v-------------------+               |
| tools/ (thin)  -> rules/ (pure) |               |
|               -> stubs/*.json   |               |
+-------------+-------------------+               |
              | callbacks: audit + snapshot       |
+-------------v-----------------------------------v-------------+
| Case store (store/core.py, SQLAlchemy)  +  ADK sessions       |
|   cases, audit_events (hash chain), pack_versions,            |
|   section_versions, state_snapshots, credit_queries, users    |
|   Postgres (target, Docker locally) or SQLite (default)       |
+---------------------------------------------------------------+
```

The constraints that shape this design come from the BA pack and Arch.md:
- No automated credit decision.
- Every human decision is attributable.
- An audit trail that can only be added to.
- Policy values governed outside the code.
- External systems are not yet available, so they are stubbed.

## Goals / Non-Goals

**Goals:**
- Record the architectural decisions behind the current behaviour, and what was traded off.
- Name the boundaries a future change must respect: no decision tools for agents, audit before apply, and rules kept in pure code.

**Non-Goals:**
- Any change in behaviour, refactor or production hardening.
- Designing the follow-up changes listed in tasks.md (each needs its own change).

## Decisions

### D1. A deterministic workflow graph, not an LLM orchestrator
The orchestrator is an ADK `Workflow` with fixed edges, parallel branches, join nodes and a routed edge for submission. Models do the work *inside* each specialist agent. They never choose what runs next.
- **Why:** Sequencing must be auditable and repeatable. A gate must never be skipped because a model decided to.
- **Alternative:** an LLM supervisor agent that delegates to sub-agents. Rejected because its path through the work is non-deterministic and harder to evidence.

### D2. Rules are pure Python; agents reach them only through tools
Calculations (CALC-001 to CALC-014), the DT-2 gate, DT-3 outcomes, DT-5 staleness, registry comparison and decision-language detection live in `rules/`. They use `Decimal` and have no LLM or I/O dependencies. Tools are thin wrappers that read state, call a rule, write state and return.
- **Why:** The figures and gate results must be reproducible and unit-testable, and an auditor must be able to recompute them.
- **Alternatives:** letting the LLM calculate (rejected: arithmetic errors, no reproducibility), or an external rules engine (deferred: the rule set is still small; see tasks.md for a possible decision-table layer).

### D3. Least privilege for each agent: tools and state keys
`BY_SPECIALIST` gives each agent an allow-list of tools. `instruction_for` renders each prompt with the skill's shared text, the agent's own `## Sub-agent:` section, the runtime rules, and *only* the state keys the agent declares.
- **Why:** This limits both mistakes and prompt injection (Arch 3.5, ARCH-G03). No agent holds a tool that records a human decision.
- **Alternative:** a single agent with every tool. Rejected because it can't keep the BR-E01 and BR-E02 separations.

### D4. Partitions for parallel writes, folded by merge nodes
ADK applies each state change by replacing the whole key, so concurrent appends would lose writes. Parallel agents therefore write to `<key>@<agent>`, and a merge function node after each join folds the partitions back into the shared key. Readers use `collect` or `merged_view`.
- **Why:** This is correct without locks, and the merge is deterministic, in partition-name order.
- **Alternative:** running the agents sequentially. Rejected because it makes preparation noticeably slower.

### D5. Human decisions: audit first, then apply as a session event
`record_human_decision` appends a `human_decision` audit event, writes section versions, and only then appends an ADK event carrying the state change.
- **Why:** No state change can exist without an audit record (BR-G02).
- **Alternative:** editing state directly and logging afterwards. Rejected because a crash between the two steps would leave a change that was never audited.

### D6. Approval prerequisites are fingerprinted
For each approval, the server computes a SHA-256 fingerprint (first 20 characters) of the evidence that should be shown. The client echoes back the fingerprint it rendered, and a mismatch is refused and audited as `process_failure` (ARCH-H09).
- **Why:** This proves the approver saw the current evidence, without the server having to keep UI state.

### D7. A tamper-evident store with append-only enforcement in the database
Audit events are hash-chained per session. Postgres advisory locks and an in-process lock serialise appends. Triggers reject UPDATE and DELETE (and TRUNCATE on Postgres) on the audit, pack, section and snapshot tables. On Postgres, a restricted `cpa_app` role has only INSERT and SELECT on those tables.
- **Why:** Integrity must not depend on application code behaving correctly.
- **Alternative:** a WORM or ledger database. Deferred until there's a production platform.

### D8. One database for the store and the ADK sessions
A single `DATABASE_URL` determines both a synchronous SQLAlchemy engine (psycopg or sqlite) and an asynchronous one for `DatabaseSessionService` (asyncpg or aiosqlite).
- **Why:** One place to back up, and case state stays consistent with its audit trail.
- **Choice of database:** SQLite is the default for tests and local runs; Postgres is the target.

### D9. Background runs inside the web process
`Runs` keeps one asyncio task per case. Its start, finish and failure are audited, so status can be worked out from the audit trail after a restart (an "interrupted" run).
- **Why:** It's simple for a prototype and needs no extra infrastructure.
- **Trade-off:** see Risks.

### D10. Policy as versioned YAML, where unset means NOT CONFIGURED
`policy.yaml` holds every governed parameter. Missing or null values resolve to a `NOT_CONFIGURED` sentinel that rules must report and must not replace with a default. Results record the policy version they used.
- **Why:** BR-G05. Values belong to the policy owner, not to developers.

### D11. The server enforces every rule; the SPA only displays
The FastAPI layer enforces sign-in (an itsdangerous-signed cookie, 8 hours), role and separation-of-duties checks, prerequisites and the audit trail. The React app hides controls using the `permissions` the server returns, but it is never trusted. The built SPA is served from FastAPI, and in development Vite forwards `/api` to the backend.
- **Live updates:** server-sent events, chosen over WebSockets because they're one-way, simple, and work through proxies.

### D12. Models are pluggable through ADK and LiteLLM
`CPA_MODEL` sets the model. A name with a provider prefix goes through LiteLLM; a plain name goes to Gemini directly. Tests inject scripted models for each agent.

## Risks / Trade-offs

- **External sources are stubs** (Companies House, bureau, screening, the Credit interface) → Results are labelled STUB, and submission receipts say NOT-TRANSMITTED. Real adapters are a follow-up change.
- **Every policy parameter is null** → The gate raises R7 advisories, and staleness and review dates can't be determined. The policy owner must populate `policy.yaml` before any real use.
- **In-process runs are lost on restart** → They are detected as "interrupted" and the user re-runs them. Production needs a durable job queue and workers.
- **Local username/password sign-in** → scrypt hashes and signed cookies are adequate for a prototype. Production needs company SSO and MFA.
- **LLM output quality and prompt injection** → Mitigated by the tool allow-lists, the restricted context, document text labelled as untrusted, the critic pass, the decision-language ban, gate checks on figures and amounts, and mandatory human review. A formal model-risk evaluation is still needed.
- **Third-party LLM API (Mistral or Gemini)** → Dealer data leaves the bank's environment. A data-processing agreement and a residency review are needed before any real data is used.
- **Decision-language detection uses regex** → It's deliberately strict: a false positive just needs rewording, while a missed phrase would be worse. It may still miss novel phrasing, so human review remains the backstop.
- **Proposed tables (DT-1) and open definitions (ROTE, haircuts, stock days)** → Flagged in the output, and need business confirmation (OQ-03, OQ-04, OQ-09).

## Migration Plan

None. This change is documentation only. Archiving it moves the 13 specs into `openspec/specs/` as the baseline.

## Open Questions

- Who owns `policy.yaml` sign-off, and how are its values promoted between environments?
- Which Credit interface, and which receipt format, will replace the NOT-TRANSMITTED placeholder (OQ-14)?
