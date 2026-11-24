"""Bureau & External Data tools (P-11; REQ-079..083, DT-5, CALC-014)."""
from google.adk.tools import ToolContext

from ..rules.validity import DT5, assess
from ..ldu.services import adapters
from ._common import S, get_store, policy, today


def lookup_held_data(tool_context: ToolContext) -> dict:
    """Information already held for this dealer from earlier cases (REQ-019, REQ-079), found by
    registered number. Reuse is subject to permitted use (BR-E05)."""
    st = S(tool_context)
    earlier = [c for c in get_store().cases_for_dealer(st.get("registered_number"), st.get("dealer_name"))
               if c["case_id"] != st.get("case_id")]
    held = [{"case_id": c["case_id"], "received_at": c["received_at"], "case_types": c["case_types"]} for c in earlier]
    st["held_cases"] = held
    return {"status": "ok", "earlier_cases": held,
            "note": "item-level reuse from earlier cases arrives with the dealer master (P-11); permitted use to confirm (BR-E05)"}


def credit_reference_lookup(tool_context: ToolContext) -> dict:
    """Credit reference result for the dealer (STUB data until the Experian/Equifax adapters exist).
    Requires the dealer's consent to searches on file (REQ-012)."""
    st = S(tool_context)
    if not any(i.get("info_class") == "consent" for i in st.get("info_items") or []):
        return {"status": "blocked", "message": "no consent to searches on file (REQ-012): search not performed"}
    rec = adapters.lookup("credit_reference", registered_number=st.get("registered_number") or "")["record"]
    if not rec:
        return {"status": "unavailable", "message": "no bureau result; manual alternative with evidence needed (REQ-092)"}
    st["credit_reference"] = {**rec, "retrieved": today()}
    return {"status": "ok", "result": st["credit_reference"]}


def assess_staleness(info_class: str, information_date: str, tool_context: ToolContext) -> dict:
    """CALC-014 age and DT-5 action for an information item. info_class one of: registry_result,
    credit_reference_result, sanctions_screening, idv_result, adverse_media, financial_statements.
    information_date YYYY-MM-DD (empty = undated = stale)."""
    if info_class not in DT5:
        return {"status": "error", "message": f"info_class must be one of {sorted(DT5)}"}
    return {"status": "ok", **assess(info_class, information_date or None, today(), policy())}
