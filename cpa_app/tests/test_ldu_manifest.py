"""LDU manifest (deployable-units spec: manifest, every agent in exactly one LDU)."""
import copy

import pytest
import yaml

from cpa_agents.ldu.manifest import DEFAULT_PATH, ManifestError, check_agents, load, parse
from cpa_agents.mesh.agents import build
from fakes import factory

RAW = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built():
    return build(llm=factory({}))


def test_current_mapping_is_complete(built):
    m = load()
    assert len(built) == 19
    check_agents(built, m)                                   # does not raise
    assert sorted(m.assigned_agents) == sorted(built)
    assert len(m.assigned_agents) == len(set(m.assigned_agents))


def test_active_and_planned_ldus():
    m = load()
    active = [u.name for u in m.ldus.values() if u.active]
    assert len(active) == 14
    assert {u.name for u in m.ldus.values() if not u.active} == {"review-scheduler", "telemetry"}
    assert m.ldu_of("nd_critic").name == "narrative-agent"
    assert m.ldu_of("pack_transmit").name == "pack-agent"


def test_unassigned_agent_stops_startup(built):
    raw = copy.deepcopy(RAW)
    raw["ldus"]["narrative-agent"]["agents"].remove("nd_critic")
    with pytest.raises(ManifestError, match="not assigned to any LDU: nd_critic"):
        check_agents(built, parse(raw))


def test_duplicated_agent_stops_startup():
    raw = copy.deepcopy(RAW)
    raw["ldus"]["pack-agent"]["agents"].append("intake_classifier")
    with pytest.raises(ManifestError, match="intake_classifier is assigned to more than one LDU"):
        parse(raw)


def test_unknown_agent_stops_startup(built):
    raw = copy.deepcopy(RAW)
    raw["ldus"]["intake-agent"]["agents"].append("ghost_agent")
    with pytest.raises(ManifestError, match="in the manifest but not built: ghost_agent"):
        check_agents(built, parse(raw))


def test_agent_in_planned_ldu_rejected(built):
    raw = copy.deepcopy(RAW)
    raw["ldus"]["review-scheduler"]["kind"] = "agent"
    raw["ldus"]["review-scheduler"]["agents"] = ["post_approval"]
    raw["ldus"]["post-approval-agent"]["agents"] = []
    with pytest.raises(ManifestError, match="planned LDU: post_approval"):
        check_agents(built, parse(raw))


@pytest.mark.parametrize("mutate,msg", [
    (lambda r: r["ldus"]["intake-agent"].update(kind="lambda"), "kind must be one of"),
    (lambda r: r["ldus"]["workbench-api"].update(agents=["x"]), "only agent LDUs can host agents"),
    (lambda r: r["ldus"]["pack-agent"].update(parallel=["nd_critic"]), "parallel agents not hosted here"),
    (lambda r: r["ldus"]["pack-agent"].update(concurrency=0), "concurrency must be a positive integer"),
])
def test_invalid_entries(mutate, msg):
    raw = copy.deepcopy(RAW)
    mutate(raw)
    with pytest.raises(ManifestError, match=msg):
        parse(raw)


def test_partitioning_comes_from_manifest_not_build():
    """Building agents (all, or only one LDU's) does not change who partitions: the manifest does."""
    from types import SimpleNamespace as N
    from cpa_agents.ldu.manifest import get_manifest
    from cpa_agents.mesh.agents import specialist
    from cpa_agents.tools import _common
    before = set(_common.PARALLEL_AGENTS)
    assert before == set(get_manifest().parallel_agents)
    specialist("nd_security_esg", "cpa-narrative-drafting", "narrative_drafter", (), section="security_esg",
               llm=factory({}))
    assert _common.PARALLEL_AGENTS == before
    assert _common.wkey("sections", N(agent_name="nd_security_esg")) == "sections@nd_security_esg"
    assert _common.wkey("sections", N(agent_name="nd_critic")) == "sections"
    assert _common.wkey("checks", N(agent_name="dd_identity")) == "checks@dd_identity"


def test_manifest_parallel_set_matches_partitioned_agents():
    from cpa_agents.tools._common import PARALLEL_AGENTS
    assert PARALLEL_AGENTS >= {"dd_sanctions", "dd_identity", "dd_adverse_media", "nd_business_background",
                               "nd_management_assessment", "nd_conduct_performance", "nd_security_esg"}
    assert not PARALLEL_AGENTS & {"dd_summary", "nd_critic", "intake_classifier"}
