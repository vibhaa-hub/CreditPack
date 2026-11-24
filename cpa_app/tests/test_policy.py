from cpa_agents.rules.policy import NOT_CONFIGURED, from_dict, load_policy


def test_shipped_policy_is_all_unset():
    p = load_policy()
    assert p.version == "0.1-unset"
    for k in ("registry_result", "credit_reference_result", "sanctions_screening", "idv_result",
              "adverse_media", "financial_statements"):
        assert p.get(f"validity_days.{k}") is NOT_CONFIGURED
    assert p.get("review_cadence.set_A") is NOT_CONFIGURED
    assert p.get("tolerances.ownership_percentage_points") is NOT_CONFIGURED
    assert p.get("escalation_criteria") is NOT_CONFIGURED and not p.is_set("recency_window_days")
    assert repr(NOT_CONFIGURED) == "NOT CONFIGURED" and not NOT_CONFIGURED


def test_set_values_return_with_version(tmp_path):
    f = tmp_path / "policy.yaml"
    f.write_text("version: '2026.11-a'\nvalidity_days:\n  sanctions_screening: 30\n", encoding="utf-8")
    p = load_policy(f)
    assert p.version == "2026.11-a" and p.get("validity_days.sanctions_screening") == 30
    assert p.get("validity_days.idv_result") is NOT_CONFIGURED


def test_env_var_selects_file(tmp_path, monkeypatch):
    f = tmp_path / "p.yaml"
    f.write_text("version: env\nrecency_window_days: 90\n", encoding="utf-8")
    monkeypatch.setenv("CPA_POLICY_FILE", str(f))
    assert load_policy().get("recency_window_days") == 90


def test_zero_is_a_real_value_not_unset():
    assert from_dict({"tolerances": {"cashflow_reconciliation_amount": 0}}).get(
        "tolerances.cashflow_reconciliation_amount") == 0
