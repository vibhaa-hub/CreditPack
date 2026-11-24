import asyncio
import copy

from google.adk.sessions import InMemorySessionService

from cpa_agents import agent as a
from cpa_agents import tools as t
from cpa_agents.store.runtime import raise_credit_query, resolve_credit_query
from conftest import fake_ctx
from test_pack_versions import READY

APP, USER, SID = "cpa", "u", "cq-1"
CASE = READY["case_id"]


async def _submitted_session(store):
    sessions = InMemorySessionService()
    await sessions.create_session(app_name=APP, user_id=USER, session_id=SID, state=copy.deepcopy(READY))
    t.transmit_pack(fake_ctx(session_id=SID, state=copy.deepcopy(READY)))     # version 1
    return sessions


def test_pack_changing_resolution_creates_linked_version(store):
    async def go():
        sessions = await _submitted_session(store)
        qid = await raise_credit_query(sessions, APP, USER, SID, "credit-uw-3", "Explain stock days", owner="Jane Smith")
        s = await sessions.get_session(app_name=APP, user_id=USER, session_id=SID)
        s.state["measures"] = {"gearing_x": 1.5, "stock_days": 62}       # the response changes the pack
        return qid, await resolve_credit_query(sessions, APP, USER, SID, "Jane Smith", qid, "added stock days", True)
    qid, out = asyncio.run(go())
    versions = store.pack_versions(CASE)
    assert [v["version"] for v in versions] == [1, 2] and out["pack_version"]["version"] == 2
    q = store.credit_queries(CASE)[0]
    assert q["status"] == "resolved" and q["pack_version_id"] == versions[1]["id"]
    assert versions[1]["reason"] == f"response to credit query {qid}"
    actions = [e["action"] for e in store.events(SID)]
    assert actions[-2:] == ["credit_query_raised", "credit_query_resolved"]


def test_non_changing_resolution_creates_no_version(store):
    async def go():
        sessions = await _submitted_session(store)
        qid = await raise_credit_query(sessions, APP, USER, SID, "credit-uw-3", "Confirm audit status")
        return await resolve_credit_query(sessions, APP, USER, SID, "Jane Smith", qid, "accounts are audited", False)
    out = asyncio.run(go())
    assert out["pack_version"] is None and len(store.pack_versions(CASE)) == 1
    assert store.credit_queries(CASE)[0]["pack_version_id"] is None


def test_agent_tool_lists_queries_read_only(store):
    q1 = store.record_credit_query(CASE, "credit-uw-3", "q1", owner="Jane Smith")
    store.record_credit_query(CASE, "credit-uw-3", "q2")
    store.resolve_credit_query(q1, "done", "Jane Smith", pack_changed=False)
    r = t.list_credit_queries(fake_ctx(state={"case_id": CASE}))
    assert [q["text"] for q in r["open"]] == ["q2"] and [q["text"] for q in r["resolved"]] == ["q1"]
    assert t.list_credit_queries in a.agents["pack_transmit"].tools


def test_resolved_query_cannot_be_resolved_again(store):
    import pytest
    q = store.record_credit_query(CASE, "credit-uw-3", "q")
    store.resolve_credit_query(q, "done", "Jane", pack_changed=False)
    with pytest.raises(ValueError):
        store.resolve_credit_query(q, "again", "Jane", pack_changed=False)
