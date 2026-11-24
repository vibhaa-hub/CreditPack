"""Workflows run through the LDU dispatcher in single-process mode give the same result as the
agents run directly (deployable-units spec: single-process mode; agent-orchestration: parallel
writes are not lost)."""
import asyncio
from collections import Counter

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from cpa_agents.ldu.dispatch import StepFailed
from cpa_agents.ldu.runtime import InProcessLdus
from cpa_agents.mesh.orchestrator import build_workflows
from cpa_agents.store.replay import replay
from cpa_agents.store.runtime import record_human_decision
from fakes import factory
from test_mesh import REQUEST, SCRIPTS

APP, USER = "cpa", "u"
VOLATILE = {"case_id", "received_at", "at", "created_at", "recorded_at", "requested_at", "saved_at", "updated_at",
            "sha256", "generated_at", "snapshot_id", "submitted_at", "transmitted_at", "submission_id"}


async def _run(wf, sessions, sid, text):
    r = Runner(agent=wf, app_name=APP, session_service=sessions)
    async for _ in r.run_async(user_id=USER, session_id=sid,
                               new_message=types.Content(role="user", parts=[types.Part(text=text)])):
        pass
    return (await sessions.get_session(app_name=APP, user_id=USER, session_id=sid)).state


def scrub(v):
    """Drop values that legitimately differ between two runs (ids, timestamps, hashes)."""
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items() if k not in VOLATILE}
    if isinstance(v, list):
        return [scrub(x) for x in v]
    if isinstance(v, str) and v.startswith(("CASE-", "CPA-")):
        return "ID"
    return v


def canonical(state):
    out = {}
    for k, v in state.items():
        if k in VOLATILE:
            continue
        v = scrub(v)
        out[k] = sorted(v, key=repr) if isinstance(v, list) else v       # order within parallel branches
    return out


async def lifecycle(wf, sid):
    sessions = InMemorySessionService()
    await sessions.create_session(app_name=APP, user_id=USER, session_id=sid)
    prep = dict(await _run(wf["preparation"], sessions, sid, REQUEST))
    sections = {k: {**v, "reviewed": True} for k, v in prep["sections"].items()}
    await record_human_decision(sessions, APP, USER, sid, "Jane Smith", {
        "cra_recorded_by": "analyst-7", "pricing_authorised_by": "pricing-committee-2",
        "sections": sections, "submission_authorised_by": "Jane Smith"}, "humans acted")
    done = dict(await _run(wf["submission"], sessions, sid, "transmit"))
    return prep, done


def test_dispatched_run_matches_direct_run(store):
    async def go():
        direct = await lifecycle(build_workflows(llm=factory(SCRIPTS)), "d1")
        async with InProcessLdus(llm=factory(SCRIPTS)) as ldus:
            remote = await lifecycle(ldus.workflows, "r1")
        return direct, remote
    (dprep, ddone), (rprep, rdone) = asyncio.run(go())

    # preparation: branches ran, partitions merged, stopped for humans
    assert len(rprep["checks"]) == 9 and not any("@" in k and rprep[k] for k in rprep)
    assert set(rprep["sections"]) == {"business_background", "management_assessment", "conduct_performance",
                                      "security_review"}
    assert rprep["gate_status"] == "BLOCKED" and "submitted" not in rprep
    assert canonical(rprep) == canonical(dprep)
    # submission after humans: transmitted, same final state
    assert rdone["submitted"]["pack_version"] == 1
    assert canonical(rdone) == canonical(ddone)

    # same audit actions (by actor and action), and an intact hash chain
    d, r = replay(ddone["case_id"]), replay(rdone["case_id"])
    key = lambda out: Counter((e["actor"], e["action"]) for e in out["events"])
    assert key(r) == key(d)
    assert r["chains"]["r1"]["ok"]


def test_agents_run_on_their_ldus(store):
    seen = []

    class Spy:
        async def dispatched(self, run_id, case_id, ldu, agent):
            seen.append((ldu, agent))

        async def finished(self, *a):
            pass

    async def go():
        async with InProcessLdus(llm=factory(SCRIPTS), observer=Spy()) as ldus:
            sessions = InMemorySessionService()
            await sessions.create_session(app_name=APP, user_id=USER, session_id="r2")
            await _run(ldus.workflows["preparation"], sessions, "r2", REQUEST)
    asyncio.run(go())
    by_ldu = {}
    for ldu, agent in seen:
        by_ldu.setdefault(ldu, set()).add(agent)
    assert by_ldu["due-diligence-agent"] == {"dd_sanctions", "dd_identity", "dd_adverse_media", "dd_summary"}
    assert by_ldu["narrative-agent"] == {"nd_business_background", "nd_management_assessment",
                                         "nd_conduct_performance", "nd_security_esg", "nd_critic"}
    assert by_ldu["evidence-agent"] == {"document_ingestion", "gap_consolidator"}
    assert len(seen) == 17 and len(set(seen)) == 17           # every preparation agent once (no transmit)


def test_failed_step_fails_the_run_and_names_the_step(store):
    async def go():
        async with InProcessLdus(llm=factory(SCRIPTS)) as ldus:
            fin = next(w for w in ldus.workers if w.ldu.name == "financial-agent")

            async def explode(job):
                raise RuntimeError("model unavailable")
            fin.execute = explode
            sessions = InMemorySessionService()
            await sessions.create_session(app_name=APP, user_id=USER, session_id="r3")
            await _run(ldus.workflows["preparation"], sessions, "r3", REQUEST)
    with pytest.raises(Exception) as ei:
        asyncio.run(go())
    err = ei.value
    while err is not None and not isinstance(err, StepFailed):
        err = err.__cause__ or err.__context__ or (err.exceptions[0] if hasattr(err, "exceptions") else None)
    assert isinstance(err, StepFailed) and err.agent == "financial_analysis"
    assert "model unavailable" in str(err)
