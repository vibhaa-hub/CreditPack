"""Postgres runtime pieces for distributed mode (design D3, D6).

`PostgresQueue` keeps step jobs in the `step_jobs` table. A replica claims the oldest queued job of
its LDU with `SELECT ... FOR UPDATE SKIP LOCKED`, so two replicas never claim the same job and never
block each other. Enqueue, release, complete and fail send a NOTIFY on `cpa_steps`
("q:<ldu>" = work available, "d:<id>" = job finished).

`Listener` is one LISTEN connection per process, on a background thread, that wakes the asyncio
waiters for a channel and key: queue waits, and the workbench SSE stream (`cpa_cases`, payload = the
session id, sent on every audit event and run change). Every wait also has a poll timeout, so a
dropped notification only delays a wake-up and never loses one."""
import asyncio
import logging
import threading
import time
from collections import defaultdict

from sqlalchemy import and_, select, text, update

from ..store import get_store
from ..store.core import CASE_CHANNEL, STEP_CHANNEL, notify
from ..store.schema import step_jobs
from .queue import CLAIMED, DONE, FAILED, QUEUED, Job, StepQueue

log = logging.getLogger(__name__)
_CLAIM = text("""
UPDATE step_jobs SET state = 'claimed', claimed_by = :worker, attempts = attempts + 1,
                     claimed_at = :now, heartbeat_at = :now
WHERE id = (SELECT id FROM step_jobs WHERE ldu = :ldu AND state = 'queued'
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING *""")


def _job(r) -> Job:
    r = dict(r)
    return Job(id=r["id"], run_id=r["run_id"], case_id=r["case_id"], ldu=r["ldu"], agent=r["agent"],
               payload=r["payload"] or {}, state=r["state"], attempts=r["attempts"], claimed_by=r["claimed_by"],
               claimed_at=r["claimed_at"], heartbeat_at=r["heartbeat_at"], result=r["result"], error=r["error"],
               enqueued_at=r["enqueued_at"])


class Listener:
    """One LISTEN connection per process. `waiter(channel, key)` returns an asyncio.Event that is set
    when a notification with that payload arrives; `done(...)` unregisters it."""

    def __init__(self, url: str, channels=(STEP_CHANNEL, CASE_CHANNEL)):
        self.url, self.channels = url, tuple(channels)
        self._waiters: dict[tuple, set] = defaultdict(set)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connected = threading.Event()
        self.received = 0
        self._thread = threading.Thread(target=self._loop, name="cpa-pg-listen", daemon=True)
        self._thread.start()

    def waiter(self, channel: str, key: str) -> asyncio.Event:
        ev = asyncio.Event()
        ev._cpa_loop = asyncio.get_running_loop()
        with self._lock:
            self._waiters[(channel, str(key))].add(ev)
        return ev

    def done(self, channel: str, key: str, ev: asyncio.Event):
        with self._lock:
            self._waiters[(channel, str(key))].discard(ev)

    def _wake(self, channel: str, payload: str):
        with self._lock:
            evs = list(self._waiters.get((channel, payload), ()))
        for ev in evs:
            try:
                ev._cpa_loop.call_soon_threadsafe(ev.set)
            except RuntimeError:                                       # loop closed
                self.done(channel, payload, ev)

    def _loop(self):
        import psycopg
        while not self._stop.is_set():
            try:
                with psycopg.connect(self.url, autocommit=True) as conn:
                    for ch in self.channels:
                        conn.execute(f"LISTEN {ch}")
                    self.connected.set()
                    while not self._stop.is_set():
                        for n in conn.notifies(timeout=1.0):
                            self.received += 1
                            self._wake(n.channel, n.payload)
            except Exception as e:                                    # reconnect; waits still poll
                self.connected.clear()
                log.warning("LISTEN connection lost (%s); retrying", e)
                self._stop.wait(2.0)

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)


_listeners: dict[str, Listener] = {}
_listeners_lock = threading.Lock()


def listener() -> Listener | None:
    """The process-wide listener for the configured database, or None when it is not Postgres."""
    eng = get_store().engine
    if eng.dialect.name != "postgresql":
        return None
    url = eng.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with _listeners_lock:
        if url not in _listeners:
            _listeners[url] = Listener(url)
        return _listeners[url]


async def wait_notified(channel: str, key: str, check, timeout: float | None, poll: float = 2.0):
    """Wait until `check()` (a sync DB read, run in a thread) returns something truthy, waking on
    NOTIFY channel/key or every `poll` seconds. Returns check()'s value, or None on timeout."""
    lst = listener()
    ev = lst.waiter(channel, key) if lst else None
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while True:
            if ev:
                ev.clear()
            got = await asyncio.to_thread(check)
            if got:
                return got
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                return None
            step = poll if left is None else min(poll, left)
            if ev:
                try:
                    await asyncio.wait_for(ev.wait(), step)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(step)
    finally:
        if ev:
            lst.done(channel, key, ev)


