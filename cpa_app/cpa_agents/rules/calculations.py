"""CALC-001..014 (BA pack section N). Decimal arithmetic; round half up at the stated precision,
on the final output only. Edge rules return labelled results instead of numbers. Definitions are
the BA pack's standard formulations, flagged for confirmation against Credit policy (OQ-04, OQ-09)."""
import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .policy import NOT_CONFIGURED

NOT_CALCULABLE = "not calculable"


@dataclass
class Result:
    calc: str
    value: Any                       # number (float/int), ISO date, or None when not calculable
    display: str                     # e.g. "1.50x", "80.00%", "not calculable"
    flags: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"calc": self.calc, "value": self.value, "display": self.display,
                "flags": list(self.flags), **({"detail": self.detail} if self.detail else {})}


def D(x) -> Decimal:
    if x is None:
        raise ValueError("input missing")
    return x if isinstance(x, Decimal) else Decimal(str(x))


def q(x: Decimal, dp: int) -> Decimal:
    return x.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)


def _num(x: Decimal, dp: int):
    v = q(x, dp)
    return int(v) if dp == 0 else float(v)


def _fmt_amount(x: Decimal) -> str:
    return f"{q(x, 0):,.0f}"


def _labelled(calc: str, label: str, flags=None) -> Result:
    return Result(calc, None, label, list(flags or []))


# ---------------- ratios and percentages ----------------
def gearing(total_borrowings, net_worth) -> Result:                       # CALC-001
    tb, nw = D(total_borrowings), D(net_worth)
    if nw <= 0:
        return _labelled("CALC-001", "not meaningful - net worth not positive")
    v = tb / nw
    return Result("CALC-001", _num(v, 2), f"{q(v, 2)}x")


def current_ratio(current_assets, current_liabilities) -> Result:         # CALC-002
    ca, cl = D(current_assets), D(current_liabilities)
    if cl == 0:
        return _labelled("CALC-002", NOT_CALCULABLE)
    v = ca / cl
    return Result("CALC-002", _num(v, 2), f"{q(v, 2)}")


def interest_cover(ebit, interest_charge) -> Result:                      # CALC-003
    e, ic = D(ebit), D(interest_charge)
    if ic == 0:
        return _labelled("CALC-003", "not calculable - no interest charge")
    v = e / ic
    return Result("CALC-003", _num(v, 2), f"{q(v, 2)}x", ["negative EBIT"] if e < 0 else [])


def net_profit_margin(net_profit, turnover) -> Result:                    # CALC-004
    np_, t = D(net_profit), D(turnover)
    if t == 0:
        return _labelled("CALC-004", NOT_CALCULABLE)
    v = np_ / t * 100
    return Result("CALC-004", _num(v, 2), f"{q(v, 2)}%", ["loss"] if np_ < 0 else [])


def year_on_year_change(current, prior, same_period_length: bool = True) -> Result:   # CALC-005
    v1, v0 = D(current), D(prior)
    flags = [] if same_period_length else ["periods differ in length"]
    if v0 == 0:
        return _labelled("CALC-005", NOT_CALCULABLE, flags)
    v = (v1 - v0) / abs(v0) * 100
    return Result("CALC-005", _num(v, 2), f"{q(v, 2)}%", flags)


def utilisation_headroom(drawn, limit) -> Result:                         # CALC-006
    dr, lm = D(drawn), D(limit)
    if lm == 0:
        return _labelled("CALC-006", NOT_CALCULABLE)
    u, h = dr / lm * 100, lm - dr
    return Result("CALC-006", _num(u, 2), f"{q(u, 2)}% utilised; headroom {_fmt_amount(h)}",
                  ["limit breach"] if dr > lm else [], {"headroom": _num(h, 0)})


def cashflow_reconciliation(opening, inflows, outflows, reported_closing, tolerance=NOT_CONFIGURED) -> Result:  # CALC-007
    calc_close = D(opening) + D(inflows) - D(outflows)
    diff = D(reported_closing) - calc_close
    tol = Decimal(0) if tolerance is NOT_CONFIGURED else D(tolerance)
    ok = abs(diff) <= tol
    flags = [] if ok else ["data quality: cashflow does not reconcile (REQ-044)"]
    if tolerance is NOT_CONFIGURED and diff != 0:
        flags.append("tolerance NOT CONFIGURED (any difference flags)")
    status = "reconciled" if ok else "not reconciled"
    return Result("CALC-007", _num(diff, 0),
                  f"Calculated closing {_fmt_amount(calc_close)}; difference {_fmt_amount(diff)} - {status}",
                  flags, {"calculated_closing": _num(calc_close, 0)})


