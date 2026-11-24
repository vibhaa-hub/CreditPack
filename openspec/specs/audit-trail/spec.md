# audit-trail Specification

## Purpose

Keeps a complete, tamper-evident record of everything agents and people do on a case, plus state snapshots after each agent step. Any case can then be replayed, verified and, if needed, restored to an earlier state without rewriting history.

## Requirements

### Requirement: Every action is audited
The system SHALL append an audit event for:
- every tool call and tool result
- every completed agent
- every deterministic workflow step
- every run start, finish and failure
- every human decision
- every sign-in, sign-out, access refusal and Credit query

Each event SHALL record the session, the case ID once known, a sequence number, time, actor type, actor, action, tool, arguments, result status and detail.

#### Scenario: Tool call audited
- **WHEN** an agent calls a tool
- **THEN** a tool_called event and a tool_result event, naming the agent and the tool, are appended

### Requirement: Hash-chained events
Each session's events SHALL be numbered from 1. Each event SHALL store the previous event's hash, and its own SHA-256 hash over the previous hash and its canonical content, starting from a genesis hash of 64 zeros. Appends within a session SHALL be serialised.

#### Scenario: Chain verifies
- **WHEN** a session's chain is verified and no event has changed
- **THEN** the result is ok, with the event count

#### Scenario: Tampered event detected
- **WHEN** a stored event's content no longer matches its hash
- **THEN** verification fails and reports the first broken sequence number

### Requirement: Append-only tables
The database SHALL reject UPDATE and DELETE on audit events, pack versions, section versions and state snapshots, and TRUNCATE as well on Postgres. On Postgres, the application role SHALL have only INSERT and SELECT on these tables.

#### Scenario: Delete attempt
- **WHEN** a DELETE is issued against audit_events
- **THEN** the database rejects it

### Requirement: State snapshot after each agent
After each agent completes, the system SHALL store a snapshot of the case state, excluding internal and temporary keys, and SHALL reference it from the agent_complete event.

#### Scenario: Snapshot linked
- **WHEN** the intake agent completes
- **THEN** a snapshot is stored, and the agent_complete event's detail contains its snapshot ID

### Requirement: Replay
A command-line replay SHALL print every audit event for a case ID or session ID in order, followed by whether each hash chain is intact. It SHALL exit with code 1 if any chain is broken. A JSON output option SHALL be available.

#### Scenario: Replay by case ID
- **WHEN** replay is run with "CASE-20261114-000001"
- **THEN** events from before and after the case ID existed are printed in order, with the chain status

### Requirement: Rollback is an audited decision
Restoring a case to a stored snapshot SHALL be recorded as a human decision. It SHALL set the state to the snapshot, clear keys added afterwards, and SHALL NOT delete or alter any earlier event.

#### Scenario: Rollback keeps history
- **WHEN** a case is rolled back to snapshot 5
- **THEN** a human_decision event labelled "rollback to snapshot 5" is appended, and all earlier events remain

### Requirement: Database selection
One database URL SHALL drive both the case store and the agent sessions. Postgres SHALL be supported, along with SQLite, which is the default when no URL is set. Any other backend SHALL be refused.

#### Scenario: Unsupported backend
- **WHEN** `DATABASE_URL` is a MySQL URL
- **THEN** startup fails with "unsupported database backend"
