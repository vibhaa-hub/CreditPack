"""Distributed mode end to end (tasks 6.1 and 6.2): every LDU runs as its own OS process on Postgres,
with the scripted models, and the workbench (in this process) only queues runs.

  6.1  samples 01 and 02 give the same final state, gate result and audit actions as single-process
       mode (apart from order within parallel branches), with two replicas each of
       due-diligence-agent and narrative-agent, and the audit hash chain verifies.
  6.2  failure drill: narrative-agent stopped -> "waiting for narrative-agent" while other cases
       still work; restarted -> the run finishes; case-orchestrator killed -> "interrupted".

Needs TEST_DATABASE_URL pointing at Postgres. Takes a minute or two (it starts ~16 processes)."""
import os
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from cpa_agents import files
from cpa_agents.ldu import get_manifest
from cpa_agents.ldu.registry import Registry
from test_ldu_inprocess import canonical
from workbench import users as U

pytestmark = [pytest.mark.distributed,
              pytest.mark.skipif(not (os.getenv("TEST_DATABASE_URL") or "").startswith("postgresql"),
                                 reason="set TEST_DATABASE_URL to a Postgres database")]

ROOT = Path(__file__).resolve().parents[1]
PW = "workbench pass 1"
SAMPLES = ["01-acme-motors-increase", "02-brightway-cars-new-dealer"]
REPLICAS = {"due-diligence-agent": 2, "narrative-agent": 2}
# differ between any two runs: ids, timestamps, upload paths, workbench bookkeeping
LOCAL_VOLATILE = {"doc_id", "path", "uri", "uploaded_at", "wb_created", "wb_owner"}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stack:
    """LDU processes started with `python -m cpa_agents.ldu run <name>`."""

    def __init__(self, db_url, uploads, extra_env=None):
        self.procs: dict[str, list[tuple[subprocess.Popen, int]]] = {}
        self.ports = {"document-extraction": _free_port(), "external-adapters": _free_port()}
        self.env = {**os.environ, "DATABASE_URL": db_url, "CPA_LDU_MODE": "distributed",
                    "CPA_LLM_FACTORY": "fakes:scripted_mesh()", "PYTHONPATH": str(ROOT / "tests"),
                    "CPA_FILE_STORE": "local", "CPA_UPLOAD_DIR": str(uploads),
                    "CPA_EXTRACTION_URL": f"http://127.0.0.1:{self.ports['document-extraction']}",
                    "CPA_ADAPTERS_URL": f"http://127.0.0.1:{self.ports['external-adapters']}",
                    **(extra_env or {})}

    def start(self, name, wait=True):
        port = self.ports.get(name) if name not in self.procs else None
        port = port or _free_port()
        p = subprocess.Popen([sys.executable, "-m", "cpa_agents.ldu", "run", name, "--port", str(port)], cwd=ROOT,
                             env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.setdefault(name, []).append((p, port))
        if wait:
            self.healthy(name, p, port)
        return p

    def healthy(self, name, p, port, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            assert p.poll() is None, f"{name} exited with {p.returncode}"
            try:
                h = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).json()
                if h.get("ok"):
                    return h
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise AssertionError(f"{name} not healthy")

    def start_all(self, skip=()):
        names = [u.name for u in get_manifest().ldus.values()
                 if u.active and u.kind in ("agent", "worker", "api") and u.name not in ("workbench-api", *skip)]
        for n in names:
            for _ in range(REPLICAS.get(n, 1)):
                self.start(n, wait=False)
        for n in names:
            for p, port in self.procs[n]:
                self.healthy(n, p, port)

    def kill(self, name):
        for p, _ in self.procs.pop(name, []):
            p.kill()
            p.wait(timeout=30)

    def stop(self):
        for n in list(self.procs):
            self.kill(n)


@pytest.fixture
def env(store, tmp_path, monkeypatch, db_url):
    uploads = tmp_path / "uploads"
    monkeypatch.setenv("CPA_UPLOAD_DIR", str(uploads))
    monkeypatch.setenv("CPA_FILE_STORE", "local")
    files.set_file_store(None)
    import workbench.app as wa
    monkeypatch.setattr(wa, "UPLOADS", uploads)
    U.add_user("jsmith", "Jane Smith", ["account_manager"], PW)
    yield uploads, db_url
    files.set_file_store(None)


def _client(app):
    c = TestClient(app)
    c.__enter__()
    assert c.post("/api/login", json={"username": "jsmith", "password": PW}).status_code == 200
    return c


def _wait(c, sid, until, timeout=240):
    end, s = time.time() + timeout, None
    while time.time() < end:
        s = c.get(f"/api/cases/{sid}/status").json()
        if until(s):
            return s
        time.sleep(0.3)
    raise AssertionError(f"timed out; last status {s}")


def _finished(s):
    assert s["state"] != "failed", s
    return s["state"] == "finished"


def _result(store, c, sid):
    st = c.get(f"/api/cases/{sid}").json()["state"]
    actions = Counter((e["actor_type"], e["actor"], e["action"], e["tool"]) for e in store.events(sid))
    return st, actions, store.verify_chain(sid)


def _comparable(state):
    def scrub(v):
        if isinstance(v, dict):
            return {k: scrub(x) for k, x in v.items() if k not in LOCAL_VOLATILE}
        if isinstance(v, list):
            return [scrub(x) for x in v]
        return v
    return canonical(scrub({k: v for k, v in state.items() if k not in LOCAL_VOLATILE}))


def test_samples_match_between_single_process_and_distributed(env, store, monkeypatch):
    uploads, db_url = env
    from cpa_agents.ldu.runtime import InProcessLdus
    from cpa_agents.store.runtime import make_session_service
    from fakes import scripted_mesh
    from workbench.app import create_app

    # single-process mode
    monkeypatch.setenv("CPA_LDU_MODE", "inprocess")
    single = _client(create_app(ldus=InProcessLdus(llm=scripted_mesh()), sessions=make_session_service(db_url),
                                secret="t"))
    local = {}
    for name in SAMPLES:
        sid = single.post(f"/api/samples/{name}/open").json()["sid"]
        _wait(single, sid, _finished)
        local[name] = _result(store, single, sid)
    single.__exit__(None, None, None)

    # distributed mode: every LDU its own process, two replicas of DD and narrative
    monkeypatch.setenv("CPA_LDU_MODE", "distributed")
    stack = Stack(db_url, uploads)
    try:
        stack.start_all()
        live = Registry().live()
        assert live["due-diligence-agent"] == 2 and live["narrative-agent"] == 2
        dist = _client(create_app(sessions=make_session_service(db_url), secret="t"))
        assert dist.app.state.runs.distributed
        sids = {name: dist.post(f"/api/samples/{name}/open").json()["sid"] for name in SAMPLES}   # concurrently
        for name, sid in sids.items():
            _wait(dist, sid, _finished)
        remote = {name: _result(store, dist, sid) for name, sid in sids.items()}
        dist.__exit__(None, None, None)
    finally:
        stack.stop()

    for name in SAMPLES:
        (ls, la, lchain), (rs, ra, rchain) = local[name], remote[name]
        assert rs["gate_status"] == ls["gate_status"]
        assert len(rs["documents"]) == len(ls["documents"]) > 0
        assert _comparable(rs) == _comparable(ls), name
        assert ra == la, name                                           # same audit actions, any order
        assert lchain["ok"] and rchain["ok"]
    from sqlalchemy import select
    from cpa_agents.store.schema import step_jobs
    with store.engine.connect() as c:
        by = Counter(r.claimed_by.rsplit("#", 1)[0] for r in c.execute(select(step_jobs)).all()
                     if r.ldu == "due-diligence-agent")
    assert len(by) == 2                                                  # both DD replicas took steps


def test_failure_drill(env, store, monkeypatch):
    uploads, db_url = env
    from cpa_agents.store.runtime import make_session_service
    from workbench.app import create_app
    monkeypatch.setenv("CPA_LDU_MODE", "distributed")
    monkeypatch.setenv("CPA_LDU_WORKER_TIMEOUT", "6")                  # read by status in this process
    monkeypatch.setenv("CPA_RUN_HEARTBEAT_TIMEOUT", "8")
    stack = Stack(db_url, uploads, {"CPA_LDU_BEAT_EVERY": "1", "CPA_RUN_HEARTBEAT_EVERY": "1"})
    try:
        stack.start_all()
        c = _client(create_app(sessions=make_session_service(db_url), secret="t"))

        # 1. narrative-agent stops: the run waits for it
        stack.kill("narrative-agent")
        sid = c.post(f"/api/samples/{SAMPLES[0]}/open").json()["sid"]
        s = _wait(c, sid, lambda s: s["state"] == "waiting", timeout=120)
        assert s["waiting_on"] == "narrative-agent"

        # human actions on another case still work meanwhile
        r = c.post("/api/cases", data={"request_text": "Dealer Other Ltd 07654321, new facility.", "run_now": "false"},
                   files=[("files", ("note.txt", b"other case evidence", "text/plain"))])
        assert r.status_code == 200, r.text
        other = r.json()["sid"]
        assert c.get(f"/api/cases/{other}").status_code == 200
        assert c.get(f"/api/cases/{other}/status").json()["state"] == "not started"
        assert c.get(f"/api/cases/{sid}/status").json()["state"] == "waiting"

        # 2. narrative-agent restarts: the same run finishes
        stack.start("narrative-agent")
        _wait(c, sid, _finished, timeout=120)
        st = c.get(f"/api/cases/{sid}").json()["state"]
        assert len(st["sections"]) == 4 and store.verify_chain(sid)["ok"]

        # 3. case-orchestrator killed mid-run: the run reads interrupted after the heartbeat timeout
        stack.kill("narrative-agent")
        sid2 = c.post(f"/api/samples/{SAMPLES[1]}/open").json()["sid"]
        _wait(c, sid2, lambda s: s["state"] == "waiting" and s["waiting_on"] == "narrative-agent", timeout=120)
        stack.kill("case-orchestrator")
        t0 = time.time()
        s = _wait(c, sid2, lambda s: s["state"] == "interrupted", timeout=60)
        assert time.time() - t0 < 30
        from cpa_agents.ldu.runs import RunStore
        assert RunStore().start(sid2, "preparation", "Jane Smith", state="queued")   # the case is free again
        c.__exit__(None, None, None)
    finally:
        stack.stop()
