"""Starting one LDU by name (deployable-units: "Start an LDU by name", "Planned LDU cannot start"),
the LDU registry, and the workbench in distributed mode (it only queues runs)."""
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService

from cpa_agents.ldu import serve
from cpa_agents.ldu.queue import DONE, InMemoryQueue, QUEUED
from cpa_agents.ldu.registry import Registry
from cpa_agents.ldu.runs import RunStore
from fakes import factory
from test_mesh import SCRIPTS
from workbench.runner import Runs

ROOT = Path(__file__).resolve().parents[1]
DD = ["dd_sanctions", "dd_identity", "dd_adverse_media", "dd_summary"]


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize("name", ["review-scheduler", "telemetry"])
def test_planned_ldu_cannot_start(name):
    with pytest.raises(serve.LduError, match="planned and not yet implemented"):
        serve.build_app(name)


def test_planned_ldu_refused_from_the_command_line():
    p = subprocess.run([sys.executable, "-m", "cpa_agents.ldu", "run", "review-scheduler"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode != 0 and "review-scheduler is planned and not yet implemented" in p.stderr


def test_unknown_ldu_refused():
    with pytest.raises(serve.LduError, match="unknown LDU 'nope'"):
        serve.build_app("nope")


def test_agent_ldu_hosts_only_its_agents_and_reports_health(store):
    q = InMemoryQueue()
    app = serve.build_app("due-diligence-agent", queue=q, llm=factory(SCRIPTS), register=False)
    with TestClient(app) as c:
        h = c.get("/health").json()
        assert h["ldu"] == "due-diligence-agent" and h["kind"] == "agent" and h["ok"] is True
        assert h["version"] == serve.version() and h["agents"] == DD
        proc = app.state.ldu
        assert proc.workers and all(sorted(w.agents) == sorted(DD) for w in proc.workers)

        async def other_ldu_job():
            return await q.enqueue("r1", "c1", "narrative-agent", "nd_critic", {"state": {}, "input": "x"})
        jid = c.portal.call(other_ldu_job)
        time.sleep(0.5)
        assert c.portal.call(q.get, jid).state == QUEUED                 # not this LDU's step


def test_agent_ldu_runs_a_step(store):
    q = InMemoryQueue()
    app = serve.build_app("due-diligence-agent", queue=q, llm=factory(SCRIPTS), register=False)
    with TestClient(app) as c:
        async def go():
            jid = await q.enqueue("r1", "c1", "due-diligence-agent", "dd_sanctions",
                                  {"state": {"case_id": "CASE-1", "parties": []}, "input": "screen"})
            return await q.wait(jid, timeout=30)
        j = c.portal.call(go)
        assert j.state == DONE and "delta" in j.result


def test_api_and_static_ldus_report_health():
    with TestClient(serve.build_app("document-extraction", register=False)) as c:
        h = c.get("/health").json()
        assert h["ldu"] == "document-extraction" and h["kind"] == "api" and h["version"] == serve.version()
        assert c.post("/extract", json={"location": "/no/such.txt", "filename": "such.txt"}).status_code == 422
    with TestClient(serve.build_app("external-adapters", register=False)) as c:
        assert c.get("/health").json()["ldu"] == "external-adapters"
    if (serve.UI_DIST / "index.html").exists():
        with TestClient(serve.build_app("workbench-ui", register=False)) as c:
            assert c.get("/health").json()["kind"] == "static"
            assert "<div id=\"root\"" in c.get("/").text


def test_distributed_agent_ldu_needs_postgres(store):
    if store.engine.dialect.name == "postgresql":
        pytest.skip("checks the SQLite refusal")
    app = serve.build_app("due-diligence-agent", register=False)
    with pytest.raises(serve.LduError, match="needs Postgres"):
        asyncio.run(app.state.ldu.start())


def test_registry_live_and_expiry(store, monkeypatch):
    monkeypatch.setenv("CPA_LDU_WORKER_TIMEOUT", "30")
    clk = Clock()
    reg = Registry(clock=clk)
    reg.register("w1", "narrative-agent", "1.0.0")
    reg.register("w2", "narrative-agent", "1.0.0")
    reg.register("w3", "due-diligence-agent", "1.0.0")
    assert reg.live() == {"narrative-agent": 2, "due-diligence-agent": 1}
    clk.t += 20
    reg.beat("w1")
    clk.t += 20                                                          # w2, w3 silent for 40 s
    assert reg.live() == {"narrative-agent": 1}
    reg.unregister("w1")
    assert reg.live_ldus() == set()


def test_distributed_workbench_queues_runs_and_reports_waiting(store, monkeypatch):
    """The web process does not execute runs; with no live case-orchestrator the run is waiting."""
    clk = Clock()
    reg = Registry(clock=clk)
    rs = RunStore(clock=clk)
    runs = Runs(InMemorySessionService(), {}, runstore=rs, distributed=True, registry=reg)

    async def start():
        return runs.start("case-q", "preparation", "the request", "Jane Smith")
    assert asyncio.run(start()) and not runs.tasks
    row = rs.latest("case-q")
    assert row["state"] == "queued" and row["input"] == "the request"
    s = runs.status("case-q")
    assert s["state"] == "waiting" and s["waiting_on"] == "case-orchestrator"
    clk.t += 600                                                         # still waiting, not interrupted
    assert runs.status("case-q")["state"] == "waiting"
    assert asyncio.run(start()) is False                                 # one active run per case

    reg.register("orch-1", "case-orchestrator")
    assert runs.status("case-q")["state"] == "running"                   # queued, an orchestrator is live
    a, b = rs.claim_queued("orch-1"), rs.claim_queued("orch-2")
    assert a["run_id"] == row["run_id"] and a["state"] == "running" and b is None
    rs.set_pending(a["run_id"], {"nd_critic": "narrative-agent"})
    s = runs.status("case-q")
    assert s["state"] == "waiting" and s["waiting_on"] == "narrative-agent"
    reg.register("n-1", "narrative-agent")
    assert runs.status("case-q")["state"] == "running"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.distributed
@pytest.mark.skipif(not (os.getenv("TEST_DATABASE_URL") or "").startswith("postgresql"),
                    reason="set TEST_DATABASE_URL to a Postgres database")
def test_start_agent_ldu_by_name_as_its_own_process(store, db_url):
    """deployable-units: only that LDU's process starts, hosting the four due-diligence agents,
    and it reports its name and version in its health check."""
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": db_url, "CPA_LDU_MODE": "distributed", "CPA_VERSION": "9.9.9-test",
           "CPA_LLM_FACTORY": "fakes:scripted_mesh()", "PYTHONPATH": str(ROOT / "tests")}
    p = subprocess.Popen([sys.executable, "-m", "cpa_agents.ldu", "run", "due-diligence-agent", "--port", str(port)],
                         cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        h, deadline = None, time.time() + 90
        while time.time() < deadline and p.poll() is None:
            try:
                h = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).json()
                break
            except httpx.HTTPError:
                time.sleep(0.5)
        assert h, p.stdout.read() if p.poll() is not None else "no health response"
        assert h == {**h, "ldu": "due-diligence-agent", "kind": "agent", "version": "9.9.9-test", "agents": DD, "ok": True}
        deadline = time.time() + 15
        while time.time() < deadline and "due-diligence-agent" not in Registry().live():
            time.sleep(0.5)
        assert Registry().live() == {"due-diligence-agent": 1}           # only this LDU is running
    finally:
        p.terminate()
        p.wait(timeout=30)


def test_compose_runs_one_service_per_active_ldu():
    import yaml
    from cpa_agents.ldu import get_manifest
    spec = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    runs = {s["command"][1]: name for name, s in spec["services"].items()
            if isinstance(s.get("command"), list) and s["command"][:1] == ["run"]}
    m = get_manifest()
    assert set(runs) == {u.name for u in m.ldus.values() if u.active}       # planned LDUs have no service
    assert all(name == ldu for ldu, name in runs.items())
    assert all(spec["services"][n]["environment"]["CPA_LDU_MODE"] == "distributed" for n in runs)
