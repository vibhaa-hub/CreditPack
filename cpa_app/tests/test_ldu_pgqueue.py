"""PostgresQueue and LISTEN/NOTIFY (design D3, D6). Needs TEST_DATABASE_URL pointing at Postgres."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cpa_agents.ldu.pgqueue import PostgresQueue, Subscription, listener
from cpa_agents.ldu.queue import CLAIMED, DONE, QUEUED
from cpa_agents.store.core import CASE_CHANNEL

pytestmark = [pytest.mark.distributed,
              pytest.mark.skipif(not (os.getenv("TEST_DATABASE_URL") or "").startswith("postgresql"),
                                 reason="set TEST_DATABASE_URL to a Postgres database")]

ROOT = Path(__file__).resolve().parents[1]
WORKER = r"""
import json, sys, time, asyncio
from cpa_agents import store
from cpa_agents.ldu.pgqueue import PostgresQueue
store.configure(sys.argv[1])
name, go_at = sys.argv[2], float(sys.argv[3])
async def main():
    q, got = PostgresQueue(), []
    while time.time() < go_at:
        time.sleep(0.005)
    while True:
        j = await q.claim("due-diligence-agent", name)
        if j is None:
            break
        got.append(j.id)
        time.sleep(0.002)                       # hold the step briefly so the two workers interleave
        await q.complete(j.id, {"delta": {}, "output": name})
    print(json.dumps(got))
asyncio.run(main())
"""


def run(coro):
    return asyncio.run(coro)


def test_two_worker_processes_claim_each_job_exactly_once(store, db_url):
    q = PostgresQueue()
    ids = run(_enqueue(q, 50))
    go_at = time.time() + 3.0                                           # both start claiming together
    procs = [subprocess.Popen([sys.executable, "-c", WORKER, db_url, f"w{i}", str(go_at)], cwd=ROOT,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in (1, 2)]
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        outs.append(json.loads(out.strip().splitlines()[-1]))
    a, b = map(set, outs)
    assert len(outs[0]) == len(a) and len(outs[1]) == len(b)             # no worker saw a job twice
    assert not a & b and a | b == set(ids)                               # each job claimed exactly once
    assert a and b                                                       # both workers did work
    jobs = run(_all(q, ids))
    assert all(j.state == DONE and j.attempts == 1 for j in jobs)
    assert {j.claimed_by for j in jobs} == {"w1", "w2"}


async def _enqueue(q, n):
    return [await q.enqueue("run-1", "case-1", "due-diligence-agent", "dd_sanctions", {"i": i}) for i in range(n)]


async def _all(q, ids):
    return [await q.get(i) for i in ids]


def test_claim_release_heartbeat_expiry(store):
    async def go():
        t = [1000.0]
        q = PostgresQueue(clock=lambda: t[0])
        jid = await q.enqueue("r1", "c1", "narrative-agent", "nd_critic", {"x": 1})
        assert await q.claim("due-diligence-agent", "w1") is None        # another LDU's queue
        j = await q.claim("narrative-agent", "w1")
        assert j.id == jid and j.state == CLAIMED and j.payload == {"x": 1}
        assert await q.claim("narrative-agent", "w2") is None
        t[0] += 30
        await q.heartbeat(jid)
        t[0] += 20
        assert await q.expired(25) == []
        t[0] += 10
        assert [x.id for x in await q.expired(25)] == [jid]
        await q.release(jid)
        assert (await q.get(jid)).state == QUEUED and q.queued_ldus() == {"narrative-agent"}
        j2 = await q.claim("narrative-agent", "w2")
        assert j2.claimed_by == "w2" and j2.attempts == 2
        await q.fail(jid, "boom")
        assert (await q.wait(jid, timeout=1)).error == "boom"
    run(go())


def test_notify_wakes_waiters_without_polling(store):
    """poll=60: the waits can only return quickly if NOTIFY woke them."""
    async def go():
        q = PostgresQueue(poll=60)
        lst = await asyncio.to_thread(listener)
        assert await asyncio.to_thread(lst.connected.wait, 10)
        jid = await q.enqueue("r1", "c1", "pack-agent", "pack_validation", {})
        await q.claim("pack-agent", "w1")

        def later():
            time.sleep(0.5)
            run(q.complete(jid, {"delta": {"a": 1}, "output": "ok"}))
        threading.Thread(target=later).start()
        t0 = time.monotonic()
        j = await q.wait(jid, timeout=30)
        assert j.result == {"delta": {"a": 1}, "output": "ok"} and time.monotonic() - t0 < 10

        def later_enqueue():
            time.sleep(0.5)
            run(q.enqueue("r1", "c1", "intake-agent", "intake_classifier", {}))
        threading.Thread(target=later_enqueue).start()
        t0 = time.monotonic()
        await q.wait_for_work("intake-agent", timeout=30)
        assert time.monotonic() - t0 < 10 and "intake-agent" in q.queued_ldus()
    run(go())


def test_case_subscription_wakes_on_audit_event(store):
    """What the SSE stream relies on: any audit append for the case, from any process, wakes it."""
    async def go():
        async with Subscription(CASE_CHANNEL, "wb-sse") as sub:
            assert await asyncio.to_thread(sub.lst.connected.wait, 10) and sub.live
            assert await sub.wait(0.3) is False
            threading.Timer(0.3, lambda: store.append_event("wb-sse", "human", "Jane Smith", "note")).start()
            t0 = time.monotonic()
            assert await sub.wait(20) is True and time.monotonic() - t0 < 10
            store.append_event("other-case", "human", "Jane Smith", "note")
            assert await sub.wait(1.5) is False                          # other cases don't wake it
    run(go())


def test_dispatched_run_on_postgres_queue_matches_direct_run(store):
    """The single-process LDU runtime with the Postgres queue in place of the in-memory one."""
    from cpa_agents.ldu.runtime import InProcessLdus
    from cpa_agents.mesh.orchestrator import build_workflows
    from fakes import factory
    from test_ldu_inprocess import canonical, lifecycle
    from test_mesh import SCRIPTS

    async def go():
        direct = await lifecycle(build_workflows(llm=factory(SCRIPTS)), "d1")
        async with InProcessLdus(llm=factory(SCRIPTS), queue=PostgresQueue(poll=0.5)) as ldus:
            remote = await lifecycle(ldus.workflows, "r1")
        return direct, remote
    (dprep, ddone), (rprep, rdone) = run(go())
    assert canonical(rprep) == canonical(dprep) and canonical(rdone) == canonical(ddone)
    assert rdone.get("submitted")


def test_requeue_expired_on_postgres(store):
    async def go():
        t = [1000.0]
        q = PostgresQueue(clock=lambda: t[0])
        jid = await q.enqueue("r1", "c1", "narrative-agent", "nd_critic", {})
        await q.claim("narrative-agent", "dead")
        t[0] += 30
        assert await q.requeue_expired("narrative-agent", 60) == []
        t[0] += 31
        assert await q.requeue_expired("due-diligence-agent", 60) == []
        assert await q.requeue_expired("narrative-agent", 60) == [jid]
        j = await q.claim("narrative-agent", "w2")
        assert j.id == jid and j.attempts == 2 and j.claimed_by == "w2"
    run(go())
