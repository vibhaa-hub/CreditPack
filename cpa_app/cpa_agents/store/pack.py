"""Deterministic credit pack assembly (design decision 7): the same case state always
yields the same pack content, and therefore the same SHA-256."""

PACK_SCHEMA = "cpa-pack/1"

_HEADER = ("case_id", "dealer_name", "registered_number", "case_types", "source", "owner", "received_at")


def assemble_pack(state: dict) -> dict:
    """Build the pack content from case state. Only pack material is included: no agent
    summaries, pending-human lists or other working keys."""
    sections = state.get("sections") or {}
    return {
        "schema": PACK_SCHEMA,
        "header": {k: state.get(k) for k in _HEADER},
        "checklist": state.get("checklist"),
        "information": state.get("info_items") or [],
        "registry_record": state.get("registry_record"),
        "verifications": state.get("verifications") or [],
        "checks": state.get("checks") or [],
        "cra_recorded_by": state.get("cra_recorded_by"),
        "measures": state.get("measures"),
        "sections": {k: sections[k] for k in sorted(sections)},
        "lending_request": state.get("lending_request"),
        "pricing_authorised_by": state.get("pricing_authorised_by"),
        "gate_status": state.get("gate_status"),
    }
