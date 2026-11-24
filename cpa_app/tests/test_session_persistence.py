import json
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]

WRITE = """
import asyncio
from google.adk.events import Event, EventActions
from cpa_agents.store.runtime import make_session_service
async def go():
    s = make_session_service()
    sess = await s.create_session(app_name="cpa", user_id="u", session_id="persist-1")
    await s.append_event(sess, Event(author="p01_intake",
        actions=EventActions(state_delta={"case_id": "CASE-20261114-000001", "checklist": {"entity": "R"}})))
asyncio.run(go())
"""

READ = """
import asyncio, json
from cpa_agents.store.runtime import make_session_service
async def go():
    sess = await make_session_service().get_session(app_name="cpa", user_id="u", session_id="persist-1")
    print(json.dumps(sess.state if sess else None))
asyncio.run(go())
"""


def test_session_state_survives_process_restart(store, db_url):
    env = {**os.environ, "DATABASE_URL": db_url}
    w = subprocess.run([sys.executable, "-c", WRITE], cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=180)
    assert w.returncode == 0, w.stderr
    r = subprocess.run([sys.executable, "-c", READ], cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    state = json.loads(r.stdout.strip().splitlines()[-1])
    assert state == {"case_id": "CASE-20261114-000001", "checklist": {"entity": "R"}}
