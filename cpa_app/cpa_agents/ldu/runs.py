"""Workflow runs outside the web process (design D6; agent-orchestration: one background run per case).

`RunStore` persists one row per run in the `runs` table. `RunExecutor` is the case-orchestrator: it
runs a workflow for a run, heartbeats the row, tracks dispatched steps (so status can say which LDU
a run is waiting for) and records run_finished / run_failed. Status is read from the row plus two
small audit queries, never from a scan of the whole audit trail."""
import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from google.adk.runners import Runner
from google.genai import types
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError

from ..store import get_store
from ..store.core import CASE_CHANNEL, STEP_CHANNEL, notify
from ..store.schema import ACTIVE_RUN_STATES, audit_events, runs
from .dispatch import Observer, StepFailed, current_run

log = logging.getLogger(__name__)
APP, USER = "cpa", "workbench"
WORKFLOWS = ("preparation", "submission", "post_approval")


def heartbeat_timeout() -> float:
    return float(os.getenv("CPA_RUN_HEARTBEAT_TIMEOUT", "60"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunStore:
    def __init__(self, clock=time.time):
        self.clock = clock

    @property
    def engine(self):
        return get_store().engine

    def start(self, sid: str, workflow: str, actor: str, state: str = "running", input: str | None = None) -> str | None:
        """Create a run row. Returns its id, or None if the case already has a live run. A running
        run whose heartbeat has expired no longer blocks a new start: it is marked interrupted.
        state="queued" leaves the run for a case-orchestrator replica to claim (distributed mode)."""
        stale = self.clock() - heartbeat_timeout()
        run_id = f"run-{uuid.uuid4().hex[:16]}"
        with self.engine.begin() as c:
            c.execute(update(runs).where(and_(runs.c.session_id == sid, runs.c.state == "running",
                                              runs.c.heartbeat_at < stale))
                      .values(state="interrupted", finished_at=_now()))
        try:
            with self.engine.begin() as c:
                c.execute(runs.insert().values(run_id=run_id, session_id=sid, workflow=workflow, state=state,
                                               started_by=actor, started_at=_now(), heartbeat_at=self.clock(),
                                               pending={}, input=input))
                notify(c, CASE_CHANNEL, sid)
                if state == "queued":
                    notify(c, STEP_CHANNEL, "q:case-orchestrator")
        except IntegrityError:
            return None
        return run_id

    def claim_queued(self, orchestrator: str) -> dict | None:
        """Take the oldest queued run for this orchestrator replica. The conditional update makes
        the claim atomic, so two replicas never run the same case."""
        for _ in range(5):
            with self.engine.connect() as c:
                rid = c.execute(select(runs.c.run_id).where(runs.c.state == "queued")
                                .order_by(runs.c.started_at).limit(1)).scalar()
            if rid is None:
                return None
            with self.engine.begin() as c:
                n = c.execute(update(runs).where(and_(runs.c.run_id == rid, runs.c.state == "queued"))
                              .values(state="running", orchestrator=orchestrator, heartbeat_at=self.clock())).rowcount
                if n:
                    self._notify_run(c, rid)
            if n:
                return self.get(rid)
        return None

    def has_queued(self) -> bool:
        with self.engine.connect() as c:
            return c.execute(select(runs.c.run_id).where(runs.c.state == "queued").limit(1)).first() is not None

    def heartbeat(self, run_id: str, orchestrator: str | None = None):
        vals = {"heartbeat_at": self.clock()}
        if orchestrator:
            vals["orchestrator"] = orchestrator
        with self.engine.begin() as c:
            c.execute(update(runs).where(runs.c.run_id == run_id).values(**vals))

    def set_pending(self, run_id: str, pending: dict):
        with self.engine.begin() as c:
            c.execute(update(runs).where(runs.c.run_id == run_id).values(pending=dict(pending),
                                                                         heartbeat_at=self.clock()))
            self._notify_run(c, run_id)

    def finish(self, run_id: str, state: str, error: str | None = None, failed_step: str | None = None):
        with self.engine.begin() as c:
            c.execute(update(runs).where(runs.c.run_id == run_id)
                      .values(state=state, finished_at=_now(), error=error, failed_step=failed_step, pending={}))
            self._notify_run(c, run_id)

    @staticmethod
    def _notify_run(c, run_id: str):
        if c.dialect.name == "postgresql":
            sid = c.execute(select(runs.c.session_id).where(runs.c.run_id == run_id)).scalar()
            if sid:
                notify(c, CASE_CHANNEL, sid)

    def get(self, run_id: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
        return dict(r) if r else None

    def latest(self, sid: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(runs).where(runs.c.session_id == sid)
                          .order_by(runs.c.started_at.desc()).limit(1)).mappings().first()
        return dict(r) if r else None

    # ---- small audit reads for status (no full-trail scan) ----
    def event_count(self, sid: str) -> int:
        with self.engine.connect() as c:
            return c.execute(select(func.count()).select_from(audit_events)
                             .where(audit_events.c.session_id == sid)).scalar() or 0

    def agents_completed(self, sid: str, since: datetime | None, limit: int = 25) -> list[str]:
        q = select(audit_events.c.actor).where(and_(audit_events.c.session_id == sid,
                                                    audit_events.c.action == "agent_complete"))
        if since is not None:
            q = q.where(audit_events.c.at >= since)
        q = q.order_by(audit_events.c.id.desc()).limit(limit)
        with self.engine.connect() as c:
            return list(reversed(c.execute(q).scalars().all()))


def legacy_status(sid: str) -> dict:
    """Status of a case whose runs pre-date the runs table: worked out from its audit trail."""
    events = get_store().events(sid)
    rs = [e for e in events if e["action"] in ("run_started", "run_finished", "run_failed")]
    last = rs[-1] if rs else None
    agents = [e["actor"] for e in events if e["action"] == "agent_complete"]
    state = ("not started" if not last else "interrupted" if last["action"] == "run_started"
             else "failed" if last["action"] == "run_failed" else "finished")
    return {"state": state, "workflow": (last or {}).get("detail", {}).get("workflow"),
            "error": (last or {}).get("detail", {}).get("error") if state == "failed" else None,
            "agents_completed": agents[-25:], "events": len(events), "waiting_on": None, "failed_step": None}


def run_status(rs: RunStore, sid: str, live_ldus=None) -> dict:
    """running | waiting | not started | finished | failed | interrupted (agent-orchestration spec).
    `live_ldus()` returns the LDUs that have a live worker; None means "don't know" (no waiting)."""
    row = rs.latest(sid)
    if row is None:
        return legacy_status(sid)
    state = row["state"]
    waiting_on = None
    if state in ACTIVE_RUN_STATES:
        if state == "running" and rs.clock() - row["heartbeat_at"] > heartbeat_timeout():
            state = "interrupted"
        else:
            live = live_ldus() if live_ldus else None
            need = sorted(set((row["pending"] or {}).values()) | ({"case-orchestrator"} if row["state"] == "queued"
                                                                  else set()))
            down = [u for u in need if live is not None and u not in live]
            state, waiting_on = ("waiting", down[0]) if down else ("running", None)
    return {"state": state, "workflow": row["workflow"], "run_id": row["run_id"],
            "error": row["error"] if state == "failed" else None, "failed_step": row["failed_step"],
            "waiting_on": waiting_on, "agents_completed": rs.agents_completed(sid, row["started_at"]),
            "events": rs.event_count(sid)}


def _step_failure(exc: BaseException) -> StepFailed | None:
    seen, todo = set(), [exc]
    while todo:
        e = todo.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, StepFailed):
            return e
        todo += [e.__cause__, e.__context__, *getattr(e, "exceptions", ())]
    return None


class RunExecutor(Observer):
    """The case-orchestrator: executes runs and is the dispatcher's observer."""

    def __init__(self, sessions, workflows: dict, runstore: RunStore | None = None,
                 heartbeat_every: float = 10.0, name: str | None = None):
        self.sessions, self.workflows = sessions, workflows
        self.runs = runstore or RunStore()
        self.heartbeat_every = heartbeat_every
        self.name = name or f"case-orchestrator@{socket.gethostname()}:{os.getpid()}"
        self._pending: dict[str, dict] = {}

    async def dispatched(self, run_id, case_id, ldu, agent):
        p = self._pending.setdefault(run_id, {})
        p[agent] = ldu
        await asyncio.to_thread(self.runs.set_pending, run_id, p)

    async def finished(self, run_id, case_id, ldu, agent, ok):
        p = self._pending.setdefault(run_id, {})
        p.pop(agent, None)
        await asyncio.to_thread(self.runs.set_pending, run_id, p)

    async def _beat(self, run_id: str):
        while True:
            await asyncio.sleep(self.heartbeat_every)
            await asyncio.to_thread(self.runs.heartbeat, run_id, self.name)

    async def execute(self, run_id: str, sid: str, workflow: str, text: str):
        store = get_store()
        token = current_run.set(run_id)
        beat = asyncio.create_task(self._beat(run_id))
        try:
            await asyncio.to_thread(self.runs.heartbeat, run_id, self.name)
            r = Runner(agent=self.workflows[workflow], app_name=APP, session_service=self.sessions)
            msg = types.Content(role="user", parts=[types.Part(text=text)])
            async for _ in r.run_async(user_id=USER, session_id=sid, new_message=msg):
                pass
            store.append_event(sid, "system", "workbench", "run_finished", detail={"workflow": workflow})
            self.runs.finish(run_id, "finished")
        except Exception as e:                                         # surfaced on the case page
            step = _step_failure(e)
            error = f"{type(e).__name__}: {e}"[:500] if step is None else f"{step.agent}: {step.error}"[:500]
            detail = {"workflow": workflow, "error": error}
            if step is not None:
                detail["step"] = step.agent
            store.append_event(sid, "system", "workbench", "run_failed", detail=detail)
            self.runs.finish(run_id, "failed", error=error, failed_step=step.agent if step else None)
        finally:
            beat.cancel()
            current_run.reset(token)
            self._pending.pop(run_id, None)
