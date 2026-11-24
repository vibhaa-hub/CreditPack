"""Agent mesh end to end with scripted models: structure, parallel branches, partition merges,
gate routing, human decisions and replay (agent-mesh tasks 3.3, 4.1-4.4)."""
import asyncio

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from cpa_agents.mesh.orchestrator import build_workflows
from cpa_agents.store.replay import replay
from cpa_agents.store.runtime import record_human_decision
from fakes import ScriptedLlm, factory

APP, USER = "cpa", "u"
REQUEST = "OEM referral. Dealer Acme Motors Ltd 01234567, increased borrowing to 5,500,000. Owner Jane Smith."
CHK = lambda party, check, ev: ("record_check_result", {"party": party, "check": check, "result": "clear",
                                                        "tool_used": "stub", "evidence_ref": ev})
SEC = lambda s, text: ("save_template_section", {"section": s, "text": text, "evidence_refs": ["FY2025 accounts"]})

SCRIPTS = {
    "intake_classifier": [("register_case", {"dealer_name": "Acme Motors Ltd", "registered_number": "01234567",
                                             "case_types": ["increased borrowing request"], "source": "OEM partner",
                                             "owner": "Jane Smith"}),
                          ("get_requirement_checklist", {})],
    "entity_structure": [("record_party", {"name": "A. Director", "role": "director", "source": "application form"}),
                         ("record_party", {"name": "A. Director", "role": "shareholder", "ownership_pct": 100,
                                           "source": "application form"}),
                         ("companies_house_lookup", {"registered_number": "01234567"}),
                         ("compare_with_registry", {}),
                         ("record_verification", {"subject": "Acme Motors Ltd", "outcome": "verified",
                                                  "evidence_ref": "CH record"})],
    "document_ingestion": [("record_info_item", {"info_class": c, "value": v, "source": "application form",
                                                 "provider": "dealer", "as_at_date": "2026-11-03"})
                           for c, v in (("consent", "consent to searches"), ("data_protection", "DP notice signed"),
                                        ("entity", "Acme Motors Ltd"), ("director", "A. Director"),
                                        ("shareholder", "A. Director 100%"), ("security", "debenture"))]
                          + [("record_financial_statement", {"period_end": "2025-12-31", "audited": True, "currency": "GBP",
                                                             "source": "FY2025 accounts", "total_borrowings": 4_500_000,
                                                             "net_worth": 3_000_000, "turnover": 15_000_000,
                                                             "net_profit": 450_000})],
    "bureau_external": [("credit_reference_lookup", {})],
    "dd_sanctions": [CHK(p, "sanctions", "screen-1") for p in ("Acme Motors Ltd", "A. Director")],
    "dd_identity": [CHK(p, c, "id-1") for p in ("Acme Motors Ltd", "A. Director") for c in ("kyc", "aml")]
                   + [CHK("A. Director", "idv", "id-2")],
    "dd_adverse_media": [CHK(p, "adverse_media", "media-1") for p in ("Acme Motors Ltd", "A. Director")],
    "dd_summary": [("check_register", {})],
    "gap_consolidator": [("list_info_gaps", {})],
    "pack_request": [("record_lending_request", {"facility_type": "wholesale", "amount": 5_500_000,
                                                 "purpose": "stock funding", "current_limit": 4_500_000}),
                     ("request_pricing_authorisation", {})],
    "financial_analysis": [("record_facility", {"lending_line": "wholesale", "drawn": 3_600_000, "limit": 4_500_000,
                                                "as_at_date": "2026-11-01", "source": "facility system"}),
                           ("calculate_measures", {})],
    "nd_business_background": [SEC("business_background", "Acme Motors Ltd is a franchise dealer.")],
    "nd_management_assessment": [SEC("management_assessment", "A. Director runs the business.")],
    "nd_conduct_performance": [SEC("conduct_performance", "Gearing is 1.50x and utilisation 80.00%.")],
    "nd_security_esg": [SEC("security_review", "A debenture is held.")],
    "nd_critic": [("review_drafts", {})],
    "pack_validation": [("run_completeness_gate", {})],
    "pack_transmit": [("run_completeness_gate", {}), ("transmit_pack", {})],
}


async def _run(wf, sessions, sid, text):
    r = Runner(agent=wf, app_name=APP, session_service=sessions)
    async for _ in r.run_async(user_id=USER, session_id=sid,
                               new_message=types.Content(role="user", parts=[types.Part(text=text)])):
        pass
    return (await sessions.get_session(app_name=APP, user_id=USER, session_id=sid)).state


@pytest.fixture
def mesh(store):
    f = factory(SCRIPTS)
    return build_workflows(llm=f), f


