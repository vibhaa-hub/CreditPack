"""Financial reconciliation (REQ-044 "unreconciled totals and inconsistent values", BR-D07).

Deterministic checks over the recorded figures. The model never decides whether numbers agree:

  tieout        a statement's own arithmetic: gross profit, total assets, net assets, cash flow
  subtotal      a table total against the sum of the lines the agent identified (verify_total)
  continuity    one year's closing cash and stock against the next year's opening figures
  version       two versions of the same period (audited vs management vs dealer-stated)
  cross_doc     figures that should agree across documents: the current limit in the request vs the
                facility statement, our drawn exposure vs the borrowings in the accounts, a stock
                valuation vs the stock in the accounts
  basis         the measures rest on unaudited figures

Each item has a stable `key` built from what it compares, so an owner's explanation stays attached
while the numbers are unchanged and lapses when they change. BLOCK items stop the DT-2 gate under
R5 until the case owner records an explanation; ADVISORY items are shown but do not block."""
import hashlib
import json
from datetime import date
from decimal import Decimal

from . import financials as fin
from .policy import NOT_CONFIGURED, Policy

LABEL = {"turnover": "turnover", "cost_of_sales": "cost of sales", "gross_profit": "gross profit",
         "net_profit": "net profit", "ebit": "EBIT", "interest_charge": "interest charge",
         "total_borrowings": "total borrowings", "net_worth": "net worth", "current_assets": "current assets",
         "current_liabilities": "current liabilities", "fixed_assets": "fixed assets",
         "total_assets": "total assets", "total_liabilities": "total liabilities",
         "long_term_liabilities": "long-term liabilities", "opening_cash": "opening cash",
         "closing_cash": "closing cash", "opening_stock": "opening stock", "closing_stock": "closing stock",
         "inflows": "cash inflows", "outflows": "cash outflows", "dividends": "dividends",
         "tangible_equity": "tangible equity", "net_profit_attributable": "net profit attributable"}


def _d(x) -> Decimal:
    return Decimal(str(x))


def _fmt(x) -> str:
    return f"{_d(x):,.0f}"


def tolerance(policy: Policy, a, b) -> tuple[bool, str]:
    """Whether two amounts agree under the policy tolerances (absolute or percentage, either passes).
    With neither configured, any difference over 0.5 (rounding) is reported."""
    amt, pct = policy.get("tolerances.reconciliation_amount"), policy.get("tolerances.reconciliation_pct")
    diff = abs(_d(a) - _d(b))
    if amt is NOT_CONFIGURED and pct is NOT_CONFIGURED:
        return diff <= Decimal("0.5"), "NOT CONFIGURED (any difference reported)"
    ok = False
    parts = []
    if amt is not NOT_CONFIGURED:
        ok |= diff <= _d(amt)
        parts.append(f"{_fmt(amt)}")
    if pct is not NOT_CONFIGURED:
        base = max(abs(_d(a)), abs(_d(b)))
        ok |= base == 0 or diff / base * 100 <= _d(pct)
        parts.append(f"{pct}%")
    return ok, " or ".join(parts)


def item_key(kind: str, *parts) -> str:
    return f"{kind}:" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _item(kind, severity, period, field, description, values, difference=None, tol=None, action=None):
    key = item_key(kind, period, field, [(v["label"], v["value"]) for v in values])
    return {"key": key, "kind": kind, "rule": "R5", "severity": severity, "period": period, "field": field,
            "description": description, "values": values,
            "difference": None if difference is None else fin.as_number(_d(difference)),
            "tolerance": tol, "action": action or "case owner to correct the figures or explain the difference"}


def _v(label, value, source):
    return {"label": label, "value": fin.as_number(_d(value)), "source": source}


