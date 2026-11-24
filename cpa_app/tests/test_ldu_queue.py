"""Step-job queue (design D3), in-memory implementation."""
import asyncio

import pytest

from cpa_agents.ldu.queue import CLAIMED, DONE, FAILED, QUEUED, InMemoryQueue


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def run(coro):
    return asyncio.run(coro)


def test_each_job_is_claimed_once():
    async def go():
        q = InMemoryQueue()
        ids = [await q.enqueue("r1", "c1", "due-diligence-agent", a, {}) for a in ("dd_sanctions", "dd_identity")]
        a = await q.claim("due-diligence-agent", "w1")
        b = await q.claim("due-diligence-agent", "w2")
        c = await q.claim("due-diligence-agent", "w3")
        assert {a.id, b.id} == set(ids) and c is None
        assert a.state == b.state == CLAIMED and a.attempts == 1
    run(go())


def test_claim_only_sees_own_ldu():
    async def go():
        q = InMemoryQueue()
        jid = await q.enqueue("r1", "c1", "narrative-agent", "nd_critic", {})
        assert await q.claim("due-diligence-agent", "w1") is None
        assert (await q.get(jid)).state == QUEUED
        assert (await q.claim("narrative-agent", "w2")).id == jid
    run(go())


def test_release_puts_a_job_back():
    async def go():
        q = InMemoryQueue()
        jid = await q.enqueue("r1", "c1", "pack-agent", "pack_validation", {})
        await q.claim("pack-agent", "w1")
        await q.release(jid)
        j = await q.claim("pack-agent", "w2")
        assert j.id == jid and j.claimed_by == "w2" and j.attempts == 2
    run(go())


def test_heartbeat_expiry():
    async def go():
        clk = Clock()
        q = InMemoryQueue(clock=clk)
        jid = await q.enqueue("r1", "c1", "intake-agent", "intake_classifier", {})
        await q.claim("intake-agent", "w1")
        clk.t += 30
        await q.heartbeat(jid)
        clk.t += 50
        assert await q.expired(60) == []
        clk.t += 20
        assert [j.id for j in await q.expired(60)] == [jid]
    run(go())


def test_wait_returns_on_complete_and_fail():
    async def go():
        q = InMemoryQueue()
        ok = await q.enqueue("r1", "c1", "financial-agent", "financial_analysis", {})
        bad = await q.enqueue("r1", "c1", "financial-agent", "financial_analysis", {})

        async def worker():
            await q.wait_for_work("financial-agent", 1)
            j = await q.claim("financial-agent", "w1")
            await q.complete(j.id, {"delta": {"measures": {"x": 1}}})
            j = await q.claim("financial-agent", "w1")
            await q.fail(j.id, "boom")

        w = asyncio.create_task(worker())
        done = await q.wait(ok, timeout=2)
        failed = await q.wait(bad, timeout=2)
        await w
        assert done.state == DONE and done.result == {"delta": {"measures": {"x": 1}}}
        assert failed.state == FAILED and failed.error == "boom"
    run(go())


def test_wait_times_out():
    async def go():
        q = InMemoryQueue()
        jid = await q.enqueue("r1", "c1", "entity-agent", "entity_structure", {})
        with pytest.raises(asyncio.TimeoutError):
            await q.wait(jid, timeout=0.05)
    run(go())


def test_requeue_expired_puts_back_a_dead_replicas_step():
    """A replica killed mid-step stops heartbeating; its LDU puts the job back for another replica."""
    async def go():
        clk = Clock()
        q = InMemoryQueue(clock=clk)
        jid = await q.enqueue("r1", "c1", "narrative-agent", "nd_critic", {})
        other = await q.enqueue("r1", "c1", "pack-agent", "pack_validation", {})
        await q.claim("narrative-agent", "dead")
        await q.claim("pack-agent", "alive")
        clk.t += 61
        assert await q.requeue_expired("narrative-agent", 60) == [jid]     # only this LDU's jobs
        assert (await q.get(other)).state == CLAIMED
        j = await q.claim("narrative-agent", "w2")
        assert j.id == jid and j.attempts == 2
    run(go())
