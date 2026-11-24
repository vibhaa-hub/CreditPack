import copy

from cpa_agents.rules.gate import evaluate
from cpa_agents.rules.policy import from_dict

FULL_POLICY = from_dict({"version": "full-1", "fca_regulatory_scope": "SME-defined",
                         "validity_days": {"financial_statements": 450, "registry_result": 90,
                                           "sanctions_screening": 90, "idv_result": 365, "adverse_media": 90}})
AS_AT = "2026-11-14"
SEC = lambda text: {"text": text, "evidence": ["FY2025 accounts"], "reviewed": True, "label": "non-human draft"}

READY = {
    "dealer_name": "Acme Motors Ltd",
    "checklist": {"entity": "R", "parties": "R", "checks": "R", "cra": "R", "media": "R",
                  "financial": "R", "security": "R", "request": "R"},
    "parties": [{"name": "A. Director", "role": "director", "individual": True}],
    "info_items": [{"info_class": c, "as_at": "2026-11-03"} for c in
                   ("entity", "director", "shareholder", "financial", "security", "consent", "data_protection")],
    "checks": [{"party": p, "check": c, "result": "clear", "date": "2026-11-10"}
               for p in ("Acme Motors Ltd", "A. Director") for c in ("kyc", "aml", "sanctions", "adverse_media")]
              + [{"party": "A. Director", "check": "idv", "result": "clear", "date": "2026-11-10"}],
    "cra_recorded_by": "analyst-7",
    "sections": {"business_background": SEC("Acme is a franchise dealer."),
                 "management_assessment": SEC("Management is experienced."),
                 "conduct_performance": SEC("Gearing is 1.50x and utilisation 80.00%."),
                 "security_review": SEC("Debenture held."),
                 "esg": SEC("No ESG concerns recorded.")},
    "measures": {"gearing_x": 1.5, "utilisation_pct": 80.0},
    "lending_request": {"facility_type": "wholesale", "amount": 5_500_000, "preparer": "Jane Smith"},
    "pricing_authorised_by": "pricing-committee-2",
    "registry_record": {"retrieved": "2026-11-10"},
}


def _eval(**changes):
    st = copy.deepcopy(READY)
    for k, v in changes.items():
        if v is None:
            st.pop(k, None)
        else:
            st[k] = v
    return evaluate(st, FULL_POLICY, AS_AT)


def _rules(r):
    return {g["rule"] for g in r["gaps"]}


def test_full_case_passes_r8():
    r = _eval()
    assert r["result"] == "PASS" and r["deciding_rule"] == "R8" and r["gaps"] == []
    assert r["completeness"]["display"] == "100.00%" and r["submission_may_be_authorised"]
    assert r["policy_version"] == "full-1"


def test_r1_missing_information_section_request_pricing():
    st = copy.deepcopy(READY["info_items"])[:-1]           # drop data_protection
    r = _eval(info_items=st, lending_request=None)
    assert r["result"] == "BLOCK" and r["deciding_rule"] == "R1"
    reasons = " | ".join(g["reason"] for g in r["gaps"])
    assert "data_protection" in reasons and "lending request missing" in reasons
    assert all(g["action"] for g in r["gaps"])              # BR-U04: every block has a corrective action
    secs = {k: v for k, v in READY["sections"].items() if k != "security_review"}
    assert "security_review" in " ".join(g["reason"] for g in _eval(sections=secs)["gaps"])


def test_r1_preparer_cannot_authorise_pricing():
    assert "BR-E02" in _eval(pricing_authorised_by="Jane Smith")["gaps"][0]["reason"]


def test_r2_outstanding_check_and_cra():
    r = _eval(checks=READY["checks"][1:], cra_recorded_by=None)
    assert r["deciding_rule"] == "R2" and {"R2"} == _rules(r)
    assert any("Acme Motors Ltd/kyc" == g.get("item") for g in r["gaps"])
    assert any("CRA" in g["reason"] for g in r["gaps"])


def test_r2_party_added_late_must_be_screened():
    parties = READY["parties"] + [{"name": "New Shareholder Ltd", "role": "shareholder"}]
    r = _eval(parties=parties)
    assert any(g.get("item") == "New Shareholder Ltd/sanctions" for g in r["gaps"])


def test_r2_authorised_exception_releases_item():
    exc = [{"rule": "R2", "item": "Acme Motors Ltd/kyc", "approved_by": "head-of-onboarding", "reason": "group KYC on file"}]
    r = _eval(checks=READY["checks"][1:], exceptions=exc)
    assert r["result"] == "ADVISORY" and any("exception" in a["reason"] for a in r["advisories"])


def test_r3_undispositioned_hit_and_halt():
    r = _eval(hits_open=[{"party": "A. Director", "check": "sanctions", "result": "potential_match"}])
    assert "R3" in _rules(r)
    assert any("halted" in g["reason"] for g in _eval(case_halted=True)["gaps"])


def test_r4_unreviewed_decision_language_uncited():
    secs = copy.deepcopy(READY["sections"])
    secs["business_background"]["reviewed"] = False
    secs["management_assessment"]["text"] = "We recommend approval."
    secs["security_review"]["evidence"] = []
    reasons = [g["reason"] for g in _eval(sections=secs)["gaps"]]
    assert any("not accepted" in x for x in reasons) and any("BR-D12" in x for x in reasons)
    assert any("ARCH-G08" in x for x in reasons) and _eval(sections=secs)["deciding_rule"] == "R4"


