import json
import os
import subprocess
import sys
from pathlib import Path

from cpa_agents import tools as t
from cpa_agents.store.replay import replay
from conftest import fake_ctx

APP_DIR = Path(__file__).resolve().parents[1]


def _case(store):
    ctx = fake_ctx(session_id="rp-1", agent="p01_intake")
    store.append_event("rp-1", "agent", "p01_intake", "tool_called", tool="register_case", args={"x": 1})
    case = t.register_case("Acme", "01234567", ["new dealer relationship"], "OEM partner", "Jane", ctx)
    store.append_event("rp-1", "agent", "p01_intake", "tool_result", tool="register_case", result_status="ok")
    store.append_event("rp-1", "human", "Jane", "human_decision", detail={"label": "classification ok"})
    return case["case_id"]


def test_replay_by_case_includes_events_before_case_existed_in_order(store):
    case_id = _case(store)
    out = replay(case_id)
    assert [e["seq"] for e in out["events"]] == [1, 2, 3]
    assert [e["action"] for e in out["events"]] == ["tool_called", "tool_result", "human_decision"]
    assert out["events"][0]["case_id"] is None and out["events"][1]["case_id"] == case_id
    assert out["chains"] == {"rp-1": {"ok": True, "events": 3, "broken_at": None}}
    assert replay("rp-1")["events"] == out["events"]


def test_cli_prints_events_against_test_database(store, db_url):
    case_id = _case(store)
    env = {**os.environ, "DATABASE_URL": db_url}
    run = subprocess.run([sys.executable, "-m", "cpa_agents.store.replay", case_id], cwd=APP_DIR,
                         env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    lines = run.stdout.strip().splitlines()
    assert "register_case" in lines[0] and "-> ok" in lines[1] and "classification ok" in lines[2]
    assert lines[-1] == "chain rp-1: 3 events, intact"

    js = subprocess.run([sys.executable, "-m", "cpa_agents.store.replay", case_id, "--json"], cwd=APP_DIR,
                        env=env, capture_output=True, text=True, timeout=120)
    assert json.loads(js.stdout)["chains"]["rp-1"]["ok"] is True


def test_cli_unknown_id(store, db_url):
    run = subprocess.run([sys.executable, "-m", "cpa_agents.store.replay", "CASE-NOPE"], cwd=APP_DIR,
                         env={**os.environ, "DATABASE_URL": db_url}, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0 and "no audit events" in run.stdout
