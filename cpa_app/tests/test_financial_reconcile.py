"""Statement versions (never overwritten), selection by basis precedence, and the deterministic
reconciliation checks that feed DT-2 R5."""
import pytest

from cpa_agents import tools as t
from cpa_agents.rules import financials as fin
from cpa_agents.rules import reconcile as rec
from cpa_agents.rules.gate import evaluate
from cpa_agents.rules.policy import from_dict
from conftest import fake_ctx

POLICY = from_dict({"version": "t", "financial_basis_precedence": ["audited", "unaudited_accounts", "management",
                                                                   "dealer_stated"]})


@pytest.fixture
def case(store):
    ctx = fake_ctx(session_id="fr-1", agent="document_ingestion")
    t.register_case("Acme Motors Ltd", "01234567", ["increased borrowing request"], "OEM partner", "Jane Smith", ctx)
    t.get_requirement_checklist(ctx)
    return ctx


def kinds(items, severity=None):
    return sorted(i["kind"] for i in items if severity is None or i["severity"] == severity)


# ---------- versions and selection ----------
def test_management_accounts_do_not_overwrite_audited_in_either_order(case):
    t.record_financial_statement("2025-12-31", True, "GBP", "FY2025 audited", case, net_profit=310_000)
    r = t.record_financial_statement("2025-12-31", False, "GBP", "FY2025 MI", case, basis="management", net_profit=355_000)
    assert len(r["versions_for_period"]) == 2 and r["used_for_period"].endswith("/audited/fy2025-audited")
    st = case.state
    assert [s["figures"]["net_profit"] for s in st["financial_statements"]] == [310_000]
    assert st["financial_statements"][0]["basis"] == "audited" and st["financial_statements"][0]["alternatives"]

    ctx = fake_ctx(session_id="fr-2", agent="document_ingestion")
    t.register_case("Acme Motors Ltd", "01234567", ["increased borrowing request"], "OEM partner", "Jane Smith", ctx)
    t.record_financial_statement("2025-12-31", False, "GBP", "FY2025 MI", ctx, basis="management", net_profit=355_000)
    t.record_financial_statement("2025-12-31", True, "GBP", "FY2025 audited", ctx, net_profit=310_000)
    assert ctx.state["financial_statements"][0]["figures"]["net_profit"] == 310_000


def test_same_source_rerecorded_replaces_only_itself(case):
    t.record_financial_statement("2025-12-31", True, "GBP", "FY2025 audited", case, net_profit=1)
    t.record_financial_statement("2025-12-31", True, "GBP", "FY2025 audited", case, net_profit=2)
    assert [v["figures"]["net_profit"] for v in case.state["financial_statement_versions"]] == [2]


def test_units_brackets_basis_and_interim(case):
    r = t.record_financial_statement("2025-12-31", True, "GBP", "acc", case, units="thousands", net_profit="(45)")
    assert case.state["financial_statements"][0]["figures"]["net_profit"] == -45_000 and r["status"] == "ok"
    assert t.record_financial_statement("2025-12-31", True, "GBP", "acc", case, basis="guess")["status"] == "error"
    assert t.record_financial_statement("2025-12-31", True, "GBP", "acc", case, units="£000")["status"] == "error"
    t.record_financial_statement("2026-09-30", False, "GBP", "YTD MI", case, basis="management", period_months=9,
                                 turnover=9_000_000)
    flags = [f["flag"] for f in t.financial_quality_flags(case)["flags"]]
    assert any("interim 9-month" in f for f in flags)
    t.calculate_measures(case)
    assert case.state["measures_basis"]["latest"]["period_end"] == "2025-12-31"      # interim not used in ratios


def test_precedence_not_configured_uses_latest_and_flags():
    vs = [dict(id="a", period_end="2025-12-31", basis="audited", currency="GBP", source="a", figures={}, recorded_at="1"),
          dict(id="b", period_end="2025-12-31", basis="management", currency="GBP", source="b", figures={}, recorded_at="2")]
    sel = fin.select(vs, from_dict({"version": "t"}))
    assert sel[0]["version_id"] == "b" and "NOT CONFIGURED" in sel[0]["selection"]
    assert fin.select(vs, POLICY)[0]["version_id"] == "a"


def test_parse_amount_forms():
    P = fin.parse_amount
    assert P("1,234") == 1234 and P("(1,234)") == -1234 and P("£2,500") == 2500 and P("-") == 0
    assert P("Turnover") is None and P(None) is None and P(12.5) == fin.Decimal("12.5")


# ---------- reconciliation ----------
def _stmt(period, basis="audited", source="acc", months=12, **f):
    return dict(id=fin.version_id(period, basis, source), period_end=period, basis=basis, currency="GBP", source=source,
                period_months=months, figures=f, recorded_at=period)


def test_tieouts_within_a_statement():
    st = {"financial_statement_versions": [_stmt("2025-12-31", turnover=100, cost_of_sales=60, gross_profit=45,
                                                 fixed_assets=10, current_assets=20, total_assets=30,
                                                 current_liabilities=5, long_term_liabilities=5, net_worth=21,
                                                 opening_cash=1, inflows=10, outflows=5, closing_cash=7,
                                                 closing_stock=25)]}
    items = rec.run(st, POLICY)
    fields = sorted(i["field"] for i in items if i["kind"] == "tieout")
    assert fields == ["closing_cash", "closing_stock", "gross_profit", "net_worth"]
    gp = next(i for i in items if i["field"] == "gross_profit")
    assert gp["difference"] == 5 and gp["severity"] == "BLOCK" and gp["rule"] == "R5"


