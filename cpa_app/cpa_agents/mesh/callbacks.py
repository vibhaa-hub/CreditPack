"""P-12 as callbacks on every agent: append-only, hash-chained audit trail in the case store."""
from ..store import get_store


def state_dict(ctx) -> dict:
    """Plain copy of session state without ADK-internal or temporary keys."""
    raw = ctx.state.to_dict() if hasattr(ctx.state, "to_dict") else dict(ctx.state)
    return {k: v for k, v in raw.items() if not k.startswith(("_", "temp:"))}


def audit_before_tool(tool, args, tool_context):
    get_store().append_event(tool_context.session.id, "agent", tool_context.agent_name, "tool_called",
                             tool=tool.name, args=args)
    return None  # None = allow the call


def audit_after_tool(tool, args, tool_context, tool_response):
    status = tool_response.get("status") if isinstance(tool_response, dict) else None
    get_store().append_event(tool_context.session.id, "agent", tool_context.agent_name, "tool_result",
                             tool=tool.name, result_status=status, detail=tool_response)
    return None  # None = keep the tool's own response


def audit_after_agent(callback_context):
    store = get_store()
    sid = callback_context.session.id
    snap = store.save_snapshot(sid, callback_context.agent_name, state_dict(callback_context))
    store.append_event(sid, "agent", callback_context.agent_name, "agent_complete",
                       detail={"snapshot_id": snap})
    return None


def audit_system(ctx, action: str, detail: dict | None = None):
    """Audit event for a deterministic workflow step (function node)."""
    get_store().append_event(ctx.session.id, "system", "orchestrator", action, detail=detail)
