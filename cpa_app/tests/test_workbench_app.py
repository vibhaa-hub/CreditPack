"""Workbench JSON API with the scripted agent mesh: sign-in, cases, documents, background runs,
every human gate with role and prerequisite checks, Credit, handoffs, queue and audit."""
import hashlib
import time

import pytest
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService
from itsdangerous import TimestampSigner
from sqlalchemy import select

from cpa_agents.mesh.orchestrator import build_workflows
from cpa_agents.store import get_store
from cpa_agents.store.replay import replay
from cpa_agents.store.schema import documents
from fakes import factory
from test_mesh import REQUEST, SCRIPTS
from workbench import users as U
from workbench.app import create_app

PW = "workbench pass 1"
PEOPLE = {"jsmith": ("Jane Smith", "account_manager"), "bjones": ("Bob Jones", "account_manager"),
          "fc7": ("Analyst Seven", "financial_crime_analyst"), "ob4": ("Onboarding Four", "onboarding_analyst"),
          "pc2": ("Pricing Committee", "pricing_authority"), "uw3": ("Credit Underwriter", "credit_underwriter"),
          "ops1": ("Ops One", "operations"), "aud": ("Audit Person", "auditor")}
WB_SCRIPTS = {**SCRIPTS, "post_approval": [("initiate_handoffs", {})]}


@pytest.fixture
def app(store, tmp_path, monkeypatch):
    import workbench.app as wa
    monkeypatch.setattr(wa, "UPLOADS", tmp_path / "uploads")
    for u, (name, role) in PEOPLE.items():
        U.add_user(u, name, [role], PW)
    return create_app(workflows=build_workflows(llm=factory(WB_SCRIPTS)), sessions=InMemorySessionService(),
                      secret="test-secret")