class Subscription:
    """A standing wait on one channel/key, for loops like the SSE stream:
    `async with Subscription(ch, key) as sub: ... await sub.wait(t)`. Notifications that arrive
    while the loop is busy are kept until the next wait(). Without Postgres, wait() just sleeps."""

    def __init__(self, channel: str, key: str):
        self.channel, self.key, self.ev, self.lst = channel, str(key), None, None

    @property
    def live(self) -> bool:
        return self.ev is not None and self.lst.connected.is_set()

    async def __aenter__(self):
        self.lst = await asyncio.to_thread(listener)
        if self.lst:
            self.ev = self.lst.waiter(self.channel, self.key)
        return self

    async def __aexit__(self, *exc):
        if self.ev:
            self.lst.done(self.channel, self.key, self.ev)

    async def wait(self, timeout: float) -> bool:
        """True if notified, False on timeout."""
        if self.ev is None:
            await asyncio.sleep(timeout)
            return False
        try:
            await asyncio.wait_for(self.ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self.ev.clear()


class PostgresQueue(StepQueue):
    def __init__(self, clock=time.time, poll: float = 2.0):
        self.clock, self.poll = clock, poll

    @property
    def engine(self):
        return get_store().engine

    # ---- sync bodies, run in a thread ----
    def _enqueue(self, run_id, case_id, ldu, agent, payload) -> int:
        with self.engine.begin() as c:
            jid = c.execute(step_jobs.insert().values(run_id=run_id, case_id=case_id, ldu=ldu, agent=agent,
                                                      payload=dict(payload), state=QUEUED, attempts=0,
                                                      enqueued_at=self.clock())
                            .returning(step_jobs.c.id)).scalar_one()
            notify(c, STEP_CHANNEL, f"q:{ldu}")
        return jid

    def _claim(self, ldu, worker) -> Job | None:
        with self.engine.begin() as c:
            r = c.execute(_CLAIM, {"worker": worker, "now": self.clock(), "ldu": ldu}).mappings().first()
        return _job(r) if r else None

    def _set(self, job_id, where_state=None, channel_payload=None, **vals):
        cond = step_jobs.c.id == job_id
        if where_state:
            cond = and_(cond, step_jobs.c.state == where_state)
        with self.engine.begin() as c:
            n = c.execute(update(step_jobs).where(cond).values(**vals)).rowcount
            if n and channel_payload:
                notify(c, STEP_CHANNEL, channel_payload)
        return n

    def _get(self, job_id) -> Job:
        with self.engine.connect() as c:
            r = c.execute(select(step_jobs).where(step_jobs.c.id == job_id)).mappings().first()
        if r is None:
            raise KeyError(job_id)
        return _job(r)

    def _finished(self, job_id):
        j = self._get(job_id)
        return j if j.finished else None

    def _has_work(self, ldu):
        with self.engine.connect() as c:
            return c.execute(select(step_jobs.c.id).where(and_(step_jobs.c.ldu == ldu, step_jobs.c.state == QUEUED))
                             .limit(1)).first() is not None

    # ---- StepQueue ----
    async def enqueue(self, run_id, case_id, ldu, agent, payload) -> int:
        return await asyncio.to_thread(self._enqueue, run_id, case_id, ldu, agent, payload)

    async def claim(self, ldu, worker):
        return await asyncio.to_thread(self._claim, ldu, worker)

    async def release(self, job_id):
        j = await self.get(job_id)
        await asyncio.to_thread(self._set, job_id, CLAIMED, f"q:{j.ldu}", state=QUEUED, claimed_by=None,
                                claimed_at=None, heartbeat_at=None)

    async def heartbeat(self, job_id):
        await asyncio.to_thread(self._set, job_id, CLAIMED, None, heartbeat_at=self.clock())

    async def complete(self, job_id, result):
        await asyncio.to_thread(self._set, job_id, None, f"d:{job_id}", state=DONE, result=dict(result))

    async def fail(self, job_id, error):
        await asyncio.to_thread(self._set, job_id, None, f"d:{job_id}", state=FAILED, error=error[:2000])

    async def get(self, job_id):
        return await asyncio.to_thread(self._get, job_id)

    async def wait(self, job_id, timeout=None):
        j = await wait_notified(STEP_CHANNEL, f"d:{job_id}", lambda: self._finished(job_id), timeout, self.poll)
        if j is None:
            raise asyncio.TimeoutError(f"step job {job_id} did not finish in {timeout}s")
        return j

    async def wait_for_work(self, ldu, timeout):
        await wait_notified(STEP_CHANNEL, f"q:{ldu}", lambda: self._has_work(ldu), timeout, self.poll)

    async def expired(self, timeout):
        def q():
            with self.engine.connect() as c:
                rows = c.execute(select(step_jobs).where(and_(step_jobs.c.state == CLAIMED,
                                                              step_jobs.c.heartbeat_at < self.clock() - timeout))
                                 ).mappings().all()
            return [_job(r) for r in rows]
        return await asyncio.to_thread(q)

    async def requeue_expired(self, ldu, timeout):
        """Put back the claimed jobs of `ldu` whose replica stopped heartbeating (it was killed
        mid-step); another replica, or the same LDU after a restart, runs them again."""
        def q():
            with self.engine.begin() as c:
                ids = c.execute(update(step_jobs).where(and_(step_jobs.c.ldu == ldu, step_jobs.c.state == CLAIMED,
                                                             step_jobs.c.heartbeat_at < self.clock() - timeout))
                                .values(state=QUEUED, claimed_by=None, claimed_at=None, heartbeat_at=None)
                                .returning(step_jobs.c.id)).scalars().all()
                if ids:
                    notify(c, STEP_CHANNEL, f"q:{ldu}")
            return list(ids)
        return await asyncio.to_thread(q)

    def queued_ldus(self) -> set[str]:
        with self.engine.connect() as c:
            return set(c.execute(select(step_jobs.c.ldu).where(step_jobs.c.state == QUEUED).distinct()).scalars())
