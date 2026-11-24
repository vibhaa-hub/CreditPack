import asyncio

from google.adk.sessions import InMemorySessionService

from cpa_agents import tools as t
from cpa_agents.store.runtime import record_human_decision
from conftest import fake_ctx


def test_two_drafts_and_a_review_give_three_versions_and_a_diff(store):
    ctx = fake_ctx(session_id="sv-1", agent="p06_template", state={"case_id": "CASE-1"})
    assert t.save_template_section("business_background", "Acme is a franchise dealer.", ["form-2026-11-03"], ctx)["version"] == 1
    assert t.save_template_section("business_background", "Acme is a franchise dealer since 2009.",
                                   ["form-2026-11-03", "ch-record"], ctx)["version"] == 2

    async def review():
        sessions = InMemorySessionService()
        await sessions.create_session(app_name="cpa", user_id="u", session_id="sv-1", state=ctx.state.to_dict())
        reviewed = {**ctx.state["sections"]["business_background"], "reviewed": True}
        await record_human_decision(sessions, "cpa", "u", "sv-1", "Jane Smith",
                                    {"sections": {"business_background": reviewed}}, "narrative reviewed")
    asyncio.run(review())

    versions = store.section_versions("CASE-1", "business_background")
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert [v["actor"] for v in versions] == ["p06_template", "p06_template", "Jane Smith"]
    assert [v["reviewed"] for v in versions] == [False, False, True]
    diff = store.section_diff("CASE-1", "business_background", 1, 2)
    assert "-Acme is a franchise dealer." in diff and "+Acme is a franchise dealer since 2009." in diff
    assert "ch-record" in diff
    assert "[reviewed: True]" in store.section_diff("CASE-1", "business_background", 2, 3)


def test_decision_language_still_rejected_without_a_version(store):
    ctx = fake_ctx(state={"case_id": "CASE-2"})
    r = t.save_template_section("conduct_performance", "We recommend approval.", [], ctx)
    assert r["status"] == "error" and store.section_versions("CASE-2", "conduct_performance") == []


def test_section_needs_a_registered_case(store):
    r = t.save_template_section("business_background", "text", [], fake_ctx())
    assert r["status"] == "error" and "register" in r["message"]
