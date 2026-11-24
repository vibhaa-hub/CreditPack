import re
from datetime import datetime

from cpa_agents import tools as t
from conftest import fake_ctx


def _register(ctx, name="Acme Motors Ltd"):
    return t.register_case(name, "01234567", ["new franchise application"], "OEM partner",
                           "Jane Smith", ctx)


def test_three_cases_same_day_get_distinct_ids_with_time(store):
    results = [_register(fake_ctx(session_id=f"s{i}")) for i in range(3)]
    ids = [r["case_id"] for r in results]
    assert len(set(ids)) == 3
    assert all(re.fullmatch(r"CASE-\d{8}-\d{6}", i) for i in ids)
    for r in results:
        received = datetime.fromisoformat(r["received_at"])
        assert received.tzinfo is not None                 # date AND time, in UTC
        assert (received.hour, received.minute, received.second, received.microsecond) != (0, 0, 0, 0)


def test_case_is_persisted_and_linked_to_session(store):
    ctx = fake_ctx(session_id="sess-xyz")
    r = _register(ctx)
    assert ctx.state["case_id"] == r["case_id"] and ctx.state["received_at"] == r["received_at"]
    row = store.get_case(r["case_id"])
    assert row["session_id"] == "sess-xyz" and row["owner"] == "Jane Smith"
    assert store.case_for_session("sess-xyz") == r["case_id"]


def test_invalid_source_creates_no_case(store, ctx):
    r = t.register_case("X", "1", ["new dealer relationship"], "carrier pigeon", "Jane", ctx)
    assert r["status"] == "error" and "case_id" not in ctx.state
    assert store.case_for_session(ctx.session.id) is None
