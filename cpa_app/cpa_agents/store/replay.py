"""Replay a case's audit trail in order (ARCH-G09, for the events this store captures).

    python -m cpa_agents.store.replay CASE-20261114-000001      # by case id
    python -m cpa_agents.store.replay case-session-1            # by session id
    python -m cpa_agents.store.replay <id> --json               # machine-readable

Uses DATABASE_URL (or the SQLite default). Ends with the hash-chain check per session.
"""
import argparse
import json
import sys

from dotenv import load_dotenv


def replay(key: str) -> dict:
    from . import get_store
    store = get_store()
    events = store.events(key)
    chains = {sid: store.verify_chain(sid) for sid in dict.fromkeys(e["session_id"] for e in events)}
    return {"key": key, "events": events, "chains": chains}


def _line(e: dict) -> str:
    what = e["tool"] or (e["detail"] or {}).get("label") or ""
    status = f" -> {e['result_status']}" if e["result_status"] else ""
    return f"{e['at']}  #{e['seq']:<4} {e['actor_type']:<6} {e['actor']:<28} {e['action']:<15} {what}{status}"


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("key", help="case id or session id")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = ap.parse_args(argv)
    out = replay(args.key)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        if not out["events"]:
            print(f"no audit events for {args.key}")
        for e in out["events"]:
            print(_line(e))
        for sid, chk in out["chains"].items():
            state = "intact" if chk["ok"] else f"BROKEN at event #{chk['broken_at']}"
            print(f"chain {sid}: {chk['events']} events, {state}")
    return 0 if all(c["ok"] for c in out["chains"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
