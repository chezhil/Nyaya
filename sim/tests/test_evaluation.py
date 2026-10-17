from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from sim.evaluation import _fairness, _fixed_sample, _ratio


def _frame(n: int = 500) -> pd.DataFrame:
    populations = np.resize(np.array(["normal", "displaced", "syndicate"]), n)
    return pd.DataFrame({
        "population": populations,
        "is_fraud": (populations == "syndicate").astype(int),
        "sender_income_band": np.resize(np.array(["low", "mid", "high", ""]), n),
    })


class EvaluationTests(unittest.TestCase):
    def test_fixed_sample_is_deterministic_unique_and_held_out(self):
        df = _frame()
        counts = {"normal": 10, "displaced": 8, "syndicate": 6}
        a = _fixed_sample(df, counts, seed=7)
        b = _fixed_sample(df, counts, seed=7)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(len(a), sum(counts.values()))
        self.assertTrue(a.index.is_unique)
        self.assertEqual(a["population"].value_counts().to_dict(), counts)

    def test_fixed_sample_refuses_oversampling(self):
        with self.assertRaisesRegex(ValueError, "unique rows are required"):
            _fixed_sample(_frame(90), {"syndicate": 100}, seed=7)

    def test_fairness_reports_rates_without_using_band_as_a_score_input(self):
        df = pd.DataFrame({"sender_income_band": ["low", "low", "mid", "mid", "high", "high"]})
        decisions = pd.DataFrame({"decision": ["HOLD", "REVIEW", "HOLD", "RELEASE", "HOLD", "REVIEW"]})
        result = _fairness(df, decisions)
        self.assertEqual(result["max_min_freeze_ratio"], 1.0)
        self.assertEqual(result["by_sender_income_band"]["mid"]["review_rate"], 0.0)

    def test_ratio_zero_denominator_is_explicitly_unbounded(self):
        self.assertIsNone(_ratio([0.0, 0.2]))

    def test_ratio_requires_at_least_two_groups(self):
        self.assertIsNone(_ratio([0.5]))
        self.assertIsNone(_ratio([]))

    def test_fairness_with_missing_or_single_group_does_not_falsely_certify(self):
        # Single band present: parity cannot be established, target_met must be False
        df = pd.DataFrame({"sender_income_band": ["low", "low"]})
        decisions = pd.DataFrame({"decision": ["HOLD", "RELEASE"]})
        result = _fairness(df, decisions)
        self.assertIsNone(result["max_min_freeze_ratio"])
        self.assertIsNone(result["max_min_review_ratio"])
        self.assertFalse(result["target_met"])

    def test_metrics_zero_length_dataset(self):
        from sim.evaluation import _metrics
        df_empty = pd.DataFrame({"population": [], "is_fraud": [], "is_mule_recipient": [], "amount": []})
        dec_empty = pd.DataFrame({"decision": [], "release_now": []})
        pol_empty = pd.DataFrame({"h_fraud": [], "h_hold": []})
        scores_empty = {"p_fraud": np.array([]), "p_mule": np.array([]), "conformal_set": []}
        m = _metrics(df_empty, dec_empty, pol_empty, scores_empty)
        self.assertEqual(m["rows"], 0)
        self.assertIsNone(m["pr_auc_model_a"])
        self.assertIsNone(m["pr_auc_model_b"])
        self.assertIsNone(m["conformal_coverage"])
        self.assertEqual(m["total_expected_harm_rupees"], 0.0)

    def test_metrics_all_legitimate_transactions(self):
        from sim.evaluation import _metrics
        df_legit = pd.DataFrame({
            "population": ["normal", "displaced"],
            "is_fraud": [0, 0],
            "is_mule_recipient": [0, 0],
            "amount": [100.0, 200.0]
        })
        dec = pd.DataFrame({"decision": ["RELEASE", "RELEASE"], "release_now": [100.0, 200.0]})
        pol = pd.DataFrame({"h_fraud": [0.0, 0.0], "h_hold": [50.0, 50.0]})
        scores = {"p_fraud": np.array([0.01, 0.02]), "p_mule": np.array([0.01, 0.01]), "conformal_set": [["legit"], ["legit"]]}
        m = _metrics(df_legit, dec, pol, scores)
        self.assertEqual(m["rows"], 2)
        self.assertIsNone(m["pr_auc_model_a"])  # undefined when 0 fraud rows
        self.assertIsNone(m["pr_auc_model_b"])  # undefined when 0 mule rows
        self.assertEqual(m["conformal_coverage"], 1.0)
        self.assertEqual(m["fraud_leakage_rupees"], 0.0)

    def test_metrics_all_fraudulent_transactions(self):
        from sim.evaluation import _metrics
        df_fraud = pd.DataFrame({
            "population": ["syndicate", "syndicate"],
            "is_fraud": [1, 1],
            "is_mule_recipient": [1, 1],
            "amount": [1000.0, 2000.0]
        })
        dec = pd.DataFrame({"decision": ["HOLD", "HOLD"], "release_now": [0.0, 0.0]})
        pol = pd.DataFrame({"h_fraud": [1000.0, 2000.0], "h_hold": [0.0, 0.0]})
        scores = {"p_fraud": np.array([0.9, 0.95]), "p_mule": np.array([0.8, 0.85]), "conformal_set": [["fraud"], ["fraud"]]}
        m = _metrics(df_fraud, dec, pol, scores)
        self.assertEqual(m["rows"], 2)
        self.assertEqual(m["pr_auc_model_a"], 1.0)
        self.assertEqual(m["pr_auc_model_b"], 1.0)
        self.assertEqual(m["conformal_coverage"], 1.0)
        self.assertEqual(m["fraud_leakage_rupees"], 0.0)

    def test_extreme_pareto_parameters(self):
        from engine.policy import decide
        # alpha=0, beta=0: holding causes 0 perceived harm, delta = h_fraud >= 0
        policy_zero = {"alpha": 0.0, "beta": 0.0, "tau": 500.0, "tau_review": 500.0, "stipend_cap": 2500.0, "theta_mule": 0.85}
        tx = {"amount": 5000.0, "in_disaster_zone": 1, "severity_tier": 2, "merchant_category": "p2p"}
        scores = {"p_fraud": 0.01, "p_mule": 0.01, "conformal_set": ["legit"]}
        d_zero = decide(scores, tx, policy_zero)
        self.assertEqual(d_zero["h_hold"], 0.0)
        self.assertEqual(d_zero["decision"], "REVIEW")  # delta > -tau_review with amount > cap escrows remainder

        # alpha=1, beta=1: exp(2) = 7.39, h_hold ≈ 7.32
        policy_active = {"alpha": 1.0, "beta": 1.0, "tau": 500.0, "tau_review": 500.0, "stipend_cap": 2500.0, "theta_mule": 0.85}
        d_active = decide(scores, tx, policy_active)
        self.assertAlmostEqual(d_active["h_hold"], 7.32, places=1)
        self.assertEqual(d_active["decision"], "REVIEW")

        # alpha=1, beta=100: h_hold = 731.54, delta = -681.54 < -500 -> RELEASE
        policy_high_beta = {"alpha": 1.0, "beta": 100.0, "tau": 500.0, "tau_review": 500.0, "stipend_cap": 2500.0, "theta_mule": 0.85}
        d_release = decide(scores, tx, policy_high_beta)
        self.assertAlmostEqual(d_release["h_hold"], 731.54, places=1)
        self.assertEqual(d_release["decision"], "RELEASE")

    def test_require_real_bundle_refuses_stub_bundle(self):
        from types import SimpleNamespace
        from api.bundle import StubBundle
        from sim.evaluation import _require_real_bundle
        ctx_stub = SimpleNamespace(bundle=StubBundle())
        with self.assertRaisesRegex(RuntimeError, "StubBundle results are refused"):
            _require_real_bundle(ctx_stub)

    def test_sanitization_and_empty_edge_cases(self):
        from sim.evaluation import (
            _data_dir, _test_positions, _fixed_sample, _score, _decisions,
            _baseline_decisions, _grid
        )
        # _data_dir with None
        self.assertTrue(str(_data_dir(None)).endswith("data"))

        # _test_positions on empty df
        empty_df = pd.DataFrame()
        self.assertEqual(len(_test_positions(empty_df)), 0)

        # _fixed_sample with empty counts
        df = pd.DataFrame({"population": ["normal"], "is_fraud": [0]})
        self.assertEqual(len(_fixed_sample(df, {}, 7)), 0)

        # _score on empty df
        mock_ctx = None
        s = _score(mock_ctx, empty_df)
        self.assertEqual(len(s["p_fraud"]), 0)
        self.assertEqual(len(s["conformal_set"]), 0)

        # _decisions on empty df
        d = _decisions(mock_ctx, empty_df, s, {})
        self.assertEqual(len(d), 0)
        self.assertIn("decision", d.columns)

        # _baseline_decisions on empty df
        b = _baseline_decisions(empty_df, np.array([]), 0.5, 2500.0)
        self.assertEqual(len(b), 0)
        self.assertIn("decision", b.columns)

        # _grid with None params
        g = _grid(None, "alpha", 0.5, (1.0, 2.0))
        self.assertEqual(g, [0.5, 1.0])


if __name__ == "__main__":
    unittest.main()
