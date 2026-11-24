"""Start one LDU by its manifest name (deployable-units: "Start an LDU by name").

    python -m cpa_agents.ldu run due-diligence-agent [--host 0.0.0.0] [--port 8080]
    python -m cpa_agents.ldu list

Every LDU process serves `GET /health` ({ldu, kind, version, ...}) and, in distributed mode,
registers itself in `ldu_workers` with a heartbeat. What else runs depends on the LDU's kind:

  agent   step workers for this LDU's agents only, on the Postgres step queue; jobs whose replica
          stopped heartbeating are put back for another replica (or this LDU after a restart)
  worker  case-orchestrator: claims queued runs and executes them, dispatching agent steps
  api     workbench-api (the web app, which only queues runs), document-extraction, external-adapters
  static  workbench-ui: the built React bundle

Planned LDUs refuse to start. Settings:
  CPA_LDU_SLOTS                  steps one agent-LDU replica runs at once (default: the LDU's concurrency)
  CPA_ORCHESTRATOR_RUNS          runs one orchestrator replica executes at once (default 4)
  CPA_STEP_HEARTBEAT_TIMEOUT     seconds before a silent step is re-queued (default 60)
  CPA_RUN_HEARTBEAT_EVERY        seconds between an orchestrator's run heartbeats (default 10; keep it
                                 well under CPA_RUN_HEARTBEAT_TIMEOUT)
  CPA_LDU_BEAT_EVERY             seconds between registry heartbeats (default 5; keep it well under
                                 CPA_LDU_WORKER_TIMEOUT, default 30)
  CPA_LLM_FACTORY                module:attr (or module:func() to call it) giving the `llm` argument
                                 for build(); tests use scripted models this way. Unset = configured models
  CPA_VERSION                    reported by /health (default: VERSION below)"""
import asyncio
import importlib
import logging
import os
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute

from .manifest import Ldu, Manifest, get_manifest

log = logging.getLogger(__name__)
VERSION = "1.0.0"
UI_DIST = Path(__file__).resolve().parents[2] / "workbench" / "frontend" / "dist"


class LduError(SystemExit):
    """Startup refused (unknown or planned LDU, wrong database)."""


def version() -> str:
    return os.getenv("CPA_VERSION", VERSION)


def resolve(name: str, manifest: Manifest | None = None) -> Ldu:
    m = manifest or get_manifest()
    if name not in m.ldus:
        raise LduError(f"unknown LDU {name!r}; known: {', '.join(sorted(m.ldus))}")
    u = m.ldus[name]
    if not u.active:
        raise LduError(f"LDU {name} is planned and not yet implemented (manifest status: {u.status})")
    return u


def llm_from_env():
    spec = os.getenv("CPA_LLM_FACTORY")
    if not spec:
        return None
    mod, _, attr = spec.partition(":")
    call = attr.endswith("()")
    obj = getattr(importlib.import_module(mod), attr.removesuffix("()"))
    return obj() if call else obj


def _need_postgres(u: Ldu):
    from ..store import get_store
    if get_store().engine.dialect.name != "postgresql":
        raise LduError(f"{u.name} in distributed mode needs Postgres: set DATABASE_URL=postgresql://...")


def _add_health(app: FastAPI, body):
    """Replace any /health route with the LDU health check, ahead of catch-all routes."""
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/health"]

    async def health():
        return body()
    app.router.routes.insert(0, APIRoute("/health", health, methods=["GET"]))


def _chain_lifespan(app: FastAPI, extra):
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        async with inner(a) as st, extra():
            yield st
    app.router.lifespan_context = lifespan


