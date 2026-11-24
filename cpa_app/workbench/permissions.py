"""Who may do what (design decision 3). Checked on the server for every action; a refusal carries
the reason and the corrective action (BR-U04) and is audited as access_denied (REQ-084)."""
from dataclasses import dataclass

ROLES = {
    "account_manager": "Account Manager",
    "wholesale_manager": "Wholesale Manager",
    "financial_crime_analyst": "Financial Crime Analyst",
    "onboarding_analyst": "Onboarding Analyst",
    "pricing_authority": "Pricing Authority",
    "credit_manager": "Credit Manager (exceptions)",
    "credit_underwriter": "Credit Underwriter",
    "operations": "Operations",
    "auditor": "Auditor",
}
CASE_OWNERS = ("account_manager", "wholesale_manager")

# action -> roles allowed
ACTIONS = {
    "create_case": CASE_OWNERS,
    "upload_document": CASE_OWNERS,
    "run_preparation": CASE_OWNERS,
    "add_note": CASE_OWNERS,
    "resolve_discrepancy": CASE_OWNERS,
    "explain_difference": CASE_OWNERS,
    "review_section": CASE_OWNERS,
    "authorise_submission": CASE_OWNERS,
    "run_submission": CASE_OWNERS,
    "disposition_hit": ("financial_crime_analyst",),
    "record_cra": ("onboarding_analyst", "financial_crime_analyst"),
    "record_manual_check": ("onboarding_analyst", "financial_crime_analyst"),
    "authorise_pricing": ("pricing_authority",),
    "authorise_exception": ("pricing_authority", "financial_crime_analyst", "credit_manager"),
    "raise_query": ("credit_underwriter",),
    "record_outcome": ("credit_underwriter",),
    "resolve_query": CASE_OWNERS,
    "run_post_approval": CASE_OWNERS + ("operations",),
    "update_handoff": ("operations",),
    "view_case": tuple(ROLES),
    "view_audit": tuple(ROLES),
}
# actions that change the pack's content: Credit must stay independent of preparation (REQ-088)
PACK_EDITS = {"create_case", "upload_document", "run_preparation", "add_note", "resolve_discrepancy", "explain_difference",
              "review_section", "authorise_submission", "run_submission", "record_manual_check",
              "authorise_pricing", "authorise_exception", "resolve_query"}


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    action: str = ""
    role: str | None = None        # the role the user acts in

    def __bool__(self):
        return self.allowed


def _name(user: dict) -> str:
    return _person(user.get("display_name"))


def _person(name: str | None) -> str:
    """'Jane Smith (Account Manager)' and 'jane smith' are the same person; the agent may record
    the owner with a role in brackets."""
    return (name or "").split("(")[0].strip().lower()


def can(user: dict | None, action: str, case: dict | None = None) -> Decision:
    if not user:
        return Decision(False, "not signed in", "sign in")
    if action not in ACTIONS:
        return Decision(False, f"unknown action {action}", "contact support")
    held = [r for r in user.get("roles", []) if r in ACTIONS[action]]
    if not held:
        need = ", ".join(ROLES[r] for r in ACTIONS[action])
        return Decision(False, f"{action.replace('_', ' ')} needs the role: {need}",
                        "ask a user with that role to act")
    if action in PACK_EDITS and "credit_underwriter" in user.get("roles", []):
        return Decision(False, "Credit cannot prepare or edit the pack (REQ-088)",
                        "a case owner or authorised role must act")
    case = case or {}
    if action == "authorise_submission":
        owner = _person(case.get("owner"))
        if owner and _name(user) != owner:
            return Decision(False, f"only the accountable owner {case.get('owner')} may authorise submission (BR-E01)",
                            f"ask {case.get('owner')} to authorise, or reassign the case")
    if action == "authorise_pricing":
        preparer = _person((case.get("lending_request") or {}).get("preparer"))
        if preparer and _name(user) == preparer:
            return Decision(False, "the preparer cannot authorise their own pricing and terms (BR-E02)",
                            "ask another pricing authority")
    return Decision(True, role=held[0])