def test_continuity_between_years_and_equity_roll():
    st = {"financial_statement_versions": [
        _stmt("2024-12-31", closing_cash=250, closing_stock=2300, net_worth=2700),
        _stmt("2025-12-31", opening_cash=260, opening_stock=2300, net_worth=3000, net_profit=450, dividends=100)]}
    items = rec.run(st, POLICY)
    cont = [i for i in items if i["kind"] == "continuity"]
    assert [(i["field"], i["severity"]) for i in cont] == [("opening_cash", "BLOCK"), ("net_worth", "ADVISORY")]


def test_version_difference_and_tolerances():
    vs = [_stmt("2025-12-31", net_profit=310_000, turnover=21_000_000),
          _stmt("2025-12-31", "management", "MI", net_profit=355_000, turnover=21_000_000)]
    items = rec.run({"financial_statement_versions": vs}, POLICY)
    v = [i for i in items if i["kind"] == "version"]
    assert len(v) == 1 and v[0]["field"] == "net_profit" and v[0]["difference"] == -45_000
    loose = from_dict({**POLICY.data, "tolerances": {"reconciliation_pct": 20}})
    assert not [i for i in rec.run({"financial_statement_versions": vs}, loose) if i["kind"] == "version"]


def test_cross_document_checks():
    base = {"financial_statement_versions": [_stmt("2025-12-31", total_borrowings=4_000_000, closing_stock=2_500_000)],
            "lending_request": {"facility_type": "wholesale", "amount": 5_500_000, "current_limit": 4_000_000},
            "facilities": [{"lending_line": "wholesale", "drawn": 4_600_000, "limit": 4_500_000, "as_at": "2026-01-15",
                            "source": "facility statement"}],
            "security": {"description": "debenture over stock", "value": 3_000_000, "date": "2026-01-10"}}
    no_window = rec.run(base, POLICY)
    assert [(i["field"], i["severity"]) for i in no_window if i["kind"] == "cross_doc"] == [
        ("limit", "BLOCK"), ("total_borrowings", "ADVISORY")]
    windowed = from_dict({**POLICY.data, "reconciliation": {"date_window_days": 30}})
    got = [(i["field"], i["severity"]) for i in rec.run(base, windowed) if i["kind"] == "cross_doc"]
    assert got == [("limit", "BLOCK"), ("total_borrowings", "BLOCK"), ("closing_stock", "BLOCK")]


def test_basis_blocks_when_measures_rest_on_unaudited(case):
    t.record_financial_statement("2024-12-31", True, "GBP", "FY24", case, turnover=1, net_profit=1)
    t.record_financial_statement("2025-12-31", False, "GBP", "FY25 MI", case, basis="management", turnover=2,
                                 net_profit=1)
    items = rec.run(case.state, POLICY)
    assert [(i["kind"], i["period"]) for i in items if i["kind"] == "basis"] == [("basis", "2025-12-31")]
    t.calculate_measures(case)
    flags = case.state["measures_detail"]["net_margin_pct"]["flags"]
    assert any("unaudited" in f for f in flags)
    assert "2025-12-31 management accounts" in case.state["measures_detail"]["turnover_yoy_pct"]["basis"]


def test_explanation_attaches_by_key_and_lapses_when_numbers_change():
    vs = [_stmt("2025-12-31", net_profit=310_000), _stmt("2025-12-31", "management", "MI", net_profit=355_000)]
    key = rec.run({"financial_statement_versions": vs}, POLICY)[0]["key"]
    st = {"financial_statement_versions": vs,
          "difference_explanations": [{"key": key, "explanation": "MI before audit adjustments", "by": "Jane Smith"}]}
    assert rec.run(st, POLICY)[0]["explained"]["by"] == "Jane Smith"
    vs[1]["figures"]["net_profit"] = 356_000
    assert rec.run(st, POLICY)[0]["explained"] is None


def test_gate_blocks_r5_until_explained():
    vs = [_stmt("2025-12-31", net_profit=310_000), _stmt("2025-12-31", "management", "MI", net_profit=355_000)]
    st = {"checklist": {"financial": "R"}, "financial_statement_versions": vs}
    g = evaluate(st, POLICY, "2026-11-19")
    r5 = [x for x in g["gaps"] if x["rule"] == "R5"]
    assert r5 and "differs between audited accounts and management accounts" in r5[0]["reason"]
    st["difference_explanations"] = [{"key": r5[0]["item"], "explanation": "timing", "by": "Jane Smith"}]
    g = evaluate(st, POLICY, "2026-11-19")
    assert not [x for x in g["gaps"] if x["rule"] == "R5"]
    assert any(a["rule"] == "R5" and "explained by Jane Smith" in a["reason"] for a in g["advisories"])


def test_reconcile_tool_reports_and_stores(case):
    t.record_financial_statement("2025-12-31", True, "GBP", "acc", case, turnover=100, cost_of_sales=60, gross_profit=45)
    r = t.reconcile_financials(case)
    assert r["open_blocking"] == 1 and r["items"][0]["kind"] == "tieout"
    assert case.state["reconciliation"][0]["description"].startswith("2025-12-31: stated gross profit")
