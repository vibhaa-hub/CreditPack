"""Due Diligence & Screening tools (P-04; REQ-025..037, DT-3, BR-P02/P03/P11, BR-D02).
No tool here can clear a hit: hits leave `hits_open` only through a recorded human decision."""
from google.adk.tools import ToolContext

from ..rules import checks as ch
from ..ldu.services import adapters
from ._common import S, append, collect, need_case, policy, today

RECORDABLE = ("kyc", "aml", "sanctions", "idv", "adverse_media", "fca_regulatory")


def sanctions_screen(party: str, tool_context: ToolContext) -> dict:
    """Screen one party against sanctions lists (STUB data until the screening adapter exists).
    Returns the result with list version and date; then record it with record_check_result."""
    r = adapters.lookup("sanctions", party=party)              # external-adapters LDU
    return {"status": "ok", "party": party, "result": r["result"],
            "list_version": r.get("list_version", "STUB"), "date": today()}


def adverse_media_search(party: str, tool_context: ToolContext) -> dict:
    """Adverse media search for one party (STUB data until the adapter exists). Anything adverse is
    a potential_match for human disposition."""
    r = adapters.lookup("adverse_media", party=party)          # external-adapters LDU
    return {"status": "ok", "party": party, "result": r["result"],
            "sources_searched": r.get("sources_searched", ["STUB news index"]), "date": today()}


def record_check_result(party: str, check: str, result: str, tool_used: str, evidence_ref: str,
                        tool_context: ToolContext, manual: bool = False, performed_by: str = "",
                        scope: str = "", check_date: str = "") -> dict:
    """Record one check (REQ-033). check: kyc | aml | sanctions | idv | adverse_media | fca_regulatory.
    result: clear | potential_match | confirmed_match | unavailable | expired | idv_failed.
    Evidence is mandatory. A manual check also needs performed_by (REQ-035/092). A potential or
    confirmed match opens a hit that only an authorised human can disposition (DT-3)."""
    st = S(tool_context)
    if err := need_case(st):
        return err
    if check not in RECORDABLE:
        return {"status": "error", "message": f"check must be one of {RECORDABLE}"}
    if check == "fca_regulatory" and not policy().is_set("fca_regulatory_scope"):
        return {"status": "error", "message": "FCA regulatory check scope NOT CONFIGURED (OQ-01)"}
    if not evidence_ref:
        return {"status": "error", "message": "evidence required (REQ-033/035)"}
    try:
        o = ch.outcome(result)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    rec = dict(party=party, check=check, result=o["outcome"], tool_used=tool_used, evidence_ref=evidence_ref,
               manual=bool(manual), performed_by=performed_by or tool_context.agent_name, scope=scope,
               date=check_date or today(), list_version=None)
    if manual and (missing := ch.validate_manual({**rec, "performed_by": performed_by})):
        return {"status": "error", "message": "; ".join(missing)}
    append(st, "checks", rec, tool_context)
    if o["opens_hit"]:
        append(st, "hits_open", dict(party=party, check=check, result=o["outcome"], evidence_ref=evidence_ref), tool_context)
    if o["halts_case"]:
        st["case_halted"] = True
    return {"status": "ok", "dt3_action": o["action"], "case_effect": o["case_effect"], "hit_opened": o["opens_hit"]}


def request_hit_disposition(party: str, check: str, tool_context: ToolContext) -> dict:
    """HUMAN GATE: ask an authorised analyst to disposition a hit. This never clears it (REQ-032)."""
    st = S(tool_context)
    item = f"hit disposition: {party}/{check}"
    if item not in collect(st, "pending_human"):
        append(st, "pending_human", item, tool_context)
    return {"status": "pending_human", "message": "sent to authorised analyst; submission blocked until dispositioned"}


def check_register(tool_context: ToolContext) -> dict:
    """Every mandatory party × check from the DT-1 checklist with its status (complete, outstanding,
    open, reperform, hold, halted) and reason, plus open hits and CRA status (BR-D02, BR-D03)."""
    st = S(tool_context)
    if not st.get("checklist"):
        return {"status": "error", "message": "build the requirement checklist first"}
    pol = policy()
    reg = ch.mandatory_register(st["checklist"], ch.parties_from_state(st))
    status = ch.register_status(reg, collect(st, "checks"), collect(st, "hits_open"), today(), pol,
                                bool(st.get("cra_recorded_by")))
    st["check_register"] = status
    summary = {k: sum(1 for s in status if s["status"] == k) for k in
               ("complete", "outstanding", "open", "reperform", "hold", "halted")}
    return {"status": "ok", "summary": summary, "register": status, "hits_open": collect(st, "hits_open"),
            "cra_recorded": bool(st.get("cra_recorded_by")), "policy_version": pol.version}
