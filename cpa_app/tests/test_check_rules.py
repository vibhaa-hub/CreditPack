import pytest

from cpa_agents.rules import checks as ch
from cpa_agents.rules.policy import from_dict

POL = from_dict({"version": "t", "validity_days": {"sanctions_screening": 90, "idv_result": 365, "adverse_media": 90}})
STATE = {"dealer_name": "Acme Motors Ltd",
         "parties": [{"name": "A. Director", "role": "director", "individual": True},
                     {"name": "Acme Holdings Ltd", "role": "shareholder", "individual": False},
                     {"name": "a. director", "role": "shareholder"}]}          # same person, deduplicated


@pytest.mark.parametrize("result,effect,hit,halt", [
    ("clear", "Check complete", False, False),
    ("potential_match", "Hold - submission blocked until dispositioned", True, False),
    ("confirmed_match", "Hold - case halted pending Financial Crime Compliance", True, True),
    ("unavailable", "Check open until evidenced", False, False),
    ("expired", "Check open", False, False),
    ("idv_failed", "Check open", False, False),
])
def test_each_dt3_row(result, effect, hit, halt):
    o = ch.outcome(result)
    assert o["case_effect"] == effect and o["opens_hit"] is hit and o["halts_case"] is halt
    assert o["action"] == ch.DT3[result][0]


def test_aliases_and_unknown_outcome():
    assert ch.outcome("Adverse finding")["outcome"] == "potential_match"
    with pytest.raises(ValueError):
        ch.outcome("probably fine")


def test_parties_include_entity_and_dedupe():
    ps = ch.parties_from_state(STATE)
    assert [p["name"] for p in ps] == ["Acme Motors Ltd", "A. Director", "Acme Holdings Ltd"]
    assert [p["individual"] for p in ps] == [False, True, False]


def test_register_new_dealer_relationship():
    reg = ch.mandatory_register({"checks": "R", "media": "R", "cra": "R"}, ch.parties_from_state(STATE))
    by = {(r["party"], r["check"]) for r in reg}
    assert ("A. Director", "idv") in by and ("Acme Motors Ltd", "idv") not in by     # ID&V only individuals
    assert all((p, c) in by for p in ("Acme Motors Ltd", "A. Director", "Acme Holdings Ltd")
               for c in ("kyc", "aml", "sanctions", "adverse_media"))
    assert ("relationship", "cra") in by and len(reg) == 3 * 4 + 1 + 1


def test_register_director_change_and_none():
    reg = ch.mandatory_register({"checks": "C", "media": "R", "cra": "R"}, ch.parties_from_state(STATE))
    assert {r["marker"] for r in reg if r["check"] == "sanctions"} == {"C"}
    assert ch.mandatory_register({"checks": "N/A", "media": "N/A", "cra": "N/A"}, ch.parties_from_state(STATE)) == []


def _status(records, hits=(), cra=True):
    reg = ch.mandatory_register({"checks": "R", "media": "N/A", "cra": "R"},
                                [{"name": "A. Director", "role": "director", "individual": True}])
    return {(s["check"]): s for s in ch.register_status(reg, records, list(hits), "2026-10-23", POL, cra)}


def test_status_outstanding_complete_reperform_hold_open():
    recs = [{"party": "A. Director", "check": "kyc", "result": "clear", "date": "2026-10-20"},
            {"party": "A. Director", "check": "sanctions", "result": "clear", "date": "2026-05-01"},
            {"party": "A. Director", "check": "idv", "result": "idv_failed", "date": "2026-10-20"}]
    s = _status(recs)
    assert s["kyc"]["status"] == "complete"
    assert s["aml"]["status"] == "outstanding"
    assert s["sanctions"]["status"] == "reperform" and "Re-screen" in s["sanctions"]["reason"]
    assert s["idv"]["status"] == "open" and "alternative evidence" in s["idv"]["reason"]
    held = _status([{"party": "A. Director", "check": "kyc", "result": "potential_match", "date": "2026-10-20"}],
                   hits=[{"party": "A. Director", "check": "kyc"}])
    assert held["kyc"]["status"] == "hold"


def test_manual_alternative_needs_evidence_and_counts_when_complete():
    bare = {"party": "A. Director", "check": "aml", "result": "unavailable", "date": "2026-10-20", "manual": True}
    assert ch.validate_manual(bare) == ["manual check missing performed_by", "manual check missing evidence_ref",
                                        "manual check missing tool_used"]
    assert _status([bare])["aml"]["status"] == "open"
    full = {**bare, "performed_by": "analyst-7", "evidence_ref": "doc-55", "tool_used": "manual register search"}
    assert _status([full])["aml"] == {**_status([full])["aml"], "status": "complete", "manual": True}


def test_cra_must_be_recorded():
    assert _status([], cra=False)["cra"]["status"] == "outstanding"
    assert _status([], cra=True)["cra"]["status"] == "complete"
