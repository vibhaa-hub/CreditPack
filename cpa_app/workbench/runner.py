"""Workbench side of workflow runs (agent-orchestration: one background run per case).

Runs are rows in the `runs` table, executed by the case-orchestrator (cpa_agents.ldu.runs.RunExecutor)
and heartbeated, so status does not depend on this process: a run whose orchestrator stopped shows
as interrupted once its heartbeat expires, and one run per case is enforced in the database across
every replica. In single-process mode the orchestrator and the agent LDUs' workers run here; in
distributed mode (`distributed=True`) this process only queues runs for case-orchestrator replicas,
and status asks the LDU registry which LDUs have a live replica."""
import asyncio

from cpa_agents.ldu.registry import Registry
from cpa_agents.ldu.runs import WORKFLOWS, RunExecutor, RunStore, run_status
from cpa_agents.store import get_store

APP, USER = "cpa", "workbench"


class Runs:
    def __init__(self, sessions, workflows: dict, ldus=None, runstore: RunStore | None = None,
                 heartbeat_every: float = 10.0, distributed: bool = False, registry: Registry | None = None):
        self.sessions = sessions
        self.distributed = distributed
        self.registry = registry or (Registry() if distributed else None)
        self.workflows = workflows
        self.ldus = ldus                                  # InProcessLdus in single-process mode, or None
        self.store = runstore or RunStore()
        self.executor = RunExecutor(sessions, workflows, self.store, heartbeat_every=heartbeat_every)
        if ldus is not None:
            ldus.dispatcher.observer = self.executor      # track dispatched steps on the run row
        self.tasks: dict[str, asyncio.Task] = {}

    def _live_ldus(self):
        if self.distributed:
            return self.registry.live_ldus()
        return self.ldus.serving_ldus | {"case-orchestrator"}

    def status(self, sid: str) -> dict:
        return run_status(self.store, sid, self._live_ldus if (self.ldus is not None or self.distributed) else None)

    def running(self, sid: str) -> bool:
        t = self.tasks.get(sid)
        return bool(t and not t.done()) or self.status(sid)["state"] in ("running", "waiting")

    def start(self, sid: str, workflow: str, text: str, actor: str) -> bool:
        if workflow not in WORKFLOWS:
            return False
        run_id = self.store.start(sid, workflow, actor, state="queued" if self.distributed else "running",
                                  input=text)
        if run_id is None:                                # a live run exists (any replica)
            return False
        get_store().append_event(sid, "human", actor, "run_started", detail={"workflow": workflow, "run_id": run_id})
        if self.distributed:                              # a case-orchestrator replica claims it
            return True
        self.tasks[sid] = asyncio.get_running_loop().create_task(self._run(run_id, sid, workflow, text))
        return True

    async def _run(self, run_id: str, sid: str, workflow: str, text: str):
        if self.ldus is not None:
            await self.ldus.start()                       # idempotent: workers for every agent LDU
        await self.executor.execute(run_id, sid, workflow, text)

    async def wait(self, sid: str):
        t = self.tasks.get(sid)
        if t:
            await t
