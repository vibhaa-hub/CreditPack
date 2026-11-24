"""Which LDUs are alive (distributed mode). Every LDU process registers a row in `ldu_workers` and
heartbeats it; `live_ldus()` is what run status uses to say "waiting for <LDU>" when a run has a
step dispatched to an LDU with no live replica."""
import os
import time

from sqlalchemy import delete, select, update

from ..store import get_store
from ..store.schema import ldu_workers


def worker_timeout() -> float:
    return float(os.getenv("CPA_LDU_WORKER_TIMEOUT", "30"))


class Registry:
    def __init__(self, clock=time.time):
        self.clock = clock

    @property
    def engine(self):
        return get_store().engine

    def register(self, worker_id: str, ldu: str, version: str | None = None):
        now = self.clock()
        with self.engine.begin() as c:
            c.execute(delete(ldu_workers).where(ldu_workers.c.worker_id == worker_id))
            c.execute(ldu_workers.insert().values(worker_id=worker_id, ldu=ldu, version=version,
                                                  started_at=now, heartbeat_at=now))

    def beat(self, worker_id: str):
        with self.engine.begin() as c:
            c.execute(update(ldu_workers).where(ldu_workers.c.worker_id == worker_id)
                      .values(heartbeat_at=self.clock()))

    def unregister(self, worker_id: str):
        with self.engine.begin() as c:
            c.execute(delete(ldu_workers).where(ldu_workers.c.worker_id == worker_id))

    def live(self, timeout: float | None = None) -> dict[str, int]:
        """{ldu: live replica count}."""
        since = self.clock() - (worker_timeout() if timeout is None else timeout)
        with self.engine.connect() as c:
            rows = c.execute(select(ldu_workers.c.ldu).where(ldu_workers.c.heartbeat_at >= since)).scalars().all()
        out: dict[str, int] = {}
        for u in rows:
            out[u] = out.get(u, 0) + 1
        return out

    def live_ldus(self) -> set[str]:
        return set(self.live())
