# Spec Delta

## Purpose

Gives signed-in people a web workbench to open cases, watch agents work, see what is waiting on their role, and act at human gates. The UI shows only what the server allows and enforces no rules itself.

## ADDED Requirements

### Requirement: Sign-in gate
Anyone who is not signed in SHALL be sent to the login page, and the page they asked for SHALL be kept as the return target. After signing in, they SHALL reach the case list or their return target.

#### Scenario: Deep link while signed out
- **WHEN** a signed-out user opens /cases/wb-123/checks
- **THEN** they see the login page, and after signing in they land on that case's Checks tab

### Requirement: Case list and queue
The Cases screen SHALL list every case with its ID, dealer, owner, stage, gate status, run state and what it is waiting on. It SHALL have a text search and a stage filter. The My queue screen SHALL list the items waiting on the user's roles across all cases, each linking to the right case tab.

#### Scenario: Queue for an analyst
- **WHEN** a financial crime analyst opens My queue and a case has an open hit
- **THEN** the item "Disposition ... for party / check" links to that case's Checks tab

### Requirement: New case with documents
The New case screen SHALL take request text and documents by drag-and-drop or by file picker: PDF, Word, Excel, CSV, text or email, up to 20 MB each. The user SHALL be able to start preparation immediately. The server SHALL refuse a case with no request text. Where sample cases exist, the user SHALL be able to open one, which starts preparation.

#### Scenario: Oversized file
- **WHEN** a 25 MB file is added
- **THEN** it is rejected with "larger than 20 MB"

### Requirement: Case page with live progress
The case page SHALL show:
- the case header: ID, dealer, owner, case types, gate status, run state, submission and outcome
- the run buttons the user is allowed to use
- a seven-stage preparation progress stepper
- banners for a failed or interrupted run
- ten tabs: Gate, Evidence, Checks, Analysis, Narrative, Request, Submission, Credit, Handoffs and Audit

The tab SHALL be part of the URL.

#### Scenario: Run button hidden without permission
- **WHEN** a pricing authority opens a case
- **THEN** no "Run preparation" button is shown

#### Scenario: Interrupted run banner
- **WHEN** the case status is "interrupted"
- **THEN** a warning says the run was interrupted and work up to the last completed agent is saved

### Requirement: Live updates
The case page SHALL subscribe to the case's server-sent event stream. Each change event SHALL refresh the case, the audit trail, the case list and the queue. While a run is in progress, the case SHALL also refresh every 3 seconds.

#### Scenario: Another user acts
- **WHEN** another user dispositions a hit on a case this user has open
- **THEN** the page updates without a manual reload

### Requirement: Approval dialogs show evidence first
Each human-gate action SHALL open a dialog that shows the evidence the approver must see, followed by the required fields. Confirm SHALL stay disabled until the required fields are filled in. Server refusals SHALL be shown as error messages with the server's reason.

#### Scenario: Server refusal shown
- **WHEN** the server refuses an approval because the evidence changed
- **THEN** the user sees an error message with that reason, and the data refreshes

### Requirement: Theme
The UI SHALL follow the system light or dark setting by default, and the user SHALL be able to switch it from the top bar.

#### Scenario: Toggle theme
- **WHEN** the user clicks the theme button in dark mode
- **THEN** the UI switches to light mode
