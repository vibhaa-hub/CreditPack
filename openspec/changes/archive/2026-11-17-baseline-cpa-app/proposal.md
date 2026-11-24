# Proposal

## Why

The Credit Pack Assessment (CPA) prototype is already built: a Google ADK agent mesh, a FastAPI workbench, a React UI and a case store. Its behaviour, however, is recorded only in code, the README and the BA pack (`Credit_Pack_Assessment_BA_Pack_v1.0.md`). Without a spec baseline, future changes have nothing to be proposed against. Examples include segment-based ratio benchmarks, real bureau and screening adapters, and SSO. This change records what the app does today as OpenSpec capabilities, so that later changes can be expressed as deltas.

## What Changes

- Document the existing behaviour as 13 new capability specs. No application code changes.
- Record the current architecture and its key design decisions in `design.md`:
  - the workflow graph
  - each agent seeing only its declared state keys and tools
  - the audit record being written before a human decision is applied
  - the append-only, hash-chained store
- Record the known gaps that stop the prototype being production-ready, as open questions and risks:
  - stubbed external sources
  - unset policy parameters
  - local sign-in
  - agent runs held in the web process
- `tasks.md` tracks verifying each spec against the code and tests. It also lists the follow-up changes the gaps suggest.

## Capabilities

### New Capabilities
- `case-intake`: Case registration, case IDs, DT-1 requirement checklist and related-case lookup.
- `evidence-assembly`: Document ingestion and extraction, information items with provenance, financial statements, notes, information requests, Companies House comparison and bureau lookups.
- `due-diligence-screening`: The mandatory check register for each party, DT-3 outcome handling, hits, manual alternatives and the CRA.
- `financial-analysis`: The deterministic calculations CALC-001 to CALC-014, facilities and security, and data-quality flags.
- `narrative-drafting`: Pack narrative sections drafted with evidence citations, the critic pass, the decision-language ban and section versions.
- `pack-completeness-gate`: The DT-2 gate, rules R1 to R8, with completeness scoring, corrective actions and authorised exceptions.
- `pack-submission`: Pricing and submission authorisation, transmission, immutable pack versions, Credit queries and the Credit outcome.
- `post-approval`: Handoffs carrying the approved terms, conditions with evidence, case closure and next review date.
- `agent-orchestration`: The deterministic preparation, submission and post-approval workflows, per-agent tool and state-key limits, partitions for parallel writes, and background runs.
- `human-decisions`: Workbench sign-in, role permissions, separation of duties, prerequisite fingerprints, and audit-first application of human decisions.
- `audit-trail`: The hash-chained audit events, append-only tables, state snapshots, replay, chain verification and rollback.
- `policy-parameters`: The governed, versioned policy file in which unset values are reported as NOT CONFIGURED.
- `workbench-ui`: The React screens, the "My queue" view, live updates and how permissions are shown in the UI.

### Modified Capabilities
None. `openspec/specs/` is empty; this is the first baseline.

## Impact

- **Code:** none changed. The specs describe:
  - `cpa_app/cpa_agents/`: mesh, tools, rules, store, skills and `policy.yaml`
  - `cpa_app/workbench/`: `app.py`, `gates.py`, `permissions.py`, `runner.py`, `users.py` and `frontend/`
  - `cpa_app/run.py`
- **Docs:** adds `openspec/`. When this change is archived, the 13 specs become the project's baseline in `openspec/specs/`.
- **Out of scope:**
  - credit decisioning, risk scoring and pricing models (the app deliberately has none)
  - production hardening
  - any behaviour change
