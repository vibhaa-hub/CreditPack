Credit Pack Assessment 

Requirements Analysis and Target Agentic Architecture 

Dealer / Wholesale Lending — Credit Pack Submission Agent 

Aligned to the Enterprise Agentic Architecture Blueprint (principles, considerations, building blocks and Agent Blueprint) 

Prepared by the Office of the CTO, BFSI  |  Version 1.0  |  22 September 2026 

TCS Confidential 

 

Contents 

​​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​ 

​​ 

 

1. Executive Summary 

The discovery is unambiguous on one point: Credit Pack Assessment is not a credit decisioning problem. The credit decision stays with Credit Underwriters. What consumes effort is the assembly of a decision-ready pack — gathering dealer, director, shareholder and financial information, running KYC/AML/sanctions/ID&V/CRA and FCA checks, interrogating Experian, Equifax and Companies House, and drafting narrative analysis into the FCA Excel template. The discovery records more than 90 minutes of average effort per submission, 100+ colleagues involved across the wider process, no happy path with 100% human intervention, substantial duplication across franchise, wholesale, fleet and retail lending, and consumption of virtually every data format in existence. 

This is the archetypal case for an agentic architecture rather than a point automation. The target design is a supervised multi-agent system that assembles evidence, performs checks, drafts the pack and presents it for human sign-off — with the lending decision, and every judgement point that carries regulatory consequence, left explicitly with the Account Manager, Wholesale Manager and Credit Underwriter. 

The architecture below is deliberately additive. It sits on the enterprise agentic stack — DSL and ontology foundation, unstructured data foundation, deterministic enterprise context, best-fit model routing, model-to-core integration, regulatory assurance and the agent control plane — and adds only the domain-specific agents, skills and blueprints required by dealer lending. Nothing in it replaces existing data or AI platform investment. 

Design stance: autonomy is granted for gathering, checking and drafting. It is withheld for deciding. 

2. Requirements Analysis 

2.1 What the process actually is 

Decomposing the five discovery stages against the nature of the work rather than the org chart gives a clearer basis for agent design: 

Stage 

Nature of work 

Automatable? 

Where judgement sits 

1. Dealer information gathering 

Retrieval, extraction, entity resolution across forms, OEM channels, conversations 

High — deterministic retrieval plus document extraction 

Completeness sign-off by Account Manager 

2. Onboarding & risk checks 

KYC, AML, sanctions, ID&V, CRA, FCA checks, adverse media — partly tooled, largely manual orchestration 

High for orchestration and evidence capture; low for disposition 

Hit/no-hit adjudication, PEP and adverse media disposition 

3. Credit application preparation 

Financial analysis, management assessment, trading, cashflow, borrowing, security, conduct, ESG narrative into the FCA template 

Medium — computation deterministic, narrative drafted then reviewed 

Every narrative assertion; management capability assessment 

4. Submission to Credit 

Assembly of lending request, terms, pricing, evidence; packaging and transmission 

High — assembly and completeness validation 

Terms, pricing and submission authorisation 

5. Post-approval activities 

Legal documentation, direct debit mandates, operational and funding setup, third-party supplier activity 

Medium — task orchestration and handoff tracking 

Legal execution and operational approval 

2.2 Requirements derived from the discovery findings 

# 

Discovery finding 

Architectural requirement 

R1 

No happy path; 100% human intervention 

Design for exception-native execution. The architecture must not assume a straight-through path; it must make human intervention cheap, structured and evidenced rather than eliminate it. 

R2 

Significant duplication across franchise, wholesale, fleet, retail and wider onboarding 

Reusable, certified agent blueprints and shared skills; entity and evidence gathered once and reused across lending lines under a shared ontology. 

R3 

Data highly fragmented — structured, Excel, email, PDF, images, reports, free text 

AI-native unstructured data foundation alongside the existing estate; multi-modal ingestion with provenance on every extracted fact. 

R4 

Information gathering dominates effort; decision sits elsewhere 

