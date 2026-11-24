# financial-analysis Specification

## Purpose

Produces the pack's financial measures with deterministic, reproducible calculations, CALC-001 to CALC-014, from recorded figures only. Each measure carries flags for edge cases and data-quality issues. No model ever performs the arithmetic.

## Requirements

### Requirement: Deterministic decimal calculations
Every measure SHALL be calculated with exact decimal arithmetic from the recorded inputs. Each result SHALL carry its CALC ID, a numeric value or a "not calculable"/"not meaningful" label, a display string and flags. The same inputs SHALL always give the same result.

#### Scenario: Gearing
- **WHEN** total borrowings are 2,900,000 and net worth is 2,000,000
- **THEN** CALC-001 gearing is 1.45, displayed as "1.45x"

#### Scenario: Zero denominator
- **WHEN** current liabilities are 0
- **THEN** CALC-002 current ratio has no value and is labelled "not calculable"

#### Scenario: Non-positive net worth
- **WHEN** net worth is 0 or negative
- **THEN** gearing is labelled "not meaningful - net worth not positive"

### Requirement: Statement measure set
From the latest statement, the system SHALL calculate gearing, current ratio, interest cover, net margin, the cashflow reconciliation and stock days. With two or more periods, it SHALL also calculate year-on-year change in turnover and net profit, flagging periods that are not 12 months apart. ROTE SHALL be calculated only if policy requires it.

#### Scenario: One period only
- **WHEN** only one statement period is recorded
- **THEN** no year-on-year measures are produced, and a quality flag says the trend is not available

#### Scenario: Missing inputs reported
- **WHEN** EBIT is absent from the latest statement
- **THEN** interest cover is not calculated and is listed under missing inputs

### Requirement: Facility and security measures
The system SHALL calculate utilisation and headroom for the requested facility line, or across all lines if none matches. It SHALL calculate security cover against the requested amount.

#### Scenario: Requested line used
- **WHEN** the lending request is for the wholesale line and wholesale and retail facilities are recorded
- **THEN** utilisation and headroom use only the wholesale facility

### Requirement: Edge-case flags
Measures SHALL raise these flags:
- "negative EBIT" on interest cover
- "loss" on net margin
- "limit breach" when drawn exceeds the limit
- "valuation basis and date not recorded" on security cover when either is missing
- "haircut rules NOT CONFIGURED" on security cover
- cashflow differences beyond the policy tolerance; with the tolerance unset, any difference

#### Scenario: Limit breach
- **WHEN** drawn is 5,500,000 against a limit of 5,000,000
- **THEN** utilisation is 110% with a "limit breach" flag

#### Scenario: Cashflow tolerance unset
- **WHEN** the reported closing cash differs from the calculated closing by 1 and the tolerance is null
- **THEN** the reconciliation is flagged as not reconciled, with "tolerance NOT CONFIGURED"

### Requirement: Data-quality flags
The system SHALL report these data-quality flags, each with a corrective action:
- no statements recorded
- unaudited statements
- a missing period between statements
- only one period recorded
- cashflow that does not reconcile

#### Scenario: Unaudited accounts
- **WHEN** the latest statement is marked unaudited
- **THEN** a flag asks the owner to accept it or obtain audited accounts

### Requirement: Date and effort calculations
CALC-012 SHALL add the review cadence in calendar months to the last review date, without overflowing the end of a month. Cadence SHALL be limited to 1, 3, 6 or 12 months. CALC-014 SHALL give an item's age in days and whether it is stale against its validity period, and an undated item SHALL be treated as stale.

#### Scenario: Month-end safe
- **WHEN** the last review was 2026-01-31 with a 1-month cadence
- **THEN** the next review date is 2026-02-28

#### Scenario: Cadence unset
- **WHEN** no cadence is supplied
- **THEN** CALC-012 returns "cadence NOT CONFIGURED"

### Requirement: Facilities and security recorded with source
Each facility SHALL record its lending line, drawn amount, limit, as-at date and source. Security SHALL record its description, value, valuation basis and valuation date.

#### Scenario: Borrowing profile
- **WHEN** two facilities are recorded
- **THEN** the borrowing profile lists both, each with its utilisation display