class LduProcess:
    """The background part of one LDU process: registry heartbeat plus the kind-specific loops."""

    def __init__(self, u: Ldu, manifest: Manifest, queue=None, sessions=None, llm=None, register=True):
        self.u, self.m = u, manifest
        self.queue, self.sessions, self.llm = queue, sessions, llm
        self.register = register
        self.id = f"{u.name}@{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.stop = asyncio.Event()
        self.tasks: list[asyncio.Task] = []
        self.workers = []
        self.executor = None
        self.started = False

    # ---- kinds ----
    def _queue(self):
        if self.queue is None:
            _need_postgres(self.u)
            from .pgqueue import PostgresQueue
            self.queue = PostgresQueue()
        return self.queue

    async def _agent_loops(self):
        from ..mesh.orchestrator import build_workflows
        from .limits import settings
        from .worker import StepWorker
        q = self._queue()
        agents = build_workflows(self.llm)["agents"]               # checks the manifest against build()
        slots = int(os.getenv("CPA_LDU_SLOTS") or settings(self.u).concurrency)
        self.workers = [StepWorker(self.u.name, agents, q, self.m, worker_id=f"{self.id}#{i}")
                        for i in range(max(1, slots))]
        timeout = float(os.getenv("CPA_STEP_HEARTBEAT_TIMEOUT", "60"))

        async def requeue():
            while not self.stop.is_set():
                ids = await q.requeue_expired(self.u.name, timeout)
                if ids:
                    log.warning("%s re-queued steps %s (their replica stopped)", self.u.name, ids)
                await asyncio.sleep(min(15.0, timeout / 2))
        return [w.serve(self.stop, poll=2.0) for w in self.workers] + [requeue()]

    async def _orchestrator_loops(self):
        from ..mesh.orchestrator import build_workflows
        from ..store.core import STEP_CHANNEL
        from ..store.runtime import make_session_service
        from .dispatch import Dispatcher
        from .pgqueue import wait_notified
        from .runs import RunExecutor, RunStore
        q = self._queue()
        rs = RunStore()
        self.executor = RunExecutor(self.sessions or make_session_service(), {}, rs, name=self.id,
                                    heartbeat_every=float(os.getenv("CPA_RUN_HEARTBEAT_EVERY", "10")))
        self.executor.workflows = build_workflows(self.llm, dispatch=Dispatcher(q, self.m, self.executor))
        slots = asyncio.Semaphore(int(os.getenv("CPA_ORCHESTRATOR_RUNS", "4")))
        running: set[asyncio.Task] = set()

        async def one(row):
            try:
                await self.executor.execute(row["run_id"], row["session_id"], row["workflow"], row["input"] or "")
            finally:
                slots.release()

        async def claim():
            while not self.stop.is_set():
                await slots.acquire()
                row = await asyncio.to_thread(rs.claim_queued, self.id)
                if row is None:
                    slots.release()
                    await wait_notified(STEP_CHANNEL, "q:case-orchestrator", rs.has_queued, timeout=5.0)
                    continue
                t = asyncio.create_task(one(row))
                running.add(t)
                t.add_done_callback(running.discard)
        return [claim()]

    async def _beat(self):
        from .registry import Registry
        reg = Registry()
        await asyncio.to_thread(reg.register, self.id, self.u.name, version())
        try:
            while not self.stop.is_set():
                await asyncio.sleep(float(os.getenv("CPA_LDU_BEAT_EVERY", "5")))
                await asyncio.to_thread(reg.beat, self.id)
        finally:
            await asyncio.to_thread(reg.unregister, self.id)

    async def start(self):
        loops = []
        if self.u.kind == "agent":
            loops = await self._agent_loops()
        elif self.u.name == "case-orchestrator":
            loops = await self._orchestrator_loops()
        if self.register:
            loops.append(self._beat())
        self.tasks = [asyncio.create_task(c) for c in loops]
        self.started = True

    async def close(self):
        self.stop.set()
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    @asynccontextmanager
    async def running(self):
        await self.start()
        try:
            yield self
        finally:
            await self.close()

    def health(self) -> dict:
        body = {"ldu": self.u.name, "kind": self.u.kind, "version": version(), "manifest_version": self.m.version,
                "ok": self.started and not any(t.done() and not t.cancelled() and t.exception() for t in self.tasks),
                "worker_id": self.id}
        if self.u.agents:
            body["agents"] = list(self.u.agents)
        return body


def build_app(name: str, manifest: Manifest | None = None, **kw) -> FastAPI:
    """The ASGI app for one LDU. Keyword arguments go to LduProcess (tests inject a queue)."""
    m = manifest or get_manifest()
    u = resolve(name, m)
    if u.kind == "api":
        app = _api_app(u)
    elif u.kind == "static":
        from fastapi.staticfiles import StaticFiles
        if not (UI_DIST / "index.html").exists():
            raise LduError(f"{name}: no UI bundle at {UI_DIST}; run npm run build in workbench/frontend")
        app = FastAPI(title=name)
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    else:
        app = FastAPI(title=name)
    proc = LduProcess(u, m, **kw)
    app.state.ldu = proc
    _chain_lifespan(app, proc.running)
    _add_health(app, proc.health)
    return app


def _api_app(u: Ldu) -> FastAPI:
    if u.name == "document-extraction":
        from .services.extraction import create_service
        return create_service()
    if u.name == "external-adapters":
        from .services.adapters import create_service
        return create_service()
    if u.name == "workbench-api":
        from workbench.app import create_app
        return create_app()
    raise LduError(f"no service is defined for api LDU {u.name}")


def init():
    """One-off setup before the LDUs start (docker compose runs it first), so replicas do not race
    to create tables: the store schema, ADK's session tables, and the upload bucket for s3."""
    from ..files import S3FileStore, get_file_store
    from ..store import get_store
    from ..store.runtime import make_session_service
    store = get_store()                                            # creates the store schema
    asyncio.run(make_session_service().list_sessions(app_name="cpa", user_id="init"))   # ADK tables
    log.info("database ready (%s)", store.engine.dialect.name)
    fs = get_file_store()
    if isinstance(fs, S3FileStore):
        import time
        for attempt in range(30):                                  # the object store may still be starting
            try:
                try:
                    fs.s3.head_bucket(Bucket=fs.bucket)
                except Exception as e:                             # noqa: BLE001
                    if getattr(e, "response", {}).get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                        raise
                    fs.s3.create_bucket(Bucket=fs.bucket)
                    log.info("created bucket %s", fs.bucket)
                break
            except Exception as e:                                 # noqa: BLE001
                if attempt == 29:
                    raise
                log.info("object store not ready (%s); retrying", e)
                time.sleep(2)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m cpa_agents.ldu", description="Run one Least Deployable Unit.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="start one LDU by its manifest name")
    r.add_argument("name")
    r.add_argument("--host", default=os.getenv("CPA_LDU_HOST", "127.0.0.1"))
    r.add_argument("--port", type=int, default=int(os.getenv("CPA_LDU_PORT", "8080")))
    sub.add_parser("list", help="list the LDUs in the manifest")
    sub.add_parser("init", help="create the database tables (store and ADK sessions) and the S3 bucket, once")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    m = get_manifest()
    if args.cmd == "list":
        for u in m.ldus.values():
            print(f"{u.name:22} {u.kind:7} {u.status:8} {', '.join(u.agents or u.components)}")
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "init":
        init()
        return 0
    app = build_app(args.name, m, llm=llm_from_env())
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0
