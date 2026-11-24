"""Financial statement versions and selection (REQ-038, REQ-044, BR-D04).

Every version of a period's figures is kept: audited accounts, unaudited statutory accounts,
management accounts and figures the dealer states (for example on the application form). Nothing
overwrites anything else. For each period the analysis uses the version whose basis ranks highest in
the policy's `financial_basis_precedence`; ties go to the most recently recorded. The selection, its
basis and the alternatives are recorded so the pack can say what the measures rest on.

Amount parsing is here too, so figures read from table cells and iXBRL facts follow one set of rules."""
import re
from decimal import Decimal, InvalidOperation

from .policy import NOT_CONFIGURED, Policy

BASES = ("audited", "unaudited_accounts", "management", "dealer_stated")
BASIS_LABEL = {"audited": "audited accounts", "unaudited_accounts": "unaudited accounts",
               "management": "management accounts", "dealer_stated": "dealer-stated figures"}
UNITS = {"units": 1, "thousands": 1_000, "millions": 1_000_000}

# Standard credit analysis fields (REQ-038). The first block feeds CALC-001..010; the second block
# exists so statements can be tied out (rules.reconcile): totals, subtotals and the equity roll.
FIN_FIELDS = ("turnover", "cost_of_sales", "net_profit", "ebit", "interest_charge", "total_borrowings",
              "net_worth", "current_assets", "current_liabilities", "opening_cash", "inflows", "outflows",
              "closing_cash", "opening_stock", "closing_stock", "tangible_equity", "net_profit_attributable",
              "gross_profit", "fixed_assets", "total_assets", "total_liabilities", "long_term_liabilities",
              "dividends")


def precedence(policy: Policy) -> list[str] | None:
    p = policy.get("financial_basis_precedence")
    return list(p) if p is not NOT_CONFIGURED else None


def rank(basis: str, order: list[str] | None) -> int:
    """Lower is better. Unknown bases rank after every listed one."""
    if not order:
        return 0
    return order.index(basis) if basis in order else len(order)


def is_annual(stmt: dict) -> bool:
    return int(stmt.get("period_months") or 12) == 12


def version_id(period_end: str, basis: str, source: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (source or "").lower()).strip("-")[:40]
    return f"{period_end}/{basis}/{slug}"


def upsert_version(versions: list[dict], new: dict) -> list[dict]:
    """Add a version. Recording the same period, basis and source again replaces that one version
    (a re-run of the same document); any other version is kept."""
    out = [v for v in versions if v["id"] != new["id"]]
    out.append(new)
    return sorted(out, key=lambda v: (v["period_end"], v.get("recorded_at") or ""))


def select(versions: list[dict], policy: Policy) -> list[dict]:
    """One statement per period end: the best-ranked basis, then the most recently recorded.
    Returned in the shape downstream code has always read, plus `basis`, `version_id`,
    `alternatives` (the other versions' ids) and `selection` (why this one)."""
    order = precedence(policy)
    by_period: dict[str, list[dict]] = {}
    for v in versions:
        by_period.setdefault(v["period_end"], []).append(v)
    out = []
    for period in sorted(by_period):
        cands = sorted(by_period[period], key=lambda v: v.get("recorded_at") or "", reverse=True)
        cands.sort(key=lambda v: rank(v["basis"], order))          # stable: latest first within a basis
        best = cands[0]
        why = ("only version" if len(cands) == 1 else
               f"{BASIS_LABEL.get(best['basis'], best['basis'])} ranks first under the policy precedence"
               if order else "most recently recorded (basis precedence NOT CONFIGURED)")
        out.append({**{k: best[k] for k in ("period_end", "currency", "source", "figures", "recorded_at")},
                    "audited": best["basis"] == "audited", "basis": best["basis"],
                    "period_months": int(best.get("period_months") or 12), "version_id": best["id"],
                    "doc_id": best.get("doc_id"), "refs": best.get("refs") or {},
                    "alternatives": [c["id"] for c in cands[1:]], "selection": why})
    return out


def annual(selected: list[dict]) -> list[dict]:
    return [s for s in selected if is_annual(s)]


# ---------------- amounts ----------------
_DASHES = {"-", "–", "—", "nil", "Nil", "NIL"}


def parse_amount(value) -> Decimal | None:
    """A money amount as written in accounts: 1,234 · (1,234) negative · £1,234 · -1234 · '-' nil.
    Returns None when the cell holds no number (text, blank)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    s = str(value).strip()
    if not s:
        return None
    if s in _DASHES:
        return Decimal(0)
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("£", "").replace("GBP", "").replace(",", "").replace(" ", "").strip()
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if neg else d


def scale(d: Decimal, units: str) -> Decimal:
    return d * UNITS[units]


def as_number(d: Decimal):
    return int(d) if d == d.to_integral_value() else float(d)
