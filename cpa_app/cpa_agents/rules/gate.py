"""DT-2 pack completeness gate (REQ-061, BR-P04): rules R1..R8 evaluated top to bottom. Every
BLOCK rule that applies is reported (so the owner sees all gaps at once); the result is the first
BLOCK rule in order, else ADVISORY (R7), else PASS (R8). Each gap carries rule, reason and the
corrective action (BR-U04). CALC-011 gives the completeness score."""
import re
from datetime import date

from . import checks as ch
from . import reconcile
from .calculations import pack_completeness
from .language import find_decision_language
from .policy import Policy
from .validity import assess

# Information classes needed per DT-1 activity (REQ-008..013)
INFO_FOR_ACTIVITY = {"entity": {"entity"}, "parties": {"director", "shareholder"},
                     "financial": {"financial"}, "security": {"security"}}
ALWAYS_INFO = {"consent", "data_protection"}

# Narrative sections (REQ-047..051). ESG is required only where the template requires it (BR-D08, OQ-08).
CORE_SECTIONS = ("business_background", "management_assessment", "conduct_performance")
SECURITY_SECTION = "security_review"
OPTIONAL_SECTIONS = ("esg",)

INFO_VALIDITY_CLASS = {"financial": "financial_statements"}

# Figures checked for consistency between sections and the computed measures (R5). After a label,
# every plain number up to the end of the line (max 160 chars) is a candidate; thousands-formatted
# amounts (inputs such as 6,200,000) and identifiers (CALC-002) are not. A mismatch is reported only
# when no candidate equals the computed measure, so "current assets 6,200,000 / ... -> 1.55" passes.
_LABELS = {
    "gearing_x": r"gearing",
    "current_ratio": r"current ratio",
    "interest_cover_x": r"interest cover",
    "net_margin_pct": r"net (?:profit )?margin",
    "utilisation_pct": r"utilisation",
}
_PLAIN_NUMBER = re.compile(r"(?<![\w,.\-])(-?\d+(?:\.\d+)?)(?![\d,]|\.\d)")

RULE_ORDER = ("R1", "R2", "R3", "R4", "R5", "R6")


def _gap(rule, reason, action, result="BLOCK", **extra):
    return {"rule": rule, "result": result, "reason": reason, "action": action, **extra}


def _required_info(checklist: dict) -> tuple[set, set]:
    req, cond = set(ALWAYS_INFO), set()
    for act, classes in INFO_FOR_ACTIVITY.items():
        if checklist.get(act) == "R":
            req |= classes
        elif checklist.get(act) == "C":
            cond |= classes
    return req, cond - req


def required_sections(checklist: dict) -> list[str]:
    return list(CORE_SECTIONS) + ([SECURITY_SECTION] if checklist.get("security") == "R" else [])


def _exception_for(state: dict, rule: str, item: str) -> dict | None:
    """BR-E04: an authorised exception names an approver and a reason."""
    for e in state.get("exceptions") or []:
        if e.get("rule") == rule and e.get("item") == item and e.get("approved_by") and e.get("reason"):
            return e
    return None


def _figures_in(text: str) -> dict[str, list[float]]:
    """label key -> candidate numbers stated after the label (see _LABELS)."""
    out: dict[str, list[float]] = {}
    for key, label in _LABELS.items():
        for m in re.finditer(label, text or "", re.IGNORECASE):
            window = text[m.end():m.end() + 160].split("\n", 1)[0]
            cands = [float(n) for n in _PLAIN_NUMBER.findall(window)]
            if cands:
                out.setdefault(key, []).append(cands)
    return out


def figure_mismatches(text: str, measures: dict) -> list[tuple[str, float, float]]:
    """(key, stated, computed) where a labelled figure matches no candidate number."""
    out = []
    for key, mentions in _figures_in(text).items():
        m = measures.get(key)
        if not isinstance(m, (int, float)):
            continue
        for cands in mentions:
            if not any(abs(c - m) <= 0.005 for c in cands):
                out.append((key, cands[0], m))
    return out


_AMOUNT = re.compile(r"(?:£|GBP\s?)?(?<![\d,.])(\d{1,3}(?:,\d{3})+)(?:\.\d+)?(?![\d,])")


