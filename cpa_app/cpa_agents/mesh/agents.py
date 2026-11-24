"""The Arch 3.2 agents: nine specialists (some with sub-agents) plus the orchestrator's own
reasoning step (gap consolidation). Every agent has only its whitelisted tools (ARCH-G03), the
audit callbacks (P-12), and reads only the state keys it declares."""
import os

from google.adk.agents import Agent

from ..tools import BY_SPECIALIST
from .callbacks import audit_after_agent, audit_after_tool, audit_before_tool
from .instructions import instruction_for

MODEL_NAME = os.getenv("CPA_MODEL", "gemini-2.5-flash")

HEADER = ("case_id", "dealer_name", "registered_number", "case_types", "source", "owner", "received_at")


def model(name: str | None = None):
    """Gemini names go to ADK directly; 'provider/model' names (e.g. mistral/mistral-large-latest)
    go through LiteLLM, which reads the provider key (MISTRAL_API_KEY) from the environment."""
    name = name or os.getenv("CPA_MODEL", MODEL_NAME)
    if "/" in name:
        from google.adk.models.lite_llm import LiteLlm
        return LiteLlm(model=name)
    return name


def specialist(name: str, skill: str, tools: str, reads: tuple, section: str | None = None,
               llm=None) -> Agent:
    """One agent. Whether it writes shared lists to its own state partition is set by `parallel:`
    in the LDU manifest (cpa_agents/ldu/manifest.yaml), not here."""
    from .instructions import load
    from ..ldu.limits import limit, settings
    from ..ldu.manifest import get_manifest
    desc = load(skill).description + (f" Sub-agent: {section}." if section else "")
    ldu = get_manifest().ldu_of(name)
    m = llm(name) if callable(llm) else (llm or model(settings(ldu).model))   # llm may be a factory: name -> model
    m = limit(m, ldu)                                          # the LDU's concurrency limit and retry
    return Agent(
        name=name, model=m, description=desc[:1000],
        instruction=instruction_for(skill, section, reads),
        tools=list(BY_SPECIALIST[tools]), output_key=f"{name}_summary",
        before_tool_callback=audit_before_tool, after_tool_callback=audit_after_tool,
        after_agent_callback=audit_after_agent)


def build(llm=None) -> dict:
    """All agents, keyed by name. `llm` overrides the model: a model object, or a factory
    `name -> model` (tests pass scripted models per agent)."""
    a = {}
    a["intake_classifier"] = specialist("intake_classifier", "cpa-intake-classifier", "intake_classifier",
                                        ("request_text",) + HEADER + ("checklist", "related_cases"), llm=llm)
    a["entity_structure"] = specialist("entity_structure", "cpa-entity-structure", "entity_structure",
                                       ("request_text",) + HEADER + ("checklist", "parties", "registry_record",
                                                                     "registry_discrepancies", "ownership"), llm=llm)
    a["document_ingestion"] = specialist("document_ingestion", "cpa-document-ingestion", "document_ingestion",
                                         ("request_text",) + HEADER + ("checklist", "documents", "info_items",
                                                                       "financial_statement_versions", "tieouts",
                                                                       "notes", "info_requests"),
                                         llm=llm)
    a["bureau_external"] = specialist("bureau_external", "cpa-bureau-external-data", "bureau_external",
                                      HEADER + ("info_items", "registry_record", "held_cases"), llm=llm)
    dd_reads = HEADER + ("checklist", "parties", "checks", "hits_open", "cra_recorded_by")
    for sub, tools in (("sanctions", "dd_sanctions"), ("identity", "dd_identity"),
                       ("adverse_media", "dd_adverse_media")):
        a[f"dd_{sub}"] = specialist(f"dd_{sub}", "cpa-due-diligence-screening", tools,
                                    dd_reads + (("info_items",) if sub == "identity" else ()),
                                    section=sub, llm=llm)
    a["dd_summary"] = specialist("dd_summary", "cpa-due-diligence-screening", "dd_summary", dd_reads,
                                 section="dd_summary", llm=llm)
    a["gap_consolidator"] = specialist("gap_consolidator", "cpa-orchestrator", "gap_consolidator",
                                       HEADER + ("checklist", "info_requests", "check_register", "registry_discrepancies",
                                                 "unreadable_documents"), llm=llm)
    a["pack_request"] = specialist("pack_request", "cpa-pack-assembly", "pack_assembly",
                                   ("request_text",) + HEADER + ("lending_request",), section="lending_request", llm=llm)
    a["financial_analysis"] = specialist("financial_analysis", "cpa-financial-analysis", "financial_analysis",
                                         ("request_text",) + HEADER + ("documents", "financial_statements", "facilities",
                                                                       "security", "lending_request", "measures",
                                                                       "difference_explanations"), llm=llm)
    narrative_reads = HEADER + ("parties", "registry_record", "verifications", "ownership", "related_cases", "notes",
                                "measures", "measures_detail", "measures_basis", "financial_quality_flags",
                                "reconciliation", "borrowing_profile",
                                "lending_request", "security", "credit_reference")
    for sub in ("business_background", "management_assessment", "conduct_performance", "security_esg"):
        a[f"nd_{sub}"] = specialist(f"nd_{sub}", "cpa-narrative-drafting", "narrative_drafter", narrative_reads,
                                    section=sub, llm=llm)
    a["nd_critic"] = specialist("nd_critic", "cpa-narrative-drafting", "narrative_critic",
                                HEADER + ("sections", "measures"), section="critic", llm=llm)
    a["pack_validation"] = specialist("pack_validation", "cpa-pack-assembly", "pack_assembly",
                                      HEADER + ("gate_result", "pending_human"), section="validation", llm=llm)
    a["pack_transmit"] = specialist("pack_transmit", "cpa-pack-assembly", "pack_transmit",
                                    HEADER + ("gate_result", "submission_authorised_by", "submitted"),
                                    section="transmit", llm=llm)
    a["post_approval"] = specialist("post_approval", "cpa-post-approval", "post_approval",
                                    HEADER + ("credit_outcome", "conditions", "lending_request", "handoffs",
                                              "conditions_status", "approved_terms", "next_review"), llm=llm)
    return a
