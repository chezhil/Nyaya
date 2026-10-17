"""Unit tests for the policy and counterfactual logic. The scorers here are test doubles with known behaviour;
they only check that the engine does what the plan's table says, not how good the real models are."""
import json
from pathlib import Path

import pytest

from engine import ENGINE_VERSION, counterfactual, decide

POLICY = json.loads((Path(__file__).resolve().parents[2] / "api" / "policy_defaults.json").read_text())


def tx(**kw):
    base = {"amount": 1000.0, "merchant_category": "grocery", "in_disaster_zone": 0, "severity_tier": 0,
            "hour": 12, "new_device": 0, "geo_shift_km": 0.0}
    return {**base, **kw}


def sc(p_fraud=0.01, p_mule=0.0, cset=("legit",)):
    return {"p_fraud": p_fraud, "p_mule": p_mule, "conformal_set": list(cset)}


def test_version():
    assert ENGINE_VERSION.startswith("engine")


def test_release_small_clean_payment():
    d = decide(sc(), tx(), POLICY)
    assert d["decision"] == "RELEASE" and d["release_now"] == 1000.0 and d["escrow"] == 0.0


def test_hold_on_mule_override_even_if_fraud_score_low():
    d = decide(sc(p_fraud=0.01, p_mule=0.95), tx(), POLICY)
    assert d["decision"] == "HOLD" and d["release_now"] == 0.0


def test_hold_when_expected_fraud_harm_beats_threshold():
    d = decide(sc(p_fraud=0.9), tx(amount=50000.0), POLICY)
    assert d["decision"] == "HOLD"
    assert d["harm_delta"] >= POLICY["tau"]


def test_review_releases_stipend_and_escrows_the_rest():
    d = decide(sc(p_fraud=0.1, cset=("legit", "fraud")), tx(amount=25000.0), POLICY)
    assert d["decision"] == "REVIEW"
    assert d["release_now"] == POLICY["stipend_cap"]
    assert d["escrow"] == pytest.approx(25000.0 - POLICY["stipend_cap"])


def test_review_under_stipend_cap_is_a_release():
    d = decide(sc(p_fraud=0.1, cset=("legit", "fraud")), tx(amount=2000.0), POLICY)
    assert d["decision"] == "RELEASE" and d["escrow"] == 0.0


def test_survival_cash_never_zero_unless_hold():
    for p in (0.0, 0.05, 0.3, 0.6):
        d = decide(sc(p_fraud=p, cset=("legit", "fraud")), tx(amount=30000.0), POLICY)
        assert d["decision"] == "HOLD" or d["release_now"] > 0


def test_severity_raises_cost_of_holding():
    base = decide(sc(p_fraud=0.2), tx(amount=20000.0, merchant_category="pharmacy"), POLICY)
    zone = decide(sc(p_fraud=0.2), tx(amount=20000.0, merchant_category="pharmacy", in_disaster_zone=1, severity_tier=5), POLICY)
    assert zone["h_hold"] > base["h_hold"]
    assert zone["harm_delta"] < base["harm_delta"]


def test_decision_is_consistent_with_amounts():
    d = decide(sc(p_fraud=0.1, cset=("legit", "fraud")), tx(amount=25000.0), POLICY)
    assert d["release_now"] + d["escrow"] == pytest.approx(25000.0)


# ---- counterfactuals ---------------------------------------------------------------------------------------

def amount_scorer(row):
    """Fraud probability grows with amount: a deterministic stand-in so the flip point is known."""
    p = min(0.95, row["amount"] / 60000.0)
    return {"p_fraud": p, "p_mule": 0.0, "conformal_set": ["legit"],
            "contribs": [{"feature": "amount", "value": row["amount"], "contribution": 1.0}]}


def test_counterfactual_none_when_already_released():
    from data.features import tx_features
    t = tx(amount=500.0)
    assert counterfactual(tx_features(t), amount_scorer, POLICY, t) is None


def test_counterfactual_finds_smaller_amount_and_flips_decision():
    from data.features import tx_features
    t = tx(amount=30000.0)
    row = tx_features(t)
    assert decide(amount_scorer(row), t, POLICY)["decision"] != "RELEASE"
    cf = counterfactual(row, amount_scorer, POLICY, t)
    assert cf is not None and cf["feature"] == "amount" and cf["to"] < 30000.0
    t2 = {**t, "amount": cf["to"]}
    assert decide(amount_scorer(tx_features(t2)), t2, POLICY)["decision"] == cf["new_decision"]
    assert cf["new_decision"] in ("REVIEW", "RELEASE") and cf["text"].startswith("This would be")


def test_counterfactual_new_device():
    from data.features import tx_features

    def scorer(row):
        p = 0.9 if row["new_device"] else 0.0
        return {"p_fraud": p, "p_mule": 0.0, "conformal_set": ["legit"],
                "contribs": [{"feature": "new_device", "value": row["new_device"], "contribution": 2.0}]}

    t = tx(amount=20000.0, new_device=1)
    cf = counterfactual(tx_features(t), scorer, POLICY, t)
    # p drops to 0, but with the default tau a Rs 20,000 payment still lands in the |delta| < tau review band
    assert cf["feature"] == "new_device" and cf["new_decision"] in ("REVIEW", "RELEASE")


def test_counterfactual_none_when_nothing_changes_outcome():
    from data.features import tx_features

    def scorer(row):
        return {"p_fraud": 0.0, "p_mule": 0.99, "conformal_set": ["legit"],
                "contribs": [{"feature": "amount", "value": row["amount"], "contribution": 1.0}]}

    t = tx(amount=20000.0)
    assert counterfactual(tx_features(t), scorer, POLICY, t) is None
