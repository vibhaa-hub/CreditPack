"""Intake & Request Classifier tools (P-01; REQ-001..007, DT-1)."""
from datetime import datetime, timedelta, timezone

from google.adk.tools import ToolContext

from ..rules.policy import NOT_CONFIGURED
from ._common import S, get_store, policy

# DT-1 (PROPOSED baseline, OQ-03): R required, C conditional/delta only, N/A not applicable
DT1 = {
    "new dealer relationship": dict(entity="R", parties="R", checks="R", cra="R", media="R", financial="R", security="R", request="R"),
    "new franchise application": dict(entity="C", parties="C", checks="C", cra="C", media="C", financial="R", security="R", request="R"),
    "increased borrowing request": dict(entity="C", parties="C", checks="C", cra="C", media="C", financial="R", security="R", request="R"),
    "dealer acquisition": dict(entity="R", parties="R", checks="R", cra="R", media="R", financial="R", security="R", request="R"),
    "dealer disposal": dict(entity="C", parties="C", checks="C", cra="C", media="C", financial="R", security="R", request="R"),
    "director or shareholder change": dict(entity="C", parties="R", checks="R", cra="R", media="R", financial="C", security="N/A", request="C"),
    "periodic dealer credit review": dict(entity="C", parties="C", checks="C", cra="R", media="R", financial="R", security="R", request="C"),
}
SOURCES = {"oem partner", "field distribution team", "dealer contact", "bank referral", "existing relationship"}


def register_case(dealer_name: str, registered_number: str, case_types: list[str],
                  source: str, owner: str, tool_context: ToolContext) -> dict:
    """Register a credit request as a case (REQ-001..005). case_types must be from:
    new dealer relationship, new franchise application, increased borrowing request,
    dealer acquisition, dealer disposal, director or shareholder change,
    periodic dealer credit review. source must be one of: OEM partner, field
    distribution team, dealer contact, bank referral, existing relationship."""
    if (source or "").lower() not in SOURCES:
        return {"status": "error", "message": f"origination source missing/invalid: {source}"}
    bad = [t for t in case_types if t.lower() not in DT1]
    if bad or not case_types:
        return {"status": "error", "message": f"unknown or missing case type(s): {bad or case_types}"}
    if not owner:
        return {"status": "error", "message": "accountable owner required"}
    st = S(tool_context)
    if st.get("case_id"):
        return {"status": "error", "message": f"this session already holds case {st['case_id']}"}
    types = [t.lower() for t in case_types]
    case = get_store().create_case(session_id=tool_context.session.id, dealer_name=dealer_name,
                                   registered_number=registered_number, case_types=types,
                                   source=source, owner=owner)
    st.update(dict(case_id=case["case_id"], dealer_name=dealer_name, registered_number=registered_number,
                   case_types=types, source=source, owner=owner, received_at=case["received_at"]))
    return {"status": "ok", **case}


def get_requirement_checklist(tool_context: ToolContext) -> dict:
    """Build the applicable requirement checklist from DT-1 (PROPOSED baseline, OQ-03) for the
    registered case types. Union across types, stricter marker wins (R over C over N/A)."""
    st = S(tool_context)
    types = st.get("case_types")
    if not types:
        return {"status": "error", "message": "register the case first"}
    rank = {"R": 3, "C": 2, "N/A": 1}
    merged: dict = {}
    for t in types:
        for k, v in DT1[t].items():
            if k not in merged or rank[v] > rank[merged[k]]:
                merged[k] = v
    st["checklist"] = merged
    return {"status": "ok", "checklist": merged, "note": "DT-1 is PROPOSED, confirm per OQ-03"}


def find_related_cases(tool_context: ToolContext) -> dict:
    """Open or recent cases for the same dealer (REQ-006), excluding this one. 'Recent' uses the
    policy recency window; if it is NOT CONFIGURED every earlier case is listed and the gap reported."""
    st = S(tool_context)
    window = policy().get("recency_window_days")
    found = [c for c in get_store().cases_for_dealer(st.get("registered_number"), st.get("dealer_name"))
             if c["case_id"] != st.get("case_id")]
    if window is not NOT_CONFIGURED:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(window))
        found = [c for c in found if datetime.fromisoformat(c["received_at"]) >= cutoff]
    related = [{"case_id": c["case_id"], "owner": c["owner"], "received_at": c["received_at"],
                "case_types": c["case_types"]} for c in found]
    st["related_cases"] = related
    return {"status": "ok", "related_cases": related,
            "recency_window": "NOT CONFIGURED (BR-G05)" if window is NOT_CONFIGURED else f"{window} days"}
