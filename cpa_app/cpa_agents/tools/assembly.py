"""Pack Assembly & Validation tools (P-06 template, P-07, P-08; REQ-053, REQ-055..067, DT-2).
Pricing is never set here and no tool records an authorisation: humans do (BR-E01, BR-E02)."""
from datetime import date

from google.adk.tools import ToolContext

from ..rules.gate import evaluate
from ..store.pack import assemble_pack
from ._common import S, append, get_store, merged_view, need_case, policy


def record_lending_request(facility_type: str, amount: float, purpose: str, tool_context: ToolContext,
                           current_limit: float | None = None, change_requested: str = "",
                           terms: str = "", pricing: str = "", type_specific_detail: str = "") -> dict:
    """Record the lending request (REQ-055): facility type (franchise | wholesale | fleet | retail),
    amount, purpose; for an existing facility the current limit and change requested. terms and
    pricing exactly as the preparer proposed them (REQ-056/057; 'not supplied' if absent; never
    invent rates). type_specific_detail: acquisition/disposal impact, persons changed, current
    exposure (REQ-059). Recording a new request withdraws any earlier pricing authorisation."""
    st = S(tool_context)
    if err := need_case(st):
        return err
    if not amount:
        return {"status": "error", "message": "amount required"}
    st["lending_request"] = dict(facility_type=facility_type, amount=amount, purpose=purpose,
                                 current_limit=current_limit, change_requested=change_requested,
                                 terms=terms or "not supplied", pricing=pricing or "not supplied",
                                 type_specific_detail=type_specific_detail, preparer=st.get("owner"))
    withdrawn = bool(st.get("pricing_authorised_by"))
    if withdrawn:
        st["pricing_authorised_by"] = None
    return {"status": "ok", **({"note": "earlier pricing authorisation withdrawn: request again"} if withdrawn else {})}


def request_pricing_authorisation(tool_context: ToolContext) -> dict:
    """HUMAN GATE: request pricing/terms authorisation from the pricing authority, a role other
    than the preparer (BR-E02). Never authorises."""
    st = S(tool_context)
    if not st.get("lending_request"):
        return {"status": "error", "message": "record the lending request first"}
    if "pricing/terms authorisation" not in (st.get("pending_human") or []):
        append(st, "pending_human", "pricing/terms authorisation")
    return {"status": "pending_human", "preparer": st["lending_request"].get("preparer")}


def run_completeness_gate(tool_context: ToolContext) -> dict:
    """DT-2 gate R1..R8 top to bottom with CALC-011 completeness. Lists every blocking gap and
    advisory with its corrective action (BR-U04)."""
    st = S(tool_context)
    res = evaluate(merged_view(st), policy(), date.today().isoformat())
    st["gate_result"] = {k: res[k] for k in ("result", "deciding_rule", "gaps", "advisories", "completeness",
                                             "mandatory_items", "policy_version", "as_at")}
    st["gate_status"] = "PASS" if res["submission_may_be_authorised"] else "BLOCKED"
    return {"status": "ok", "gate": res["result"], "deciding_rule": res["deciding_rule"],
            "completeness": res["completeness"]["display"], "gaps": res["gaps"], "advisories": res["advisories"],
            "next": "request_submission_authorisation" if res["submission_may_be_authorised"]
            else "humans must resolve the gaps"}


def request_submission_authorisation(tool_context: ToolContext) -> dict:
    """HUMAN GATE: ask the accountable manager to authorise submission (BR-E01). Never authorises."""
    st = S(tool_context)
    if st.get("gate_status") != "PASS":
        return {"status": "error", "message": "gate not passed"}
    if "submission authorisation" not in (st.get("pending_human") or []):
        append(st, "pending_human", "submission authorisation")
    return {"status": "pending_human", "authoriser": st.get("owner")}


def transmit_pack(tool_context: ToolContext) -> dict:
    """Transmit to Credit and store an immutable pack version (REQ-063/064). Re-evaluates the DT-2
    gate itself and refuses unless it allows submission AND the accountable owner authorised."""
    st = S(tool_context)
    res = evaluate(merged_view(st), policy(), date.today().isoformat())
    by = st.get("submission_authorised_by")
    if not res["submission_may_be_authorised"] or not by:
        return {"status": "blocked", "reason": "gate does not allow submission" if not res["submission_may_be_authorised"]
                else "not authorised by the accountable manager", "gaps": res["gaps"]}
    owner = (st.get("owner") or "").lower()
    if owner and owner.split(" (")[0] not in str(by).lower():
        return {"status": "blocked", "reason": f"submission must be authorised by the case owner {st.get('owner')} (BR-E01)"}
    store = get_store()
    pv = store.create_pack_version(st["case_id"], assemble_pack(merged_view(st)), created_by=str(by),
                                   reason="submission to Credit")
    receipt = "NOT-TRANSMITTED: Credit interface not built (OQ-14)"
    sub_id = store.record_submission(st["case_id"], pv["id"], authorised_by=str(by), receipt_ref=receipt)
    st["submitted"] = dict(date=date.today().isoformat(), receipt=receipt, submission_id=sub_id,
                           pack_version=pv["version"], sha256=pv["sha256"], by=by, gate=res["result"],
                           policy_version=res["policy_version"])
    return {"status": "ok", **st["submitted"]}


def list_credit_queries(tool_context: ToolContext) -> dict:
    """List Credit queries for this case with owner and status (REQ-065). Read-only:
    queries are raised and resolved by people, never by an agent."""
    case_id = S(tool_context).get("case_id")
    if not case_id:
        return {"status": "error", "message": "no case registered"}
    qs = get_store().credit_queries(case_id)
    return {"status": "ok", "open": [q for q in qs if q["status"] == "open"],
            "resolved": [q for q in qs if q["status"] == "resolved"]}
