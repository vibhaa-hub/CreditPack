# Spec Delta

## Purpose

Drafts the pack's narrative sections from evidence, checks them for unsupported claims, wrong figures and decision language, and keeps every version. Nothing reaches Credit until the case owner accepts it.

## ADDED Requirements

### Requirement: Draft sections are labelled and unreviewed
The system SHALL accept drafts only for the sections business_background, management_assessment, conduct_performance, security_review and esg. Each draft SHALL be stored as a "non-human draft", marked unreviewed, with its cited evidence references and the drafting agent. Empty text SHALL be refused.

#### Scenario: Draft saved
- **WHEN** an agent saves business_background with two evidence references
- **THEN** the section is stored as an unreviewed non-human draft with a new version number

#### Scenario: Unknown section
- **WHEN** a draft is saved for the section "pricing_opinion"
- **THEN** it is refused, and the response lists the allowed sections

### Requirement: Decision language is never allowed
Text that states or implies a credit decision, a recommendation, or a prediction or probability of approval SHALL be refused, both when an agent saves a draft and when a human amends a section. Examples: "recommend approval", "will be approved", "likely to be granted", "we approve".

#### Scenario: Agent draft with a recommendation
- **WHEN** a draft contains "We recommend approval of the increase"
- **THEN** it is refused, and the response quotes the matched words

#### Scenario: Human amendment with a prediction
- **WHEN** the case owner amends a section to say "approval is highly likely"
- **THEN** the amendment is refused, citing BR-D12

### Requirement: Uncited drafted text is flagged
A drafted section with no evidence references SHALL be saved with a warning. It SHALL fail the gate until evidence is cited or a named human authors it.

#### Scenario: No citations
- **WHEN** a draft is saved with an empty evidence list
- **THEN** the response warns that it will fail validation

### Requirement: Critic review
A critic pass SHALL report, for every section:
- decision language
- missing citations
- ratios that differ from the calculated measures
- amounts that match no figure in the case

It SHALL list any core sections that are missing. The critic SHALL only report findings and SHALL NOT change any section.

#### Scenario: Figure mismatch found
- **WHEN** a section says "gearing 1.2x" and the calculated gearing is 1.45
- **THEN** the critic reports the mismatch and the required change "use 1.45"

### Requirement: Owner review of sections
Only a case owner (account manager or wholesale manager) SHALL be able to accept, amend or reject a section:
- Accepting SHALL mark the section reviewed.
- Amending SHALL replace the text, label it "human" and mark it reviewed.
- Rejecting SHALL remove the section and record the rejected text.

Each action SHALL be an audited human decision.

#### Scenario: Reject
- **WHEN** the owner rejects management_assessment
- **THEN** the section is removed, its text is kept in rejected_sections, and it must be drafted again

### Requirement: Section version history
Every draft, amendment and acceptance SHALL create a new, unchangeable version of the section in the store. A diff between any two versions SHALL be available.

#### Scenario: Amendment creates a version
- **WHEN** the owner amends a section that is at version 1
- **THEN** version 2 is stored with the human text, and the diff shows the change
