"""external-adapters LDU (deployable-units: external data behind one LDU; design D8)."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from cpa_agents import tools as t
from cpa_agents.ldu import services
from cpa_agents.ldu.services import adapters
from conftest import fake_ctx


@pytest.fixture(autouse=True)
def fresh_buckets():
    adapters.BUCKETS.clear()
    yield
    adapters.BUCKETS.clear()


@pytest.fixture(params=["inprocess", "distributed"])
def ldu_mode(request, monkeypatch):
    monkeypatch.setenv("CPA_LDU_MODE", request.param)
    if request.param == "distributed":
        services.set_client("external-adapters", TestClient(adapters.create_service()))
    yield request.param
    services.set_client("external-adapters", None)


@pytest.fixture
def case(store):
    ctx = fake_ctx(session_id="ad-1", agent="entity_structure")
    t.register_case("Acme Motors Ltd", "01234567", ["increased borrowing request"], "OEM partner", "Jane Smith", ctx)
    return ctx


def test_tools_get_the_same_stub_results_in_both_modes(case, ldu_mode):
    assert t.companies_house_lookup("01234567", case)["record"]["provider"] == "Companies House (STUB)"
    assert t.companies_house_lookup("99999999", case)["status"] == "unavailable"
    s = t.sanctions_screen("Acme Motors Ltd", case)
    assert s["status"] == "ok" and s["result"] in ("clear", "potential_match", "confirmed_match") and s["list_version"]
    m = t.adverse_media_search("Acme Motors Ltd", case)
    assert m["sources_searched"] == ["STUB news index"]
    case.state["info_items"] = [{"info_class": "consent"}]
    assert t.credit_reference_lookup(case)["status"] in ("ok", "unavailable")


def test_rate_limit_makes_excess_requests_wait_and_answers_all():
    clock = [0.0]
    b = adapters.TokenBucket(rate=5, burst=5, clock=lambda: clock[0])
    waits = [b.reserve() for _ in range(8)]                   # 8 requests at the same instant
    assert waits[:5] == [0.0] * 5                             # within the limit: no wait
    assert waits[5:] == pytest.approx([0.2, 0.4, 0.6])        # excess spaced at 5 per second
    assert b.waited == 3


def test_provider_limit_from_environment_applies_across_callers(monkeypatch):
    monkeypatch.setenv("CPA_ADAPTER_COMPANIES_HOUSE_RATE", "1000")
    assert adapters.bucket("companies_house").rate == 1000
    assert adapters.bucket("sanctions").rate == 10            # default


def test_service_rate_limits_and_returns_every_result(monkeypatch):
    monkeypatch.setenv("CPA_ADAPTER_SANCTIONS_RATE", "5")
    c = TestClient(adapters.create_service())
    results = [c.post("/lookup/sanctions", json={"party": f"Party {i}"}).json() for i in range(8)]
    assert len(results) == 8 and all(r["stub"] for r in results)
    assert adapters.bucket("sanctions").waited >= 2           # requests over the burst of 5 waited for a token
    assert c.post("/lookup/nope", json={}).status_code == 404
    assert c.get("/health").json()["providers"] == ["adverse_media", "companies_house", "credit_reference", "sanctions"]
