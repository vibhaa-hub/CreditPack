import threading

from sqlalchemy import select

from cpa_agents.store.core import GENESIS
from cpa_agents.store.schema import audit_events


def _rows(store, session_id):
    with store.engine.connect() as c:
        return [dict(r) for r in c.execute(select(audit_events).where(audit_events.c.session_id == session_id)
                                           .order_by(audit_events.c.seq)).mappings()]


def _fill(store, sid="s1", n=5):
    for i in range(n):
        store.append_event(sid, "agent", "p01_intake", "tool_called", tool="register_case",
                           args={"i": i, "dealer": "Acme"})


def test_valid_chain_verifies(store):
    _fill(store)
    rows = _rows(store, "s1")
    assert rows[0]["prev_hash"] == GENESIS and rows[0]["seq"] == 1
    assert all(b["prev_hash"] == a["hash"] for a, b in zip(rows, rows[1:]))
    assert store.verify_chain("s1") == {"ok": True, "events": 5, "broken_at": None}


def test_altered_row_reports_broken_link(store):
    _fill(store)
    rows = _rows(store, "s1")            # copy outside the database (no triggers apply)
    rows[2]["args"] = {"i": 2, "dealer": "Someone Else"}
    assert store.verify_chain("s1", rows=rows) == {"ok": False, "events": 5, "broken_at": 3}


def test_deleted_row_reports_broken_link(store):
    _fill(store)
    rows = _rows(store, "s1")
    del rows[1]
    assert store.verify_chain("s1", rows=rows)["broken_at"] == 3


def test_chains_are_per_session(store):
    _fill(store, "a", 2)
    _fill(store, "b", 3)
    assert store.verify_chain("a")["events"] == 2 and store.verify_chain("b")["events"] == 3


def test_concurrent_appends_keep_one_valid_chain(store):
    threads = [threading.Thread(target=_fill, args=(store, "par", 10)) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert store.verify_chain("par") == {"ok": True, "events": 40, "broken_at": None}


def test_full_arguments_are_kept(store):
    long_text = "x" * 500
    ev = store.append_event("s1", "agent", "p06", "tool_called", tool="save_template_section",
                            args={"text": long_text})
    assert ev["args"]["text"] == long_text
    assert _rows(store, "s1")[0]["args"]["text"] == long_text
