# Credit Pack Assessment — agent prototype

A Google ADK agent mesh that prepares dealer credit packs, with named people acting at the human
gates through a web workbench. Requirements: `../Credit_Pack_Assessment_BA_Pack_v1.0.md` and
`../Arch.md`. Full technical architecture, including every agent and tool: see
[ARCHITECTURE.md](ARCHITECTURE.md).

**Contents**
1. [Pick how to run it](#1-pick-how-to-run-it)
2. [First-time setup: common](#2-first-time-setup-common)
3. [First-time setup: single process](#3-first-time-setup-single-process-startps1)
4. [First-time setup: Docker stack](#4-first-time-setup-docker-stack-one-container-per-ldu)
5. [Every time](#5-every-time)
6. [Run a demo case](#6-run-a-demo-case)
7. [Check, troubleshoot, reset](#7-check-troubleshoot-reset)
8. [Other commands](#8-other-commands)
9. [Configuration reference](#9-configuration-reference)
10. [How it works](#10-how-it-works)

All commands are PowerShell, run from this folder (`cpa_app/`) unless a step says otherwise.

## 1. Pick how to run it

There are two ways to run the app. They use separate databases and ports, so you can run both
at once.

| | Single process (`start.ps1`) | Docker stack (`docker compose`) |
|---|---|---|
| What runs | One Python process on your machine with every agent inside it, plus Postgres in one Docker container (or a SQLite file) | 17 containers: Postgres, an S3 object store, a one-off `init`, and one container per LDU (the workbench, orchestrator, document extraction, external adapters and the 9 agent units) |
| Open | http://127.0.0.1:8000 | http://127.0.0.1:8001 |
| Database | `cpa-postgres` container (or SQLite) | its own Postgres inside the stack |
| Uploaded files | `cpa_agents/.adk/uploads/` | the stack's S3 object store |
| OCR of scanned files | only if you install Tesseract (section 9) | included in the image |
| Use it for | day-to-day development and demos | checking the deployable units, scaling, failure handling |

You need **Python 3.11+**, **Node.js 18+** and **Docker Desktop**. The Docker stack alone needs
only Docker Desktop, but you still want the Python setup to run tests and manage users locally.

## 2. First-time setup: common

Do these once, whichever way you run it.

**2.1 Python environment.** From the outer project folder (the one that contains `cpa_app/`):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
cd cpa_app
pip install -r requirements.txt
```
`start.ps1` expects the venv at `..\venv`, exactly as created here.

**2.2 Configuration.** Back in `cpa_app/`:
```powershell
Copy-Item .env.example .env
```
Open `.env` and set a model and its key, for example Mistral:
```
MISTRAL_API_KEY=<your Mistral key>
CPA_MODEL=mistral/mistral-large-latest
```
or Gemini: `GOOGLE_API_KEY=<key>` and `CPA_MODEL=gemini-2.5-flash`. Both ways of running read
the model settings from this file. `start.ps1` adds `CPA_WORKBENCH_SECRET` (which keeps sign-ins
valid across restarts) the first time it runs.

## 3. First-time setup: single process (`start.ps1`)

**3.1 Choose the database.**

- **SQLite (simplest):** leave `DATABASE_URL` out of `.env`. Nothing else to do: go to 3.2.
- **Postgres (closer to production):** pick an `<admin-password>` and an `<app-password>`, then:
  ```powershell
  # 1. create the Postgres container (kept for later runs) and a test database
  docker run -d --name cpa-postgres -e POSTGRES_PASSWORD=<admin-password> -e POSTGRES_DB=cpa `
    -p 127.0.0.1:5432:5432 -v cpa-pgdata:/var/lib/postgresql/data postgres:16
  docker exec cpa-postgres psql -U postgres -c "CREATE DATABASE cpa_test"

  # 2. create every table as the admin user
  $env:DATABASE_URL = "postgresql://postgres:<admin-password>@127.0.0.1:5432/cpa"
  ..\venv\Scripts\python -m cpa_agents.ldu init
  Remove-Item Env:DATABASE_URL

  # 3. create the restricted app user (it can add rows but never edit or delete the audit trail)
  docker cp cpa_agents/store/sql/postgres_roles.sql cpa-postgres:/tmp/postgres_roles.sql
  docker exec cpa-postgres psql -U postgres -d cpa -v ON_ERROR_STOP=1 `
    -v app_password="'<app-password>'" -f /tmp/postgres_roles.sql
  ```
  Then add the app user to `.env`:
  ```
  DATABASE_URL=postgresql://cpa_app:<app-password>@127.0.0.1:5432/cpa
  ```
  If `docker` is not found, open a new terminal or add
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin` to PATH.

**3.2 Users.** Create one sign-in per person; each command asks for a password (10+ characters).
Repeat `--role` to give someone several roles.
```powershell
..\venv\Scripts\python -m workbench.users add jsmith      --name "Jane Smith"        --role account_manager
..\venv\Scripts\python -m workbench.users add analyst     --name "FC Analyst"        --role financial_crime_analyst
..\venv\Scripts\python -m workbench.users add onboarding  --name "Onboarding Analyst" --role onboarding_analyst
..\venv\Scripts\python -m workbench.users add pricing     --name "Pricing Authority" --role pricing_authority
..\venv\Scripts\python -m workbench.users add underwriter --name "Credit Underwriter" --role credit_underwriter
..\venv\Scripts\python -m workbench.users add ops         --name "Operations"        --role operations
..\venv\Scripts\python -m workbench.users add auditor     --name "Auditor"           --role auditor
..\venv\Scripts\python -m workbench.users list
```
If you skip this, `start.ps1` asks for a first Account Manager when it starts. `demo_user.txt`
lists the demo accounts already created on this machine (local use only).

**3.3 First start.** Run `.\start.ps1` (section 5.1). The first time, it also installs the UI
packages and builds the UI, which takes a few minutes.

## 4. First-time setup: Docker stack (one container per LDU)

**4.1 Build and start.** Start Docker Desktop, then:
```powershell
docker compose up -d --build
docker compose ps            # wait until every service shows "healthy"; init shows "exited (0)"
```
The first build takes several minutes. `init` creates the tables and the upload bucket, then
exits; the other services start after it.

**4.2 Users.** The stack has its own database, so it starts with no users. Either:

- **create them** inside the stack (each asks for a password):
  ```powershell
  docker compose exec workbench-api python -m workbench.users add jsmith --name "Jane Smith" --role account_manager
  docker compose exec workbench-api python -m workbench.users list
  ```
- **or copy the users** (with their passwords) from the single-process `cpa-postgres` database:
  ```powershell
  docker exec cpa-postgres psql -U postgres -d cpa -c "\copy users TO '/tmp/users.csv' CSV"
  docker cp cpa-postgres:/tmp/users.csv users.csv
  docker cp users.csv cpa-ldu-postgres-1:/tmp/users.csv
  docker exec cpa-ldu-postgres-1 psql -U postgres -d cpa -c "\copy users FROM '/tmp/users.csv' CSV"
  Remove-Item users.csv
  ```
  This fails with "duplicate key" if a user with the same name already exists in the stack.

Then open http://127.0.0.1:8001 and sign in.

## 5. Every time

### 5.1 Single process

```powershell
.\start.ps1
```
Open **http://127.0.0.1:8000**. You don't need to activate the venv. In order, the script:
1. checks the Python packages (installs them if missing);
2. stops if something already listens on the port;
3. checks `.env` has the model key and adds the session secret if missing;
4. if `.env` points at Postgres: starts Docker Desktop and the `cpa-postgres` container and waits
   until it is ready;
5. rebuilds the UI if its source changed;
6. offers to create the first user if there is none;
7. starts the workbench with every agent inside it.

Options: `.\start.ps1 -Port 8080`, `.\start.ps1 -Model gemini-2.5-flash`. If PowerShell blocks
the script: `powershell -ExecutionPolicy Bypass -File .\start.ps1`.

**Stop:** `Ctrl+C` in that terminal. Optionally `docker stop cpa-postgres`. Cases are kept, and
the next `.\start.ps1` picks up where you left off.

### 5.2 Docker stack

```powershell
docker compose up -d           # start (no rebuild)
docker compose up -d --build   # start after you changed code or requirements.txt
docker compose ps              # all healthy?
```
Open **http://127.0.0.1:8001**.

```powershell
docker compose logs -f financial-agent                 # follow one unit's log
docker compose up -d --scale narrative-agent=2         # run two replicas of a unit
docker compose stop                                    # stop, keep everything
docker compose down                                    # remove the containers, keep data
docker compose down -v                                 # remove containers AND the stack's database and files
```

## 6. Run a demo case

1. Sign in as a case owner (for example `jsmith`, Account Manager).
2. **New case** lists two fictional sample cases. **Open** one, and preparation starts on its own:
   - **01 Acme Motors, increased borrowing:** clean figures, including iXBRL accounts that match
     the spreadsheets.
   - **02 Brightway Cars, new dealer:** FY2025 management accounts disagree with the audited
     accounts, so the Analysis tab shows two blocking differences.

   To make your own case, use **New case**, paste the request text and drop documents from
   `samples/` (or your own files).
3. Watch the stepper in the case header. When the run stops, the **Gate** tab lists what blocks
   submission and who must act.
4. Sign in as each role and act on its tab: the financial crime analyst dispositions hits (Checks),
   the owner explains differences (Analysis) and accepts narrative (Narrative), the pricing
   authority authorises pricing (Request), then the owner authorises and runs submission.
5. The **Audit** tab shows every tool call, result and human decision in order.

## 7. Check, troubleshoot, reset

| Problem | Fix |
|---|---|
| "Port 8000 already in use" | The workbench is already running in another terminal; use it, stop it, or `.\start.ps1 -Port 8080`. |
| "Container cpa-postgres not found" | Do section 3.1 (Postgres), or remove `DATABASE_URL` from `.env` to use SQLite. |
| "permission denied" on `runs` at startup | The database was created before the LDU change. Once: set `$env:DATABASE_URL` to the admin URL, run `..\venv\Scripts\python -m cpa_agents.ldu init`, then `docker cp cpa_agents/store/sql/upgrade_ldu_tables.sql cpa-postgres:/tmp/` and `docker exec cpa-postgres psql -U postgres -d cpa -v ON_ERROR_STOP=1 -f /tmp/upgrade_ldu_tables.sql`, then `Remove-Item Env:DATABASE_URL`. |
| Docker build fails on `apt-get` (Tesseract) | The image fetches Debian packages over HTTPS; if your network blocks that too, build without OCR: `docker compose build --build-arg OCR=0`. |
| A Docker service is not healthy | `docker compose logs <service>`; `docker compose ps` names it. |
| A run shows "waiting for <unit>" | That unit has no live worker: `docker compose up -d <unit>`. |

```powershell
docker ps -a --filter name=cpa-postgres               # is the single-process database up?
docker logs cpa-postgres --tail 50
Get-NetTCPConnection -LocalPort 8000 -State Listen    # is start.ps1's workbench running?
```

**Start over** (deletes all cases):
- single process with Postgres: `docker rm -f cpa-postgres; docker volume rm cpa-pgdata`, then redo 3.1;
- single process with SQLite: delete `cpa_agents/.adk/cpa.db`;
- Docker stack: `docker compose down -v`, then redo section 4.

## 8. Other commands

Activate the venv first (`..\venv\Scripts\Activate.ps1`) or prefix each command with
`..\venv\Scripts\python`.

| Command | What it does |
|---|---|
| `python run.py` | Full demo without the UI: the three workflows, with simulated people acting at the gates; prints the gate result and an evidence summary |
| `python run.py --model mistral/mistral-large-latest` | Same, with another model |
| `python -m cpa_agents.store.replay CASE-20261114-000001` | Replays a case's audit trail (case id or session id; `--json` for JSON) and checks the hash chain; exit code 1 if broken |
| `python -m pytest -q` | All tests, on temporary SQLite files |
| `$env:TEST_DATABASE_URL = "postgresql://postgres:<admin-password>@127.0.0.1:5432/cpa_test"; python -m pytest -q` | The same suite on Postgres. Use the dedicated `cpa_test` database: the suite drops its tables |
| `python -m workbench.users list` / `disable <name>` | Manage sign-ins |
| `python -m workbench --model <model> --port 8000` | The workbench without `start.ps1` (build the UI first) |
| `python -m google.adk.cli web . --port 8765` | ADK's developer UI for the preparation workflow: http://127.0.0.1:8765/dev-ui/ |
| `python -m cpa_agents.ldu list` | The LDU manifest |
| `python -m cpa_agents.ldu run <ldu> --port <port>` | One LDU as its own process (distributed mode without Docker; needs Postgres and `CPA_LDU_MODE=distributed`) |

**UI development with hot reload:** keep the workbench running on port 8000, then
`cd workbench/frontend; npm run dev` and open http://127.0.0.1:5173 (Vite forwards `/api` to
8000). `start.ps1` rebuilds the bundle automatically next time.

## 9. Configuration reference

All settings go in `.env` (the Docker stack passes the model settings through; it sets its own
database and storage).

**Model.** `CPA_MODEL` picks the model. Plain names (`gemini-2.5-flash`) use Gemini with
`GOOGLE_API_KEY`; names with a provider prefix (`mistral/mistral-large-latest`) go through
LiteLLM with that provider's key (`MISTRAL_API_KEY`).

**Per-LDU model, concurrency and retry.** Set them in `cpa_agents/ldu/manifest.yaml`, or override
one LDU with environment variables named after it (upper case, `-` becomes `_`):
```
CPA_LDU_NARRATIVE_AGENT_MODEL=mistral/mistral-large-latest   # only the narrative drafters and critic
CPA_LDU_NARRATIVE_AGENT_CONCURRENCY=2                        # at most 2 model calls in flight per replica
CPA_LDU_DUE_DILIGENCE_AGENT_MAX_ATTEMPTS=6                   # tries per model call
```
An LDU without a model uses `CPA_MODEL`. Rate-limit (429), timeout and server (5xx) errors are
retried with exponential backoff and jitter (`CPA_MODEL_RETRY_BASE_DELAY`, default 1 s, capped
at `CPA_MODEL_RETRY_MAX_DELAY`, default 30 s). Only the model call is retried, never a whole
step, because tool calls are not idempotent.

**Database.** `DATABASE_URL`:

| Value | Use |
|---|---|
| unset | SQLite file `cpa_agents/.adk/cpa.db` |
| `sqlite:///path/to/file.db` | another SQLite file |
| `postgresql://user:password@host:5432/cpa` | Postgres 15+ (target) |

**OCR.** Scanned PDFs and images are read with Tesseract when it is installed. The Docker image
has it. For the single process, install Tesseract for Windows (for example
`winget install UB-Mannheim.TesseractOCR`) and either put it on PATH or set
`TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`. `CPA_OCR=off` turns it off.
Without it, a scanned file is reported as unreadable rather than read as empty.

**Policy.** `cpa_agents/policy.yaml` holds governed parameters: validity periods, review cadence,
tolerances, recency window, escalation criteria, FCA check scope, the order of trust between
statement bases and the reconciliation date window. All except the proposed
`financial_basis_precedence` are unset (`null` = NOT CONFIGURED) until the policy owner sets them.
Bump `version` on every change; gate results record it.

**Runs.** `CPA_LDU_MODE` is `inprocess` (default, `start.ps1`) or `distributed` (the Docker
stack). `CPA_RUN_HEARTBEAT_TIMEOUT` (60 s) marks a run interrupted when its orchestrator stops;
`CPA_STEP_HEARTBEAT_TIMEOUT` (60 s) hands a step to another replica when its worker stops.

## 10. How it works

### Agent mesh

The **Credit Pack Orchestrator** is a deterministic ADK `Workflow` (`cpa_agents/mesh/orchestrator.py`).
Order, parallelism and gate routing are graph edges, not model choices. A human gate ends a run,
and the next run starts from the saved session.

```
preparation run
  capture_request -> intake_classifier
    -> [ entity_structure -> due_diligence ]            due_diligence = sanctions || identity || adverse_media
    || [ document_ingestion -> bureau_external ]                          -> merge -> dd_summary
    -> evidence_join -> merge -> gap_consolidator -> pack_request -> financial_analysis
    -> narrative_drafting                               = background || management || conduct || security_esg
    -> pack_validation (DT-2 gate) -> STOP for humans                     -> merge -> critic
submission run      submission_gate --pass--> pack_transmit   --blocked--> report_blocked
post-approval run   post_approval (handoffs, conditions, closure, next review)
```

| Arch 3.2 agent | Skill (`cpa_agents/skills/`) | Agents |
|---|---|---|
| Credit Pack Orchestrator | `cpa-orchestrator` | workflow + `gap_consolidator` |
| Intake & Request Classifier | `cpa-intake-classifier` | `intake_classifier` |
| Entity & Structure | `cpa-entity-structure` | `entity_structure` |
| Document Ingestion & Extraction | `cpa-document-ingestion` | `document_ingestion` |
| Bureau & External Data | `cpa-bureau-external-data` | `bureau_external` |
| Due Diligence & Screening | `cpa-due-diligence-screening` | `dd_sanctions`, `dd_identity`, `dd_adverse_media`, `dd_summary` |
| Financial Analysis | `cpa-financial-analysis` | `financial_analysis` |
| Narrative Drafting | `cpa-narrative-drafting` | `nd_business_background`, `nd_management_assessment`, `nd_conduct_performance`, `nd_security_esg`, `nd_critic` |
| Pack Assembly & Validation | `cpa-pack-assembly` | `pack_request`, `pack_validation`, `pack_transmit` |
| Post-Approval Coordination | `cpa-post-approval` | `post_approval` |

There is no credit-decision, pricing or sanctions-clearing agent. No agent has a tool that
records a human decision.

- **Skills** are `SKILL.md` files loaded with ADK's skill loader. Each graph step is wired to one
  skill; a sub-agent gets its skill's shared text plus its own `## Sub-agent:` section, and only
  the state keys it declares. `cpa-governance-audit` (P-12) is reference material; it has no agent.
- **Rules** (`cpa_agents/rules/`) are plain Python, and agents only call them through tools:
  all 14 calculations (CALC-001..014), the DT-2 gate (R1..R8), DT-3 check outcomes, the registry
  comparison, DT-5 staleness, decision-language detection, statement versions (`financials.py`)
  and financial reconciliation (`reconcile.py`).
- **Documents are read progressively.** The `document-extraction` LDU turns each upload into
  pages, tables with cell references (`T1!B12`, the sheet's own row for Excel) and, for iXBRL
  accounts filed at Companies House, tagged facts; scanned pages are OCR'd when Tesseract is
  installed. The result is cached beside the uploaded file. Agents outline a document, search it
  and read only the pages or rows they need; every read says where the next part starts.
- **Figures are copied by code.** Agents record statements by cell reference
  (`record_statement_from_cells`) or straight from iXBRL tags (`import_ixbrl_accounts`), with a
  basis (audited, unaudited accounts, management, dealer-stated) and units (£000 = thousands).
  Every version is kept; the analysis uses the best basis per period and says so.
- **Financial reconciliation** checks a statement's own arithmetic, table totals, opening vs prior
  closing balances, versions of the same period, the request's current limit vs the facility
  record, drawn exposure vs borrowings in the accounts, a stock valuation vs stock, and measures
  resting on unaudited figures. Each BLOCK item stops the gate under R5 until the case owner
  corrects the figures or records an explanation (workbench action `explain_difference`).
- **Parallel agents** write to their own partition of shared keys, which a merge step folds back
  after each join, so no write is lost.
- **External sources** (Companies House, bureau, screening, Credit) are stubs backed by
  `cpa_agents/stubs/*.json`.

### Least Deployable Units (LDUs)

An LDU is the smallest piece that can be deployed, restarted and scaled on its own: an `agent`
worker (hosting one or more agents), an `api` service, a non-LLM `worker`, or the `static` UI.
`cpa_agents/ldu/manifest.yaml` lists all of them, and every process refuses to start if an agent
is in no LDU, in two, or named but not built.

| LDU | Kind | Agents / code | AST unit |
|---|---|---|---|
| `workbench-ui` | static | `workbench/frontend/dist` | |
| `workbench-api` | api | `workbench/` (sign-in, cases, every human gate) | human gates |
| `case-orchestrator` | worker | the workflow graph and its merge and gate steps | |
| `intake-agent` | agent | `intake_classifier` | DU-01 |
| `entity-agent` | agent | `entity_structure` | DU-03 |
| `evidence-agent` | agent | `document_ingestion`, `gap_consolidator` | DU-02 |
| `document-extraction` | api | structured extraction (pages, tables, iXBRL, OCR) of uploaded files | DU-02 |
| `master-data-agent` | agent | `bureau_external` | DU-11 |
| `due-diligence-agent` | agent | `dd_sanctions`, `dd_identity`, `dd_adverse_media`, `dd_summary` | DU-04 |
| `external-adapters` | api | registry, sanctions, adverse-media and credit-reference lookups | DU-03/04/11 |
| `financial-agent` | agent | `financial_analysis` | DU-05 |
| `narrative-agent` | agent | `nd_*` drafters and `nd_critic` | DU-06 |
| `pack-agent` | agent | `pack_request`, `pack_validation`, `pack_transmit` | DU-07/08 |
| `post-approval-agent` | agent | `post_approval` | DU-09 |

`review-scheduler` (DU-10) and `telemetry` (DU-12) are planned and not built.

**How a run works.** The case-orchestrator runs the workflow graph. Each agent node is a step sent
to the agent's LDU over a queue. A worker for that LDU runs the agent in an isolated step session
with a copy of the case state and returns the state the agent changed; the orchestrator applies it
to the case session, so it is the only writer. Runs are rows in the `runs` table with a heartbeat:
a run whose orchestrator stops shows as **interrupted**, and a run blocked on an LDU with no worker
shows as **waiting** for it.

- **Single-process mode** (`start.ps1`, the tests) runs the orchestrator and one worker per agent
  LDU inside the workbench process, on an in-memory queue.
- **Distributed mode** (the Docker stack) runs each LDU as its own process. Steps go through the
  `step_jobs` table: a replica claims a job with `SELECT … FOR UPDATE SKIP LOCKED`, so replicas
  never take the same step, and Postgres `LISTEN/NOTIFY` wakes workers, the orchestrator and live
  case pages without polling. Every LDU answers `GET /health` and heartbeats a row in
  `ldu_workers`. Uploads go to S3-compatible storage (SeaweedFS), and `document-extraction` and
  `external-adapters` are called over HTTP. The stack connects as the Postgres admin, which is
  fine locally; a shared deployment should use the restricted role in
  `cpa_agents/store/sql/postgres_roles.sql`.

### Workbench (web UI)

Where named, signed-in people act at the human gates (Arch.md layer L7). The front end is React 18
+ TypeScript + Material UI in `workbench/frontend/`; the API is FastAPI in `workbench/app.py` and
enforces every rule (sign-in, roles, approval prerequisites, audit). The browser only displays
what the server allows.

Roles: `account_manager`, `wholesale_manager`, `financial_crime_analyst`, `onboarding_analyst`,
`pricing_authority`, `credit_manager`, `credit_underwriter`, `operations` and `auditor`.

| Screen | What it does |
|---|---|
| Cases | searchable, stage-filtered list with gate status, agent state and who each case waits on |
| My queue | everything waiting on your role across cases; one click opens the right tab |
| New case | sample cases, or request text plus drag-and-drop documents (PDF, Word, Excel, CSV, text, email, iXBRL, images; 20 MB each, SHA-256 recorded) |
| Case header | live pipeline stepper while agents run, and the run buttons |
| Gate | DT-2 result, completeness bar, each blocking gap with its corrective action, advisories, authorised exceptions |
| Evidence | request, documents and upload, information items with source and date, parties, registry discrepancies, requests, notes |
| Checks | check register, hit disposition (financial crime analyst), CRA, manual checks with evidence |
| Analysis | measures with CALC id, basis and flags, reconciliation with explanations, data-quality flags, borrowing profile, every statement version |
| Narrative | each draft beside its evidence and critic findings, version diff, accept, amend or reject |
| Request | lending request; pricing authorisation dialog showing exposure and security (never the preparer) |
| Submission | gate summary, submission authorisation (case owner only), pack versions with fingerprints |
| Credit | queries (underwriter raises, owner resolves, optionally a new pack version) and outcome |
| Handoffs | handoffs and conditions with evidence (operations), next review date |
| Audit | filterable audit trail with the hash-chain check |

The case page refreshes live (server-sent events) when agents finish a step or another person
acts. Wrong roles are refused with the reason and audited as `access_denied`; Credit users cannot
edit the pack (REQ-088); every approval dialog shows the evidence first and sends its fingerprint,
and if the evidence changed meanwhile the server refuses the approval (ARCH-H09).

### Storage

The case store keeps unique case ids, an append-only hash-chained audit trail, pack versions
(immutable once written), narrative section history, Credit queries and a state snapshot after
every agent step. ADK sessions are stored in the same database. Postgres rejects UPDATE and DELETE
on `audit_events`, `pack_versions`, `section_versions` and `state_snapshots`, and the restricted
app role gets only INSERT and SELECT on them.
