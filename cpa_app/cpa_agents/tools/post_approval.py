"""Post-Approval Coordination tools (P-09, P-10; REQ-068..078, BR-P06..P10, CALC-012)."""
from google.adk.tools import ToolContext

from ..rules import calculations as c
from ._common import S

HANDOFFS = ["legal documentation", "direct debit mandate", "operational set-up",
            "funding system configuration", "supplier activity"]


def initiate_handoffs(tool_context: ToolContext) -> dict:
    """Create post-approval handoffs, each carrying the approved terms unchanged (REQ-068..070).
    Refused unless Credit's approval is recorded (BR-P06). Idempotent."""
    st = S(tool_context)
    if st.get("credit_outcome") not in ("approved", "approved with conditions"):
        return {"status": "blocked", "reason": "no approval recorded by Credit"}
    if st.get("handoffs"):
        return {"status": "ok", "handoffs": st["handoffs"], "note": "already initiated"}
    lr = st.get("lending_request") or {}
    approved = {k: lr.get(k) for k in ("facility_type", "amount", "terms", "pricing")}
    st["approved_terms"] = approved
    st["handoffs"] = [dict(task=t, status="open", owner=None, due=None, approved_terms=approved) for t in HANDOFFS]
    st["conditions_status"] = [dict(condition=cnd, status="open", evidence=None) for cnd in st.get("conditions") or []]
    return {"status": "ok", "handoffs": st["handoffs"], "conditions": st["conditions_status"]}


def check_case_closure(tool_context: ToolContext) -> dict:
    """Whether the case may close (BR-P10): every handoff complete or closed with a reason, every
    condition satisfied with evidence (BR-P08), downstream terms equal to approved terms (BR-P07)."""
    st = S(tool_context)
    blockers = []
    approved = st.get("approved_terms")
    for h in st.get("handoffs") or []:
        if h["status"] not in ("complete", "closed"):
            blockers.append(f"handoff open: {h['task']}")
        elif h["status"] == "closed" and not h.get("reason"):
            blockers.append(f"handoff closed without reason: {h['task']}")
        if approved and h.get("approved_terms") != approved:
            blockers.append(f"terms mismatch in {h['task']} (BR-P07)")
    for cnd in st.get("conditions_status") or []:
        if cnd["status"] != "satisfied" or not cnd.get("evidence"):
            blockers.append(f"condition not satisfied with evidence: {cnd['condition']}")
    if not st.get("handoffs"):
        blockers.append("no handoffs initiated")
    return {"status": "ok", "closure": "ELIGIBLE" if not blockers else "BLOCKED", "blockers": blockers}


def next_review_date(last_review: str, tool_context: ToolContext, cadence_months: int | None = None) -> dict:
    """CALC-012: last review + N calendar months, month-end safe. cadence_months must come from the
    DT-4 policy table (1, 3, 6 or 12; OQ-05) or the person instructing; never guessed."""
    if cadence_months is not None and cadence_months not in (1, 3, 6, 12):
        return {"status": "error", "message": "cadence must be 1, 3, 6 or 12 months (DT-4)"}
    r = c.next_review_date(last_review, cadence_months)
    if r.value is None:
        return {"status": "error", "message": "cadence not configured (OQ-05)"}
    S(tool_context)["next_review"] = {"due": r.value, "cadence_months": cadence_months, "last_review": last_review}
    return {"status": "ok", "next_review": r.value}
