import asyncio

from google.adk.sessions import InMemorySessionService

from cpa_agents.store.runtime import record_human_decision, rollback_to_snapshot

APP, USER, SID = "cpa", "u1", "hd-1"


async def _session(state=None):
    sessions = InMemorySessionService()
    await sessions.create_session(app_name=APP, user_id=USER, session_id=SID, state=state or {})
    return sessions


def test_decision_is_audited_and_applied(store):
    async def go():
        sessions = await _session({"case_id": "CASE-1", "hits_open": [{"party": "X"}]})
        ev = await record_human_decision(sessions, APP, USER, SID, "analyst-7",
                                         {"hits_open": [], "cra_recorded_by": "analyst-7"}, "hit cleared, CRA")
        s = await sessions.get_session(app_name=APP, user_id=USER, session_id=SID)
        return ev, s
    ev, s = asyncio.run(go())
    assert s.state["hits_open"] == [] and s.state["cra_recorded_by"] == "analyst-7"
    events = store.events(SID)
    assert len(events) == 1 and events[0]["action"] == "human_decision"
    assert events[0]["actor_type"] == "human" and events[0]["actor"] == "analyst-7"
    assert events[0]["args"]["cra_recorded_by"] == "analyst-7" and events[0]["case_id"] == "CASE-1"
    assert events[0]["detail"] == {"label": "hit cleared, CRA"} and ev["hash"] == events[0]["hash"]


def test_section_review_creates_section_version(store):
    draft = {"text": "Acme trades well.", "evidence": ["acc-2025"], "label": "non-human draft", "reviewed": False}

    async def go():
        sessions = await _session({"case_id": "CASE-1", "sections": {"background": draft}})
        await record_human_decision(sessions, APP, USER, SID, "Jane Smith",
                                    {"sections": {"background": {**draft, "reviewed": True}}}, "reviewed")
    asyncio.run(go())
    v = store.section_versions("CASE-1", "background")
    assert len(v) == 1 and v[0]["reviewed"] is True and v[0]["actor"] == "Jane Smith"


def test_rollback_is_an_audited_decision(store):
    store.save_snapshot(SID, "p01_intake", {"case_id": "CASE-1", "gate_status": None})

    async def go():
        sessions = await _session({"case_id": "CASE-1", "gate_status": "PASS", "submitted": {"x": 1}})
        snap = store.snapshots(SID)[0]["id"]
        await rollback_to_snapshot(sessions, APP, USER, SID, "ops-lead", snap)
        return snap, await sessions.get_session(app_name=APP, user_id=USER, session_id=SID)
    snap, s = asyncio.run(go())
    assert s.state["gate_status"] is None and s.state.get("submitted") is None
    ev = store.events(SID)[-1]
    assert ev["action"] == "human_decision" and ev["detail"]["label"] == f"rollback to snapshot {snap}"
