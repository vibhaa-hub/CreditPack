# Spec Delta

## Purpose

Runs the specialist agents in a fixed, deterministic order in three workflows separated by human gates. Each agent sees only its own tools and the state keys it needs, parallel agents never lose each other's writes, and runs are tracked so that interruptions are visible.

## ADDED Requirements

### Requirement: Three deterministic workflows
The system SHALL provide three workflows. Order, parallelism and routing SHALL be fixed by the workflow graph, not chosen by a model.
- **Preparation:** capture request, then intake, then entity → due diligence in parallel with documents → bureau, then gaps, lending request, financial analysis, parallel narrative drafting with the critic, validation, and a stop for humans.
- **Submission:** gate check, then transmit or report blocked.
- **Post-approval.**

#### Scenario: Preparation stops for humans
- **WHEN** the preparation workflow finishes validation
- **THEN** it records "awaiting_humans" with the gate status and pending human items, and starts no submission

#### Scenario: Submission routes on the gate
- **WHEN** the submission workflow runs while the gate passes but the owner has not authorised
- **THEN** it takes the "blocked" route, records "submission_blocked", and transmits nothing

### Requirement: Per-agent tool allow-list
Each agent SHALL be given only the tools listed for its specialist role. No agent SHALL have a tool that records a human decision, clears a hit, authorises pricing or submission, or decides on credit.

#### Scenario: Narrative drafter tools
- **WHEN** the narrative drafter agent is built
- **THEN** its only tool is the save-section tool

### Requirement: Per-agent context restriction
Each agent's instruction SHALL be built from its skill file: the shared text plus only its own sub-agent section, the runtime rules, and the case-state keys it declares it reads. Empty values SHALL be omitted.

#### Scenario: Bureau agent context
- **WHEN** the bureau agent's instruction is rendered
- **THEN** it contains only the case header keys, info_items, registry_record and held_cases from state

### Requirement: Parallel writes are not lost
Agents that run at the same time SHALL write shared list and dict keys to their own partition. A merge step after each join SHALL fold the partitions back into the shared key and clear them. Readers and the gate SHALL see any unmerged partitions as already merged.

#### Scenario: Two screening agents append checks
- **WHEN** the sanctions and adverse media agents each record a check in parallel
- **THEN** after the merge, the shared checks list contains both records

### Requirement: One background run per case
The workbench SHALL run at most one workflow per case at a time, in the background. It SHALL audit run_started, run_finished and run_failed, with the error. Status SHALL be one of running, not started, finished, failed or interrupted. A run that started but never finished, for example because the server restarted, SHALL show as interrupted.

#### Scenario: Concurrent start refused
- **WHEN** a run is started for a case that already has a run in progress
- **THEN** the request is refused with HTTP 409

#### Scenario: Server restart mid-run
- **WHEN** the process restarts during a preparation run
- **THEN** the case status shows "interrupted", and work up to the last completed agent is kept

### Requirement: Configurable model
The model SHALL be chosen by `CPA_MODEL` or a command-line override. Names with a provider prefix, such as `mistral/mistral-large-latest`, SHALL go through LiteLLM using that provider's key. Plain names SHALL use Gemini.

#### Scenario: Mistral from .env
- **WHEN** `CPA_MODEL=mistral/mistral-large-latest` and `MISTRAL_API_KEY` are set
- **THEN** every agent uses that Mistral model through LiteLLM