Agents are scoped to evidence assembly, check orchestration and drafting. No agent holds lending decision authority. 

R5 

90+ minutes average effort; 100+ colleagues; event and periodic review cycles (monthly to annual) 

Elastic, event-driven execution supporting both event-triggered onboarding and scheduled periodic reviews; FinOps metering per pack. 

R6 

Regulated activity — FCA, KYC/AML, sanctions, Consumer Duty and data protection obligations 

Continuous regulatory assurance: agent identity, EVALs, residency, full decision replay and immutable audit of every retrieval, check and draft. 

R7 

Volumes not validated in discovery 

Benefits case and capacity sizing must be treated as indicative until MI is baselined. Instrument volume, effort and rework from day one. 

2.3 Constraints and guardrails taken as binding 

The following are inputs to the design, not design choices. They are drawn from the enterprise agentic architecture guidance held in OneDrive. 

Governance at the level of the agent — the blueprint is registered, certified and revocable before anything runs; nothing reaches production uncertified. 

Assurance is declared inside the blueprint, never bolted on after go-live. An agent cannot be certified without its EVALs and guardrails. 

Continuous governance across the operational lifecycle — evaluation frameworks, policy enforcement, agent identity, behavioural monitoring and decision replay, aligned to SR 11-7, DORA, SMCR and the EU AI Act. 

Context engineering over prompt engineering — a versioned, retrievable context layer with deterministic controls, memory and persistence. 

Intelligence orchestrated, not model-centric — best-fit routing across frontier, mid-tier and domain SLMs on complexity, latency, regulatory constraint and cost, with caching and fallback. 

Transport carries control — MCP, A2A, APIs, system adapters and event streams carry agent discovery, tool discovery, identity, authorisation and policy enforcement. 

FinOps is a first-class architectural capability; unmetered agents become unbounded cost. 

Every execution leaves the enterprise smarter — outcomes, human interventions, evaluation results and agent reflections feed back into context, ontology, skills and EVALs. 

 

3. Target Agentic Architecture 

3.1 Layered view 

The stack below is the enterprise blueprint instantiated for dealer credit. Every agent passes through the same layers; business intent enters at engagement, is grounded in enterprise context, executed through best-fit models and governed integration to core systems, and settled against the data and knowledge foundation. Regulatory assurance and the feedback loop cut across all layers. 

L7 — Experience & Engagement 

Credit Pack Workbench for Account Manager / Wholesale Manager: evidence tray, exception queue, draft-with-provenance, one-click accept / amend / reject. 

Conversational and voice capture of dealer and director discussions. Outlook and Teams entry points. HITL review surfaces with mandatory approval prerequisites. 

L6 — Agent Control Plane 

Agent registry and blueprints - agent lifecycle and certification - control tower for drift, behaviour and observability - FinOps metering per pack and per agent. 

Agent-initiated actions are monitored, evaluated and certified before touching production systems. 

L5 — Orchestration & Agent Mesh 

Credit Pack Orchestrator (goal-level supervisor) delegating to task-level specialist agents. 

Plan / act / reflect loops, deterministic state machine per submission, saga-style compensation, escalation routing to named human roles. 

L4 — Enterprise Context & Meta Intelligence 

Versioned dealer, group and relationship context - deterministic controls - short and long-term memory - harness and loop engineering - compounding skills and EVALs. 

Encodes how this lender reasons about dealers: franchise dynamics, group structures, seasonality of stocking, historical credit outcomes. 

L3 — Model Control 

W for narrative synthesis and management assessment; mid-tier for summarisation and classification; domain SLMs for financial spreading, document classification and entity extraction. 

Hybrid compute pool (GPU / CPU / edge), caching, fallback and cost ceilings per submission. 

L2 — Model-to-Core Integration 

MCP servers and A2A for tool and agent discovery; REST/gRPC adapters and event streams. 

Adapters: Experian, Equifax, Companies House, SOPRA Apak, Auxiga Smart3, credit systems, sanctions/AML screening, email and document stores. Anti-corruption layer per external source. 

