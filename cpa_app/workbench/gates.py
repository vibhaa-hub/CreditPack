"""Human gate actions (design decisions 3-4, Arch 3.4). Each action: permission check, prerequisite
check (the data the approver saw must still be current), then one audited human decision.
Returns (ok, message). Pure state logic lives here so it can be tested without HTTP."""
import hashlib
import json
from datetime import date

from cpa_agents.rules import checks as ch
from cpa_agents.rules import reconcile
from cpa_agents.rules.gate import evaluate
from cpa_agents.rules.policy import load_policy
from cpa_agents.store import get_store
from cpa_agents.store.runtime import raise_credit_query, record_human_decision, resolve_credit_query

from .permissions import can
from .runner import APP, USER
from .users import actor


def prereq_hash(data) -> str:
    """Fingerprint of the prerequisite data shown with an approval form (ARCH-H09)."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:20]


# prerequisite data per action, computed from current state (what the approver must see)
def prerequisites(action: str, st: dict, **kw) -> dict:
    if action == "disposition_hit":
        hit = (st.get("hits_open") or [])[int(kw["idx"])]
        recs = [c for c in st.get("checks") or [] if c["party"] == hit["party"] and c["check"] == hit["check"]]
        return {"hit": hit, "check_records": recs, "prior_dispositions": st.get("hit_dispositions") or []}
    if action == "resolve_discrepancy":
        return {"discrepancy": (st.get("registry_discrepancies") or [])[int(kw["idx"])],
                "registry_record": st.get("registry_record")}
    if action == "explain_difference":
        item = next(i for i in reconcile.run(st, load_policy()) if i["key"] == kw["key"])
        return {"item": {k: item[k] for k in ("key", "kind", "description", "values", "difference", "tolerance")}}
    if action == "review_section":
        sec = (st.get("sections") or {})[kw["section"]]
        return {"section": kw["section"], "text": sec.get("text"), "evidence": sec.get("evidence"),
                "version": sec.get("version"), "critic": [f for f in st.get("critic_findings") or []
                                                         if f["section"] == kw["section"]]}
    if action == "authorise_pricing":
        return {"lending_request": st.get("lending_request"), "measures": st.get("measures"),
                "security": st.get("security")}
    if action == "authorise_submission":
        g = evaluate(st, load_policy(), date.today().isoformat())
        return {"gate": g["result"], "gaps": g["gaps"], "completeness": g["completeness"]["display"],
                "sections": {k: v.get("version") for k, v in (st.get("sections") or {}).items()}}
    if action in ("record_cra", "record_manual_check"):
        reg = ch.mandatory_register(st.get("checklist") or {}, ch.parties_from_state(st))
        return {"register": ch.register_status(reg, st.get("checks") or [], st.get("hits_open") or [],
                                               date.today().isoformat(), load_policy(), bool(st.get("cra_recorded_by")))}
    return {}


class Gates:
    def __init__(self, sessions):
        self.sessions = sessions

    async def state(self, sid: str) -> dict:
        from cpa_agents.tools._common import merged_view
        s = await self.sessions.get_session(app_name=APP, user_id=USER, session_id=sid)
        return merged_view(s.state) if s else {}

    async def _decide(self, sid, user, role, delta, label):
        await record_human_decision(self.sessions, APP, USER, sid, actor(user, role), delta, label)

    def _denied(self, sid, user, action, reason):
        get_store().append_event(sid or "workbench", "human", actor(user) if user else "anonymous", "access_denied",
                                 detail={"action": action, "reason": reason})

    async def act(self, sid: str, user: dict, action: str, form: dict) -> tuple[bool, str]:
        st = await self.state(sid)
        d = can(user, action, st)
        if not d:
            self._denied(sid, user, action, d.reason)
            return False, f"{d.reason} - {d.action}"
        if form.get("_prereq") is not None or action in ("disposition_hit", "resolve_discrepancy", "review_section",
                                                         "explain_difference", "authorise_pricing",
                                                         "authorise_submission"):
            try:
                expected = prereq_hash(prerequisites(action, st, **{k: form[k] for k in ("idx", "section", "key")
                                                                    if k in form}))
            except (IndexError, KeyError, ValueError, StopIteration):
                return False, "that item no longer exists - reload the page"
            if form.get("_prereq") != expected:
                get_store().append_event(sid, "human", actor(user, d.role), "process_failure",
                                         detail={"action": action, "reason": "approval prerequisites not current (ARCH-H09)"})
                return False, "the information shown has changed since you opened it - reload and review again (ARCH-H09)"
        handler = getattr(self, f"_{action}", None)
        if handler is None:
            return False, f"no handler for {action}"
        return await handler(sid, user, d.role, st, form)

    # ---------- checks and hits ----------
    async def _disposition_hit(self, sid, user, role, st, f):
        if not (f.get("rationale") or "").strip():
            return False, "a rationale is required (REQ-032)"
        hits = list(st.get("hits_open") or [])
        hit = hits.pop(int(f["idx"]))
        disp = {**hit, "disposition": f.get("disposition"), "rationale": f["rationale"].strip(), "by": actor(user, role)}
        delta = {"hits_open": hits, "hit_dispositions": (st.get("hit_dispositions") or []) + [disp]}
        if f.get("disposition") == "true match":
            delta["case_halted"] = True
            delta["hits_open"] = hits + [hit]          # a true match stays open: escalated, case halted
        else:
            # a cleared confirmed match does not un-halt by itself unless no other halting hit remains
            if st.get("case_halted") and not any(h.get("result") == "confirmed_match" for h in hits):
                delta["case_halted"] = False
        await self._decide(sid, user, role, delta, f"hit {hit['party']}/{hit['check']}: {f.get('disposition')}")
        return True, "disposition recorded"

    async def _record_cra(self, sid, user, role, st, f):
        if not (f.get("outcome") and (f.get("basis") or "").strip()):
            return False, "CRA outcome and basis are required (REQ-029)"
        await self._decide(sid, user, role, {"cra_recorded_by": actor(user, role),
                                             "cra": {"outcome": f["outcome"], "basis": f["basis"].strip(),
                                                     "date": date.today().isoformat()}},
                           f"CRA recorded: {f['outcome']}")
        return True, "CRA recorded"

    async def _record_manual_check(self, sid, user, role, st, f):
        need = [k for k in ("party", "check", "result", "evidence_ref", "tool_used") if not (f.get(k) or "").strip()]
        if need:
            return False, f"missing {', '.join(need)} (REQ-035)"
        try:
            o = ch.outcome(f["result"])
        except ValueError as e:
            return False, str(e)
        rec = dict(party=f["party"], check=f["check"], result=o["outcome"], tool_used=f["tool_used"],
                   evidence_ref=f["evidence_ref"], manual=True, performed_by=actor(user, role),
                   date=date.today().isoformat())
        delta = {"checks": (st.get("checks") or []) + [rec]}
        if o["opens_hit"]:
            delta["hits_open"] = (st.get("hits_open") or []) + [dict(party=f["party"], check=f["check"], result=o["outcome"])]
        await self._decide(sid, user, role, delta, f"manual {f['check']} for {f['party']}: {o['outcome']}")
        return True, "check recorded"

    # ---------- entity ----------
    async def _resolve_discrepancy(self, sid, user, role, st, f):
        if not (f.get("resolution") or "").strip():
            return False, "a resolution is required (BR-D01)"
        disc = list(st.get("registry_discrepancies") or [])
        i = int(f["idx"])
        disc[i] = {**disc[i], "resolved_by": actor(user, role), "resolution": f["resolution"].strip()}
        await self._decide(sid, user, role, {"registry_discrepancies": disc},
                           f"registry discrepancy resolved: {disc[i]['field']}")
        return True, "discrepancy resolved"

    # ---------- narrative ----------
    async def _review_section(self, sid, user, role, st, f):
        name, decision = f["section"], f.get("decision")
        secs = dict(st.get("sections") or {})
        sec = dict(secs[name])
        who = actor(user, role)
        if decision == "accept":
            secs[name] = {**sec, "reviewed": True, "reviewed_by": who}
        elif decision == "amend":
            text = (f.get("text") or "").strip()
            from cpa_agents.rules.language import find_decision_language
            if not text:
                return False, "amended text is empty"
            if find_decision_language(text):
                return False, "the amended text states or implies a credit decision (BR-D12)"
            secs[name] = {**sec, "text": text, "label": "human", "author": who, "reviewed": True, "reviewed_by": who}
        elif decision == "reject":
            secs.pop(name)
        else:
            return False, "choose accept, amend or reject"
        delta = {"sections": secs}
        if decision == "reject":
            delta["rejected_sections"] = (st.get("rejected_sections") or []) + [{"section": name, "by": who,
                                                                                 "text": sec.get("text")}]
        await self._decide(sid, user, role, delta, f"section {name}: {decision}")
        return True, {"accept": "section accepted", "amend": "section amended and accepted",
                      "reject": "section rejected - redraft needed"}[decision]

    # ---------- pricing, exceptions, submission ----------
    async def _authorise_pricing(self, sid, user, role, st, f):
        if not st.get("lending_request"):
            return False, "no lending request recorded yet"
        await self._decide(sid, user, role, {"pricing_authorised_by": actor(user, role),
                                             "pricing_authorisation": {"by": actor(user, role), "values": st["lending_request"],
                                                                       "date": date.today().isoformat()},
                                             "pending_human": [p for p in st.get("pending_human") or []
                                                               if p != "pricing/terms authorisation"]},
                           "pricing and terms authorised")
        return True, "pricing authorised"

    async def _authorise_exception(self, sid, user, role, st, f):
        if not ((f.get("rule") or "").strip() and (f.get("item") or "").strip() and (f.get("reason") or "").strip()):
            return False, "rule, item and reason are required (BR-E04)"
        exc = {"rule": f["rule"].strip(), "item": f["item"].strip(), "reason": f["reason"].strip(),
               "approved_by": actor(user, role), "date": date.today().isoformat()}
        await self._decide(sid, user, role, {"exceptions": (st.get("exceptions") or []) + [exc]},
                           f"authorised exception {exc['rule']} {exc['item']}")
        return True, "exception recorded"

    async def _authorise_submission(self, sid, user, role, st, f):
        g = evaluate(st, load_policy(), date.today().isoformat())
        if not g["submission_may_be_authorised"]:
            return False, "the gate does not allow submission yet: " + "; ".join(x["reason"] for x in g["gaps"][:3])
        await self._decide(sid, user, role, {"submission_authorised_by": actor(user, role),
                                             "pending_human": [p for p in st.get("pending_human") or []
                                                               if p != "submission authorisation"]},
                           "submission to Credit authorised")
        return True, "submission authorised - run the submission step"

    # ---------- financial reconciliation (REQ-044) ----------
    async def _explain_difference(self, sid, user, role, st, f):
        text = (f.get("explanation") or "").strip()
        if len(text) < 10:
            return False, "an explanation of at least 10 characters is required (REQ-044)"
        item = next(i for i in reconcile.run(st, load_policy()) if i["key"] == f["key"])
        expl = [e for e in st.get("difference_explanations") or [] if e["key"] != f["key"]]
        expl.append({"key": f["key"], "kind": item["kind"], "description": item["description"], "values": item["values"],
                     "explanation": text, "by": actor(user, role), "date": date.today().isoformat()})
        await self._decide(sid, user, role, {"difference_explanations": expl},
                           f"financial difference explained: {item['description'][:120]}")
        return True, "explanation recorded"

    # ---------- notes ----------
    async def _add_note(self, sid, user, role, st, f):
        if not (f.get("text") or "").strip():
            return False, "note text is required"
        note = {"text": f["text"].strip(), "author": actor(user, role), "date": f.get("date") or date.today().isoformat(),
                "participants": [p.strip() for p in (f.get("participants") or "").split(",") if p.strip()]}
        await self._decide(sid, user, role, {"notes": (st.get("notes") or []) + [note]}, "note added (REQ-017)")
        return True, "note added"

    # ---------- Credit ----------
    async def _raise_query(self, sid, user, role, st, f):
        if not st.get("submitted"):
            return False, "the pack has not been submitted"
        if not (f.get("text") or "").strip():
            return False, "query text is required"
        qid = await raise_credit_query(self.sessions, APP, USER, sid, actor(user, role), f["text"].strip(),
                                       owner=st.get("owner"))
        return True, f"query {qid} raised"

    async def _resolve_query(self, sid, user, role, st, f):
        if not (f.get("resolution") or "").strip():
            return False, "a resolution is required"
        out = await resolve_credit_query(self.sessions, APP, USER, sid, actor(user, role), int(f["query_id"]),
                                         f["resolution"].strip(), pack_changed=f.get("pack_changed") == "on")
        pv = out["pack_version"]
        return True, "query resolved" + (f" - pack version {pv['version']} created" if pv else "")

    async def _record_outcome(self, sid, user, role, st, f):
        if f.get("outcome") not in ("approved", "approved with conditions", "declined", "referred"):
            return False, "choose an outcome"
        if not st.get("submitted"):
            return False, "the pack has not been submitted"
        conds = [c.strip() for c in (f.get("conditions") or "").splitlines() if c.strip()]
        await self._decide(sid, user, role, {"credit_outcome": f["outcome"], "conditions": conds,
                                             "credit_reference": f.get("reference") or "",
                                             "outcome_recorded_by": actor(user, role),
                                             "outcome_date": date.today().isoformat()},
                           f"Credit outcome: {f['outcome']}")
        return True, "outcome recorded"

    async def _update_handoff(self, sid, user, role, st, f):
        if f.get("kind") == "condition":
            conds = list(st.get("conditions_status") or [])
            i = int(f["idx"])
            if not (f.get("evidence") or "").strip():
                return False, "evidence is required to satisfy a condition (BR-P08)"
            conds[i] = {**conds[i], "status": "satisfied", "evidence": f["evidence"].strip(), "by": actor(user, role)}
            await self._decide(sid, user, role, {"conditions_status": conds}, f"condition satisfied: {conds[i]['condition']}")
            return True, "condition satisfied"
        hs = list(st.get("handoffs") or [])
        i = int(f["idx"])
        status = f.get("status")
        if status not in ("open", "in progress", "complete", "closed"):
            return False, "choose a status"
        if status == "closed" and not (f.get("reason") or "").strip():
            return False, "closing without completion needs a reason (BR-P10)"
        hs[i] = {**hs[i], "status": status, "owner": f.get("owner") or hs[i].get("owner") or actor(user, role),
                 "reason": (f.get("reason") or "").strip() or hs[i].get("reason")}
        await self._decide(sid, user, role, {"handoffs": hs}, f"handoff {hs[i]['task']}: {status}")
        return True, "handoff updated"
