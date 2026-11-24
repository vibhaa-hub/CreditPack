"""Narrative Drafting tools (P-06 narrative; REQ-047..054, BR-D07, BR-D12, BR-G06, ARCH-G08)."""
from google.adk.tools import ToolContext

from ..rules.gate import CORE_SECTIONS, OPTIONAL_SECTIONS, SECURITY_SECTION, figure_mismatches, unsupported_amounts
from ..rules.language import find_decision_language
from ._common import S, collect_dict, get_store, merged_view, need_case, wkey

SECTIONS = CORE_SECTIONS + (SECURITY_SECTION,) + OPTIONAL_SECTIONS


def save_template_section(section: str, text: str, evidence_refs: list[str], tool_context: ToolContext) -> dict:
    """Save a DRAFT narrative section, labelled non-human and unreviewed (REQ-052/090). section is one
    of business_background, management_assessment, conduct_performance, security_review, esg.
    evidence_refs lists the sources each assertion relies on (ARCH-G08). Text that states or implies a
    credit decision is rejected (BR-D12). Only the case owner can mark a section reviewed."""
    st = S(tool_context)
    if err := need_case(st):
        return err
    if section not in SECTIONS:
        return {"status": "error", "message": f"section must be one of {SECTIONS}"}
    hits = find_decision_language(text)
    if hits:
        return {"status": "error", "message": "decision language not allowed in pack (BR-D12): "
                + "; ".join(h["text"] for h in hits)}
    if not (text or "").strip():
        return {"status": "error", "message": "empty section"}
    version = get_store().add_section_version(st["case_id"], section, text, evidence_refs,
                                              label="non-human draft", reviewed=False,
                                              actor=tool_context.agent_name)
    k = wkey("sections", tool_context)
    secs = dict(st.get(k) or {})
    secs[section] = dict(text=text, evidence=list(evidence_refs or []), label="non-human draft",
                         drafted_by=tool_context.agent_name, reviewed=False,
                         supported=bool(evidence_refs), version=version)
    st[k] = secs
    return {"status": "ok", "reviewed": False, "version": version,
            **({} if evidence_refs else {"warning": "no evidence cited: will fail validation (ARCH-G08)"})}


def review_drafts(tool_context: ToolContext) -> dict:
    """Critic pass over every drafted section: decision language (BR-D12), missing citations
    (ARCH-G08) and figures that differ from the computed measures. Reports findings; changes nothing."""
    st = S(tool_context)
    measures = st.get("measures") or {}
    findings = []
    sections = collect_dict(st, "sections")
    view = merged_view(st)
    for name, sec in sorted(sections.items()):
        for h in find_decision_language(sec.get("text", "")):
            findings.append({"section": name, "issue": f"decision language ({h['kind']}): {h['text']}",
                             "required_change": "remove the statement"})
        if not sec.get("evidence") and sec.get("label") != "human":
            findings.append({"section": name, "issue": "no evidence cited",
                             "required_change": "cite the sources for each assertion"})
        for key, val, m in figure_mismatches(sec.get("text", ""), measures):
            findings.append({"section": name, "issue": f"states {key} {val}; analysis shows {m}",
                             "required_change": f"use {m}"})
        for amt in unsupported_amounts(sec.get("text", ""), view):
            findings.append({"section": name, "issue": f"amount {amt} matches no figure in the case",
                             "required_change": "use the evidenced figure or remove it"})
    missing = [s for s in CORE_SECTIONS if s not in sections]
    st["critic_findings"] = findings
    return {"status": "ok", "findings": findings, "missing_core_sections": missing,
            "sections_reviewed": sorted(sections)}
