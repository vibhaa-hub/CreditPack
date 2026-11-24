from types import SimpleNamespace

from cpa_agents import agent as a
from conftest import fake_ctx


def test_callbacks_write_three_event_types_and_a_snapshot(store):
    ctx = fake_ctx(session_id="cb-1", agent="p05_financial", state={"case_id": "CASE-X", "measures": {"g": 1.5}})
    tool = SimpleNamespace(name="calculate_measures")
    args = {"total_borrowings": 4_500_000, "net_worth": 3_000_000}

    assert a.audit_before_tool(tool, args, ctx) is None
    assert a.audit_after_tool(tool, args, ctx, {"status": "ok", "measures": {"gearing_x": 1.5}}) is None
    assert a.audit_after_agent(ctx) is None

    events = store.events("cb-1")
    assert [e["action"] for e in events] == ["tool_called", "tool_result", "agent_complete"]
    assert events[0]["args"] == args and events[0]["actor"] == "p05_financial"
    assert events[1]["result_status"] == "ok"
    snaps = store.snapshots("cb-1")
    assert len(snaps) == 1 and events[2]["detail"] == {"snapshot_id": snaps[0]["id"]}
    assert store.get_snapshot("cb-1")["state"] == {"case_id": "CASE-X", "measures": {"g": 1.5}}
    assert store.verify_chain("cb-1")["ok"]


def test_audit_log_is_no_longer_kept_in_state(store):
    ctx = fake_ctx(session_id="cb-2")
    a.audit_before_tool(SimpleNamespace(name="x"), {}, ctx)
    a.audit_after_agent(ctx)
    assert "audit_log" not in ctx.state


def test_snapshot_excludes_internal_and_temp_keys(store):
    ctx = fake_ctx(session_id="cb-3", state={"case_id": "C", "_internal": 1, "temp:scratch": 2})
    a.audit_after_agent(ctx)
    assert store.get_snapshot("cb-3")["state"] == {"case_id": "C"}


def test_every_agent_has_all_three_callbacks():
    assert len(a.agents) == 19
    for ag in a.agents.values():
        assert ag.before_tool_callback is a.audit_before_tool
        assert ag.after_tool_callback is a.audit_after_tool
        assert ag.after_agent_callback is a.audit_after_agent