L1 — DSL Foundation & Ontology 

Dealer lending ontology: Dealer, Legal Entity, Group, Franchise, Director, Shareholder, Facility, Security, Covenant, Check, Evidence, Pack Section. 

DSL expressing credit pack intent, completeness rules and section requirements — machine-readable, queryable at runtime, grown incrementally from real agent usage. 

L0 — Data & Knowledge Foundation 

Core data and analytics (DWH, lake, data products) for structured dealer, exposure and performance data. 

AI-native unstructured foundation for emails, PDFs, scanned accounts, images, call notes, reports and commentary — with lineage and provenance on every extracted fact. 

Cross-cutting — Regulatory Assurance 

Agent identity - regulatory EVALs - data residency - decision replay of every retrieval, check, inference and draft - immutable audit and evidence pack for Credit, Compliance and Internal Audit. 

Cross-cutting — Continuous Feedback Loop 

Agent reflection - HITL overrides and corrections captured at point of review with reason codes - fine-tuning instructions - auto research - reinjection into context, ontology, DSL and skills. 

 

3.2 Agent inventory 

Ten agents, one supervisor and nine specialists. Each is declared as an Agent Blueprint across intent, capability and assurance before any instance runs. 

Agent 

Goal (intent) 

Key skills / tools 

Autonomy & control 

Credit Pack Orchestrator 

Produce a complete, evidenced, decision-ready FCA credit pack for a stated request type 

Plan decomposition, state machine, delegation, completeness scoring, escalation 

Supervised (L3). Plans and sequences; cannot approve, price or submit. 

Intake & Request Classifier 

Classify the trigger (new dealer, new franchise, increased borrowing, acquisition/disposal, director or shareholder change, periodic review) and derive the required pack profile 

Email/form parsing, request taxonomy, pack profile rules from DSL 

Supervised. Misclassification escalates rather than guesses. 

Entity & Structure Agent 

Establish and verify legal entity, group, directors and shareholders 

Companies House, internal customer master, entity resolution, ownership graph construction 

Supervised. Conflicting ownership data always escalates. 

Document Ingestion & Extraction Agent 

Convert accounts, MI, statements, forms and correspondence into structured, provenance-tagged facts 

Multi-modal OCR/extraction, document classification, financial spreading, confidence scoring 

Monitored (L2). Low-confidence extractions routed to human verification. 

Bureau & External Data Agent 

Retrieve and normalise external credit and entity data 

Experian, Equifax, Companies House adapters; quota and rate-limit governed 

Monitored. Tool whitelisting and per-agent quotas enforced. 

Due Diligence & Screening Agent 

Orchestrate KYC, AML, sanctions, ID&V, CRA, FCA and adverse media checks and assemble the evidence set 

Screening platform tools, adverse media search, evidence capture, check register 

Assisted (L1) on disposition. Every hit is adjudicated by a human; the agent never clears an alert. 

Financial Analysis Agent 

Produce trading, profitability, cashflow, borrowing and security analysis with full derivation trail 

Deterministic financial calculation skills, ratio and trend analysis, covenant headroom 

Supervised. All computation deterministic and replayable — no model-generated arithmetic. 

Narrative Drafting Agent 

Draft business background, management assessment, conduct and performance, and ESG commentary — each sentence source-linked 

Retrieval-grounded generation, citation enforcement, tone and template conformance 

Assisted. Draft only. Nothing enters the pack without named human acceptance. 

Pack Assembly & Validation Agent 

Assemble the FCA template, validate completeness and internal consistency, produce the submission bundle 

Excel template binding, completeness rules, consistency checks, evidence index 

Supervised. Blocks submission on any unresolved gap or unaccepted draft. 

Post-Approval Coordination Agent 

Track legal documentation, direct debit mandates, funding and operational setup and third-party supplier tasks to completion 

