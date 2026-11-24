"""DT-5 information validity using CALC-014 (REQ-082, BR-G05). Validity periods are policy
parameters (OQ-06); unset means the item cannot be confirmed current and is reported as a gap."""
from .calculations import information_age
from .policy import NOT_CONFIGURED, Policy

# DT-5: information class -> action when the validity period is exceeded
DT5 = {
    "registry_result": "Flag stale; refresh or authorised exception",
    "credit_reference_result": "Flag stale; refresh or authorised exception",
    "sanctions_screening": "Re-screen",
    "idv_result": "Re-perform",
    "adverse_media": "Re-perform",
    "financial_statements": "Request updated statements",
}


def assess(info_class: str, information_date: str | None, as_at: str, policy: Policy) -> dict:
    """Return age, stale (True/False/None when validity is unset) and the DT-5 action."""
    if info_class not in DT5:
        raise ValueError(f"unknown DT-5 information class: {info_class}")
    v = policy.get(f"validity_days.{info_class}")
    r = information_age(as_at, information_date, v)
    stale = r.detail.get("stale")
    return {"info_class": info_class, "age_days": r.value, "stale": stale,
            "validity_days": None if v is NOT_CONFIGURED else v,
            "configured": v is not NOT_CONFIGURED,
            "action": DT5[info_class] if stale else None,
            "display": r.display, "policy_version": policy.version}