def known_amounts(state: dict) -> set[float]:
    """Every money figure the case can evidence: lending request, current limit and the change,
    facilities (drawn, limit, headroom), security value, measures and statement figures."""
    out: set[float] = set()
    lr = state.get("lending_request") or {}
    for v in (lr.get("amount"), lr.get("current_limit")):
        if isinstance(v, (int, float)):
            out.add(float(v))
    if isinstance(lr.get("amount"), (int, float)) and isinstance(lr.get("current_limit"), (int, float)):
        out.add(abs(float(lr["amount"]) - float(lr["current_limit"])))
    for f in state.get("facilities") or []:
        d, lm = f.get("drawn"), f.get("limit")
        out.update(float(x) for x in (d, lm) if isinstance(x, (int, float)))
        if isinstance(d, (int, float)) and isinstance(lm, (int, float)):
            out.add(float(lm - d))
    sec = state.get("security") or {}
    if isinstance(sec.get("value"), (int, float)):
        out.add(float(sec["value"]))
    for v in (state.get("measures") or {}).values():
        if isinstance(v, (int, float)):
            out.add(float(v))
    for s in (state.get("financial_statements") or []) + (state.get("financial_statement_versions") or []):
        out.update(float(v) for v in (s.get("figures") or {}).values() if isinstance(v, (int, float)))
    return out


def unsupported_amounts(text: str, state: dict) -> list[str]:
    """Money amounts (thousands-separated, optionally £/GBP) in the text that match no case figure
    (BR-D07: every statement traces to evidence). Identifiers such as registered numbers are not
    written with separators and are ignored."""
    known = known_amounts(state)
    out = []
    for m in _AMOUNT.finditer(text or ""):
        val = float(m.group(1).replace(",", ""))
        if not any(abs(val - k) <= 0.5 for k in known):
            out.append(m.group(1))
    return out


