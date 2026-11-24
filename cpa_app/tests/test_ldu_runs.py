"""Runs table and run status (agent-orchestration: one background run per case, as modified by
split-into-least-deployable-units)."""
import asyncio

import pytest
from google.adk.sessions import InMemorySessionService

from cpa_agents.ldu.runs import RunStore
from cpa_agents.ldu.runtime import InProcessLdus
from fakes import factory
from test_mesh import REQUEST, SCRIPTS
from workbench.runner import APP, USER, Runs


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


async def _session(sessions, sid):
    await sessions.create_session(app_name=APP, user_id=USER, session_id=sid, state={"request_text": REQUEST})


def test_one_active_run_per_case_across_replicas(store):
    """Two web replicas share the database: the second start is refused (the API answers 409)."""
    a, b = RunStore(), RunStore()
    first = a.start("case-1", "preparation", "Jane Smith")
    assert first and b.start("case-1", "submission", "Jane Smith") is None
    assert b.start("case-2", "preparation", "Jane Smith")          # other cases are not blocked
    a.finish(first, "finished")
    assert b.start("case-1", "submission", "Jane Smith")


def test_expired_heartbeat_reads_interrupted_and_frees_the_case(store, monkeypatch):
    monkeypatch.setenv("CPA_RUN_HEARTBEAT_TIMEOUT", "60")
    clk = Clock()
    rs = RunStore(clock=clk)
    runs = Runs(InMemorySessionService(), {}, runstore=rs)
    run_id = rs.start("case-3", "preparation", "Jane Smith")
    clk.t += 59
    assert runs.status("case-3")["state"] == "running"
    clk.t += 2                                                     # orchestrator silent > 60 s
    assert runs.status("case-3")["state"] == "interrupted"
    assert not runs.running("case-3")
    again = rs.start("case-3", "preparation", "Jane Smith")        # the stale run no longer blocks
    assert again and rs.get(run_id)["state"] == "interrupted"


def test_no_run_reads_not_started(store):
    assert Runs(InMemorySessionService(), {}).status("nothing-here")["state"] == "not started"


def test_run_through_ldus_finishes_and_reports_agents(store):
    async def go():
        sessions = InMemorySessionService()
        await _session(sessions, "case-4")
        ldus = InProcessLdus(llm=factory(SCRIPTS))
        runs = Runs(sessions, ldus.workflows, ldus=ldus)
        assert runs.start("case-4", "preparation", REQUEST, "Jane Smith")
        assert not runs.start("case-4", "preparation", REQUEST, "Jane Smith")   # second start refused
        await runs.wait("case-4")
        await ldus.stop()
        return runs.status("case-4")
    s = asyncio.run(go())
    assert s["state"] == "finished", s
    assert "pack_validation" in s["agents_completed"] and "dd_summary" in s["agents_completed"]
    assert s["waiting_on"] is None and s["events"] > 0


def test_failed_step_is_named_on_the_run_and_in_the_audit(store):
    async def go():
        sessions = InMemorySessionService()
        await _session(sessions, "case-5")
        ldus = InProcessLdus(llm=factory(SCRIPTS))
        fin = next(w for w in ldus.workers if w.ldu.name == "financial-agent")

        async def explode(job):
            raise RuntimeError("model unavailable")
        fin.execute = explode
        runs = Runs(sessions, ldus.workflows, ldus=ldus)
        runs.start("case-5", "preparation", REQUEST, "Jane Smith")
        await runs.wait("case-5")
        await ldus.stop()
        return runs.status("case-5")
    s = asyncio.run(go())
    assert s["state"] == "failed" and s["failed_step"] == "financial_analysis"
    assert "model unavailable" in s["error"]
    failed = [e for e in store.events("case-5") if e["action"] == "run_failed"]
    assert failed and failed[-1]["detail"]["step"] == "financial_analysis"
    assert "pack_validation" not in s["agents_completed"]           # no later step ran


def test_waiting_for_a_down_ldu_then_continues(store):
    """No narrative-agent worker: the run waits and says so; it continues when a worker starts."""
    async def go():
        sessions = InMemorySessionService()
        await _session(sessions, "case-6")
        ldus = InProcessLdus(llm=factory(SCRIPTS))
        narrative = next(w for w in ldus.workers if w.ldu.name == "narrative-agent")
        ldus.workers.remove(narrative)                              # that LDU is down
        runs = Runs(sessions, ldus.workflows, ldus=ldus)
        runs.start("case-6", "preparation", REQUEST, "Jane Smith")
        for _ in range(200):
            await asyncio.sleep(0.05)
            s = runs.status("case-6")
            if s["state"] == "waiting":
                break
        waiting = s
        assert runs.running("case-6")                               # human actions still refused mid-run
        stop = asyncio.Event()
        late = asyncio.create_task(narrative.serve(stop, poll=0.1))  # the LDU comes back
        await runs.wait("case-6")
        stop.set()
        await late
        await ldus.stop()
        return waiting, runs.status("case-6")
    waiting, done = asyncio.run(go())
    assert waiting["state"] == "waiting" and waiting["waiting_on"] == "narrative-agent", waiting
    assert done["state"] == "finished" and "nd_critic" in done["agents_completed"]


def test_stream_sends_change_on_run_transition(store, tmp_path, monkeypatch):
    import json
    import threading
    from fastapi.testclient import TestClient
    import workbench.app as wa
    from workbench import users as U
    from workbench.app import create_app
    monkeypatch.setattr(wa, "UPLOADS", tmp_path / "uploads")
    U.add_user("jsmith", "Jane Smith", ["account_manager"], "workbench pass 1")
    app = create_app(ldus=InProcessLdus(llm=factory(SCRIPTS)), sessions=InMemorySessionService(), secret="s")
    with TestClient(app) as c:
        assert c.post("/api/login", json={"username": "jsmith", "password": "workbench pass 1"}).status_code == 200
        sid = c.post("/api/cases", data={"request_text": REQUEST, "run_now": "true"}).json()["sid"]
        states, done = [], threading.Event()

        def read():
            with c.stream("GET", f"/api/cases/{sid}/stream") as r:
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        states.append(json.loads(line[6:])["state"])
                        if states[-1] in ("finished", "failed"):
                            done.set()
                            return
        t = threading.Thread(target=read, daemon=True)
        t.start()
        assert done.wait(60), states
    assert states[-1] == "finished" and len(states) >= 2              # at least one transition was pushed
