"""Workbench: financial differences are listed, wait on the case owner, and are explained through an
audited human decision with a prerequisite check (ARCH-H09) before the gate stops blocking (R5)."""
from fastapi.testclient import TestClient

from cpa_agents.store import get_store
from cpa_agents.store.runtime import record_human_decision
from test_workbench_app import act, app, detail, login, open_case   # noqa: F401  (app is a fixture)

VERSIONS = [
    {"id": "2025-12-31/audited/acc", "period_end": "2025-12-31", "basis": "audited", "currency": "GBP", "source": "acc",
     "period_months": 12, "figures": {"net_profit": 310_000}, "recorded_at": "2026-11-01T00:00:00"},
    {"id": "2025-12-31/management/mi", "period_end": "2025-12-31", "basis": "management", "currency": "GBP",
     "source": "MI", "period_months": 12, "figures": {"net_profit": 355_000}, "recorded_at": "2026-11-02T00:00:00"}]


def seed(app, sid):
    async def go():
        await record_human_decision(app.state.sessions, "cpa", "workbench", sid, "seed", {
            "case_id": "CASE-R", "owner": "Jane Smith", "checklist": {"financial": "R"},
            "financial_statement_versions": VERSIONS}, "seed")
    with TestClient(app) as tc:
        tc.portal.call(go)


def test_difference_listed_waits_on_owner_and_is_explained(app):
    am = login(app, "jsmith")
    sid = open_case(am, run=False)
    seed(app, sid)
    d = detail(am, sid)
    item = next(r for r in d["reconciliation"] if r["kind"] == "version")
    assert item["severity"] == "BLOCK" and item["explained"] is None
    assert any("Explain financial difference" in w["item"] and w["role"] == "account_manager" for w in d["waiting"])
    assert any(g["rule"] == "R5" and g.get("item") == item["key"] for g in d["gate"]["gaps"])
    pre = d["prereq"][f"rec:{item['key']}"]

    uw = login(app, "uw3")
    r = act(uw, sid, "explain_difference", key=item["key"], explanation="looks fine to me", _prereq=pre)
    assert r.status_code == 403 and "Account Manager" in r.json()["error"]        # Credit cannot explain it away
    assert "reload" in act(am, sid, "explain_difference", key=item["key"], explanation="x" * 20, _prereq="stale").json()["error"]
    assert "10 characters" in act(am, sid, "explain_difference", key=item["key"], explanation="ok", _prereq=pre).json()["error"]
    assert "no longer exists" in act(am, sid, "explain_difference", key="version:nope", explanation="x" * 20,
                                     _prereq=pre).json()["error"]

    r = act(am, sid, "explain_difference", key=item["key"],
            explanation="Management accounts were drawn up before the audit adjustment for stock obsolescence.",
            _prereq=pre)
    assert r.json()["ok"], r.text
    d = detail(am, sid)
    again = next(r for r in d["reconciliation"] if r["key"] == item["key"])
    assert again["explained"]["by"].startswith("Jane Smith")
    assert not any(g["rule"] == "R5" for g in d["gate"]["gaps"])
    assert not any("Explain financial difference" in w["item"] for w in d["waiting"])
    assert any("financial difference explained" in str(e) for e in get_store().events(sid))      # audited