# ---------------- within one statement ----------------
_IDENTITIES = (
    # (result field, [(sign, field)...], description)
    ("gross_profit", [(1, "turnover"), (-1, "cost_of_sales")], "gross profit = turnover - cost of sales"),
    ("total_assets", [(1, "fixed_assets"), (1, "current_assets")], "total assets = fixed assets + current assets"),
    ("net_worth", [(1, "total_assets"), (-1, "total_liabilities")], "net worth = total assets - total liabilities"),
    ("net_worth", [(1, "fixed_assets"), (1, "current_assets"), (-1, "current_liabilities"),
                   (-1, "long_term_liabilities")],
     "net worth = fixed assets + current assets - current liabilities - long-term liabilities"),
    ("total_liabilities", [(1, "current_liabilities"), (1, "long_term_liabilities")],
     "total liabilities = current liabilities + long-term liabilities"),
)


def tieouts(stmt: dict, policy: Policy) -> list[dict]:
    f, out = stmt.get("figures") or {}, []
    src, period = stmt.get("source"), stmt["period_end"]
    for result, terms, desc in _IDENTITIES:
        if result not in f or any(t not in f for _, t in terms):
            continue
        calc = sum((s * _d(f[t]) for s, t in terms), Decimal(0))
        ok, tol = tolerance(policy, f[result], calc)
        if not ok:
            out.append(_item("tieout", "BLOCK", period, result,
                             f"{period}: stated {LABEL[result]} does not equal {desc}",
                             [_v(f"stated {LABEL[result]}", f[result], src), _v("calculated", calc, "rules.reconcile")],
                             _d(f[result]) - calc, tol))
    if all(k in f for k in ("opening_cash", "inflows", "outflows", "closing_cash")):
        calc = _d(f["opening_cash"]) + _d(f["inflows"]) - _d(f["outflows"])
        t = policy.get("tolerances.cashflow_reconciliation_amount")
        ok = abs(_d(f["closing_cash"]) - calc) <= (_d(0.5) if t is NOT_CONFIGURED else _d(t))
        if not ok:
            out.append(_item("tieout", "BLOCK", period, "closing_cash",
                             f"{period}: closing cash does not equal opening cash + inflows - outflows (CALC-007)",
                             [_v("stated closing cash", f["closing_cash"], src), _v("calculated", calc, "CALC-007")],
                             _d(f["closing_cash"]) - calc,
                             "NOT CONFIGURED (any difference reported)" if t is NOT_CONFIGURED else _fmt(t)))
    if "closing_stock" in f and "current_assets" in f and _d(f["closing_stock"]) > _d(f["current_assets"]):
        out.append(_item("tieout", "BLOCK", period, "closing_stock",
                         f"{period}: closing stock is larger than total current assets",
                         [_v("closing stock", f["closing_stock"], src), _v("current assets", f["current_assets"], src)],
                         _d(f["closing_stock"]) - _d(f["current_assets"]), None,
                         "check the figures were read from the right lines and period"))
    return out


# ---------------- between periods ----------------
def continuity(selected: list[dict], policy: Policy) -> list[dict]:
    out = []
    yrs = fin.annual(selected)
    for prev, cur in zip(yrs, yrs[1:]):
        if _months(prev["period_end"], cur["period_end"]) != 12:
            continue                                   # a gap is a quality flag, not a mismatch
        pf, cf = prev.get("figures") or {}, cur.get("figures") or {}
        for close, open_ in (("closing_cash", "opening_cash"), ("closing_stock", "opening_stock")):
            if close in pf and open_ in cf:
                ok, tol = tolerance(policy, pf[close], cf[open_])
                if not ok:
                    out.append(_item("continuity", "BLOCK", cur["period_end"], open_,
                                     f"{cur['period_end']}: {LABEL[open_]} does not equal {LABEL[close]} at {prev['period_end']}",
                                     [_v(f"{LABEL[close]} {prev['period_end']}", pf[close], prev.get("source")),
                                      _v(f"{LABEL[open_]} {cur['period_end']}", cf[open_], cur.get("source"))],
                                     _d(cf[open_]) - _d(pf[close]), tol))
        if all(k in cf for k in ("net_worth", "net_profit", "dividends")) and "net_worth" in pf:
            calc = _d(pf["net_worth"]) + _d(cf["net_profit"]) - _d(cf["dividends"])
            ok, tol = tolerance(policy, cf["net_worth"], calc)
            if not ok:
                out.append(_item("continuity", "ADVISORY", cur["period_end"], "net_worth",
                                 f"{cur['period_end']}: net worth moved by more than profit less dividends "
                                 "(other reserve movements, e.g. revaluation or share issue, may explain it)",
                                 [_v("stated net worth", cf["net_worth"], cur.get("source")),
                                  _v("prior net worth + profit - dividends", calc, "rules.reconcile")],
                                 _d(cf["net_worth"]) - calc, tol, "confirm the other reserve movements"))
    return out


