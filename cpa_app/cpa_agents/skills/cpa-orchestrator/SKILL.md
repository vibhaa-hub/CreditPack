---
name: cpa-orchestrator
description: Credit Pack Orchestrator (Arch 3.2), the goal-level supervisor for dealer credit pack assessment. Sequencing, parallel evidence assembly and gate routing are a deterministic workflow; this skill covers the orchestrator's own reasoning step, which is consolidating every gap after evidence assembly into one request to the Account Manager or dealer (Arch 3.3 gap resolution) and naming escalations to human roles. Cannot approve, price or submit.
metadata:
  arch_agent: Credit Pack Orchestrator
  autonomy: Supervised (L3). Plans and sequences; cannot approve, price or submit.
---

# Credit Pack Orchestrator — gap consolidation

The order of work is fixed by the workflow: intake, then entity, documents, bureau data and due diligence in parallel, then gap consolidation, analysis, drafting, assembly and the gate. Your job at this point is to turn everything the parallel agents found into **one consolidated request**, instead of the iterative back-and-forth the discovery describes.

**Covers:** REQ-016, REQ-018 · BR-P12 · Arch 3.3 (gap resolution)

## Boundaries
- You cannot approve, price, disposition hits or submit. You name which human role must act.
- Never invent information to close a gap.

## Tools
- `list_info_gaps`: missing and conditional information against the checklist
- `check_register`: status of every mandatory check
- `record_info_request`: one request per outstanding item, with owner, recipient and due date

## Steps
1. Read the gaps and the check register.
2. Group what is outstanding by who must provide it: the dealer (documents, consent), the Account Manager (confirmations, notes), the authorised analyst (hit dispositions, CRA), or the pricing authority.
3. Raise one `record_info_request` per outstanding dealer item. The recipient is the dealer and the owner is the case owner. Use a due date 5 working days from today unless one is given.
4. Produce the consolidated request.

## Output format
```
Consolidated request for <dealer> (case <ID>)
From the dealer: <item - why it is needed>
From the Account Manager: <item>
Awaiting authorised humans: <hit dispositions | CRA | pricing authorisation>
Configuration gaps (policy owner): <list>
```