Task orchestration, SLA tracking, nudges, handoff register across SOPRA Apak, Auxiga Smart3 and operations 

Monitored. Coordinates and chases; executes nothing financially binding. 

Deliberately absent: there is no credit decisioning agent, no pricing agent and no sanctions-clearing agent. Those authorities remain with Credit Underwriting, the pricing authority and Financial Crime respectively. 

 

3.3 Runtime flow — event to submission 

Trigger. An OEM referral, dealer application, bank referral or scheduled periodic review raises an event. The Intake & Request Classifier derives the request type and the required pack profile from the DSL. 

Context hydration. The Orchestrator retrieves versioned dealer, group and relationship context and any prior pack for the same entity — the primary lever against the duplication identified in discovery. 

Parallel evidence assembly. Entity & Structure, Document Ingestion, Bureau & External Data and Due Diligence agents execute concurrently. Every fact lands in the evidence store with source, timestamp, retrieving agent identity and confidence. 

Gap resolution. The Orchestrator scores completeness against the pack profile and raises a single consolidated request to the Account Manager or dealer, rather than the iterative to-and-fro of the current process. 

Analysis and drafting. Financial Analysis computes deterministically; Narrative Drafting produces source-linked commentary. Critic and reflection passes run before anything surfaces to a human. 

Human review. The Workbench presents draft, evidence and derivation side by side. The reviewer accepts, amends or rejects each section. Overrides are captured with reason codes and flow to the feedback loop. 

Assembly and submission. Pack Assembly validates completeness and consistency, binds the FCA template and produces the bundle. Submission to Credit is authorised by a named human. 

Post-approval. The Coordination Agent opens and tracks legal, mandate, funding and supplier tasks until closure. 

3.4 Human-in-the-loop control points 

Following the oversight principles held in OneDrive, each control point declares its minimum approval prerequisites. Where those prerequisites are absent the reviewer cannot verify the output, and approval given in that condition is treated as a process failure rather than a valid approval. 

Control point 

Role 

Authority 

Minimum prerequisites for valid approval 

Request classification confirmation 

Account Manager 

Approve / reclassify 

Trigger source, derived request type, resulting pack profile 

Evidence completeness gate 

Account Manager 

Approve / request more 

Completeness score, gap list, confidence flags on extractions 

Screening disposition 

Financial Crime / Compliance 

Clear / escalate / decline 

Full alert detail, source data, match rationale, prior dispositions 

Financial analysis review 

Wholesale Manager 

Accept / correct 

Derivation trail to source document and page 

Narrative acceptance 

Account / Wholesale Manager 

Accept / amend / reject per section 

Source citation per assertion; uncited text cannot be accepted 

Terms, parameters and pricing 

Authorised pricing role 

Set and approve 

Exposure position, security, ROTE inputs — human-entered 

Submission authorisation 

Wholesale Manager 

Submit to Credit 

Validated pack, complete evidence index, all sections accepted 

Credit decision 

Credit Underwriter 

Approve / decline / condition 

Independent assessment on Credit's own systems — outside agent scope 

 

3.5 Guardrails and controls 

Control 

Implementation 

Context integrity 

Schema and content validation on every context write; rejection of malformed or unattributed facts. 

Context access control 

Agent-policy and role-based access; privacy checks on writes; dealer and director personal data scoped to the agents that need it. 

Tool invocation governance 

Tool whitelisting per blueprint; rate and quota limits on bureau calls; no agent may invoke an unregistered tool. 

HITL interlocks 

Mandatory human review on all high-risk invocations — screening disposition, pricing, submission. 

Rate limits and enforcement 

Context size limits; per-agent, per-tool quotas; loop and runaway-execution protection. 

Context versioning and rollback 

Temporal context snapshots enabling rollback of a submission to any prior state for recovery or audit. 

Prompt and content injection defence 

Dealer-supplied documents and external web content are treated as untrusted input; instruction-bearing content is neutralised before it reaches a reasoning loop. 

Grounding enforcement 

