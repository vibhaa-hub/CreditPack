"""Due diligence check rules: mandatory register (REQ-025..031 from DT-1 × parties), DT-3 outcome
to action and case effect, re-performance on expiry (BR-P11) and manual alternatives (REQ-035/092).
Hits are never cleared here: only a recorded human disposition clears a hit (REQ-032, BR-P03)."""
from .policy import Policy
from .validity import assess

CHECK_TYPES = ("kyc", "aml", "sanctions", "idv", "adverse_media", "fca_regulatory")
CHECK_VALIDITY_CLASS = {"sanctions": "sanctions_screening", "idv": "idv_result", "adverse_media": "adverse_media"}

# DT-3: outcome -> (required action, case effect, state effect)
DT3 = {
    "clear": ("Record result, source, list or data version and date", "Check complete", "complete"),
    "potential_match": ("Present to authorised person for disposition; record rationale",
                        "Hold - submission blocked until dispositioned", "hit_open"),
    "confirmed_match": ("Escalate per policy (OQ-02); apply any restriction on onward disclosure required by "
                        "law - verify with counsel", "Hold - case halted pending Financial Crime Compliance", "halted"),
    "unavailable": ("Use manual alternative with evidence (REQ-092) or hold", "Check open until evidenced", "open"),
    "expired": ("Re-perform (BR-P11)", "Check open", "open"),
    "idv_failed": ("Record failure; notify case owner; request alternative evidence", "Check open", "open"),
}
ALIASES = {"adverse_finding": "potential_match", "failed": "idv_failed", "match": "potential_match"}


def normalise_outcome(result: str) -> str:
    r = (result or "").strip().lower().replace(" ", "_")
    r = ALIASES.get(r, r)
    if r not in DT3:
        raise ValueError(f"unknown check outcome {result!r}; use one of {sorted(DT3)}")
    return r


def outcome(result: str) -> dict:
    """DT-3 row for a check outcome."""
    r = normalise_outcome(result)
    action, effect, state_effect = DT3[r]
    return {"outcome": r, "action": action, "case_effect": effect, "state_effect": state_effect,
            "opens_hit": state_effect in ("hit_open", "halted"), "halts_case": state_effect == "halted"}


def parties_from_state(state: dict) -> list[dict]:
    """Entity plus every recorded director, shareholder and UBO (BR-D02: all are screened)."""
    out = [{"name": state.get("dealer_name") or "dealer entity", "role": "entity", "individual": False}]
    seen = {out[0]["name"].lower()}
    for p in state.get("parties") or []:
        key = p["name"].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append({"name": p["name"], "role": p.get("role", "party"),
                        "individual": bool(p.get("individual", p.get("role") in ("director", "ubo")))})
    return out


def mandatory_register(checklist: dict, parties: list[dict]) -> list[dict]:
    """Which check each party needs, from the DT-1 markers. 'R' = required; 'C' = conditional
    (delta only: required for new or changed parties, or when the earlier result expired)."""
    out = []
    checks_marker, media_marker = checklist.get("checks"), checklist.get("media")
    for p in parties:
        if checks_marker in ("R", "C"):
            for chk in ("kyc", "aml", "sanctions") + (("idv",) if p["individual"] else ()):
                out.append({"party": p["name"], "role": p["role"], "check": chk, "marker": checks_marker})
        if media_marker in ("R", "C"):
            out.append({"party": p["name"], "role": p["role"], "check": "adverse_media", "marker": media_marker})
    if checklist.get("cra") in ("R", "C"):
        out.append({"party": "relationship", "role": "relationship", "check": "cra", "marker": checklist["cra"]})
    return out


def validate_manual(record: dict) -> list[str]:
    """REQ-035/092: a manual check or manual alternative needs performer, evidence and source."""
    missing = [f for f in ("performed_by", "evidence_ref", "tool_used") if not record.get(f)]
    return [f"manual check missing {m}" for m in missing]


def latest(records: list[dict], party: str, check: str) -> dict | None:
    hits = [r for r in records if r.get("party", "").lower() == party.lower() and r.get("check") == check]
    return hits[-1] if hits else None


def register_status(register: list[dict], records: list[dict], hits_open: list[dict], as_at: str,
                    policy: Policy, cra_recorded: bool) -> list[dict]:
    """Status of every register line: complete / outstanding / open / hold / halted / reperform."""
    status = []
    open_keys = {(h.get("party", "").lower(), h.get("check")) for h in hits_open or []}
    for line in register:
        st = dict(line)
        if line["check"] == "cra":
            st.update(status="complete" if cra_recorded else "outstanding",
                      reason=None if cra_recorded else "CRA outcome not recorded by the assessor (BR-D03)")
            status.append(st)
            continue
        rec = latest(records, line["party"], line["check"])
        if rec is None:
            st.update(status="outstanding", reason=f"{line['check']} not performed for {line['party']}")
        else:
            o = outcome(rec["result"])
            if (line["party"].lower(), line["check"]) in open_keys:
                st.update(status="halted" if o["halts_case"] else "hold", reason=o["case_effect"])
            elif o["state_effect"] == "complete" or (rec.get("manual") and not validate_manual(rec)
                                                    and o["outcome"] == "unavailable"):
                vc = CHECK_VALIDITY_CLASS.get(line["check"])
                v = assess(vc, rec.get("date"), as_at, policy) if vc else None
                if v and v["stale"]:
                    st.update(status="reperform", reason=f"{line['check']} expired: {v['action']} (BR-P11)")
                else:
                    st.update(status="complete", reason=None, manual=bool(rec.get("manual")))
            elif o["outcome"] in ("potential_match", "confirmed_match"):
                st.update(status="complete", reason=None, dispositioned=True)   # hit no longer open
            else:
                st.update(status="open", reason=o["case_effect"] + f" ({o['action']})")
        status.append(st)
    return status
