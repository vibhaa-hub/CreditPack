import pytest

from cpa_agents.rules.language import find_decision_language, has_decision_language
from cpa_agents.rules.policy import from_dict
from cpa_agents.rules.validity import DT5, assess

SET = from_dict({"version": "t1", "validity_days": {k: 90 for k in DT5}})
UNSET = from_dict({"version": "t0"})


@pytest.mark.parametrize("cls,action", list(DT5.items()))
def test_each_dt5_class_stale_gives_its_action(cls, action):
    r = assess(cls, "2026-07-01", "2026-10-23", SET)
    assert r["stale"] is True and r["age_days"] == 114 and r["action"] == action
    assert r["policy_version"] == "t1"
    fresh = assess(cls, "2026-10-01", "2026-10-23", SET)
    assert fresh["stale"] is False and fresh["action"] is None


def test_undated_item_is_stale_even_without_policy():
    r = assess("sanctions_screening", None, "2026-10-23", UNSET)
    assert r["stale"] is True and r["action"] == "Re-screen"


def test_unset_validity_is_reported_not_guessed():
    r = assess("idv_result", "2026-01-01", "2026-10-23", UNSET)
    assert r["stale"] is None and r["configured"] is False and "NOT CONFIGURED" in r["display"]


def test_unknown_class_rejected():
    with pytest.raises(ValueError):
        assess("horoscope", "2026-01-01", "2026-10-23", SET)


DECISION = [
    "We recommend approval of the increased facility.",
    "The preparer recommends that the limit is granted.",
    "This application should be approved.",
    "The increase will certainly be approved by Credit.",
    "Approval is highly likely given the trading record.",
    "The dealer is likely to be approved.",
    "There is a high probability of approval.",
    "We approve the request.",
    "The facility has been approved.",
    "Approve the increase to 5.5m.",
    "We fully support the application.",
    "Credit decision: approve.",
    "Decline is expected given the losses.",
]
NEUTRAL = [
    "Credit's approval is required before first drawdown.",
    "The dealer was appointed by the OEM as a franchise partner in 2019.",
    "Approval of the previous facility in 2023 was conditional on a stock audit.",
    "The case owner must review this section before it is used.",
    "Pricing awaits authorisation by the pricing authority.",
    "Turnover rose 11.11% year on year; gearing is 1.50x.",
    "The request is for an increase in the wholesale facility to 5,500,000.",
]


@pytest.mark.parametrize("text", DECISION)
def test_decision_phrasings_are_caught(text):
    assert has_decision_language(text), text


@pytest.mark.parametrize("text", NEUTRAL)
def test_neutral_sentences_pass(text):
    assert find_decision_language(text) == [], text