Narrative sections fail validation if any assertion lacks a resolvable source reference. 

Decision replay 

Every retrieval, inference, tool call, human override and state transition is replayable end to end for a named submission. 

FinOps 

Token, inference and compute cost metered per submission and per agent, with ceilings and alerting in the control plane. 

3.6 Non-functional position 

Concern 

Position 

Determinism 

All financial computation, completeness rules, check registers and pack assembly are deterministic. Probabilistic components are confined to extraction, classification, retrieval and drafting — each with a human acceptance gate. 

Explainability 

Every figure traces to a source document and page; every narrative assertion to a citation; every check to its evidence artefact. 

Resilience 

Bureau and screening outages degrade to queued retry with the submission held in a recoverable state; no partial pack may be submitted. 

Data protection 

Consent and authority documentation captured as first-class evidence artefacts; residency enforced at the model gateway; personal data minimised in prompts and context. 

Reusability 

Entity, screening, extraction and bureau agents are built as shared blueprints usable by franchise, wholesale, fleet and retail lending — the direct answer to the duplication finding. 

Observability 

Per-submission traces, drift and behavioural monitoring, EVAL results and effort telemetry surfaced in the control tower. 

 

4. Delivery Approach 

Phase 

Scope 

Exit criteria 

Phase 0 — Foundations 

Dealer lending ontology and DSL seed; evidence store with provenance; agent registry entries and blueprint definitions; EVAL suites authored before build 

Blueprints certified; EVALs and guardrails declared; MI baseline established for volumes and effort 

Phase 1 — Evidence assembly 

Intake Classifier, Entity & Structure, Document Ingestion, Bureau & External Data agents; Workbench evidence tray 

Measured reduction in gathering effort; extraction precision within EVAL thresholds 

Phase 2 — Checks and analysis 

Due Diligence & Screening orchestration, Financial Analysis agent, screening disposition control point 

Complete, audit-ready check register per submission; zero agent-cleared alerts 

Phase 3 — Drafting and assembly 

Narrative Drafting, Pack Assembly & Validation, full HITL control set, submission authorisation 

Packs accepted by Credit without rework attributable to assembly quality 

Phase 4 — Reuse and extension 

Post-Approval Coordination; extension of shared blueprints to fleet, retail and wider onboarding 

Second and third lending lines consuming certified blueprints with no rebuild 

5. Risks and Anti-Patterns 

Risk / anti-pattern 

Mitigation 

Assurance bolted on after deployment 

EVALs and guardrails declared inside the blueprint; certification is impossible without them. 

A registry nobody uses 

Finding and adapting a blueprint must be demonstrably faster than building one; measured as a delivery KPI. 

A large static ontology built ahead of use 

Ontology grown incrementally from real agent usage and kept queryable at runtime. 

Reuse pitched at the wrong layer or granularity 

Explicit decision on what is shared at infrastructure, blueprint and instance level, settled up front. 

FinOps as an afterthought 

Cost ceilings per submission metered in the control plane from Phase 1. 

Substituting probabilistic output for deterministic obligation 

Regulated computation and check disposition remain deterministic or human; models never own an obligation. 

Automation bias at review gates 

Minimum approval prerequisites enforced at each gate; approval without them is recorded as a process failure and monitored. 

Unvalidated benefits case 

Volume and effort MI instrumented from Phase 0; the 90-minute and 100-colleague figures treated as indicative until baselined. 

6. Open Points for Validation 

Annual case volumes by request type and by lending line — not validated in discovery and required for sizing and the benefits case. 

Ownership of the screening disposition control point between Financial Crime and the first line. 

Whether the FCA Excel template remains the target artefact or is replaced by a structured pack with Excel as a rendering — materially changes Pack Assembly. 

Credit's appetite to consume a structured, machine-readable pack rather than a document. 

Which screening and onboarding software solutions are already in place, and their API surface for agent orchestration. 

Model residency and approved model list applicable to dealer personal data under the prevailing AI governance policy. 