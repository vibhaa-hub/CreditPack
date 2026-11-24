# Spec Delta

## Purpose

Makes sure every party to a case receives the KYC, AML, sanctions, identity and adverse media checks its case types require, that check outcomes drive the DT-3 action, and that hits are cleared only by an authorised person.

## ADDED Requirements

### Requirement: Mandatory check register
The system SHALL derive the check register from the DT-1 checklist and the case's parties: the entity plus every director, shareholder and UBO. When checks are R or C, each party SHALL need KYC, AML and sanctions checks, plus IDV for individuals. When media is R or C, each party SHALL need adverse media. When cra is R or C, the relationship SHALL need a CRA.

#### Scenario: Individual director gets IDV
- **WHEN** checks are marked R and the case has an individual director
- **THEN** the register lists kyc, aml, sanctions and idv for that director

#### Scenario: Corporate shareholder has no IDV
- **WHEN** a shareholder is a company
- **THEN** the register lists kyc, aml and sanctions for it, but not idv

### Requirement: Check results need evidence
A check result SHALL record the party, check type, outcome, tool used, evidence reference, performer and date. A result without evidence SHALL be refused. A manual check SHALL also require a named performer. An FCA regulatory check SHALL be refused while its scope is NOT CONFIGURED.

#### Scenario: Missing evidence
- **WHEN** a sanctions result is recorded with no evidence reference
- **THEN** it is refused with "evidence required"

#### Scenario: FCA scope unset
- **WHEN** an fca_regulatory result is recorded and `fca_regulatory_scope` is null
- **THEN** it is refused as NOT CONFIGURED

### Requirement: DT-3 outcome handling
Each outcome SHALL map to a DT-3 action and case effect:
- clear completes the check
- potential_match opens a hit and holds submission
- confirmed_match opens a hit and halts the case
- unavailable needs a manual alternative with evidence
- expired needs re-performing
- idv_failed keeps the check open

#### Scenario: Potential match opens a hit
- **WHEN** a sanctions check returns potential_match
- **THEN** a hit is added to the open hits and the register line shows "hold"

#### Scenario: Confirmed match halts the case
- **WHEN** a check returns confirmed_match
- **THEN** the case is marked halted

### Requirement: Only humans clear hits
No agent SHALL be able to clear a hit. Agents SHALL only request a disposition. A financial crime analyst SHALL record each disposition, with a rationale, as an audited human decision.

#### Scenario: Agent requests disposition
- **WHEN** an agent calls the hit-disposition request for a party
- **THEN** a pending-human item is added and the hit stays open

#### Scenario: Analyst records a true match
- **WHEN** an analyst dispositions a hit as "true match" with a rationale
- **THEN** the hit stays open and the case is halted

### Requirement: Check expiry forces re-performance
For sanctions, IDV and adverse media, a completed check older than its policy validity period SHALL show "reperform" instead of "complete".

#### Scenario: Expired sanctions screen
- **WHEN** sanctions validity is set to 30 days and the last clear screen is 45 days old
- **THEN** the register line shows "reperform" with the DT-5 action "Re-screen"

### Requirement: CRA recorded by an assessor
The CRA line SHALL be complete only once an onboarding analyst or financial crime analyst has recorded a CRA outcome and its basis.

#### Scenario: CRA outstanding
- **WHEN** the checklist requires a CRA and none is recorded
- **THEN** the CRA line is "outstanding" with the reason "CRA outcome not recorded by the assessor"
