"""Run the Credit Pack Orchestrator end to end, with simulated humans between its runs.

    python run.py                                   # model from CPA_MODEL
    python run.py --model mistral/mistral-large-latest

Three workflow runs (see cpa_agents/mesh/orchestrator.py): preparation (intake, parallel
evidence assembly, gaps, request, analysis, drafting with critic, validation gate) stops for
humans; submission (deterministic gate + authorisation check, then transmit); post-approval.

Humans are simulated by writing session state through the case store, so every decision is
audited. Agents have no tool that can do this, which is what keeps hit disposition, CRA, manual
checks, discrepancy resolution, narrative review, pricing and submission authorisation and the
Credit outcome human-only. Sessions, audit trail and pack versions persist in DATABASE_URL.
"""
import argparse
import asyncio
import json
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner                         # noqa: E402
from google.genai import types                                # noqa: E402

APP, USER = "cpa", "am-001"
SID = f"case-session-{uuid.uuid4().hex[:8]}"   # sessions persist, so each demo run gets its own
OWNER = "Jane Smith"

REQUEST = """New request via OEM referral. Dealer: Acme Motors Ltd, registered number 01234567.
Case types: new franchise application AND increased borrowing request. Source: OEM partner.
Owner: Jane Smith (Account Manager).
Dealer supplied (source: signed application form 2026-11-03):
- Directors: A. Director (individual). Shareholders: A. Director 100%.
- Consent to searches and data-protection notice signed 2026-11-03.
- Financials (source: FY2025 audited accounts PDF, period ending 2025-12-31, GBP): total borrowings 4,500,000;
  net worth 3,000,000; current assets 6,200,000; current liabilities 4,000,000; EBIT 900,000; interest 300,000;
  net profit 450,000; turnover 15,000,000.
- Prior year (source: FY2024 audited accounts PDF, period ending 2024-12-31, GBP): turnover 13,500,000; net profit 400,000.
- Existing wholesale facility (source: facility system, as at 2026-11-01): drawn 3,600,000; limit 4,500,000.
- Security (source: valuer's letter): debenture over stock, desktop valuation 6,600,000 dated 2026-10-01.
Lending request: increase wholesale facility to 5,500,000 for stock funding; terms and pricing proposed by
the preparer: 'standard wholesale terms, pricing per rate card' (no figures supplied).
Please prepare everything up to the authorisation gate."""


async def run(workflow, sessions, text: str) -> dict:
    r = Runner(agent=workflow, app_name=APP, session_service=sessions)
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    async for ev in r.run_async(user_id=USER, session_id=SID, new_message=msg):
        if ev.content and ev.content.parts and ev.is_final_response():
            txt = "".join(p.text or "" for p in ev.content.parts).strip()
            if txt:
                print(f"\n--- {ev.author} ---\n{txt[:1500]}{' …' if len(txt) > 1500 else ''}")
    return (await sessions.get_session(app_name=APP, user_id=USER, session_id=SID)).state


async def human_decision(sessions, actor: str, delta: dict, label: str) -> None:
    """Simulated human action by a named person: audited, then applied to the session."""
    from cpa_agents.store.runtime import record_human_decision   # lazy: agents import after --model
    await record_human_decision(sessions, APP, USER, SID, actor, delta, label)
    print(f"\n[HUMAN {actor}] {label}")


def print_gate(st: dict, title: str) -> None:
    g = st.get("gate_result") or {}
    print(f"\n=== {title}: {g.get('result')} (deciding rule {g.get('deciding_rule')}), "
          f"completeness {g.get('completeness', {}).get('display')}, policy {g.get('policy_version')}")
    for gap in g.get("gaps", []):
        print(f"  BLOCK {gap['rule']}: {gap['reason']}  ->  {gap['action']}")
    for adv in g.get("advisories", []):
        print(f"  advisory {adv['rule']}: {adv['reason']}")