def test_r5_numbers_inconsistent():
    secs = copy.deepcopy(READY["sections"])
    secs["conduct_performance"]["text"] = "Gearing is 1.65x. The facility increase to 6,000,000 is requested."
    r = _eval(sections=secs)
    assert r["deciding_rule"] == "R5" and len([g for g in r["gaps"] if g["rule"] == "R5"]) == 2


LIVE_MISTRAL_SENTENCES = [   # accurate sentences that the first R5 version wrongly blocked (live run 2026-11-14)
    "Legal entity: ACME MOTORS LIMITED, registered number 01234567, a private limited company.",
    "increase of the wholesale facility limit from GBP 4,500,000 to GBP 5,500,000, +GBP 1,000,000",
    "Security cover (calculated): 1.20x - security value GBP 6,600,000 against the requested facility limit of GBP 5,500,000.",
    "wholesale facility drawn GBP 3,600,000 against current limit GBP 4,500,000 (80.00% utilised; headroom 900,000)",
    "Borrowing profile: wholesale - drawn 3,600,000, limit 4,500,000, utilisation 80.00%.",
    "- Current ratio: current assets 6,200,000 / current liabilities 4,000,000 → 1.55 (CALC-002)",
    "- Gearing: total borrowings 4,500,000 / net worth 3,000,000 → 1.50x (CALC-001)",
]


def test_r5_accepts_every_evidenced_amount_from_live_run():
    secs = copy.deepcopy(READY["sections"])
    secs["conduct_performance"]["text"] = " ".join(LIVE_MISTRAL_SENTENCES)
    lr = {**READY["lending_request"], "current_limit": 4_500_000}
    r = _eval(sections=secs, lending_request=lr, security={"value": 6_600_000},
              facilities=[{"lending_line": "wholesale", "drawn": 3_600_000, "limit": 4_500_000}],
              financial_statements=[{"figures": {"current_assets": 6_200_000, "current_liabilities": 4_000_000,
                                                 "total_borrowings": 4_500_000, "net_worth": 3_000_000}}])
    assert [g for g in r["gaps"] if g["rule"] == "R5"] == [] and r["result"] == "PASS"


def test_r5_still_flags_a_wrong_ratio_after_its_inputs():
    secs = copy.deepcopy(READY["sections"])
    secs["conduct_performance"]["text"] = "- Current ratio: current assets 6,200,000 / current liabilities 4,000,000 -> 1.65"
    r = _eval(sections=secs, measures={"current_ratio": 1.55},
              financial_statements=[{"figures": {"current_assets": 6_200_000, "current_liabilities": 4_000_000}}])
    assert [g["reason"] for g in r["gaps"]] == ["conduct_performance states current_ratio 1.65, analysis shows 1.55"]


def test_r5_flags_amount_matching_no_case_figure():
    secs = copy.deepcopy(READY["sections"])
    secs["conduct_performance"]["text"] = "Turnover of GBP 15,000,000 supports a limit of £7,250,000."
    st = {"financial_statements": [{"figures": {"turnover": 15_000_000}}]}
    r = _eval(sections=secs, **st)
    assert [g["reason"].split(",")[0] for g in r["gaps"] if g["rule"] == "R5"] == ["conduct_performance states amount 7"]


def test_r6_stale_information_and_exception():
    items = copy.deepcopy(READY["info_items"])
    items[3]["as_at"] = "2024-12-31"                      # financial statements > 450 days old
    r = _eval(info_items=items)
    assert r["deciding_rule"] == "R6" and "Request updated statements" in r["gaps"][0]["action"]
    exc = [{"rule": "R6", "item": "financial dated 2024-12-31", "approved_by": "credit-manager", "reason": "FY26 due"}]
    assert _eval(info_items=items, exceptions=exc)["result"] == "ADVISORY"
    no_approver = [{**exc[0], "approved_by": None}]
    assert _eval(info_items=items, exceptions=no_approver)["result"] == "BLOCK"   # BR-E04


def test_r7_advisory_only_may_proceed():
    secs = {k: v for k, v in READY["sections"].items() if k != "esg"}
    r = _eval(sections=secs)
    assert r["result"] == "ADVISORY" and r["submission_may_be_authorised"] and r["gaps"] == []


def test_first_block_rule_wins_and_all_gaps_listed():
    r = _eval(lending_request=None, hits_open=[{"party": "A. Director", "check": "kyc"}])
    assert r["deciding_rule"] == "R1" and {"R1", "R3"} <= _rules(r)


def test_unset_policy_reports_configuration_gaps_as_advisories():
    r = evaluate(copy.deepcopy(READY), from_dict({"version": "unset"}), AS_AT)
    assert r["result"] == "ADVISORY"
    assert any("NOT CONFIGURED" in a["reason"] for a in r["advisories"])


def test_unresolved_registry_discrepancy_blocks():
    d = [{"field": "director", "issue": "on registry but not supplied"}]
    assert "BR-D01" in _eval(registry_discrepancies=d)["gaps"][0]["action"]
    assert _eval(registry_discrepancies=[{**d[0], "resolved_by": "Jane Smith"}])["result"] == "PASS"
