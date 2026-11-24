"""Entity & Structure tools (P-03; REQ-020..024, BR-D01, BR-D10)."""
from google.adk.tools import ToolContext

from ..rules.registry import compare_all
from ..ldu.services import adapters
from ._common import S, append, need_case, policy, today

ROLES = ("director", "shareholder", "ubo")


def record_party(name: str, role: str, tool_context: ToolContext, ownership_pct: float | None = None,
                 individual: bool | None = None, source: str = "") -> dict:
    """Record a director, shareholder or ultimate beneficial owner the dealer supplied (REQ-009/010).
    role: director | shareholder | ubo. ownership_pct for shareholders/UBOs. individual: True for a
    person, False for a company (a corporate shareholder needs its beneficial owners)."""
    st = S(tool_context)
    if err := need_case(st):
        return err
    if role not in ROLES:
        return {"status": "error", "message": f"role must be one of {ROLES}"}
    if not source:
        return {"status": "error", "message": "no source: party would be unverified (BR-G03)"}
    ind = individual if individual is not None else role != "shareholder" or not _looks_corporate(name)
    parties = [p for p in st.get("parties") or [] if not (p["name"].lower() == name.lower() and p["role"] == role)]
    parties.append(dict(name=name, role=role, pct=ownership_pct, individual=bool(ind), source=source))
    st["parties"] = parties
    out = {"status": "ok", "parties": len(parties)}
    if role == "shareholder" and not ind:
        out["note"] = f"{name} is corporate: record its beneficial owners (REQ-010)"
    return out


def _looks_corporate(name: str) -> bool:
    n = name.lower()
    return any(w in n for w in (" ltd", " limited", " plc", " llp", " holdings", " group"))


def companies_house_lookup(registered_number: str, tool_context: ToolContext) -> dict:
    """Fetch the Companies House record (STUB data until the adapter exists). Unknown numbers are
    'unavailable': record a manual alternative with evidence (REQ-092)."""
    st = S(tool_context)
    rec = adapters.lookup("companies_house", registered_number=registered_number)["record"]   # external-adapters LDU
    if not rec:
        st["registry_record"] = {"registered_number": registered_number, "status": "unavailable",
                                 "retrieved": today(), "provider": "Companies House (STUB)"}
        return {"status": "unavailable", "message": "no registry record; manual alternative with evidence needed"}
    rec = {**rec, "retrieved": today(), "provider": "Companies House (STUB)"}
    st["registry_record"] = rec
    return {"status": "ok", "record": rec}


def compare_with_registry(tool_context: ToolContext) -> dict:
    """Compare the dealer-supplied entity, directors and shareholders (with %) against the registry
    record (REQ-020/021) and reconcile ownership (BR-D10). Stores every discrepancy as unresolved:
    only the case owner resolves them (BR-D01)."""
    st = S(tool_context)
    if err := need_case(st):
        return err
    reg = st.get("registry_record") or {}
    if not reg.get("entity"):
        return {"status": "error", "message": "no registry record to compare: run companies_house_lookup"}
    parties = st.get("parties") or []
    supplied = {"entity": {"name": st.get("dealer_name"), "registered_number": st.get("registered_number")},
                "directors": [p["name"] for p in parties if p["role"] == "director"],
                "shareholders": [{"name": p["name"], "pct": p.get("pct")} for p in parties if p["role"] == "shareholder"]}
    res = compare_all(supplied, reg, policy())
    st["registry_discrepancies"] = [{**d, "resolved_by": None} for d in res["discrepancies"]]
    st["ownership"] = res["ownership"]
    return {"status": "ok", **res}


def record_verification(subject: str, outcome: str, evidence_ref: str, tool_context: ToolContext) -> dict:
    """Record an entity or individual verification outcome. Evidence is mandatory (REQ-024)."""
    if not evidence_ref:
        return {"status": "error", "message": "evidence required"}
    append(S(tool_context), "verifications", dict(subject=subject, outcome=outcome, evidence=evidence_ref, date=today()))
    return {"status": "ok"}
