"""Credit Pack Orchestrator (Arch 3.2, L5): a deterministic ADK Workflow per run. Sequencing,
parallel evidence assembly, merges and gate routing are graph edges, not model choices. A human
gate is the end of a run; the next run starts from persisted session state.

preparation:
  START -> capture_request -> intake_classifier
        -> [ entity_structure -> due_diligence(sanctions || identity || adverse_media -> merge -> dd_summary) ]
        || [ document_ingestion -> bureau_external ]
        -> evidence_join -> merge_evidence -> gap_consolidator -> pack_request -> financial_analysis
        -> narrative_drafting(background || management || conduct || security_esg -> merge -> critic)
        -> pack_validation -> await_humans
submission:     START -> submission_gate --pass--> pack_transmit ; --blocked--> report_blocked
post_approval:  START -> post_approval
"""
from datetime import date

from google.adk.agents import Context
from google.adk.workflow import START, JoinNode, Workflow

from ..ldu.manifest import check_agents
from ..rules.gate import evaluate
from ..rules.policy import load_policy
from ..tools._common import merge_partitions, merged_view
from .agents import build
from .callbacks import audit_system


# ---------- deterministic steps (function nodes) ----------
def capture_request(ctx: Context):
    """Keep the incoming request text in state so specialists can read it as data."""
    parts = getattr(getattr(ctx, "user_content", None), "parts", None) or []
    text = "".join(getattr(p, "text", "") or "" for p in parts).strip()
    if text and not ctx.state.get("request_text"):
        ctx.state["request_text"] = text
    audit_system(ctx, "request_captured", {"chars": len(text)})


def _merge(ctx: Context, label: str):
    delta = merge_partitions(ctx.state)
    for k, v in delta.items():
        ctx.state[k] = v
    audit_system(ctx, label, {"merged_keys": sorted(k for k in delta if "@" not in k)})


def merge_due_diligence(ctx: Context):
    _merge(ctx, "merge_due_diligence")


def merge_drafts(ctx: Context):
    _merge(ctx, "merge_drafts")


def merge_evidence(ctx: Context):
    _merge(ctx, "merge_evidence")


def await_humans(ctx: Context):
    """End of the preparation run: humans act next (hit disposition, CRA, review, pricing, submission)."""
    st = merged_view(ctx.state)
    audit_system(ctx, "awaiting_humans", {"gate_status": st.get("gate_status"),
                                          "pending_human": st.get("pending_human") or []})


def submission_gate(ctx: Context):
    """Deterministic gate before transmission: DT-2 must allow submission and the accountable owner
    must have authorised. Routes 'pass' or 'blocked'."""
    st = merged_view(ctx.state)
    res = evaluate(st, load_policy(), date.today().isoformat())
    ok = res["submission_may_be_authorised"] and bool(st.get("submission_authorised_by"))
    ctx.state["gate_status"] = "PASS" if res["submission_may_be_authorised"] else "BLOCKED"
    ctx.state["gate_result"] = {k: res[k] for k in ("result", "deciding_rule", "gaps", "advisories", "completeness",
                                                    "mandatory_items", "policy_version", "as_at")}
    audit_system(ctx, "submission_gate", {"result": res["result"], "authorised": bool(st.get("submission_authorised_by")),
                                          "route": "pass" if ok else "blocked"})
    ctx.route = "pass" if ok else "blocked"


def report_blocked(ctx: Context):
    st = merged_view(ctx.state)
    audit_system(ctx, "submission_blocked", {"gaps": [g["reason"] for g in (st.get("gate_result") or {}).get("gaps", [])],
                                             "authorised": bool(st.get("submission_authorised_by"))})


# ---------- workflows ----------
def build_workflows(llm=None, dispatch=None) -> dict:
    """The three run workflows. `dispatch` (an ldu.dispatch.Dispatcher) runs agent steps on their
    LDUs; omit it to run every agent in-process (tests, `adk web`)."""
    agents = build(llm)
    check_agents(agents)                # every built agent is in exactly one LDU (deployable-units spec)
    # With a dispatcher, each agent node becomes a remote step on the agent's LDU (same name, same
    # place in the graph); without one, the agents run in this process as before.
    a = {n: dispatch.node(n) for n in agents} if dispatch else agents
    due_diligence = Workflow(name="due_diligence", edges=[
        (START, (a["dd_sanctions"], a["dd_identity"], a["dd_adverse_media"]), JoinNode(name="dd_join"),
         merge_due_diligence, a["dd_summary"]),
    ])
    narrative_drafting = Workflow(name="narrative_drafting", edges=[
        (START, (a["nd_business_background"], a["nd_management_assessment"], a["nd_conduct_performance"],
                 a["nd_security_esg"]), JoinNode(name="drafts_join"), merge_drafts, a["nd_critic"]),
    ])
    evidence_join = JoinNode(name="evidence_join")
    preparation = Workflow(name="cpa_preparation", edges=[
        (START, capture_request, a["intake_classifier"], (a["entity_structure"], a["document_ingestion"])),
        (a["entity_structure"], due_diligence, evidence_join),
        (a["document_ingestion"], a["bureau_external"], evidence_join),
        (evidence_join, merge_evidence, a["gap_consolidator"], a["pack_request"], a["financial_analysis"],
         narrative_drafting, a["pack_validation"], await_humans),
    ])
    submission = Workflow(name="cpa_submission", edges=[
        (START, submission_gate),
        (submission_gate, {"pass": a["pack_transmit"], "blocked": report_blocked}),
    ])
    post_approval = Workflow(name="cpa_post_approval", edges=[(START, a["post_approval"])])
    return {"preparation": preparation, "submission": submission, "post_approval": post_approval,
            "agents": agents, "due_diligence": due_diligence, "narrative_drafting": narrative_drafting}
