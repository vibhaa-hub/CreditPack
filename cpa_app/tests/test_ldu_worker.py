"""Step worker (design D4): isolated step session, state delta, own-LDU-only, failures reported."""
import asyncio

import pytest

from cpa_agents.ldu.queue import DONE, FAILED, QUEUED, InMemoryQueue
from cpa_agents.ldu.worker import StepWorker, compute_delta
from cpa_agents.mesh.agents import build
from fakes import factory
from test_mesh import REQUEST, SCRIPTS


@pytest.fixture
def agents(store):
    return build(llm=factory(SCRIPTS))


def test_compute_delta():
    assert compute_delta({"a": 1, "b": [1], "gone": 2}, {"a": 1, "b": [1, 2], "new": "x"}) == \
        {"b": [1, 2], "new": "x", "gone": None}


def test_intake_step_returns_delta_and_audits_on_the_case(agents, store):
    async def go():
        q = InMemoryQueue()
        w = StepWorker("intake-agent", agents, q, heartbeat_every=0.05)
        jid = await q.enqueue("run-1", "case-s1", "intake-agent", "intake_classifier",
                              {"state": {"request_text": REQUEST}, "input": REQUEST})
        assert await w.process_one()
        return await q.get(jid)
    job = asyncio.run(go())
    assert job.state == DONE, job.error
    d = job.result["delta"]
    assert d["case_id"] and d["dealer_name"] == "Acme Motors Ltd" and "request_text" not in d
    assert d["intake_classifier_summary"] == job.result["output"] == "intake_classifier done"
    events = store.events("case-s1")
    assert {e["action"] for e in events} >= {"tool_called", "tool_result", "agent_complete"}
    assert all(e["actor"] == "intake_classifier" for e in events)
    assert any(e["case_id"] == d["case_id"] for e in events)


def test_worker_does_not_touch_any_case_session(agents, store):
    """The worker has no session service for the case: the delta is the only thing it hands back."""
    async def go():
        q = InMemoryQueue()
        w = StepWorker("narrative-agent", agents, q)
        jid = await q.enqueue("run-1", "case-s2", "narrative-agent", "nd_security_esg",
                              {"state": {"case_id": "CPA-T-1", "sections": {}}, "input": "go"})
        await w.process_one()
        return await q.get(jid)
    job = asyncio.run(go())
    assert job.state == DONE, job.error
    assert set(job.result["delta"]) >= {"sections@nd_security_esg", "nd_security_esg_summary"}
    assert "sections" not in job.result["delta"]                   # parallel agent writes its partition


def test_step_for_another_ldu_is_left_for_it(agents, store):
    async def go():
        q = InMemoryQueue()
        dd = StepWorker("due-diligence-agent", agents, q)
        jid = await q.enqueue("run-1", "case-s3", "due-diligence-agent", "nd_critic", {"state": {}, "input": ""})
        await dd.process_one()
        return await q.get(jid)
    job = asyncio.run(go())
    assert job.state == QUEUED and job.result is None


def test_worker_hosts_only_its_ldus_agents(agents):
    w = StepWorker("pack-agent", agents, InMemoryQueue())
    assert set(w.agents) == {"pack_request", "pack_validation", "pack_transmit"}
    with pytest.raises(ValueError, match="not an active agent LDU"):
        StepWorker("workbench-api", agents, InMemoryQueue())


def test_agent_error_fails_the_job(agents, store):
    class Boom(Exception):
        pass

    async def go():
        q = InMemoryQueue()
        w = StepWorker("financial-agent", agents, q)

        async def explode(*a, **k):
            raise Boom("model unavailable")
        w.execute = explode
        jid = await q.enqueue("run-1", "case-s4", "financial-agent", "financial_analysis", {"state": {}, "input": ""})
        await w.process_one()
        return await q.get(jid)
    job = asyncio.run(go())
    assert job.state == FAILED and job.error == "Boom: model unavailable"
