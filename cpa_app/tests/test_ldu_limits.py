"""Per-LDU model settings, concurrency limit and retry (deployable-units spec; design D9)."""
import asyncio

import pytest
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from cpa_agents.ldu import limits
from cpa_agents.ldu.manifest import Ldu, get_manifest
from cpa_agents.ldu.runtime import InProcessLdus
from cpa_agents.ldu.worker import run_step
from cpa_agents.mesh.agents import build
from fakes import ScriptedLlm, factory
from test_mesh import REQUEST, SCRIPTS
from workbench.runner import APP, USER, Runs


class RateLimitError(Exception):
    status_code = 429


class Slow(BaseLlm):
    model: str = "slow"

    async def generate_content_async(self, llm_request, stream=False):
        await asyncio.sleep(0.05)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))


class Flaky(ScriptedLlm):
    """Fails the first `fail` model calls with a rate-limit error, then follows its script."""
    fail: int = 0
    failed: list = []

    async def generate_content_async(self, llm_request, stream=False):
        if len(self.failed) < self.fail:
            self.failed.append(1)
            raise RateLimitError("429 Too Many Requests")
        async for r in super().generate_content_async(llm_request, stream):
            yield r


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setenv("CPA_MODEL_RETRY_BASE_DELAY", "0.001")
    limits.LIMITERS.clear()
    yield
    limits.LIMITERS.clear()


def test_concurrency_limit_per_replica():
    ldu = Ldu(name="t-limit", kind="agent", status="active", agents=("x",), concurrency=2)
    m = limits.limit(Slow(), ldu)

    async def one():
        return [r async for r in m.generate_content_async(LlmRequest())]

    async def go():
        await asyncio.gather(*(one() for _ in range(5)))
    asyncio.run(go())
    assert limits.LIMITERS["t-limit"].peak == 2


def test_rate_limited_twice_then_succeeds_and_tools_run_once(store):
    name = "financial_analysis"
    flaky = Flaky(calls=list(SCRIPTS[name]), final=f"{name} done", seen_instructions=[], fail=2, failed=[])
    agents = build(llm=lambda n: flaky if n == name else factory({})(n))

    async def go():
        return await run_step(agents[name], "case-l1", {"case_id": "CASE-L1"}, "go")
    out = asyncio.run(go())
    assert limits.LIMITERS["financial-agent"].retries == 2
    assert len(out["delta"]["facilities"]) == 1                       # record_facility ran once
    assert out["output"] == "financial_analysis done"


def test_retries_exhausted_fail_the_run_and_stop_it(store):
    always = Flaky(calls=[], final="x", seen_instructions=[], fail=10 ** 6, failed=[])

    async def go():
        sessions = InMemorySessionService()
        await sessions.create_session(app_name=APP, user_id=USER, session_id="case-l2", state={"request_text": REQUEST})
        ldus = InProcessLdus(llm=lambda n: always if n == "pack_request" else factory(SCRIPTS)(n))
        runs = Runs(sessions, ldus.workflows, ldus=ldus)
        runs.start("case-l2", "preparation", REQUEST, "Jane Smith")
        await runs.wait("case-l2")
        await ldus.stop()
        return runs.status("case-l2")
    s = asyncio.run(go())
    assert s["state"] == "failed" and s["failed_step"] == "pack_request"
    assert "RateLimitError" in s["error"] or "429" in s["error"]
    assert "financial_analysis" not in s["agents_completed"]
    assert limits.LIMITERS["pack-agent"].retries == get_manifest().ldu("pack-agent").max_attempts - 1


def test_non_transient_errors_are_not_retried():
    class Broken(BaseLlm):
        model: str = "broken"
        calls: list = []

        async def generate_content_async(self, llm_request, stream=False):
            self.calls.append(1)
            raise ValueError("bad request")
            yield                                                     # pragma: no cover

    b = Broken(calls=[])
    m = limits.limit(b, Ldu(name="t-broken", kind="agent", status="active", agents=("x",)))

    async def go():
        return [r async for r in m.generate_content_async(LlmRequest())]
    with pytest.raises(ValueError):
        asyncio.run(go())
    assert len(b.calls) == 1


def test_model_per_ldu_from_environment(monkeypatch):
    monkeypatch.setenv("CPA_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("CPA_LDU_NARRATIVE_AGENT_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("CPA_LDU_NARRATIVE_AGENT_CONCURRENCY", "7")
    a = build()
    assert a["nd_critic"].model.model == "gemini-2.5-pro" and a["nd_security_esg"].model.model == "gemini-2.5-pro"
    assert a["intake_classifier"].model.model == "gemini-2.5-flash"
    assert limits.LIMITERS["narrative-agent"].s.concurrency == 7
    assert limits.LIMITERS["intake-agent"].s.concurrency == get_manifest().ldu("intake-agent").concurrency


def test_limited_model_keeps_its_class(monkeypatch):
    from google.adk.models.google_llm import Gemini
    from google.adk.models.lite_llm import LiteLlm
    monkeypatch.setenv("CPA_MODEL", "mistral/mistral-large-latest")
    a = build()
    assert isinstance(a["intake_classifier"].model, LiteLlm)
    monkeypatch.setenv("CPA_MODEL", "gemini-2.5-flash")
    assert isinstance(build()["intake_classifier"].model, Gemini)