def versions(all_versions: list[dict], policy: Policy) -> list[dict]:
    """Two versions of the same period whose shared figures disagree."""
    out = []
    by_period: dict[str, list[dict]] = {}
    for v in all_versions:
        by_period.setdefault(v["period_end"], []).append(v)
    for period, vs in sorted(by_period.items()):
        for i, a in enumerate(vs):
            for b in vs[i + 1:]:
                fa, fb = a.get("figures") or {}, b.get("figures") or {}
                for k in sorted(set(fa) & set(fb)):
                    ok, tol = tolerance(policy, fa[k], fb[k])
                    if not ok:
                        out.append(_item("version", "BLOCK", period, k,
                                         f"{period}: {LABEL.get(k, k)} differs between "
                                         f"{fin.BASIS_LABEL.get(a['basis'], a['basis'])} and "
                                         f"{fin.BASIS_LABEL.get(b['basis'], b['basis'])}",
                                         [_v(fin.BASIS_LABEL.get(a["basis"], a["basis"]), fa[k], a.get("source")),
                                          _v(fin.BASIS_LABEL.get(b["basis"], b["basis"]), fb[k], b.get("source"))],
                                         _d(fa[k]) - _d(fb[k]), tol))
    return out


# ---------------- across documents ----------------
def cross_documents(state: dict, selected: list[dict], policy: Policy) -> list[dict]:
    out = []
    lr = state.get("lending_request") or {}
    fac = state.get("facilities") or []
    line = [f for f in fac if f.get("lending_line") == lr.get("facility_type")]
    if line and isinstance(lr.get("current_limit"), (int, float)):
        lim = sum(_d(f["limit"]) for f in line)
        ok, tol = tolerance(policy, lr["current_limit"], lim)
        if not ok:
            out.append(_item("cross_doc", "BLOCK", None, "limit",
                             f"current {lr.get('facility_type')} limit in the lending request does not match the facility record",
                             [_v("lending request current limit", lr["current_limit"], "lending request"),
                              _v("facility limit", lim, ", ".join(sorted({f.get('source') or '' for f in line})))],
                             _d(lr["current_limit"]) - lim, tol))
    window = policy.get("reconciliation.date_window_days")
    yrs = fin.annual(selected)
    latest = yrs[-1] if yrs else None
    lf = (latest or {}).get("figures") or {}
    ours = [f for f in fac if f.get("lending_line") != "external"]
    if latest and ours and "total_borrowings" in lf:
        as_at = max(f.get("as_at") or "" for f in ours)
        close = _close_dates(as_at, latest["period_end"], window)
        drawn = sum(_d(f["drawn"]) for f in ours)
        if close is None:
            out.append(_item("cross_doc", "ADVISORY", latest["period_end"], "total_borrowings",
                             "cannot compare our drawn exposure with borrowings in the accounts: "
                             "reconciliation.date_window_days NOT CONFIGURED",
                             [_v(f"drawn with us at {as_at}", drawn, "facilities"),
                              _v(f"total borrowings at {latest['period_end']}", lf["total_borrowings"], latest.get("source"))],
                             None, None, "policy owner to set the comparison window"))
        elif close and drawn > _d(lf["total_borrowings"]) and not tolerance(policy, drawn, lf["total_borrowings"])[0]:
            out.append(_item("cross_doc", "BLOCK", latest["period_end"], "total_borrowings",
                             "drawn exposure with us is larger than the total borrowings shown in the accounts "
                             "(borrowing may be missing from the accounts, or classified elsewhere)",
                             [_v(f"drawn with us at {as_at}", drawn, "facilities"),
                              _v(f"total borrowings at {latest['period_end']}", lf["total_borrowings"], latest.get("source"))],
                             drawn - _d(lf["total_borrowings"]), tolerance(policy, drawn, lf["total_borrowings"])[1]))
    sec = state.get("security") or {}
    if latest and "closing_stock" in lf and isinstance(sec.get("value"), (int, float)) \
            and "stock" in (sec.get("description") or "").lower():
        close = _close_dates(sec.get("date") or "", latest["period_end"], window)
        if close and _d(sec["value"]) > _d(lf["closing_stock"]) \
                and not tolerance(policy, sec["value"], lf["closing_stock"])[0]:
            out.append(_item("cross_doc", "BLOCK", latest["period_end"], "closing_stock",
                             "stock valuation is higher than the stock in the accounts at a nearby date",
                             [_v(f"valuation at {sec.get('date')}", sec["value"], "security valuation"),
                              _v(f"closing stock at {latest['period_end']}", lf["closing_stock"], latest.get("source"))],
                             _d(sec["value"]) - _d(lf["closing_stock"]),
                             tolerance(policy, sec["value"], lf["closing_stock"])[1]))
    return out


