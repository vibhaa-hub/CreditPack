"""Every BA pack section N worked example reproduced exactly, plus each edge rule."""
from cpa_agents.rules import calculations as c
from cpa_agents.rules.policy import NOT_CONFIGURED


# ---------- worked examples (exact output column) ----------
def test_calc_001_gearing():
    assert c.gearing(4_500_000, 3_000_000).display == "1.50x"


def test_calc_002_current_ratio():
    assert c.current_ratio(6_200_000, 4_000_000).display == "1.55"


def test_calc_003_interest_cover():
    assert c.interest_cover(900_000, 300_000).display == "3.00x"


def test_calc_004_net_profit_margin():
    assert c.net_profit_margin(450_000, 15_000_000).display == "3.00%"


def test_calc_005_year_on_year():
    assert c.year_on_year_change(15_000_000, 13_500_000).display == "11.11%"


def test_calc_006_utilisation_headroom():
    r = c.utilisation_headroom(3_600_000, 4_500_000)
    assert r.display == "80.00% utilised; headroom 900,000" and r.detail["headroom"] == 900_000


def test_calc_007_cashflow():
    r = c.cashflow_reconciliation(250_000, 1_800_000, 1_650_000, 400_000)
    assert r.display == "Calculated closing 400,000; difference 0 - reconciled" and r.flags == []


def test_calc_008_security_cover():
    assert c.security_cover(5_200_000, 4_000_000, "desktop valuation", "2026-10-01").display == "1.30x"


def test_calc_009_stock_days():
    assert c.stock_days(2_300_000, 2_500_000, 12_000_000).display == "Average stock 2,400,000; 73.00 days"


def test_calc_010_rote():
    assert c.rote(120_000, 950_000, 1_050_000).display == "Average tangible equity 1,000,000; 12.00%"


def test_calc_011_completeness():
    r = c.pack_completeness(42, 48)
    assert r.display == "87.50%" and "blocks" in r.flags


def test_calc_012_next_review():
    assert c.next_review_date("2026-08-31", 3).display == "2026-11-30"


def test_calc_013_effort():
    r = c.effort_against_reference({"intake": 8, "information": 28, "checks": 22, "analysis": 18,
                                    "authoring": 14, "submission": 6})
    assert r.display == "Total 96 min; variance vs 90-minute indicative reference +6 min (6.67%)"


def test_calc_014_staleness():
    assert c.information_age("2026-10-23", "2026-07-01", 90).display == "Age 114 days; STALE"


# ---------- edge rules ----------
def test_edge_rules_return_labels_not_numbers():
    assert c.gearing(1, 0).display == "not meaningful - net worth not positive"
    assert c.gearing(1, -5).value is None
    assert c.current_ratio(1, 0).display == "not calculable"
    assert c.interest_cover(1, 0).display == "not calculable - no interest charge"
    assert c.net_profit_margin(1, 0).display == "not calculable"
    assert c.year_on_year_change(1, 0).display == "not calculable"
    assert c.utilisation_headroom(1, 0).display == "not calculable"
    assert c.security_cover(1, 0, "b", "d").display == "not calculable"
    assert c.stock_days(1, 1, 0).display == "not calculable"
    assert c.rote(1, 0, 0).display == "not meaningful"
    assert c.pack_completeness(0, 0).display == "not calculable"


def test_edge_negative_and_breach_flags():
    r = c.interest_cover(-300_000, 300_000)
    assert r.display == "-1.00x" and "negative EBIT" in r.flags
    assert c.net_profit_margin(-150_000, 15_000_000).display == "-1.00%"
    br = c.utilisation_headroom(5_000_000, 4_500_000)
    assert br.display.startswith("111.11% utilised; headroom -500,000") and "limit breach" in br.flags
    assert "periods differ in length" in c.year_on_year_change(2, 1, same_period_length=False).flags
    assert c.year_on_year_change(-50, -100).display == "50.00%"     # divides by |V0|


def test_edge_cashflow_difference_and_tolerance():
    r = c.cashflow_reconciliation(250_000, 1_800_000, 1_650_000, 401_000)
    assert "not reconciled" in r.display and any("REQ-044" in f for f in r.flags)
    assert c.cashflow_reconciliation(250_000, 1_800_000, 1_650_000, 401_000, tolerance=5_000).flags == []


def test_edge_security_without_valuation_basis():
    assert any("REQ-015" in f for f in c.security_cover(5_200_000, 4_000_000).flags)


def test_edge_completeness_100_does_not_block():
    assert c.pack_completeness(48, 48).flags == []


def test_edge_review_month_end_and_unset_cadence():
    assert c.next_review_date("2026-01-31", 1).display == "2026-02-28"
    assert c.next_review_date("2027-11-30", 3).display == "2028-02-29"     # leap year
    assert c.next_review_date("2026-10-31", 12).display == "2027-10-31"
    assert "NOT CONFIGURED" in c.next_review_date("2026-08-31", NOT_CONFIGURED).display


def test_edge_undated_information_is_stale_and_unset_validity():
    assert c.information_age("2026-10-23", None, 90).detail["stale"] is True
    r = c.information_age("2026-10-23", "2026-07-01")
    assert r.value == 114 and r.detail["stale"] is None and "NOT CONFIGURED" in r.display
    assert c.information_age("2026-10-23", "2026-10-01", 90).detail["stale"] is False


def test_rounding_is_half_up_on_final_output_only():
    assert c.current_ratio(1.005, 1).display == "1.01"          # half up, not banker's
    assert c.current_ratio(2, 3).display == "0.67"