def evaluate(state: dict, policy: Policy, as_at: str | None = None) -> dict:
    as_at = as_at or date.today().isoformat()
    checklist = state.get("checklist") or {}
    gaps: list[dict] = []
    advisories: list[dict] = []
    done = total = 0

    if not checklist:
        gaps.append(_gap("R1", "no applicable requirement set (DT-1) for this case",
                         "run intake classification to build the checklist"))

    # ---- R1 mandatory section or field missing ----
    have = {i.get("info_class") for i in state.get("info_items") or []}
    req_info, cond_info = _required_info(checklist)
    for cls in sorted(req_info):
        total += 1
        if cls in have:
            done += 1
        else:
            gaps.append(_gap("R1", f"mandatory information missing: {cls}",
                             f"capture {cls} information with its source (REQ-015)"))
    for cls in sorted(cond_info - have):
        advisories.append(_gap("R7", f"conditional information not captured: {cls}",
                               "confirm it is unchanged since the last case or refresh it", "ADVISORY"))
    sections = state.get("sections") or {}
    for s in required_sections(checklist) if checklist else []:
        total += 1
        if s in sections and (sections[s].get("text") or "").strip():
            done += 1
        else:
            gaps.append(_gap("R1", f"mandatory template section missing: {s}",
                             f"draft the {s.replace('_', ' ')} section and have the owner accept it"))
    for s in OPTIONAL_SECTIONS:
        if s not in sections:
            advisories.append(_gap("R7", f"optional section empty: {s}",
                                   "complete if the template requires it (BR-D08, OQ-08)", "ADVISORY"))
    for key, what, action in (("lending_request", "lending request", "record the lending request (REQ-055)"),
                              ("pricing_authorised_by", "pricing and terms authorisation",
                               "obtain authorisation from the pricing authority (REQ-058)")):
        total += 1
        if state.get(key):
            done += 1
        else:
            gaps.append(_gap("R1", f"{what} missing", action))
    lr = state.get("lending_request") or {}
    pa = state.get("pricing_authorised_by")
    if pa and lr.get("preparer") and str(pa).strip().lower() == str(lr["preparer"]).strip().lower():
        gaps.append(_gap("R1", "pricing authorised by its preparer (BR-E02)",
                         "obtain authorisation from a different authorised role"))

    # ---- R2 mandatory check outstanding ----
    parties = ch.parties_from_state(state)
    register = ch.mandatory_register(checklist, parties)
    status = ch.register_status(register, state.get("checks") or [], state.get("hits_open") or [],
                                as_at, policy, bool(state.get("cra_recorded_by")))
    for line in status:
        total += 1
        if line["status"] == "complete":
            done += 1
        elif line["status"] in ("outstanding", "open", "reperform"):
            item = f"{line['party']}/{line['check']}"
            exc = _exception_for(state, "R2", item)
            if exc:
                done += 1
                advisories.append(_gap("R2", f"{item} open under authorised exception", "none",
                                       "ADVISORY", exception=exc))
            else:
                gaps.append(_gap("R2", f"mandatory check outstanding: {line['reason']}",
                                 "perform the check, or record a manual alternative with evidence (REQ-092)",
                                 item=item))
    if checklist.get("checks") in ("R", "C") and not policy.is_set("fca_regulatory_scope"):
        advisories.append(_gap("R7", "FCA regulatory check scope NOT CONFIGURED (OQ-01)",
                               "SME to define the scope in policy.yaml before go-live", "ADVISORY"))

    # ---- R3 hit undispositioned ----
    for h in state.get("hits_open") or []:
        gaps.append(_gap("R3", f"undispositioned {h.get('result', 'hit')}: {h.get('party')}/{h.get('check')}",
                         "authorised analyst to record a disposition with rationale (REQ-032)"))
    if state.get("case_halted"):
        gaps.append(_gap("R3", "case halted: confirmed match escalated to Financial Crime Compliance",
                         "await Financial Crime Compliance outcome"))

    # ---- R4 narrative unreviewed (incl. decision language BR-D12 and uncited text ARCH-G08) ----
    for name, sec in sorted(sections.items()):
        if not sec.get("reviewed"):
            gaps.append(_gap("R4", f"narrative not accepted by the case owner: {name}",
                             "case owner to accept, amend or reject the section (REQ-052)"))
        if find_decision_language(sec.get("text", "")):
            gaps.append(_gap("R4", f"decision language in {name} (BR-D12)",
                             "remove any statement or implication of a credit decision"))
        if not sec.get("evidence") and sec.get("label") != "human":
            gaps.append(_gap("R4", f"uncited drafted text in {name} (ARCH-G08)",
                             "link each assertion to evidence, or have a named human author it"))

    # ---- R5 numbers inconsistent between sections ----
    measures = state.get("measures") or {}
    for name, sec in sorted(sections.items()):
        for key, val, m in figure_mismatches(sec.get("text", ""), measures):
            gaps.append(_gap("R5", f"{name} states {key} {val}, analysis shows {m}",
                             "correct the section to the computed figure"))
    for name, sec in sorted(sections.items()):
        for amt in unsupported_amounts(sec.get("text", ""), state):
            gaps.append(_gap("R5", f"{name} states amount {amt}, which matches no figure in the case "
                                   f"(lending request {float(lr.get('amount') or 0):,.0f})",
                             "correct the amount to the lending request or the evidenced figure"))
    # numbers inconsistent between sources: tie-outs, versions, documents, unaudited basis (REQ-044)
    for it in reconcile.run(state, policy):
        if it["explained"]:
            advisories.append(_gap("R5", f"{it['description']} - explained by {it['explained'].get('by')}",
                                   "none", "ADVISORY", item=it["key"], explanation=it["explained"].get("explanation")))
        elif it["severity"] == "BLOCK":
            gaps.append(_gap("R5", it["description"], it["action"] + " (record the explanation in the workbench)",
                             item=it["key"]))
        else:
            advisories.append(_gap("R7", it["description"], it["action"], "ADVISORY", item=it["key"]))

    # ---- R6 information past validity ----
    for item in state.get("info_items") or []:
        vc = INFO_VALIDITY_CLASS.get(item.get("info_class"))
        if not vc:
            continue
        v = assess(vc, item.get("as_at"), as_at, policy)
        label = f"{item.get('info_class')} dated {item.get('as_at') or 'undated'}"
        if v["stale"]:
            exc = _exception_for(state, "R6", label)
            if exc:
                advisories.append(_gap("R6", f"{label} past validity under authorised exception", "none",
                                       "ADVISORY", exception=exc))
            else:
                gaps.append(_gap("R6", f"{label} past validity ({v['display']})",
                                 f"{v['action']}, or record an authorised exception (BR-E04)", item=label))
        elif v["stale"] is None:
            advisories.append(_gap("R7", f"cannot confirm {label} is current: validity NOT CONFIGURED (OQ-06)",
                                   "policy owner to set DT-5 validity periods", "ADVISORY"))
    reg = state.get("registry_record") or {}
    if reg:
        v = assess("registry_result", reg.get("retrieved"), as_at, policy)
        if v["stale"]:
            gaps.append(_gap("R6", f"registry record past validity ({v['display']})", v["action"]))
    for d in state.get("registry_discrepancies") or []:
        if not d.get("resolved_by"):
            gaps.append(_gap("R1", f"registry discrepancy unresolved: {d.get('field')} ({d.get('issue')})",
                             "case owner to resolve and record the resolution (BR-D01)"))

    completeness = pack_completeness(done, total)
    blocking = [g for g in gaps if g["result"] == "BLOCK"]
    if blocking or completeness.value is None or completeness.value < 100:
        first = min((RULE_ORDER.index(g["rule"]) for g in blocking), default=0)
        result, deciding = "BLOCK", RULE_ORDER[first]
    elif advisories:
        result, deciding = "ADVISORY", "R7"
    else:
        result, deciding = "PASS", "R8"
    return {"result": result, "deciding_rule": deciding,
            "submission_may_be_authorised": result in ("PASS", "ADVISORY"),
            "gaps": blocking, "advisories": advisories,
            "completeness": completeness.as_dict(), "mandatory_items": {"complete": done, "applicable": total},
            "check_register": status, "policy_version": policy.version, "as_at": as_at}