def basis(selected: list[dict]) -> list[dict]:
    """The latest annual period (and the prior one, used for year-on-year) rest on unaudited figures."""
    out = []
    yrs = fin.annual(selected)
    for s in yrs[-2:]:
        if s["basis"] != "audited":
            out.append(_item("basis", "BLOCK", s["period_end"], None,
                             f"{s['period_end']}: measures use {fin.BASIS_LABEL.get(s['basis'], s['basis'])}, not audited accounts",
                             [{"label": "basis", "value": s["basis"], "source": s.get("source")}], None, None,
                             "obtain audited accounts, or record why the unaudited figures are acceptable"))
    for s in selected:
        if not fin.is_annual(s):
            out.append(_item("basis", "ADVISORY", s["period_end"], None,
                             f"{s['period_end']}: interim {s.get('period_months')}-month "
                             f"{fin.BASIS_LABEL.get(s['basis'], s['basis'])} are shown but not used in the ratios",
                             [{"label": "basis", "value": s["basis"], "source": s.get("source")}], None, None,
                             "none: shown for information"))
    return out


def subtotals(state: dict) -> list[dict]:
    out = []
    for t in state.get("tieouts") or []:
        if not t.get("ok"):
            out.append(_item("subtotal", "BLOCK", t.get("period"), t.get("label"),
                             f"{t.get('label')}: the lines do not add up to the stated total "
                             f"({t.get('doc_id')} {t.get('table_id')} column {t.get('column')})",
                             [_v("stated total", t["total"], t.get("total_ref")),
                              _v("sum of lines", t["sum"], ", ".join(t.get("component_refs") or []))],
                             _d(t["total"]) - _d(t["sum"]), t.get("tolerance")))
    return out


# ---------------- all together ----------------
def run(state: dict, policy: Policy) -> list[dict]:
    """Every reconciliation item for the case, with any recorded explanation attached."""
    vers = state.get("financial_statement_versions") or []
    selected = fin.select(vers, policy) if vers else (state.get("financial_statements") or [])
    items = []
    for s in selected:
        if s.get("period_end"):
            items += tieouts(s, policy)
    items += subtotals(state)
    items += continuity([s for s in selected if s.get("period_end")], policy)
    items += versions(vers, policy)
    items += cross_documents(state, [s for s in selected if s.get("period_end")], policy)
    if vers:
        items += basis(selected)
    expl = {e["key"]: e for e in state.get("difference_explanations") or []}
    seen, out = set(), []
    for it in items:
        if it["key"] in seen:
            continue
        seen.add(it["key"])
        out.append({**it, "explained": expl.get(it["key"])})
    return out


def _months(a: str, b: str) -> int:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    return (db.year - da.year) * 12 + db.month - da.month


def _close_dates(a: str, b: str, window) -> bool | None:
    """Whether two dates are within the policy window. None when the window is not configured."""
    if window is NOT_CONFIGURED:
        return None
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days) <= int(window)
    except ValueError:
        return False
