"""Step worker for an agent LDU (design D4).

A worker claims step jobs from its LDU's queue and runs each one in an isolated in-memory step
session that has the case's session ID (so audit callbacks and store writes land on the right
case) and is seeded with the case state from the job. It completes the job with the step's state
delta and the agent's final text. It never writes to the case's ADK session: the orchestrator
applies the delta, as the only writer."""
import asyncio
import json
import logging
import os
import socket
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .manifest import Manifest, get_manifest
from .queue import Job, StepQueue

log = logging.getLogger(__name__)
APP, USER = "cpa", "workbench"


class WrongLdu(Exception):
    pass


def jsonable(state: dict) -> dict:
    """Plain JSON-safe copy of session state (what a job payload or result can carry)."""
    return json.loads(json.dumps(state, default=str))


def compute_delta(before: dict, after: dict) -> dict:
    """Keys whose value changed or appeared; keys that disappeared map to None."""
    delta = {k: v for k, v in after.items() if k not in before or before[k] != v}
    delta.update({k: None for k in before if k not in after})
    return delta


async def run_step(agent, case_id: str, state: dict, text: str) -> dict:
    """Run one agent turn in an isolated step session. Returns {"delta", "output"}."""
    sessions = InMemorySessionService()
    seed = jsonable(state)
    await sessions.create_session(app_name=APP, user_id=USER, session_id=case_id, state=dict(seed))
    runner = Runner(agent=agent, app_name=APP, session_service=sessions)
    output = None
    msg = types.Content(role="user", parts=[types.Part(text=text or "")])
    async for ev in runner.run_async(user_id=USER, session_id=case_id, new_message=msg):
        if ev.author == agent.name and ev.content and ev.content.parts and not ev.get_function_calls():
            t = "".join(p.text for p in ev.content.parts if p.text and not getattr(p, "thought", False))
            if t:
                output = t
    final = await sessions.get_session(app_name=APP, user_id=USER, session_id=case_id)
    after = jsonable({k: v for k, v in final.state.items() if not k.startswith("temp:")})
    return {"delta": compute_delta(seed, after), "output": output}


class StepWorker:
    """One replica's worker loop for one agent LDU."""

    def __init__(self, ldu: str, agents: dict, queue: StepQueue, manifest: Manifest | None = None,
                 worker_id: str | None = None, heartbeat_every: float = 10.0):
        self.manifest = manifest or get_manifest()
        self.ldu = self.manifest.ldu(ldu)
        if self.ldu.kind != "agent" or not self.ldu.active:
            raise ValueError(f"{ldu} is not an active agent LDU")
        missing = [a for a in self.ldu.agents if a not in agents]
        if missing:
            raise ValueError(f"{ldu}: agents not built: {', '.join(missing)}")
        self.agents = {a: agents[a] for a in self.ldu.agents}       # only its own agents
        self.queue = queue
        self.id = worker_id or f"{ldu}@{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.heartbeat_every = heartbeat_every

    async def execute(self, job: Job) -> dict:
        if job.agent not in self.agents:
            raise WrongLdu(f"{job.agent} is not hosted by {self.ldu.name}")
        return await run_step(self.agents[job.agent], job.case_id, job.payload.get("state") or {},
                              job.payload.get("input") or "")

    async def _beat(self, job_id: int):
        while True:
            await asyncio.sleep(self.heartbeat_every)
            await self.queue.heartbeat(job_id)

    async def process_one(self) -> bool:
        """Claim and run one job. Returns False when there was nothing to do."""
        job = await self.queue.claim(self.ldu.name, self.id)
        if job is None:
            return False
        if job.agent not in self.agents:                         # misrouted: leave it for its own LDU
            log.warning("%s rejected step for %s", self.id, job.agent)
            await self.queue.release(job.id)
            return True
        beat = asyncio.create_task(self._beat(job.id))
        try:
            result = await self.execute(job)
        except Exception as e:                                   # noqa: BLE001  (reported on the run)
            await self.queue.fail(job.id, f"{type(e).__name__}: {e}")
        else:
            await self.queue.complete(job.id, result)
        finally:
            beat.cancel()
        return True

    async def serve(self, stop: asyncio.Event, poll: float = 1.0):
        while not stop.is_set():
            if not await self.process_one():
                await self.queue.wait_for_work(self.ldu.name, poll)
