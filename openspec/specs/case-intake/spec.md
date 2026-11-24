# case-intake Specification

## Purpose

Turns an incoming dealer credit request into a registered case with a unique ID, an accountable owner and the checklist of information and checks its case types require.

## Requirements

### Requirement: Case registration with validated header
The system SHALL register a case only when the dealer name, registered number, at least one known case type, a known origination source and an accountable owner are supplied. One session SHALL hold at most one case.

#### Scenario: Valid request registers a case
- **WHEN** a request names a dealer, its registered number, the case type "increased borrowing request", the source "OEM partner" and an owner
- **THEN** a case is created and the dealer name, registered number, case types, source, owner and received time are stored on the case

#### Scenario: Unknown source is refused
- **WHEN** the origination source is not one of: OEM partner, field distribution team, dealer contact, bank referral or existing relationship
- **THEN** registration fails with "origination source missing/invalid" and no case is created

#### Scenario: Unknown case type is refused
- **WHEN** a case type outside the seven DT-1 case types is supplied, or none is supplied
- **THEN** registration fails and names the unknown types

#### Scenario: Second registration in the same session is refused
- **WHEN** a session that already holds a case tries to register another
- **THEN** registration fails and names the existing case ID

### Requirement: Unique sequential case IDs
Each case SHALL receive a unique ID in the form `CASE-YYYYMMDD-NNNNNN`, where the date is the received date and NNNNNN is a database sequence number.

#### Scenario: Concurrent registrations get distinct IDs
- **WHEN** two cases are registered on the same day
- **THEN** they receive different IDs that share the date part

### Requirement: DT-1 requirement checklist
The system SHALL build the case checklist from the DT-1 table by taking the union across all of the case's types. Each activity (entity, parties, checks, cra, media, financial, security, request) SHALL be marked R (required), C (conditional, delta only) or N/A. Where types disagree, the stricter marker wins.

#### Scenario: Stricter marker wins across types
- **WHEN** a case has types "director or shareholder change" (security N/A) and "increased borrowing request" (security R)
- **THEN** the checklist marks security as R

#### Scenario: Checklist needs a registered case
- **WHEN** the checklist is requested before the case is registered
- **THEN** the request fails with "register the case first"

### Requirement: Related-case lookup
The system SHALL list earlier cases for the same dealer, matched by registered number or by exact name ignoring case, excluding the current case. If the policy recency window is set, only cases received inside it SHALL be listed. If it is unset, all earlier cases SHALL be listed and the window reported as NOT CONFIGURED.

#### Scenario: Recency window unset
- **WHEN** the dealer has two earlier cases and `recency_window_days` is null
- **THEN** both cases are listed with owner, received time and types, and the window is reported as NOT CONFIGURED
