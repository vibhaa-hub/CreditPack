# human-decisions Specification

## Purpose

Makes sure that every decision at a human gate is taken by a signed-in, named person with the right role, after seeing the current evidence, and that it is written to the audit trail before it changes the case.

## Requirements

### Requirement: Signed-in users
Users SHALL be created from the command line with a username, display name, one or more roles and a password of at least 10 characters. Passwords SHALL be stored as salted scrypt hashes. Sign-in SHALL set a signed, HTTP-only cookie that expires after 8 hours. Disabled users SHALL NOT sign in.

#### Scenario: Wrong password
- **WHEN** a sign-in uses the wrong password
- **THEN** it returns 401, and an access_denied event is audited

#### Scenario: Expired cookie
- **WHEN** a request carries a cookie older than 8 hours
- **THEN** the user is treated as not signed in

### Requirement: Role permissions per action
The server SHALL check every action against the roles allowed for it, for example:
- disposition_hit: financial crime analyst only
- authorise_pricing: pricing authority only
- update_handoff: operations only

A refusal SHALL return the reason and a corrective action, and SHALL be audited as access_denied.

#### Scenario: Wrong role
- **WHEN** an account manager tries to disposition a hit
- **THEN** the server returns 403 with "disposition hit needs the role: Financial Crime Analyst", and audits the refusal

### Requirement: Separation of duties
The server SHALL enforce three separations:
- Pricing SHALL NOT be authorised by its preparer.
- Submission SHALL be authorised only by the case owner.
- Credit underwriters SHALL NOT perform any action that changes the pack.

Names SHALL be compared ignoring case and any role suffix in brackets.

#### Scenario: Owner name with role suffix
- **WHEN** the case owner is recorded as "Jane Smith (Account Manager)" and Jane Smith authorises submission
- **THEN** she is recognised as the owner

### Requirement: Approval prerequisites must be current
For hit disposition, discrepancy resolution, section review, pricing authorisation and submission authorisation, the client SHALL send the fingerprint of the evidence it showed. If that fingerprint differs from one computed from the current state, the server SHALL refuse the action and audit a process_failure.

#### Scenario: Evidence changed while the dialog was open
- **WHEN** an agent updates the lending request after the pricing dialog opened, and the authority then confirms
- **THEN** the approval is refused with "the information shown has changed since you opened it", and a process_failure is audited

### Requirement: Audit before apply
Each human decision SHALL first be appended to the audit trail as human_decision, with the actor, the state change and a label. Only then SHALL it be applied to the case state. A section changed by the decision SHALL create a new section version.

#### Scenario: Decision recorded
- **WHEN** an analyst dispositions a hit as "false positive" with a rationale
- **THEN** a human_decision event naming the analyst and role is in the audit trail, and the hit has moved from open hits to dispositions

### Requirement: No action during an agent run
Human actions on a case SHALL be refused while an agent run for that case is in progress.

#### Scenario: Act while running
- **WHEN** a user submits an action while preparation is running
- **THEN** the server returns 409 with "An agent run is in progress"

### Requirement: Required fields per decision
Each decision SHALL require its own fields:
- a rationale for a disposition
- the outcome and basis for a CRA
- party, check, result, evidence and tool for a manual check
- a resolution for a discrepancy or query
- rule, item and reason for an exception
- evidence for a condition

#### Scenario: Exception without reason
- **WHEN** an exception is submitted without a reason
- **THEN** it is refused with "rule, item and reason are required"
