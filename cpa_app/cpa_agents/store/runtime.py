"""Human-side operations that touch both the ADK session and the case store.

Agents have no tool that reaches these functions: they are for run.py and, later, a UI.
Every decision is written to the audit trail first, then applied to the session, so a
change can never reach state without an audit record.
"""
from google.adk.events import Event, EventActions

from . import derive_urls, get_store


def make_session_service(url: str | None = None):
    """ADK sessions persisted in the same database as the case store (async driver)."""
    from google.adk.sessions import DatabaseSessionService
    return DatabaseSessionService(db_url=derive_urls(url)[1])


def _changed_sections(current: dict, delta: dict) -> dict:
    old = current.get("sections") or {}
    return {k: v for k, v in (delta.get("sections") or {}).items() if v != old.get(k)}


async def record_human_decision(sessions, app_name: str, user_id: str, session_id: str,
                                actor: str, delta: dict, label: str) -> dict:
    """Audit and apply one human decision (a state change authored by a named person)."""
    store = get_store()
    session = await sessions.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    if session is None:
        raise KeyError(f"no session {session_id}")
    current = dict(session.state)
    case_id = current.get("case_id") or store.case_for_session(session_id)
    ev = store.append_event(session_id, "human", actor, "human_decision", case_id=case_id,
                            args=delta, detail={"label": label})
    if case_id:   # decision 8: a human review or edit of a section is a new section version
        for name, sec in _changed_sections(current, delta).items():
            store.add_section_version(case_id, name, sec.get("text", ""), sec.get("evidence"),
                                      sec.get("label", "human"), sec.get("reviewed", False), actor)
    await sessions.append_event(session, Event(author="human", actions=EventActions(state_delta=delta)))
    return ev


async def raise_credit_query(sessions, app_name: str, user_id: str, session_id: str,
                             raised_by: str, text: str, owner: str | None = None) -> int:
    """Credit raises a query on the submitted pack (REQ-065). Audited."""
    store = get_store()
    session = await sessions.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    case_id = session.state.get("case_id") or store.case_for_session(session_id)
    qid = store.record_credit_query(case_id, raised_by, text, owner=owner)
    store.append_event(session_id, "human", raised_by, "credit_query_raised", case_id=case_id,
                       detail={"query_id": qid, "text": text, "owner": owner})
    return qid


async def resolve_credit_query(sessions, app_name: str, user_id: str, session_id: str, actor: str,
                               query_id: int, resolution: str, pack_changed: bool) -> dict:
    """Resolve a Credit query (BR-P13). If the response changed the pack, the current
    session state becomes a new pack version linked to the query. Audited."""
    from .pack import assemble_pack
    store = get_store()
    session = await sessions.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    content = assemble_pack(dict(session.state)) if pack_changed else None
    out = store.resolve_credit_query(query_id, resolution, actor, pack_changed, new_content=content)
    store.append_event(session_id, "human", actor, "credit_query_resolved",
                       case_id=session.state.get("case_id"),
                       detail={"query_id": query_id, "resolution": resolution, "pack_changed": pack_changed,
                               "pack_version": (out["pack_version"] or {}).get("version")})
    return out


async def rollback_to_snapshot(sessions, app_name: str, user_id: str, session_id: str,
                               actor: str, snapshot_id: int) -> dict:
    """Restore state to a stored snapshot as an audited human decision (design decision 10).
    Keys added after the snapshot are cleared (set to None); history is never rewritten."""
    store = get_store()
    snap = store.get_snapshot(session_id, snapshot_id=snapshot_id)
    if snap is None:
        raise KeyError(f"no snapshot {snapshot_id} for session {session_id}")
    session = await sessions.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    current = {k: v for k, v in dict(session.state).items() if not k.startswith(("_", "temp:"))}
    delta = {**{k: None for k in current if k not in snap["state"]}, **snap["state"]}
    return await record_human_decision(sessions, app_name, user_id, session_id, actor, delta,
                                       f"rollback to snapshot {snapshot_id}")
