# policy-parameters Specification

## Purpose

Keeps every regulated or policy-set threshold, period and criterion outside the code, as a versioned parameter owned by the policy owner. Unset values are reported as NOT CONFIGURED and are never replaced by a guessed default.

## Requirements

### Requirement: Governed policy file
Policy SHALL be read from `policy.yaml`, or from the file named by `CPA_POLICY_FILE`. It SHALL hold:
- a version and an owner
- DT-5 validity days for each information class
- the DT-4 review cadence table
- the cashflow and ownership tolerances
- the related-case recency window
- the escalation criteria and FCA regulatory scope

#### Scenario: Alternate policy file
- **WHEN** `CPA_POLICY_FILE` points to another YAML file
- **THEN** that file's values and version are used

### Requirement: Unset means NOT CONFIGURED
A missing or null parameter SHALL be NOT CONFIGURED. Every rule that needs it SHALL report it as a configuration gap or advisory. No rule SHALL substitute a default value.

#### Scenario: Validity unset
- **WHEN** `validity_days.sanctions_screening` is null and a sanctions result is assessed
- **THEN** staleness is reported as unknown, with "validity NOT CONFIGURED", rather than current or stale

#### Scenario: Recency window unset
- **WHEN** `recency_window_days` is null
- **THEN** related-case lookup lists all earlier cases and reports the window as NOT CONFIGURED

### Requirement: Policy version recorded on results
Gate results, check registers and staleness assessments SHALL record the policy version they were evaluated under.

#### Scenario: Version on gate result
- **WHEN** the gate is evaluated with policy version "0.1-unset"
- **THEN** the gate result's policy_version is "0.1-unset"

### Requirement: DT-1 table is a proposed baseline
The DT-1 checklist table SHALL be treated as a proposed baseline that still needs business confirmation (OQ-03). Checklist responses SHALL say that it is proposed.

#### Scenario: Checklist note
- **WHEN** a checklist is built
- **THEN** the response includes "DT-1 is PROPOSED, confirm per OQ-03"