def login(app, username):
    c = TestClient(app)
    c.__enter__()
    r = c.post("/api/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text
    return c


def wait_run(c, sid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get(f"/api/cases/{sid}/status").json()
        if s["state"] in ("finished", "failed"):
            return s
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def open_case(c, files=None, run=True):
    r = c.post("/api/cases", data={"request_text": REQUEST, "run_now": "true" if run else "false"}, files=files or [])
    assert r.status_code == 200, r.text
    return r.json()["sid"]


def detail(c, sid):
    return c.get(f"/api/cases/{sid}").json()


def act(c, sid, action, **body):
    return c.post(f"/api/cases/{sid}/act/{action}", json=body)


# ---------- sign-in ----------
def test_login_me_logout_and_protected_api(app):
    c = TestClient(app)
    assert c.get("/api/cases").status_code == 401
    r = c.post("/api/login", json={"username": "jsmith", "password": "bad"})
    assert r.status_code == 401 and r.json()["error"] == "Wrong username or password."
    c = login(app, "jsmith")
    me = c.get("/api/me").json()
    assert me["user"]["display_name"] == "Jane Smith" and me["can"]["create_case"] and "auditor" in me["roles"]
    c.post("/api/logout")
    assert c.get("/api/me").status_code == 401
    actions = [e["action"] for e in get_store().events("workbench")]
    assert actions.count("access_denied") == 1 and "signed_in" in actions and "signed_out" in actions


def test_expired_and_tampered_cookies_rejected(app, monkeypatch):
    old = TimestampSigner("test-secret", salt="cpa-workbench")
    monkeypatch.setattr(old, "get_timestamp", lambda: int(time.time()) - 9 * 3600)
    c = TestClient(app)
    c.cookies.set("cpa_wb", old.sign("jsmith").decode())
    assert c.get("/api/me").status_code == 401
    c.cookies.set("cpa_wb", "jsmith.tampered.sig")
    assert c.get("/api/me").status_code == 401


def test_denied_action_is_audited(app):
    r = login(app, "uw3").post("/api/cases", data={"request_text": "x"})
    assert r.status_code == 403 and r.json()["action"]
    assert any(e["action"] == "access_denied" and e["detail"]["action"] == "create_case"
               for e in get_store().events("workbench"))


# ---------- cases and documents ----------
def test_new_case_with_upload_and_type_limit(app):
    c = login(app, "jsmith")
    bad = c.post("/api/cases", data={"request_text": REQUEST}, files=[("files", ("run.exe", b"MZ", "application/x"))])
    assert bad.status_code == 400 and "not allowed" in bad.json()["error"]
    sid = open_case(c, files=[("files", ("accounts.txt", b"FY2025 turnover 15,000,000", "text/plain"))], run=False)
    with get_store().engine.connect() as conn:
        row = conn.execute(select(documents).where(documents.c.session_id == sid)).mappings().first()
    assert row["sha256"] == hashlib.sha256(b"FY2025 turnover 15,000,000").hexdigest()
    assert row["uploaded_by"].startswith("Jane Smith")
    d = detail(c, sid)
    assert d["state"]["documents"][0]["filename"] == "accounts.txt" and d["request_text"] == REQUEST
    assert [x["sid"] for x in c.get("/api/cases").json()["cases"]] == [sid]
    assert c.post(f"/api/cases/{sid}/upload", files=[("files", ("more.csv", b"a,b", "text/csv"))]).json()["ok"]
    assert len(detail(c, sid)["state"]["documents"]) == 2


# ---------- background runs and live stream ----------
def test_preparation_runs_in_background_and_status_reports(app):
    c = login(app, "jsmith")
    sid = open_case(c)
    assert c.post(f"/api/cases/{sid}/run/preparation").status_code in (200, 409)   # second start refused while running
    s = wait_run(c, sid)
    assert s["state"] == "finished" and "pack_validation" in s["agents_completed"]
    d = detail(c, sid)
    assert d["state"]["case_id"].startswith("CASE-") and d["gate"]["result"] == "BLOCK"
    assert any("pricing and terms authorisation missing" in g["reason"] for g in d["gate"]["gaps"])
    assert d["permissions"]["review_section"]["allowed"] and not d["permissions"]["disposition_hit"]["allowed"]


def test_stream_requires_sign_in(app):
    assert TestClient(app).get("/api/cases/x/stream").status_code == 401


# ---------- every role through a full case ----------
def test_full_case_through_every_role(app):
    am = login(app, "jsmith")
    sid = open_case(am)
    wait_run(am, sid)
    uw, other = login(app, "uw3"), login(app, "bjones")
    d = detail(am, sid)
    p = d["prereq"]["sec:business_background"]
    r = act(uw, sid, "review_section", section="business_background", decision="accept", _prereq=p)
    assert r.status_code == 403
    assert "BR-E01" in act(other, sid, "authorise_submission", _prereq="x").json()["error"]
    r = act(am, sid, "review_section", section="business_background", decision="accept", _prereq="stale")
    assert r.status_code == 400 and "ARCH-H09" in r.json()["error"]
    assert any(e["action"] == "process_failure" for e in get_store().events(sid))

    assert act(login(app, "ob4"), sid, "record_cra", outcome="medium", basis="clean history").json()["ok"]
    for name in ("business_background", "management_assessment", "conduct_performance", "security_review"):
        r = act(am, sid, "review_section", section=name, decision="accept", _prereq=detail(am, sid)["prereq"][f"sec:{name}"])
        assert r.json()["ok"], r.text
    pc = login(app, "pc2")
    assert act(pc, sid, "authorise_pricing", _prereq=detail(pc, sid)["prereq"]["pricing"]).json()["ok"]
    r = act(am, sid, "authorise_submission", _prereq=detail(am, sid)["prereq"]["submission"])
    assert r.json()["ok"], r.text
    assert am.post(f"/api/cases/{sid}/run/submission").json()["ok"]
    wait_run(am, sid)
    d = detail(am, sid)
    assert d["state"]["submitted"]["pack_version"] == 1 and [p["version"] for p in d["packs"]] == [1]

    assert act(uw, sid, "raise_query", text="Explain stock turn").json()["ok"]
    qid = detail(am, sid)["queries"][0]["id"]
    r = act(am, sid, "resolve_query", query_id=qid, resolution="commentary added", pack_changed=True)
    assert "pack version 2" in r.json()["message"]
    assert act(uw, sid, "record_outcome", outcome="approved with conditions", reference="CR-1",
               conditions="stock audit before first drawdown").json()["ok"]
    assert am.post(f"/api/cases/{sid}/run/post_approval").json()["ok"]
    wait_run(am, sid)
    ops = login(app, "ops1")
    assert act(ops, sid, "update_handoff", kind="handoff", idx=0, status="complete").json()["ok"]
    assert "BR-P08" in act(ops, sid, "update_handoff", kind="condition", idx=0, evidence="").json()["error"]
    assert act(ops, sid, "update_handoff", kind="condition", idx=0, evidence="audit report 12").json()["ok"]

    assert any("Handoff" in i["item"] for i in ops.get("/api/queue").json()["items"])
    case_id = get_store().case_for_session(sid)
    out = replay(case_id)
    humans = {e["actor"] for e in out["events"] if e["actor_type"] == "human"}
    for name in ("Jane Smith (jsmith", "Onboarding Four (ob4", "Pricing Committee (pc2", "Credit Underwriter (uw3",
                 "Ops One (ops1"):
        assert any(h.startswith(name) for h in humans), name
    assert out["chains"][sid]["ok"] and [v["version"] for v in get_store().pack_versions(case_id)] == [1, 2]
    a = login(app, "aud").get(f"/api/cases/{sid}/audit").json()
    assert a["chain"]["ok"] and len(a["events"]) > 50


def test_hit_disposition_and_discrepancy(app):
    am = login(app, "jsmith")
    sid = open_case(am, run=False)
    from cpa_agents.store.runtime import record_human_decision

    async def seed():
        await record_human_decision(app.state.sessions, "cpa", "workbench", sid, "seed", {
            "case_id": "CASE-T", "owner": "Jane Smith",
            "hits_open": [{"party": "HIT TEST PERSON", "check": "sanctions", "result": "potential_match"}],
            "registry_discrepancies": [{"field": "director", "issue": "on registry but not supplied", "resolved_by": None}]},
            "seed")
    with TestClient(app) as tc:
        tc.portal.call(seed)
    fc = login(app, "fc7")
    p = detail(fc, sid)["prereq"]["hit:0"]
    assert "REQ-032" in act(fc, sid, "disposition_hit", idx=0, disposition="false positive", rationale="", _prereq=p).json()["error"]
    assert act(fc, sid, "disposition_hit", idx=0, disposition="false positive", rationale="DOB differs", _prereq=p).json()["ok"]
    assert detail(am, sid)["state"]["hits_open"] == []
    r = act(am, sid, "resolve_discrepancy", idx=0, resolution="director resigned", _prereq=detail(am, sid)["prereq"]["disc:0"])
    assert r.json()["ok"] and detail(am, sid)["state"]["registry_discrepancies"][0]["resolved_by"].startswith("Jane Smith")


WRONG_ROLE = {"disposition_hit": "jsmith", "record_cra": "jsmith", "record_manual_check": "pc2",
              "resolve_discrepancy": "fc7", "review_section": "pc2", "authorise_pricing": "jsmith",
              "authorise_exception": "jsmith", "authorise_submission": "fc7", "add_note": "ops1",
              "raise_query": "jsmith", "record_outcome": "jsmith", "resolve_query": "uw3", "update_handoff": "jsmith",
              "explain_difference": "fc7"}


@pytest.mark.parametrize("action,who", list(WRONG_ROLE.items()))
def test_every_gate_action_refuses_the_wrong_role(app, action, who):
    sid = open_case(login(app, "jsmith"), run=False)
    r = act(login(app, who), sid, action, idx=0, section="x", _prereq="x")
    assert r.status_code == 403 and r.json()["error"]
    assert any(e["action"] == "access_denied" and e["detail"]["action"] == action for e in get_store().events(sid))


def test_manual_check_exception_and_note(app):
    sid = open_case(login(app, "jsmith"), run=False)
    ob = login(app, "ob4")
    assert "REQ-035" in act(ob, sid, "record_manual_check", party="Acme", check="aml").json()["error"]
    assert act(ob, sid, "record_manual_check", party="Acme", check="aml", result="clear", tool_used="manual register",
               evidence_ref="file 9").json()["ok"]
    fc = login(app, "fc7")
    assert "BR-E04" in act(fc, sid, "authorise_exception", rule="R2").json()["error"]
    assert act(fc, sid, "authorise_exception", rule="R2", item="Acme/kyc", reason="group KYC on file").json()["ok"]
    assert act(login(app, "jsmith"), sid, "add_note", text="Call with dealer", participants="A. Director").json()["ok"]
    st = detail(ob, sid)["state"]
    assert st["checks"][0]["manual"] and st["exceptions"][0]["approved_by"].startswith("Analyst Seven") and st["notes"]


def test_queue_shows_each_role_its_own_items(app):
    am = login(app, "jsmith")
    sid = open_case(am)
    wait_run(am, sid)
    items = lambda u: [i["item"] for i in login(app, u).get("/api/queue").json()["items"]]
    assert "Review section business background" in items("jsmith")
    assert "Record the CRA outcome" in items("ob4")
    assert "Authorise pricing and terms" in items("pc2")
    assert items("ops1") == [] and not any("Review section" in i for i in items("pc2"))


def test_spa_fallback_and_unknown_api(app):
    c = TestClient(app)
    assert c.get("/api/nope").status_code in (401, 404)
    r = c.get("/cases/abc")
    assert r.status_code in (200, 503)            # index.html once built; 503 with build instructions before


def test_samples_list_and_open(app):
    am = login(app, "jsmith")
    samples = am.get("/api/samples").json()["samples"]
    names = [s["name"] for s in samples]
    assert "01-acme-motors-increase" in names and "02-brightway-cars-new-dealer" in names
    acme = next(s for s in samples if s["name"] == "01-acme-motors-increase")
    assert "application_form.docx" in acme["documents"] and "request.txt" not in acme["documents"]
    bright = next(s for s in samples if s["name"].startswith("02"))
    assert bright["expect"] and "README.txt" not in bright["documents"]
    assert login(app, "uw3").post("/api/samples/01-acme-motors-increase/open").status_code == 403
    assert am.post("/api/samples/nope/open").status_code == 404
    sid = am.post("/api/samples/01-acme-motors-increase/open").json()["sid"]
    wait_run(am, sid)
    d = detail(am, sid)
    assert len(d["state"]["documents"]) == 6 and "Acme Motors Ltd" in d["request_text"]      # incl. the iXBRL filing
    assert d["state"]["case_id"].startswith("CASE-")
