"""Single-process mode (CPA_LDU_MODE=inprocess): every active agent LDU's worker runs in this
process on an in-memory queue, behind the same dispatcher the distributed mode uses."""
import asyncio

from ..mesh.orchestrator import build_workflows
from .config import mode  # noqa: F401  (re-export)
from .dispatch import Dispatcher, Observer
from .manifest import Manifest, get_manifest
from .queue import InMemoryQueue, StepQueue
from .worker import StepWorker


class InProcessLdus:
    def __init__(self, llm=None, queue: StepQueue | None = None, manifest: Manifest | None = None,
                 observer: Observer | None = None):
        self.manifest = manifest or get_manifest()
        self.queue = queue or InMemoryQueue()
        self.dispatcher = Dispatcher(self.queue, self.manifest, observer)
        self.workflows = build_workflows(llm, dispatch=self.dispatcher)
        self.workers = [StepWorker(u.name, self.workflows["agents"], self.queue, self.manifest)
                        for u in self.manifest.ldus.values() if u.kind == "agent" and u.active]
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    @property
    def serving_ldus(self) -> set[str]:
        return {w.ldu.name for w in self.workers} if self._tasks else set()

    async def start(self):
        if not self._tasks:
            self._stop.clear()
            self._tasks = [asyncio.create_task(w.serve(self._stop, poll=0.5)) for w in self.workers]

    async def stop(self):
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.stop()
