"""Import boundaries between agent LDUs (design D1): an agent LDU's tool modules import only the
shared libraries and their own module, never another LDU's tools."""
import ast
from pathlib import Path

import pytest

from cpa_agents.ldu.manifest import get_manifest

TOOLS = Path(__file__).resolve().parents[1] / "cpa_agents" / "tools"

# Which agent LDU owns each tool module.
OWNER = {"intake": "intake-agent", "entity": "entity-agent", "documents": "evidence-agent",
         "bureau": "master-data-agent", "diligence": "due-diligence-agent", "financial": "financial-agent",
         "narrative": "narrative-agent", "assembly": "pack-agent", "post_approval": "post-approval-agent"}
SHARED = {"rules", "store", "ldu", "files", "_common", "policy", "extract"}           # relative imports allowed from any tool module

# Agents using a tool owned by another LDU. Allowed only for read-only tools (no state writes).
CROSS_LDU_TOOLS = {("gap_consolidator", "check_register")}


def violations(module: str, source: str) -> list[str]:
    """Relative imports in `source` that reach another LDU's tool module."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level:
            target = (node.module or "").split(".")[0]
            if node.level == 1 and target in OWNER and target != module:
                bad.append(f"{module} imports tools.{target} ({OWNER[target]})")
            elif node.level == 1 and not target:                     # `from . import x`
                bad += [f"{module} imports tools.{a.name}" for a in node.names if a.name in OWNER and a.name != module]
            elif node.level == 2 and target not in SHARED:
                bad.append(f"{module} imports cpa_agents.{target}, which is not a shared library")
    return bad


def test_every_tool_module_has_an_owner():
    mods = {p.stem for p in TOOLS.glob("*.py")} - {"__init__", "_common"}
    assert mods == set(OWNER)
    m = get_manifest()
    assert all(m.ldu(u).kind == "agent" for u in OWNER.values())


@pytest.mark.parametrize("module", sorted(OWNER))
def test_tool_module_imports_stay_inside_its_ldu(module):
    assert violations(module, (TOOLS / f"{module}.py").read_text(encoding="utf-8")) == []


def test_checker_catches_a_cross_import():
    assert violations("narrative", "from .diligence import sanctions_screen\n") == \
        ["narrative imports tools.diligence (due-diligence-agent)"]
    assert violations("narrative", "from . import financial\n") == ["narrative imports tools.financial"]
    assert violations("intake", "from ..mesh import agents\n") == \
        ["intake imports cpa_agents.mesh, which is not a shared library"]


def test_agents_use_only_their_ldus_tools_except_listed():
    from cpa_agents.mesh.agents import build
    from fakes import factory
    m = get_manifest()
    crossing = set()
    for name, ag in build(llm=factory({})).items():
        home = m.ldu_of(name).name
        for t in ag.tools:
            mod = t.__module__.rsplit(".", 1)[-1]
            if OWNER.get(mod, home) != home:
                crossing.add((name, t.__name__))
    assert crossing == CROSS_LDU_TOOLS
