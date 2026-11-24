from cpa_agents import tools as t
from conftest import fake_ctx


def _ctx_for(case_types, items=()):
    ctx = fake_ctx(state={"case_types": case_types,
                          "info_items": [{"info_class": c} for c in items]})
    t.get_requirement_checklist(ctx)
    return ctx


def test_new_dealer_relationship_requires_everything():
    r = t.list_info_gaps(_ctx_for(["new dealer relationship"]))
    assert r["missing"] == ["consent", "data_protection", "director", "entity", "financial",
                            "security", "shareholder"]
    assert r["conditional"] == []


def test_new_franchise_makes_entity_and_parties_conditional():
    r = t.list_info_gaps(_ctx_for(["new franchise application"], items=["financial"]))
    assert r["missing"] == ["consent", "data_protection", "security"]
    assert r["conditional"] == ["director", "entity", "shareholder"]
    assert r["present"] == ["financial"]


def test_director_change_does_not_ask_for_security():
    r = t.list_info_gaps(_ctx_for(["director or shareholder change"]))
    assert "security" not in r["missing"] + r["conditional"]
    assert {"director", "shareholder"} <= set(r["missing"]) and "financial" in r["conditional"]


def test_combined_types_take_the_stricter_marker():
    r = t.list_info_gaps(_ctx_for(["new franchise application", "dealer acquisition"]))
    assert "entity" in r["missing"] and r["conditional"] == []


def test_needs_checklist():
    assert t.list_info_gaps(fake_ctx())["status"] == "error"
