# deployable-units Specification

## Purpose

Divides the CPA application into Least Deployable Units (LDUs), each deployable and scalable on its own, while keeping agent behaviour, tool allow-lists, human gates and the audit trail unchanged.

## Requirements

### Requirement: LDU manifest
The system SHALL declare every LDU in one manifest. Each entry SHALL give the LDU's name and kind (agent, api, worker or static), the agents or components it contains, the AST deployable unit it serves, and whether it is active or planned. Each LDU SHALL be startable from the shared code base by its manifest name.

#### Scenario: Start an LDU by name
- **WHEN** an operator starts the application with LDU name `due-diligence-agent`
- **THEN** only that LDU's process starts, hosting the four due-diligence agents, and it reports its name and version in its health check

#### Scenario: Planned LDU cannot start
- **WHEN** an operator starts an LDU that the manifest marks as planned
- **THEN** startup fails with a message that the LDU is not yet implemented

### Requirement: Every agent belongs to exactly one LDU
Every agent the system builds SHALL be assigned to exactly one active LDU of kind agent. The system SHALL refuse to start if any agent is unassigned, assigned twice, or named in the manifest but not built.

#### Scenario: Unassigned agent
- **WHEN** a new agent is added to the agent mesh but not to the manifest
- **THEN** every LDU refuses to start and names the unassigned agent

#### Scenario: Current mapping is complete
- **WHEN** the manifest is checked against the built agents
- **THEN** all 19 current agents are found, each in exactly one LDU

### Requirement: An LDU runs only its own agents
An agent LDU SHALL execute steps only for the agents it hosts, and each agent SHALL keep the same tool allow-list and readable state keys it has in single-process mode.

#### Scenario: Step for another LDU
- **WHEN** a step for `nd_critic` is delivered to the `due-diligence-agent` LDU
- **THEN** the LDU rejects the step without running it, and the step stays available to `narrative-agent`

### Requirement: Independent scaling
Each LDU SHALL support any number of replicas without configuration changes to other LDUs. Each dispatched step SHALL be executed by exactly one replica.

#### Scenario: Two due-diligence replicas
- **WHEN** two replicas of `due-diligence-agent` are running and a case dispatches its three parallel screening steps
- **THEN** each step runs exactly once across the replicas, and after the merge the checks list contains all three agents' records

#### Scenario: Scaling one LDU only
- **WHEN** `narrative-agent` is scaled from one to four replicas
- **THEN** no other LDU is restarted or reconfigured

### Requirement: Per-LDU model settings and concurrency limit
Each agent LDU SHALL have its own model setting, which defaults to the global model, and its own limit on concurrent model calls per replica.

#### Scenario: Concurrency limit respected
- **WHEN** an LDU replica with a limit of 2 has 5 steps ready
- **THEN** no more than 2 model calls from that replica are in flight at once, and the rest wait

#### Scenario: Different model per LDU
- **WHEN** the model for `narrative-agent` is set and the model for `intake-agent` is not
- **THEN** narrative agents use the LDU's model and intake uses the global model

### Requirement: Transient model errors are retried
A model call that fails with a rate-limit, timeout or server error SHALL be retried with exponential backoff, up to a configured number of attempts. A completed step SHALL never be re-run automatically. When the attempts are used up, the step SHALL fail, and the run SHALL record run_failed naming the step and the error.

#### Scenario: Rate limited then succeeds
- **WHEN** a model call returns a rate-limit error twice and then succeeds
- **THEN** the step completes once, and its tool writes appear once

#### Scenario: Retries exhausted
- **WHEN** every attempt fails
- **THEN** the run is recorded as failed with the step name and error, and no later step runs

### Requirement: Files reachable from every LDU
Uploaded documents SHALL be stored where any replica of any LDU can read them. Document identity, content hash and provenance SHALL be unchanged.

#### Scenario: Upload and read on different hosts
- **WHEN** a document is uploaded through one `workbench-api` replica and read by an `evidence-agent` replica on another host
- **THEN** the agent reads the same bytes, and the provenance recorded for extracted facts names the same document ID

### Requirement: External data behind one LDU
All calls to external data sources (registry, sanctions, adverse media, credit reference) SHALL go through the `external-adapters` LDU. That LDU SHALL enforce a per-provider rate limit and keep the STUB labelling of results.

#### Scenario: Provider rate limit
- **WHEN** agents across several LDUs request more registry lookups per second than the configured limit
- **THEN** the excess requests wait instead of reaching the provider, and every result is still returned

### Requirement: Failure isolation
If an LDU is unavailable, steps for it SHALL wait in the queue. Run status SHALL show which LDU the run is waiting for. Other LDUs and all human actions that are allowed in the current state SHALL keep working.

#### Scenario: Narrative LDU down
- **WHEN** no `narrative-agent` replica is running and a preparation run reaches narrative drafting
- **THEN** the run status shows "waiting for narrative-agent", and the run continues when a replica starts

#### Scenario: Human actions unaffected
- **WHEN** an agent LDU is down
- **THEN** users can still sign in, open cases and record human decisions on cases that are not running

### Requirement: Single-process mode
The system SHALL support running all active LDUs in one process with no external queue or object store. Workflows, gates and the sequence of audit events SHALL be the same as in distributed mode, apart from the order of events from steps that run in parallel.

#### Scenario: Local start
- **WHEN** the application starts in single-process mode on SQLite
- **THEN** a sample case runs end to end with no Docker services other than the database, and the existing test suite passes

#### Scenario: Same result distributed
- **WHEN** the same sample case is run in single-process mode and in distributed mode with the same scripted models
- **THEN** both produce the same final case state, the same gate result, and the same audit actions, apart from the order within parallel branches
