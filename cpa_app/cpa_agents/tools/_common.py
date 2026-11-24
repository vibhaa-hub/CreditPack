"""Shared helpers for agent tools. Tools are thin: read state, call a rule, write state, return."""
from datetime import date, datetime, timezone

from ..ldu.manifest import get_manifest
from ..rules.policy import load_policy
from ..store import get_store


def S(ctx):
    return ctx.state


def plain(st) -> dict:
    """Plain dict copy of session state (ADK State is not dict()-convertible)."""
    return st.to_dict() if hasattr(st, "to_dict") else dict(st)


# Agents that run concurrently with others writing the same keys. ADK applies each state delta by
# replacing the whole key, so concurrent read-modify-write loses updates. These agents write to a
# partition `<key>@<agent>`; a deterministic merge node after the join folds partitions back
# (mesh.orchestrator.merge_partitions). Readers use collect(), which sees base + partitions.
# Declared in the LDU manifest (`parallel:`), so every process partitions the same way no matter
# which agents it builds. A set, so tests can extend it temporarily.
PARALLEL_AGENTS: set[str] = set(get_manifest().parallel_agents)
SEP = "@"


def wkey(key: str, ctx=None) -> str:
    agent = getattr(ctx, "agent_name", None)
    return f"{key}{SEP}{agent}" if agent in PARALLEL_AGENTS else key


def collect(st, key: str) -> list:
    """Base list plus every partition written by parallel agents not yet merged."""
    raw = plain(st)
    out = list(raw.get(key) or [])
    for k in sorted(raw):
        if k.startswith(key + SEP) and raw[k]:
            out.extend(raw[k])
    return out


def collect_dict(st, key: str) -> dict:
    raw = plain(st)
    out = dict(raw.get(key) or {})
    for k in sorted(raw):
        if k.startswith(key + SEP) and raw[k]:
            out.update(raw[k])
    return out


def append(st, key: str, item, ctx=None) -> list:
    """Append to a list in state as a new list (ADK only records writes, not in-place mutation).
    Parallel agents write to their own partition. Returns the list as the caller now sees it."""
    k = wkey(key, ctx)
    lst = list(st.get(k) or [])
    lst.append(item)
    st[k] = lst
    return collect(st, key)


def today() -> str:
    return date.today().isoformat()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def policy():
    return load_policy()


def need_case(st) -> dict | None:
    if not st.get("case_id"):
        return {"status": "error", "message": "register the case first"}
    return None


def merge_partitions(state: dict) -> dict:
    """State delta that folds every `<key>@<agent>` partition into `<key>` and clears the partition.
    Lists are concatenated (in partition-name order); dicts are merged."""
    raw = plain(state)
    delta: dict = {}
    bases = sorted({k.split(SEP, 1)[0] for k in raw if SEP in k and raw[k]})
    for base in bases:
        parts = sorted(k for k in raw if k.startswith(base + SEP) and raw[k])
        cur = raw.get(base)
        if isinstance(raw[parts[0]], dict):
            merged = dict(cur or {})
            for p in parts:
                merged.update(raw[p])
        else:
            merged = list(cur or [])
            for p in parts:
                merged.extend(raw[p])
        delta[base] = merged
        for p in parts:
            delta[p] = None
    return delta


def merged_view(st) -> dict:
    """Plain state with any unmerged partitions folded in (what the gate and pack must see)."""
    raw = plain(st)
    return {k: v for k, v in {**raw, **merge_partitions(raw)}.items() if SEP not in k}


__all__ = ["S", "plain", "merged_view", "append", "collect", "collect_dict", "merge_partitions", "wkey", "PARALLEL_AGENTS",
           "today", "now", "policy", "need_case", "get_store"]