def test_graph_structure(mesh):
    wf, _ = mesh
    names = {n.name for n in wf["preparation"].graph.nodes}
    assert {"capture_request", "intake_classifier", "entity_structure", "document_ingestion", "due_diligence",
            "bureau_external", "evidence_join", "merge_evidence", "gap_consolidator", "pack_request",
            "financial_analysis", "narrative_drafting", "pack_validation", "await_humans"} <= names
    assert {n.name for n in wf["due_diligence"].graph.nodes} >= {"dd_sanctions", "dd_identity", "dd_adverse_media",
                                                                 "dd_join", "merge_due_diligence", "dd_summary"}
    assert {n.name for n in wf["narrative_drafting"].graph.nodes} >= {"nd_business_background", "nd_critic", "merge_drafts"}


def test_no_agent_can_record_a_human_decision(mesh):
    wf, _ = mesh
    forbidden = {"record_human_decision", "rollback_to_snapshot", "resolve_credit_query", "raise_credit_query"}
    for ag in wf["agents"].values():
        assert not ({getattr(tl, "__name__", "") for tl in ag.tools} & forbidden), ag.name
        assert all(not getattr(tl, "__name__", "").startswith(("authorise", "approve", "clear_")) for tl in ag.tools)


def test_instruction_scopes_context(mesh, store):
    wf, f = mesh
    from cpa_agents.mesh.instructions import context_for
    a = wf["agents"]
    state = {"case_id": "C", "parties": [{"name": "A. Director"}], "financial_statements": [{"p": 1}],
             "checks@dd_identity": [{"check": "kyc"}]}
    fin = context_for(state, a["financial_analysis"].instruction.reads)
    assert "parties" not in fin and fin["financial_statements"] == [{"p": 1}]       # no personal data
    dd = context_for(state, a["dd_summary"].instruction.reads)
    assert dd["checks"] == [{"check": "kyc"}] and "financial_statements" not in dd   # partitions folded in
    text = a["dd_sanctions"].instruction(type("C", (), {"state": state})())
    assert "## Your part: sanctions" in text and "## Sub-agent: identity" not in text and "Runtime rules" in text


def test_preparation_runs_branches_merges_and_stops_at_humans(mesh, store):
    wf, f = mesh

    async def go():
        sessions = InMemorySessionService()
        await sessions.create_session(app_name=APP, user_id=USER, session_id="m1")
        return await _run(wf["preparation"], sessions, "m1", REQUEST)
    st = asyncio.run(go())
    assert st["request_text"] == REQUEST
    assert len(st["checks"]) == 2 + 4 + 1 + 2 and not any("@" in k and st[k] for k in st)   # partitions merged
    assert set(st["sections"]) == {"business_background", "management_assessment", "conduct_performance", "security_review"}
    assert st["measures"]["gearing_x"] == 1.5 and st["measures"]["utilisation_pct"] == 80.0
    assert st["gate_status"] == "BLOCKED" and "submitted" not in st
    reasons = " | ".join(g["reason"] for g in st["gate_result"]["gaps"])
    assert "pricing and terms authorisation missing" in reasons and "CRA" in reasons and "not accepted" in reasons
    assert store.pack_versions(st["case_id"]) == []
    out = replay(st["case_id"])
    actors = {e["actor"] for e in out["events"]}
    assert set(SCRIPTS) - {"pack_transmit"} <= actors and "orchestrator" in actors
    assert out["chains"]["m1"]["ok"]


def test_submission_blocked_then_passes_after_humans(mesh, store):
    wf, f = mesh

    async def go():
        sessions = InMemorySessionService()
        await sessions.create_session(app_name=APP, user_id=USER, session_id="m2")
        st = await _run(wf["preparation"], sessions, "m2", REQUEST)
        blocked = await _run(wf["submission"], sessions, "m2", "transmit")
        sections = {k: {**v, "reviewed": True} for k, v in st["sections"].items()}
        await record_human_decision(sessions, APP, USER, "m2", "Jane Smith", {
            "cra_recorded_by": "analyst-7", "pricing_authorised_by": "pricing-committee-2",
            "sections": sections, "submission_authorised_by": "Jane Smith"}, "humans acted")
        done = await _run(wf["submission"], sessions, "m2", "transmit")
        return blocked, done
    blocked, done = asyncio.run(go())
    assert "submitted" not in blocked and blocked["gate_status"] == "BLOCKED"
    assert done["submitted"]["pack_version"] == 1 and store.pack_versions(done["case_id"])[0]["sha256"] == done["submitted"]["sha256"]
    actions = [e["action"] for e in replay(done["case_id"])["events"]]
    assert "submission_blocked" in actions and actions.count("submission_gate") == 2
    assert replay(done["case_id"])["chains"]["m2"]["ok"]
