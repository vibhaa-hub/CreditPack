"""Entry point for `adk web` / `adk run cpa_agents` and for run.py.

The Credit Pack Orchestrator (Arch 3.2) is a deterministic ADK Workflow over nine specialist
agents; see cpa_agents/mesh/orchestrator.py for the graph. Three runs, separated by human gates:

  preparation_workflow   intake -> parallel evidence assembly -> gaps -> request -> analysis
                         -> drafting (+critic) -> validation gate -> STOP for humans
  submission_workflow    deterministic gate + authorisation check -> transmit (or report blocked)
  post_approval_workflow handoffs, conditions, closure check, next review date

P-12 (governance/audit) is the audit callbacks on every agent plus the append-only case store
(cpa_agents/store). There is no credit-decision, pricing or sanctions-clearing agent.
"""
from .mesh import build_workflows
from .mesh.agents import model                                     # noqa: F401  (re-export)
from .mesh.callbacks import audit_after_agent, audit_after_tool, audit_before_tool, state_dict  # noqa: F401

_wf = build_workflows()
preparation_workflow = _wf["preparation"]
submission_workflow = _wf["submission"]
post_approval_workflow = _wf["post_approval"]
agents = _wf["agents"]

root_agent = preparation_workflow   # `adk web` / `adk run cpa_agents`
