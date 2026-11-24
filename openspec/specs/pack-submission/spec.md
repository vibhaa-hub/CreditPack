# pack-submission Specification

## Purpose

Takes a complete pack from the lending request to Credit. Pricing and submission are authorised by named people, each submission creates an immutable pack version, Credit queries are handled, and the Credit outcome is recorded. Credit stays independent of preparation.

## Requirements

### Requirement: Lending request as proposed
The lending request SHALL record the facility type, amount, purpose, current limit, change requested, terms and pricing exactly as the preparer proposed them. Missing terms or pricing SHALL be recorded as "not supplied" and SHALL NOT be invented. Recording a new request SHALL withdraw any earlier pricing authorisation.

#### Scenario: Re-recorded request withdraws pricing
- **WHEN** pricing has been authorised and the lending request is recorded again
- **THEN** the pricing authorisation is cleared, and the response says to request it again

### Requirement: Pricing authorisation by a different person
Only a pricing authority SHALL authorise pricing and terms, and never the lending request's preparer. The authorisation SHALL record who authorised it, the values authorised and the date.

#### Scenario: Preparer refused
- **WHEN** the preparer, who also holds the pricing authority role, tries to authorise
- **THEN** the action is refused with "the preparer cannot authorise their own pricing and terms", and the refusal is audited

### Requirement: Submission authorised by the case owner
Only the accountable case owner SHALL authorise submission, and only when the gate allows it.

#### Scenario: Gate blocked
- **WHEN** the owner tries to authorise while the gate is BLOCK
- **THEN** the action is refused, and the first gaps are listed

#### Scenario: Not the owner
- **WHEN** a different account manager tries to authorise submission
- **THEN** the action is refused with "only the accountable owner ... may authorise submission"

### Requirement: Transmission re-checks the gate
The transmit step SHALL re-evaluate the gate itself and SHALL refuse unless the gate allows submission and the case owner has authorised. On success it SHALL create the next pack version and a submission record. Because no Credit interface exists yet, the receipt SHALL be marked NOT-TRANSMITTED.

#### Scenario: Successful submission
- **WHEN** the gate passes and the owner has authorised
- **THEN** pack version N+1 is stored with its SHA-256, a submission is recorded, and the case shows submitted with that version and receipt

### Requirement: Immutable pack versions
Pack versions SHALL be numbered from 1 per case and fingerprinted with SHA-256 of their canonical content. Once written, they SHALL NOT be updatable or deletable.

#### Scenario: Update attempt rejected
- **WHEN** an UPDATE is issued against a stored pack version
- **THEN** the database rejects it

### Requirement: Credit cannot edit the pack
A user holding the credit_underwriter role SHALL be refused every action that changes pack content, even if they also hold a preparer role.

#### Scenario: Underwriter uploads a document
- **WHEN** a user with credit_underwriter and account_manager roles uploads a document
- **THEN** the action is refused with "Credit cannot prepare or edit the pack"

### Requirement: Credit queries and outcome
Once a pack is submitted:
- A credit underwriter SHALL be able to raise queries.
- The case owner SHALL resolve each query. If the response changes the pack, the resolution SHALL create a new pack version linked to the query.
- A resolved query SHALL NOT be resolved again.
- The underwriter SHALL record the outcome (approved, approved with conditions, declined or referred), with any conditions.

#### Scenario: Pack-changing resolution
- **WHEN** the owner resolves a query and marks the pack as changed
- **THEN** a new pack version is created with the reason "response to credit query N"

#### Scenario: Outcome before submission
- **WHEN** an outcome is recorded on a case that has not been submitted
- **THEN** it is refused with "the pack has not been submitted"
