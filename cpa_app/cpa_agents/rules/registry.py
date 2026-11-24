"""Registry comparison (REQ-020/021, BR-D01) and ownership reconciliation (REQ-022, BR-D10).
Discrepancies are reported for the case owner to resolve; nothing here resolves them."""
import re
from decimal import Decimal

from .policy import NOT_CONFIGURED, Policy

_SUFFIX = re.compile(r"\b(limited|ltd|plc|llp)\.?$")


def norm_name(s: str) -> str:
    s = re.sub(r"[^\w\s&]", " ", (s or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    return _SUFFIX.sub("ltd", s).strip()


def compare_entity(supplied: dict, registry: dict) -> list[dict]:
    """Compare supplied entity fields with the registry record. Only fields present on both sides
    are compared; a field missing from the registry record is itself a discrepancy."""
    out = []
    for f in ("name", "registered_number", "registered_address", "legal_form"):
        a, b = supplied.get(f), registry.get(f)
        if a is None:
            continue
        if b is None:
            out.append({"field": f, "supplied": a, "registry": None, "issue": "not in registry record"})
        elif (norm_name(a) if f in ("name", "legal_form", "registered_address") else str(a).strip().upper()) != \
             (norm_name(b) if f in ("name", "legal_form", "registered_address") else str(b).strip().upper()):
            out.append({"field": f, "supplied": a, "registry": b, "issue": "differs"})
    return out


def compare_people(role: str, supplied: list[str], registry: list[str]) -> list[dict]:
    """Directors or shareholders: who was supplied but is not on the register, and vice versa."""
    s = {norm_name(x): x for x in supplied or []}
    r = {norm_name(x): x for x in registry or []}
    out = [{"field": role, "supplied": s[k], "registry": None, "issue": "supplied but not on registry"}
           for k in s if k not in r]
    out += [{"field": role, "supplied": None, "registry": r[k], "issue": "on registry but not supplied"}
            for k in r if k not in s]
    return out


def reconcile_ownership(shareholders: list[dict], policy: Policy) -> dict:
    """BR-D10: percentages must be shown and sum to 100 within the policy tolerance (percentage
    points). With no tolerance configured, any gap from 100 is flagged."""
    missing = [s.get("name") for s in shareholders if s.get("pct") is None]
    total = sum(Decimal(str(s["pct"])) for s in shareholders if s.get("pct") is not None)
    tol = policy.get("tolerances.ownership_percentage_points")
    tol_d = Decimal(0) if tol is NOT_CONFIGURED else Decimal(str(tol))
    gap = abs(Decimal(100) - total)
    issues = [f"ownership percentage missing for {m}" for m in missing]
    if gap > tol_d:
        issues.append(f"ownership totals {total}% (gap {gap} pts exceeds tolerance "
                      f"{'NOT CONFIGURED' if tol is NOT_CONFIGURED else tol})")
    return {"total_pct": float(total), "gap_pts": float(gap), "reconciled": not issues,
            "issues": issues, "policy_version": policy.version}


def compare_all(supplied: dict, registry: dict, policy: Policy) -> dict:
    """Full comparison: entity fields, directors, shareholders, ownership percentages."""
    disc = compare_entity(supplied.get("entity", {}), registry.get("entity", {}))
    disc += compare_people("director", supplied.get("directors", []), registry.get("directors", []))
    disc += compare_people("shareholder", [s["name"] for s in supplied.get("shareholders", [])],
                           [s["name"] for s in registry.get("shareholders", [])])
    own = reconcile_ownership(supplied.get("shareholders", []), policy)
    return {"discrepancies": disc, "ownership": own, "matches": not disc and own["reconciled"]}
