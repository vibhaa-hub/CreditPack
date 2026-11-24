from cpa_agents.rules.policy import from_dict
from cpa_agents.rules.registry import compare_all, norm_name, reconcile_ownership

POL = from_dict({"version": "t", "tolerances": {"ownership_percentage_points": 0.5}})
REG = {"entity": {"name": "ACME MOTORS LIMITED", "registered_number": "01234567", "legal_form": "Private limited company"},
       "directors": ["A. Director", "B. Second"],
       "shareholders": [{"name": "A. Director", "pct": 60}, {"name": "Acme Holdings Ltd", "pct": 40}]}


def _supplied(**over):
    base = {"entity": {"name": "Acme Motors Ltd", "registered_number": "01234567"},
            "directors": ["A. Director", "B. Second"],
            "shareholders": [{"name": "A. Director", "pct": 60}, {"name": "Acme Holdings Limited", "pct": 40}]}
    base.update(over)
    return base


def test_match_after_normalising_names_and_suffixes():
    r = compare_all(_supplied(), REG, POL)
    assert r["matches"] and r["discrepancies"] == [] and r["ownership"]["total_pct"] == 100
    assert norm_name("ACME MOTORS LIMITED") == norm_name("Acme Motors Ltd.")


def test_name_mismatch():
    r = compare_all(_supplied(entity={"name": "Acme Cars Ltd", "registered_number": "01234567"}), REG, POL)
    assert r["discrepancies"] == [{"field": "name", "supplied": "Acme Cars Ltd", "registry": "ACME MOTORS LIMITED",
                                   "issue": "differs"}]


def test_missing_director():
    r = compare_all(_supplied(directors=["A. Director"]), REG, POL)
    assert r["discrepancies"] == [{"field": "director", "supplied": None, "registry": "B. Second",
                                   "issue": "on registry but not supplied"}]


def test_extra_shareholder():
    sh = [{"name": "A. Director", "pct": 50}, {"name": "Acme Holdings Ltd", "pct": 40}, {"name": "C. Investor", "pct": 10}]
    r = compare_all(_supplied(shareholders=sh), REG, POL)
    assert {"field": "shareholder", "supplied": "C. Investor", "registry": None,
            "issue": "supplied but not on registry"} in r["discrepancies"]


def test_percentages_off_tolerance_and_missing():
    r = reconcile_ownership([{"name": "A", "pct": 60}, {"name": "B", "pct": 39}], POL)
    assert not r["reconciled"] and "gap 1 pts exceeds tolerance 0.5" in r["issues"][0]
    assert reconcile_ownership([{"name": "A", "pct": 60}, {"name": "B", "pct": 39.6}], POL)["reconciled"]
    assert "missing for B" in reconcile_ownership([{"name": "A", "pct": 100}, {"name": "B"}], POL)["issues"][0]


def test_no_tolerance_configured_flags_any_gap():
    r = reconcile_ownership([{"name": "A", "pct": 99.9}], from_dict({"version": "u"}))
    assert not r["reconciled"] and "NOT CONFIGURED" in r["issues"][0]
