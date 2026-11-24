import pytest

from workbench import users as u
from workbench.permissions import ACTIONS, can

AM = {"username": "jsmith", "display_name": "Jane Smith", "roles": ["account_manager"]}
AM2 = {"username": "bjones", "display_name": "Bob Jones", "roles": ["account_manager"]}
FC = {"username": "a7", "display_name": "Analyst Seven", "roles": ["financial_crime_analyst"]}
PA = {"username": "pc2", "display_name": "Pricing Committee", "roles": ["pricing_authority"]}
UW = {"username": "uw3", "display_name": "Credit Underwriter", "roles": ["credit_underwriter"]}
CASE = {"owner": "Jane Smith", "lending_request": {"preparer": "Jane Smith"}}


# ---------- 1.1 users ----------
def test_hash_and_verify():
    h = u.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and u.verify_password("correct horse battery", h)
    assert not u.verify_password("wrong", h) and not u.verify_password("x", "garbage")
    assert u.hash_password("same password!") != u.hash_password("same password!")       # per-user salt


def test_add_authenticate_disable(store):
    u.add_user("jsmith", "Jane Smith", ["account_manager"], "a long password")
    assert u.authenticate("jsmith", "a long password") == AM
    assert u.authenticate("jsmith", "nope") is None and u.authenticate("ghost", "a long password") is None
    u.set_active("jsmith", False)
    assert u.authenticate("jsmith", "a long password") is None
    with pytest.raises(ValueError):
        u.add_user("jsmith", "Again", ["account_manager"], "a long password")
    with pytest.raises(ValueError):
        u.add_user("x", "X", ["wizard"], "a long password")
    with pytest.raises(ValueError):
        u.add_user("y", "Y", ["auditor"], "short")


def test_cli_round_trip(store, db_url, capsys, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    assert u.main(["add", "pc2", "--name", "Pricing Committee", "--role", "pricing_authority",
                   "--password", "pricing pass 1"]) == 0
    u.main(["list"])
    assert "pc2" in capsys.readouterr().out
    u.main(["disable", "pc2"])
    assert u.list_users()[0]["active"] is False


def test_actor_label():
    assert u.actor(AM, "account_manager") == "Jane Smith (jsmith, account_manager)"


# ---------- 1.2 permissions ----------
@pytest.mark.parametrize("action,roles", list(ACTIONS.items()))
def test_each_action_allows_only_its_roles(action, roles):
    for role in roles:
        user = {"username": "x", "display_name": "Jane Smith", "roles": [role]}
        if role == "credit_underwriter" and action in ("view_case", "view_audit", "raise_query", "record_outcome"):
            assert can(user, action, CASE)
        elif action == "authorise_pricing":
            assert can({**user, "display_name": "Someone Else"}, action, CASE)
        elif role != "credit_underwriter":
            assert can(user, action, CASE), (action, role)
    outsider = {"username": "o", "display_name": "O", "roles": [r for r in ("auditor",) if r not in roles]}
    if outsider["roles"]:
        d = can(outsider, action, CASE)
        assert not d and d.reason and d.action


def test_only_owner_authorises_submission():
    assert can(AM, "authorise_submission", CASE)
    d = can(AM2, "authorise_submission", CASE)
    assert not d and "BR-E01" in d.reason


def test_preparer_cannot_authorise_pricing():
    prep = {"username": "js", "display_name": "Jane Smith", "roles": ["pricing_authority"]}
    assert "BR-E02" in can(prep, "authorise_pricing", CASE).reason and can(PA, "authorise_pricing", CASE)


def test_underwriter_cannot_edit_pack_even_with_owner_role():
    both = {**UW, "roles": ["credit_underwriter", "account_manager"]}
    d = can(both, "review_section", CASE)
    assert not d and "REQ-088" in d.reason
    assert can(UW, "raise_query", CASE) and can(UW, "record_outcome", CASE)


def test_hit_disposition_role_and_not_signed_in():
    assert can(FC, "disposition_hit") and not can(AM, "disposition_hit")
    assert can(None, "view_case").reason == "not signed in"


def test_owner_recorded_with_role_in_brackets_still_matches():
    case = {"owner": "Jane Smith (Account Manager)", "lending_request": {"preparer": "Jane Smith (Account Manager)"}}
    assert can(AM, "authorise_submission", case) and not can(AM2, "authorise_submission", case)
    prep = {"username": "js", "display_name": "Jane Smith", "roles": ["pricing_authority"]}
    assert "BR-E02" in can(prep, "authorise_pricing", case).reason