async def humans_act(sessions, st: dict) -> None:
    """What the named people do between preparation and submission (each audited separately)."""
    from cpa_agents.rules import checks as ch
    from cpa_agents.rules.policy import load_policy
    from cpa_agents.tools._common import merged_view
    from datetime import date
    st = merged_view(st)

    hits = st.get("hits_open") or []
    if hits:
        await human_decision(sessions, "analyst-7 (Financial Crime)", {
            "hits_open": [], "hit_dispositions": [{**h, "disposition": "false positive", "rationale": "DOB and address differ",
                                                   "by": "analyst-7"} for h in hits]},
            f"dispositioned {len(hits)} hit(s) with rationale")
    reg = ch.mandatory_register(st.get("checklist") or {}, ch.parties_from_state(st))
    status = ch.register_status(reg, st.get("checks") or [], [], date.today().isoformat(), load_policy(), True)
    manual = [dict(party=s["party"], check=s["check"], result="clear", tool_used="manual check by analyst (demo)",
                   evidence_ref="analyst manual check file (demo)", manual=True, performed_by="analyst-7",
                   date=date.today().isoformat())
              for s in status if s["check"] != "cra" and s["status"] in ("outstanding", "open", "reperform")]
    await human_decision(sessions, "analyst-7 (Onboarding)", {
        "checks": (st.get("checks") or []) + manual, "cra_recorded_by": "analyst-7 (CRA: medium, basis on file)"},
        f"recorded CRA and {len(manual)} manual check(s) with evidence")
    disc = st.get("registry_discrepancies") or []
    if disc:
        await human_decision(sessions, OWNER, {"registry_discrepancies": [
            {**d, "resolved_by": OWNER, "resolution": "confirmed with dealer (demo)"} for d in disc]},
            f"resolved {len(disc)} registry discrepancy(ies)")
    sections = {k: {**v, "reviewed": True, "reviewed_by": OWNER} for k, v in (st.get("sections") or {}).items()}
    await human_decision(sessions, OWNER, {"sections": sections}, f"accepted {len(sections)} narrative section(s)")
    await human_decision(sessions, "pricing-committee-2", {"pricing_authorised_by": "pricing-committee-2"},
                         "authorised pricing and terms")
    await human_decision(sessions, OWNER, {"submission_authorised_by": OWNER, "pending_human": []},
                         "authorised submission to Credit")


async def main(model: str | None) -> None:
    if model:
        os.environ["CPA_MODEL"] = model
    from cpa_agents.agent import post_approval_workflow, preparation_workflow, submission_workflow
    from cpa_agents.store import get_store
    from cpa_agents.store.pack import assemble_pack  # noqa: F401
    from cpa_agents.store.runtime import make_session_service, raise_credit_query, resolve_credit_query
    store = get_store()
    sessions = make_session_service()
    await sessions.create_session(app_name=APP, user_id=USER, session_id=SID)
    print(f"session {SID} | model {os.getenv('CPA_MODEL')}")

    # 1) preparation: intake -> parallel evidence -> gaps -> request -> analysis -> drafting -> gate
    st = await run(preparation_workflow, sessions, REQUEST)
    print_gate(st, "Gate after preparation")
    print("pending human:", st.get("pending_human"))

    # 2) humans act
    await humans_act(sessions, st)

    # 3) submission: deterministic gate + authorisation, then transmit
    st = await run(submission_workflow, sessions, "Humans have recorded their decisions. Transmit if the gate allows.")
    print_gate(st, "Gate at submission")

    # 3b) Credit query that changes the pack -> new pack version
    if st.get("submitted"):
        qid = await raise_credit_query(sessions, APP, USER, SID, "credit-underwriter-3",
                                       "Please add commentary on stock turn.", owner=OWNER)
        print(f"\n[CREDIT] query {qid} raised")
        secs = dict(st.get("sections") or {})
        secs["credit_query_response"] = {"text": "Stock turn commentary added at Credit's request.",
                                         "evidence": ["FY2025 audited accounts"], "label": "human", "reviewed": True}
        await human_decision(sessions, OWNER, {"sections": secs}, f"response to credit query {qid}")
        out = await resolve_credit_query(sessions, APP, USER, SID, OWNER, qid, "commentary added", pack_changed=True)
        print(f"[HUMAN {OWNER}] query {qid} resolved -> pack version {out['pack_version']['version']}")

        # 4) Credit decides (human), then post-approval coordination
        await human_decision(sessions, "credit-underwriter-3", {"credit_outcome": "approved with conditions",
                                                                "conditions": ["updated stock audit before first drawdown"]},
                             "Credit recorded outcome")
        st = await run(post_approval_workflow, sessions, "Approval recorded. Start handoffs, check closure. "
                                                         "Last review date 2026-10-31; policy cadence for this dealer is "
                                                         "quarterly (3 months).")
    else:
        print("\n(pack was not submitted: see the gate above)")

    case_id = st.get("case_id")
    versions = store.pack_versions(case_id) if case_id else []
    chain = store.verify_chain(SID)
    print("\n=== evidence")
    print("case id        :", case_id)
    print("pack versions  :", [(v["version"], v["sha256"][:12], v["reason"]) for v in versions])
    print("audit events   :", len(store.events(SID)))
    print("agents in audit:", len({e["actor"] for e in store.events(SID) if e["actor_type"] == "agent"}))
    print("audit chain    :", "intact" if chain["ok"] else f"BROKEN at event #{chain['broken_at']}")
    print(f"replay         : python -m cpa_agents.store.replay {case_id or SID}")
    print(json.dumps({k: st.get(k) for k in ("submitted", "measures", "next_review")}, indent=2, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    asyncio.run(main(ap.parse_args().model))