def security_cover(security_value, exposure, valuation_basis: str | None = None,
                   valuation_date: str | None = None) -> Result:            # CALC-008
    sv, ex = D(security_value), D(exposure)
    flags = []
    if not valuation_basis or not valuation_date:
        flags.append("valuation basis and date not recorded (REQ-015)")
    if ex == 0:
        return _labelled("CALC-008", NOT_CALCULABLE, flags)
    v = sv / ex
    return Result("CALC-008", _num(v, 2), f"{q(v, 2)}x", flags + ["haircut rules NOT CONFIGURED (OQ-09)"])


def stock_days(opening_stock, closing_stock, cost_of_sales) -> Result:    # CALC-009
    avg = (D(opening_stock) + D(closing_stock)) / 2
    cos = D(cost_of_sales)
    if cos == 0:
        return _labelled("CALC-009", NOT_CALCULABLE)
    v = avg / cos * 365
    return Result("CALC-009", _num(v, 2), f"Average stock {_fmt_amount(avg)}; {q(v, 2)} days",
                  ["proposed measure: confirm with SME (OQ-09)"], {"average_stock": _num(avg, 0)})


def rote(net_profit_attributable, opening_tangible_equity, closing_tangible_equity) -> Result:  # CALC-010
    avg = (D(opening_tangible_equity) + D(closing_tangible_equity)) / 2
    if avg <= 0:
        return _labelled("CALC-010", "not meaningful", ["definition open (OQ-04)"])
    v = D(net_profit_attributable) / avg * 100
    return Result("CALC-010", _num(v, 2), f"Average tangible equity {_fmt_amount(avg)}; {q(v, 2)}%",
                  ["definition open (OQ-04)"], {"average_tangible_equity": _num(avg, 0)})


def pack_completeness(completed_mandatory: int, applicable_mandatory: int) -> Result:   # CALC-011
    cm, am = D(completed_mandatory), D(applicable_mandatory)
    if am == 0:
        return _labelled("CALC-011", NOT_CALCULABLE, ["blocks"])
    v = cm / am * 100
    return Result("CALC-011", _num(v, 2), f"{q(v, 2)}%", [] if q(v, 2) >= 100 else ["blocks"])


# ---------------- dates and effort ----------------
def next_review_date(last_review: str, cadence_months) -> Result:         # CALC-012
    if cadence_months is NOT_CONFIGURED or cadence_months is None:
        return _labelled("CALC-012", "cadence NOT CONFIGURED (DT-4, OQ-05)")
    n = int(cadence_months)
    lr = date.fromisoformat(last_review)
    total = lr.month - 1 + n
    y, m = lr.year + total // 12, total % 12 + 1
    d = min(lr.day, calendar.monthrange(y, m)[1])
    nd = date(y, m, d).isoformat()
    return Result("CALC-012", nd, nd)


def effort_against_reference(stage_minutes: dict, reference_minutes=90) -> Result:   # CALC-013
    total = sum(D(v) for v in stage_minutes.values())
    rf = D(reference_minutes)
    var = total - rf
    pct = var / rf * 100
    sign = "+" if var >= 0 else "-"
    return Result("CALC-013", _num(total, 0),
                  f"Total {q(total, 0)} min; variance vs {q(rf, 0)}-minute indicative reference "
                  f"{sign}{abs(q(var, 0))} min ({q(pct, 2)}%)",
                  ["indicative reference, not validated MI (DS-5)"],
                  {"variance_min": _num(var, 0), "variance_pct": _num(pct, 2)})


def information_age(as_at: str, information_date: str | None, validity_days=NOT_CONFIGURED) -> Result:  # CALC-014
    if not information_date:
        return Result("CALC-014", None, "no date; STALE", ["stale"], {"stale": True})
    age = (date.fromisoformat(as_at) - date.fromisoformat(information_date[:10])).days
    if validity_days is NOT_CONFIGURED or validity_days is None:
        return Result("CALC-014", age, f"Age {age} days; validity NOT CONFIGURED (OQ-06)",
                      ["validity NOT CONFIGURED"], {"stale": None})
    stale = age > int(validity_days)
    return Result("CALC-014", age, f"Age {age} days; {'STALE' if stale else 'current'}",
                  ["stale"] if stale else [], {"stale": stale})
