"""The ten Arch 3.2 skills load through ADK's skill loader and keep everything the twelve old
process-unit skills covered (every REQ, BR, CALC and DT id they named)."""
import re
from pathlib import Path

import pytest
from google.adk.skills import load_skill_from_dir

SKILLS = Path(__file__).resolve().parents[1] / "cpa_agents" / "skills"
NEW = ["cpa-orchestrator", "cpa-intake-classifier", "cpa-entity-structure", "cpa-document-ingestion",
       "cpa-bureau-external-data", "cpa-due-diligence-screening", "cpa-financial-analysis",
       "cpa-narrative-drafting", "cpa-pack-assembly", "cpa-post-approval", "cpa-governance-audit"]
OLD_IDS = {line.split()[0]: set(line.split()[1:])
           for line in (Path(__file__).parent / "data" / "old_skill_ids.txt").read_text().splitlines()}


def _ids(text):
    ids = set()
    for p, a, b in re.findall(r"\b(REQ|CALC)-(\d+)(?:\.\.(\d+))?", text):
        ids.update(f"{p}-{i:03d}" for i in range(int(a), int(b or a) + 1))
    ids.update(re.findall(r"\bBR-[GEPDU]\d+\b", text))
    ids.update(re.findall(r"\bDT-\d\b", text))
    return ids


@pytest.mark.parametrize("name", NEW)
def test_skill_loads_with_adk(name):
    s = load_skill_from_dir(SKILLS / name)
    assert s.name == name and len(s.description) > 80 and s.instructions.strip()


def test_only_new_skills_remain():
    assert sorted(p.name for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith("_")) == sorted(NEW)


def test_every_old_id_is_still_covered():
    covered = set().union(*(_ids((SKILLS / n / "SKILL.md").read_text(encoding="utf-8")) for n in NEW))
    missing = {old: sorted(ids - covered) for old, ids in OLD_IDS.items() if ids - covered}
    assert missing == {}


@pytest.mark.parametrize("skill,section", [
    ("cpa-due-diligence-screening", "sanctions"), ("cpa-due-diligence-screening", "identity"),
    ("cpa-due-diligence-screening", "adverse_media"), ("cpa-due-diligence-screening", "dd_summary"),
    ("cpa-narrative-drafting", "business_background"), ("cpa-narrative-drafting", "management_assessment"),
    ("cpa-narrative-drafting", "conduct_performance"), ("cpa-narrative-drafting", "security_esg"),
    ("cpa-narrative-drafting", "critic"),
])
def test_sub_agent_sections_exist(skill, section):
    assert f"## Sub-agent: {section}\n" in (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("skill,phrase", [
    ("cpa-due-diligence-screening", "never clears an alert"),
    ("cpa-due-diligence-screening", "Never auto-clear"),
    ("cpa-narrative-drafting", "You never mark a section reviewed"),
    ("cpa-pack-assembly", "never mark anything authorised"),
    ("cpa-pack-assembly", "You request it; you never give it"),
    ("cpa-post-approval", "No approval, no handoff"),
    ("cpa-financial-analysis", "You never do arithmetic yourself"),
])
def test_hard_gates_kept(skill, phrase):
    assert phrase in (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
