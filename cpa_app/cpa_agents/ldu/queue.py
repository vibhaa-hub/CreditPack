"""Step-job queue (design D3). The orchestrator enqueues one job per agent step on the queue of
the agent's LDU; a replica of that LDU claims it, runs the step and completes it with a result.

`StepQueue` is the interface. `InMemoryQueue` serves single-process mode (and SQLite);
`PostgresQueue` (SELECT ... FOR UPDATE SKIP LOCKED) serves distributed mode."""
import asyncio
import itertools
import time
from dataclasses import dataclass, field

QUEUED, CLAIMED, DONE, FAILED = "queued", "claimed", "done", "failed"


@dataclass
class Job:
    id: int
    run_id: str
    case_id: str
    ldu: str
    agent: str
    payload: dict
    state: str = QUEUED
    attempts: int = 0
    claimed_by: str | None = None
    claimed_at: float | None = None
    heartbeat_at: float | None = None
    result: dict | None = None
    error: str | None = None
    enqueued_at: float = field(default_factory=time.time)

    @property
    def finished(self) -> bool:
        return self.state in (DONE, FAILED)


class StepQueue:
    """Interface. All methods are async so the Postgres implementation can do I/O."""

    async def enqueue(self, run_id: str, case_id: str, ldu: str, agent: str, payload: dict) -> int: ...
    async def claim(self, ldu: str, worker: str) -> Job | None: ...
    async def release(self, job_id: int) -> None: ...
    async def heartbeat(self, job_id: int) -> None: ...
    async def complete(self, job_id: int, result: dict) -> None: ...
    async def fail(self, job_id: int, error: str) -> None: ...
    async def get(self, job_id: int) -> Job: ...
    async def wait(self, job_id: int, timeout: float | None = None) -> Job: ...
    async def wait_for_work(self, ldu: str, timeout: float) -> None: ...
    async def expired(self, timeout: float) -> list[Job]: ...
    async def requeue_expired(self, ldu: str, timeout: float) -> list[int]: ...


class InMemoryQueue(StepQueue):
    def __init__(self, clock=time.time):
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self._changed = asyncio.Condition()
        self.clock = clock

    async def _notify(self):
        async with self._changed:
            self._changed.notify_all()

    async def enqueue(self, run_id, case_id, ldu, agent, payload) -> int:
        jid = next(self._ids)
        self._jobs[jid] = Job(jid, run_id, case_id, ldu, agent, dict(payload), enqueued_at=self.clock())
        await self._notify()
        return jid

    async def claim(self, ldu, worker):
        for j in sorted(self._jobs.values(), key=lambda j: j.id):
            if j.ldu == ldu and j.state == QUEUED:
                j.state, j.claimed_by, j.attempts = CLAIMED, worker, j.attempts + 1
                j.claimed_at = j.heartbeat_at = self.clock()
                return j
        return None

    async def release(self, job_id):
        j = self._jobs[job_id]
        if j.state == CLAIMED:
            j.state, j.claimed_by, j.claimed_at, j.heartbeat_at = QUEUED, None, None, None
            await self._notify()

    async def heartbeat(self, job_id):
        j = self._jobs[job_id]
        if j.state == CLAIMED:
            j.heartbeat_at = self.clock()

    async def complete(self, job_id, result):
        j = self._jobs[job_id]
        j.state, j.result = DONE, dict(result)
        await self._notify()

    async def fail(self, job_id, error):
        j = self._jobs[job_id]
        j.state, j.error = FAILED, error[:2000]
        await self._notify()

    async def get(self, job_id):
        return self._jobs[job_id]

    async def wait(self, job_id, timeout=None):
        async def done():
            async with self._changed:
                await self._changed.wait_for(lambda: self._jobs[job_id].finished)
        await asyncio.wait_for(done(), timeout)
        return self._jobs[job_id]

    async def wait_for_work(self, ldu, timeout):
        def ready():
            return any(j.ldu == ldu and j.state == QUEUED for j in self._jobs.values())
        try:
            async with self._changed:
                await asyncio.wait_for(self._changed.wait_for(ready), timeout)
        except asyncio.TimeoutError:
            pass

    async def expired(self, timeout):
        now = self.clock()
        return [j for j in self._jobs.values() if j.state == CLAIMED and now - (j.heartbeat_at or 0) > timeout]

    async def requeue_expired(self, ldu, timeout):
        """Put back the claimed jobs of `ldu` whose replica stopped heartbeating."""
        ids = [j.id for j in await self.expired(timeout) if j.ldu == ldu]
        for i in ids:
            await self.release(i)
        return ids

    def queued_ldus(self) -> set[str]:
        return {j.ldu for j in self._jobs.values() if j.state == QUEUED}
