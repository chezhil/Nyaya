import numpy as np
import pandas as pd
import pytest

from data.features import (
    MODEL_A_FEATURES,
    MODEL_B_FEATURES,
    RecipientWindow,
    compute_mci,
    tx_features,
    tx_features_frame,
)
from data.generate import GenConfig, generate
from data.openfema import severity_tier


@pytest.fixture(scope="module")
def small():
    return generate(GenConfig(n_normal=3000, n_displaced=800, n_syndicate=300, seed=1, n_merchants=200))


def test_deterministic():
    cfg = GenConfig(n_normal=500, n_displaced=100, n_syndicate=60, seed=3, n_merchants=100)
    a, _ = generate(cfg)
    b, _ = generate(cfg)
    pd.testing.assert_frame_equal(a, b)


def test_columns_and_labels(small):
    tx, acc = small
    for c in MODEL_B_FEATURES + ["population", "is_fraud", "is_mule_recipient", "sender_income_band"]:
        assert c in tx.columns
    assert tx["ts"].is_monotonic_increasing
    assert set(tx.loc[tx.is_fraud == 1, "population"]) <= {"ato", "syndicate", "syndicate_forward"}
    assert (tx.loc[tx.population == "displaced", "is_fraud"] == 0).all()
    assert (tx["amount"] > 0).all()
    assert np.allclose(tx["oldbalanceOrg"] - tx["amount"], tx["newbalanceOrig"], atol=0.02)
    assert acc["account_id"].is_unique


def test_mule_signal_present(small):
    tx, _ = small
    mule = tx[tx.population == "syndicate"]
    normal = tx[tx.population == "normal"]
    assert mule["fan_in_15m"].median() > 5 * max(1, normal["fan_in_15m"].median())
    assert mule["account_age_days"].median() < 60 < normal["account_age_days"].median()


@pytest.mark.parametrize("variant,feature", [("smurf", "fan_in_15m"), ("device_spoof", "device_reuse_density"),
                                             ("slow_drip", "forward_within_10m_ratio")])
def test_variants_weaken_their_feature(small, variant, feature):
    base = small[0]
    adv, _ = generate(GenConfig(n_normal=3000, n_displaced=800, n_syndicate=300, seed=1, n_merchants=200,
                                variant=variant))
    b = base.loc[base.population == "syndicate", feature].mean()
    a = adv.loc[adv.population == "syndicate", feature].mean()
    assert a < 0.6 * b


def test_frame_matches_single_row(small):
    tx, _ = small
    frame = tx_features_frame(tx.head(50))
    for i, row in enumerate(tx.head(50).to_dict("records")):
        single = tx_features(row)
        assert all(np.isclose(frame.iloc[i][k], single[k]) for k in MODEL_A_FEATURES)


def test_window_forwarding_no_lookahead():
    w = RecipientWindow()
    w.add(0, "a", "mule", 100)
    w.add(10, "b", "mule", 100)
    assert w.features("mule", 10)["forward_within_10m_ratio"] == 0
    w.add(70, "mule", "cash", 190)  # forwards both
    f = w.features("mule", 70)
    assert f == {"fan_in_15m": 2, "unique_senders_15m": 2, "forward_within_10m_ratio": 1.0}
    assert w.features("mule", 10_000)["fan_in_15m"] == 0


def test_mci_ranks_pass_through_hub_highest():
    edges = [(f"v{i}", "mule", 100.0) for i in range(20)] + [("mule", "cash", 1900.0)]
    edges += [(f"c{i}", "shop", 100.0) for i in range(20)]
    m = compute_mci(edges)
    assert m["mule"] > m["shop"] > 0


def test_openfema_tiers():
    assert severity_tier("DR", "Hurricane", True) == 5
    assert severity_tier("EM", "Flood", False) == 3
    assert severity_tier("FM", "Fire", False) == 1
