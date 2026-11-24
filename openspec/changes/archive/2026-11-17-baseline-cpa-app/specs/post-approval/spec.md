# Spec Delta

## Purpose

Coordinates the work after Credit approves: handoffs that carry the approved terms unchanged, conditions satisfied with evidence, a closure check, and the next periodic review date.

## ADDED Requirements

### Requirement: Handoffs only after approval
Handoffs SHALL be created only when the Credit outcome is "approved" or "approved with conditions". Five handoffs SHALL be created:
- legal documentation
- direct debit mandate
- operational set-up
- funding system configuration
- supplier activity

Each SHALL carry the approved facility type, amount, terms and pricing. Creating handoffs again SHALL return the existing set.

#### Scenario: Declined case
- **WHEN** post-approval runs on a case whose outcome is "declined"
- **THEN** no handoffs are created, and the result is "no approval recorded by Credit"

#### Scenario: Idempotent
- **WHEN** handoffs already exist and are requested again
- **THEN** the existing handoffs are returned unchanged

### Requirement: Handoff and condition updates by operations
Only operations SHALL update handoffs:
- A handoff status SHALL be one of open, in progress, complete or closed.
- Closing without completion SHALL require a reason.
- A condition SHALL be marked satisfied only with evidence.

#### Scenario: Close without reason
- **WHEN** operations sets a handoff to "closed" with no reason
- **THEN** the update is refused

#### Scenario: Condition without evidence
- **WHEN** operations marks a condition satisfied with empty evidence
- **THEN** the update is refused, citing BR-P08

### Requirement: Closure eligibility
A case SHALL be eligible to close only when all of the following hold:
- handoffs exist
- every handoff is complete, or closed with a reason
- every condition is satisfied with evidence
- every handoff's terms equal the approved terms

Otherwise each blocker SHALL be listed.

#### Scenario: Terms drift
- **WHEN** a handoff's carried terms differ from the approved terms
- **THEN** closure is BLOCKED, with "terms mismatch" for that handoff

### Requirement: Next review date
The next review date SHALL be calculated with CALC-012 from the last review date and a cadence of 1, 3, 6 or 12 months. The cadence comes from the DT-4 policy table or from the person instructing, and SHALL NOT be guessed.

#### Scenario: Invalid cadence
- **WHEN** a cadence of 2 months is supplied
- **THEN** it is refused with "cadence must be 1, 3, 6 or 12 months"
