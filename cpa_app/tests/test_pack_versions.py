import copy

from google.adk.sessions.state import State

from cpa_agents import tools as t
from cpa_agents.store.pack import assemble_pack
from conftest import fake_ctx

from test_gate_rules import READY as GATE_READY

READY = {**copy.deepcopy(GATE_READY), "case_id": "CASE-20261114-000001", "registered_number": "01234567",
         "case_types": ["increased borrowing request"], "source": "OEM partner", "owner": "Jane Smith",
         "gate_status": "PASS", "submission_authorised_by": "Jane Smith",
         "p06_summary": "working text that is not pack material"}


def test_same_state_same_hash_and_order_independent():
    a = assemble_pack(copy.deepcopy(READY))
    reordered = dict(reversed(list(copy.deepcopy(READY).items())))
    assert a == assemble_pack(reordered)
    assert "p06_summary" not in str(a) and list(a["sections"]) == sorted(READY["sections"])


def test_transmit_creates_version_and_submission(store):
    ctx = fake_ctx(state=copy.deepcopy(READY))
    r = t.transmit_pack(ctx)
    assert r["status"] == "ok" and r["pack_version"] == 1 and len(r["sha256"]) == 64
    assert r["receipt"].startswith("NOT-TRANSMITTED") and r["submission_id"]
    v = store.pack_versions(READY["case_id"])
    assert len(v) == 1 and v[0]["sha256"] == r["sha256"] and v[0]["created_by"] == "Jane Smith"


def test_second_transmit_is_version_2_and_version_1_unchanged(store):
    ctx = fake_ctx(state=copy.deepcopy(READY))
    first = t.transmit_pack(ctx)
    v1_before = store.pack_versions(READY["case_id"])[0]
    ctx.state["measures"] = {"gearing_x": 1.5, "utilisation_pct": 80.0, "current_ratio": 1.55}
    second = t.transmit_pack(ctx)
    versions = store.pack_versions(READY["case_id"])
    assert second["pack_version"] == 2 and second["sha256"] != first["sha256"]
    assert versions[0] == v1_before and versions[0]["content"]["measures"] == {"gearing_x": 1.5, "utilisation_pct": 80.0}


def test_identical_state_gives_identical_hash_across_transmits(store):
    ctx = fake_ctx(state=copy.deepcopy(READY))
    assert t.transmit_pack(ctx)["sha256"] == t.transmit_pack(ctx)["sha256"]


def test_transmit_blocked_when_case_incomplete_or_unauthorised(store):
    # the stored gate_status flag is not trusted: transmit re-runs the gate itself
    for missing in ("lending_request", "submission_authorised_by", "cra_recorded_by"):
        st = copy.deepcopy(READY)
        st.pop(missing)
        assert t.transmit_pack(fake_ctx(state=st))["status"] == "blocked", missing
    assert store.pack_versions(READY["case_id"]) == []


def test_owner_must_authorise_submission(store):
    st = copy.deepcopy(READY)
    st["submission_authorised_by"] = "Somebody Else"
    r = t.transmit_pack(fake_ctx(state=st))
    assert r["status"] == "blocked" and "BR-E01" in r["reason"]


def test_transmit_re_evaluates_gate_even_if_state_says_pass(store):
    st = copy.deepcopy(READY)
    st["hits_open"] = [{"party": "A. Director", "check": "sanctions"}]      # gate_status still "PASS"
    assert t.transmit_pack(fake_ctx(state=st))["status"] == "blocked"


def test_works_with_real_adk_state_object(store):
    ctx = fake_ctx(state=State(copy.deepcopy(READY), {}))
    assert t.transmit_pack(ctx)["pack_version"] == 1
