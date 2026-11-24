# Spec Delta

## Purpose

Decides deterministically whether a pack is complete enough to be authorised for submission. It applies DT-2 rules R1 to R8 and reports every gap at once, each with its corrective action, together with a completeness score.

## ADDED Requirements

### Requirement: Gate result and deciding rule
The gate SHALL return BLOCK, ADVISORY or PASS:
- BLOCK if any blocking gap exists or completeness is below 100%. The deciding rule SHALL be the earliest of R1 to R6 among the blocking gaps.
- Otherwise ADVISORY if any advisory exists, with deciding rule R7.
- Otherwise PASS, with deciding rule R8.

Submission SHALL be authorisable only on PASS or ADVISORY.

#### Scenario: Several blocking rules
- **WHEN** a case has an open hit (R3) and a missing lending request (R1)
- **THEN** the result is BLOCK, the deciding rule is R1, and both gaps are listed

#### Scenario: Advisories only
- **WHEN** all mandatory items are complete but the esg section is empty
- **THEN** the result is ADVISORY with deciding rule R7, and submission may be authorised

### Requirement: Every gap has a corrective action
Each gap and advisory SHALL carry its rule, its result (BLOCK or ADVISORY), a reason, and the corrective action a person must take.

#### Scenario: Missing pricing authorisation
- **WHEN** pricing has not been authorised
- **THEN** an R1 gap reads "pricing and terms authorisation missing", with the action "obtain authorisation from the pricing authority"

### Requirement: R1 mandatory items
R1 SHALL block when any of the following is true:
- the checklist is missing
- required information is missing
- a required narrative section is missing or empty
- the lending request or pricing authorisation is missing
- pricing was authorised by its own preparer
- a registry discrepancy is unresolved

#### Scenario: Pricing authorised by preparer
- **WHEN** the pricing authoriser is the same person as the lending request preparer
- **THEN** R1 blocks with "pricing authorised by its preparer"

### Requirement: R2 to R6 blocking rules
The gate SHALL block on:
- **R2:** a mandatory check that is outstanding, open or due for re-performance
- **R3:** an undispositioned hit, or a halted case
- **R4:** a section that is unreviewed, contains decision language, or is uncited agent text
- **R5:** a stated ratio that differs from the calculated measure, or an amount that matches no figure in the case
- **R6:** financial information or a registry record past its validity period

#### Scenario: Narrative figure mismatch
- **WHEN** a section states interest cover 4.0 and the calculated value is 3.2
- **THEN** R5 blocks, naming the section and both figures

#### Scenario: Stale statements
- **WHEN** financial statement validity is set to 455 days and the latest statement is 500 days old
- **THEN** R6 blocks with the action "Request updated statements"

### Requirement: Authorised exceptions
An exception authorised by a pricing authority, financial crime analyst or credit manager SHALL record a rule, an item and a reason. A matching R2 or R6 gap SHALL then become an advisory that references the exception, and SHALL count towards completeness.

#### Scenario: Stale item under exception
- **WHEN** an R6 exception is recorded for "financial dated 2024-03-31"
- **THEN** that item appears as an advisory "past validity under authorised exception" and no longer blocks

### Requirement: Unconfigured policy is advisory, not a guess
Where a validity period or the FCA scope is not configured, the gate SHALL raise an R7 advisory naming the missing parameter. It SHALL NOT assume any value.

#### Scenario: Validity unset
- **WHEN** `validity_days.financial_statements` is null
- **THEN** each dated financial item raises the advisory "cannot confirm ... is current: validity NOT CONFIGURED"

### Requirement: Completeness score and policy version
The gate SHALL report CALC-011 completeness, computed as complete mandatory items divided by applicable mandatory items, together with both counts. It SHALL also report the policy version and the as-at date it was evaluated under.

#### Scenario: Partial completeness
- **WHEN** 18 of 20 mandatory items are complete
- **THEN** completeness is 90.00% and the result is BLOCK
