# Spec Delta

## MODIFIED Requirements

### Requirement: Parallel writes are not lost
Agents that run at the same time SHALL write shared list and dict keys to their own partition. A merge step after each join SHALL fold the partitions back into the shared key and clear them. Readers and the gate SHALL see any unmerged partitions as already merged. This SHALL hold whether the parallel agents run in one process or in separate LDU replicas. Which agents write to partitions SHALL be fixed by configuration, not by which agents a process happens to build.

#### Scenario: Two screening agents append checks
- **WHEN** the sanctions and adverse media agents each record a check in parallel
- **THEN** after the merge, the shared checks list contains both records

#### Scenario: Parallel agents in separate processes
- **WHEN** the four narrative drafters run at the same time on different `narrative-agent` replicas, each saving its section
- **THEN** after the merge, all four sections are present, and no replica's session write overwrites another's

### Requirement: One background run per case
The system SHALL run at most one workflow per case at a time, outside the web process, and the run SHALL survive a restart of the web process. It SHALL audit run_started, run_finished and run_failed, with the error and the failing step. Status SHALL be one of running, waiting, not started, finished, failed or interrupted. A waiting status SHALL name the LDU the run is waiting for. A run whose orchestrator stops sending heartbeats for longer than the configured timeout SHALL show as interrupted.

#### Scenario: Concurrent start refused
- **WHEN** a run is started for a case that already has a run in progress, through any web replica
- **THEN** the request is refused with HTTP 409

#### Scenario: Web process restart mid-run
- **WHEN** the web process restarts during a preparation run
- **THEN** the run carries on, and the case status shows "running" once the web process is back

#### Scenario: Orchestrator crash mid-run
- **WHEN** the orchestrator process stops during a preparation run and does not come back within the heartbeat timeout
- **THEN** the case status shows "interrupted", and work up to the last completed agent is kept
